# @PydevCodeAnalysisIgnore
# pylint: disable=undefined-variable
'''Jupyter server config'''
c.NotebookApp.open_browser = False
c.NotebookApp.ip = '0.0.0.0'  # '*'
c.NotebookApp.port = 8192  # If you change the port here, make sure you update it in the jupyter_installer.sh file as well
c.NotebookApp.password = u'sha1:af1da2cb6d07:5ff21eaf523f1f6afcced77a17eededbaa6ff42c'
c.Authenticator.admin_users = {'jupyter'}
c.LocalAuthenticator.create_system_users = True
