#!/bin/bash

chmod +x ./*.sh*
chmod +x ./*.py*
sh run.sh | tee /tmp/cloudcreation_log.out
