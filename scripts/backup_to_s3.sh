#!/bin/bash

# Coralogix DR Tool - Backup to S3 Script

# aws s3 sync $LOCALFOLDER s3://$S3BUCKET --exclude ".*" --exclude "*/.*" --region $REGION
aws s3 sync /home/ec2-user/cx-drmigration-tool s3://cx-coe-jiostar-drtool-backup-bucket --exclude ".*" --exclude "*/.*" 

