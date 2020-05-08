#!/usr/bin/env python3

"""
To deploy and install hail on AWS using spot instances
"""

import subprocess as sp
import json
import os
import pathlib
import re
import sys
import time
import boto3
import paramiko
import yaml
import requests


def dtime(t0):
    '''Give delta time in minutes'''
    return "%.2f minutes" % ((time.time() - t0) / 60)


def _getoutput(icmd):
    '''to simulate commands.getoutput in order to work with python 2.6 up to 3.x'''
    out = sp.Popen(icmd, shell=True, stderr=sp.STDOUT, stdout=sp.PIPE).communicate()[0][:-1]
    try:
        o = str(out.decode(errors='ignore'))  # to force str in python 3
    except AttributeError:
        o = out
    return o


tic = time.time()

PATH = os.path.dirname(os.path.abspath(__file__))

base_path = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
with open(base_path.joinpath('config_EMR_spot.yaml'), 'r') as config_file:
    config = yaml.safe_load(config_file).get('config')

# Handle Security Group
my_ip = requests.get('https://checkip.amazonaws.com').text.strip()
sg = config.get('WORKER_SECURITY_GROUP')

# to delete opened to anyone SSH and Jupyter rules
cmd = """aws ec2 revoke-security-group-ingress --group-id %s --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "Ipv6Ranges": [{"CidrIpv6": "::/0"}]},{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},{"IpProtocol": "tcp", "FromPort": 8192, "ToPort": 8192, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},{"IpProtocol": "tcp", "FromPort": 8192, "ToPort": 8192, "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}]'""" % sg
out_del = _getoutput(cmd)
print("Revoke wide opened SG rules")

# to create ip specific rules for SSH and Jupyter
cmd = """aws ec2 authorize-security-group-ingress --group-id %s --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "%s/32"}]},{"IpProtocol": "tcp", "FromPort": 8192, "ToPort": 8192, "IpRanges": [{"CidrIp": "%s/32"}]}]'""" % (sg, my_ip, my_ip)
out_do = _getoutput(cmd)

if "already exists" in out_do:
    print("SG Rule for this IP %s already set" % my_ip)
elif out_do:
    print("ERROR: %s" % out_do)
else:
    print("SSH and Jupyter SG rules for IP %s created" % my_ip)

# Spot instances and different CORE/MASTER instances
command = 'aws emr create-cluster --applications Name=Hadoop Name=Spark --tags \'project=' + config['PROJECT_TAG'] + '\' \'Owner=' + config['OWNER_TAG'] + '\' \'Name=' + config['EC2_NAME_TAG'] + '\' --ec2-attributes \'{"KeyName":"' + config['KEY_NAME'] + '","InstanceProfile":"EMR_EC2_DefaultRole","SubnetId":"' + config['SUBNET_ID'] + '","EmrManagedSlaveSecurityGroup":"' + config['WORKER_SECURITY_GROUP'] + '","EmrManagedMasterSecurityGroup":"' + config['MASTER_SECURITY_GROUP'] + '"}\' --service-role EMR_DefaultRole --release-label emr-5.23.0 --log-uri \'' + config['S3_BUCKET'] + '\' --name \'' + config['EMR_CLUSTER_NAME'] + '\' --instance-groups \'[{"InstanceCount":1,"EbsConfiguration":{"EbsBlockDeviceConfigs":[{"VolumeSpecification":{"SizeInGB":' + config['MASTER_HD_SIZE'] + ',"VolumeType":"gp2"},"VolumesPerInstance":1}]},"InstanceGroupType":"MASTER","InstanceType":"' + config['MASTER_INSTANCE_TYPE'] + '","Name":"Master-Instance"},{"InstanceCount":' + config['WORKER_COUNT'] + ',"BidPrice":"' + config['WORKER_BID_PRICE'] + '","EbsConfiguration":{"EbsBlockDeviceConfigs":[{"VolumeSpecification":{"SizeInGB":' + config['WORKER_HD_SIZE'] + ',"VolumeType":"gp2"},"VolumesPerInstance":1}]},"InstanceGroupType":"CORE","InstanceType":"' + config['WORKER_INSTANCE_TYPE'] + '","Name":"Core-Group"}]\' --configurations \'[{"Classification":"spark","Properties":{"maximizeResourceAllocation":"true"}},{"Classification":"yarn-site","Properties":{"yarn.nodemanager.vmem-check-enabled":"false"},"Configurations":[]}]\' --auto-scaling-role EMR_AutoScaling_DefaultRole --ebs-root-volume-size 32 --scale-down-behavior TERMINATE_AT_TASK_COMPLETION --region ' + config['REGION'] + ' --bootstrap-actions Path="s3://hail-bootstrap/bootstrap_python36.sh"'

print("\n\nYour AWS CLI export command:\n")
print(command)

response = os.popen(command).read()
cluster_id_json = json.loads(response)
cluster_id = cluster_id_json['ClusterId']

# Gives EMR cluster information
client_EMR = boto3.client('emr', region_name=config['REGION'])

# Cluster state update
status_EMR = 'STARTING'

# Wait until the cluster is created
print('\nCreating EMR...')
prev_status = ''
while status_EMR != 'EMPTY':
    details_EMR = client_EMR.describe_cluster(ClusterId=cluster_id)
    status_EMR = details_EMR.get('Cluster').get('Status').get('State')
    if prev_status != status_EMR:
        print('Cluster status: %s %s' % (status_EMR, dtime(tic)))
        prev_status = status_EMR
    time.sleep(5)
    if status_EMR == 'WAITING':
        print('\nCluster successfully created! Starting HAIL installation...')
        print("\n Total time to provision your cluster: %s" % dtime(tic))
        break
    if status_EMR == 'TERMINATED_WITH_ERRORS':
        sys.exit("Cluster un-successfully created. Ending installation...")

# Relax SG
cmd = """aws ec2 revoke-security-group-ingress --group-id %s --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "%s/32"}]},{"IpProtocol": "tcp", "FromPort": 8192, "ToPort": 8192, "IpRanges": [{"CidrIp": "%s/32"}]}]'""" % (sg, my_ip, my_ip)
out_del = _getoutput(cmd)
cmd = """aws ec2 authorize-security-group-ingress --group-id %s --ip-permissions '[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "Ipv6Ranges": [{"CidrIpv6": "::/0"}]},{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},{"IpProtocol": "tcp", "FromPort": 8192, "ToPort": 8192, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},{"IpProtocol": "tcp", "FromPort": 8192, "ToPort": 8192, "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}]'""" % sg
out_do = _getoutput(cmd)
print("SG rules relaxed for SSH and Jupyter. Cluster wide world opened")

# Get public DNS from master node
master_dns = details_EMR.get('Cluster').get('MasterPublicDnsName')
master_IP = re.sub("-", ".", master_dns.split(".")[0].split("ec2-")[1])
print('\nMaster DNS: ' + master_dns)

# print('Master IP: '+ master_IP+'\n')
print('\nClusterId: ' + cluster_id + '\n')

# Copy the key into the master
command = 'scp -o \'StrictHostKeyChecking no\' -i ' + config['PATH_TO_KEY'] + config['KEY_NAME'] + '.pem ' + config['PATH_TO_KEY'] + config['KEY_NAME'] + '.pem hadoop@' + master_dns + ':/home/hadoop/.ssh/id_rsa'
# print(command)
os.system(command)
print('Copying keys...')

# Copy the installation script into the master
command = 'scp -o \'StrictHostKeyChecking no\' -i ' + config['PATH_TO_KEY'] + config['KEY_NAME'] + '.pem ' + PATH + '/install_hail_and_python36.sh hadoop@' + master_dns + ':/home/hadoop'
# print(command)
os.system(command)

print('\n SSH access via:\n\n    ssh -i ~/london-hail.pem hadoop@%s\n' % master_dns)

print('Installing HAIL software and its dependencies...')
print('Allow extra 4-8 minutes for full installation')

key = paramiko.RSAKey.from_private_key_file(config['PATH_TO_KEY'] + config['KEY_NAME'] + '.pem')
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=master_IP, username="hadoop", pkey=key)

# Execute a command(cmd) after connecting/ssh to an instance
VERSION = config['HAIL_VERSION']
command = './install_hail_and_python36.sh -v ' + VERSION
# print(command)
stdin, stdout, stderr = client.exec_command('cd /home/hadoop/')
stdin, stdout, stderr = client.exec_command(command)

h_output = stdout.read()

to_bashrc = r'''
# Added by Hail-on-AWS script (Phenopolis version)
export SPARK_HOME=/usr/lib/spark
export PYSPARK_PYTHON=python3
export HAIL_HOME=/opt/hail-on-AWS-spot-instances

export PYTHONPATH=\"/home/hadoop/hail-python.zip:\$SPARK_HOME/python:\${SPARK_HOME}/python/lib/py4j-src.zip\"

# Needed for HDFS
JAR_PATH=\"/home/hadoop/hail-all-spark.jar:/usr/share/aws/emr/emrfs/lib/emrfs-hadoop-assembly-2.32.0.jar\"
export PYSPARK_SUBMIT_ARGS=\"--conf spark.driver.extraClassPath='\$JAR_PATH' --conf spark.executor.extraClassPath='\$JAR_PATH' pyspark-shell\"

alias ltr='ls -ltr'
'''

stdin, stdout, stderr = client.exec_command('/opt/hail-on-AWS-spot-instances/src/jupyter_run.sh; echo "::: Jupyter Started!"')

stdin, stdout, stderr = client.exec_command('echo "%s" >> ~/.bashrc; echo "::: .bashrc updated!"' % to_bashrc)

# close the client connection
if client is not None:
    client.close()
    del client, stdin, stdout, stderr

toc = time.time() - tic
print("\n Total execution time: %s" % dtime(tic))

print('\nIt is all ready!')
print('\n This is your Jupyter Lab link: http://%s:8192\n password: phenopolis\n' % master_IP)
