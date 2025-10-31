#!/usr/bin/env python3
"""
S3 Backup Script for Coralogix DR Migration Tool

This script backs up important directories and files to S3 using EC2 instance profile.
Designed to run on EC2 instances with appropriate S3 permissions.
"""

import os
import sys
import boto3
import json
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
import argparse

class S3BackupManager:
    """Manages backup operations to S3."""
    
    def __init__(self, bucket_name: str, region: str = 'us-east-1'):
        """
        Initialize S3 backup manager.
        
        Args:
            bucket_name: S3 bucket name for backups
            region: AWS region (default: us-east-1)
        """
        self.bucket_name = bucket_name
        self.region = region
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize S3 client using instance profile
        try:
            self.s3_client = boto3.client('s3', region_name=region)
            print(f"✅ Connected to S3 in region: {region}")
        except Exception as e:
            print(f"❌ Failed to connect to S3: {e}")
            sys.exit(1)
    
    def verify_bucket_access(self) -> bool:
        """Verify that we can access the S3 bucket."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            print(f"✅ Bucket access verified: {self.bucket_name}")
            return True
        except Exception as e:
            print(f"❌ Cannot access bucket {self.bucket_name}: {e}")
            return False
    
    def create_backup_archive(self, backup_dirs: list, backup_name: str) -> Optional[str]:
        """
        Create a compressed archive of specified directories.
        
        Args:
            backup_dirs: List of directories to backup
            backup_name: Name for the backup archive
            
        Returns:
            Path to created archive or None if failed
        """
        try:
            # Create temporary archive file
            temp_dir = tempfile.mkdtemp()
            archive_path = os.path.join(temp_dir, f"{backup_name}_{self.timestamp}.tar.gz")
            
            print(f"📦 Creating backup archive: {backup_name}")
            
            with tarfile.open(archive_path, 'w:gz') as tar:
                for backup_dir in backup_dirs:
                    if os.path.exists(backup_dir):
                        print(f"  📁 Adding: {backup_dir}")
                        tar.add(backup_dir, arcname=os.path.basename(backup_dir))
                    else:
                        print(f"  ⚠️  Directory not found: {backup_dir}")
            
            # Get archive size
            archive_size = os.path.getsize(archive_path)
            print(f"✅ Archive created: {archive_size / (1024*1024):.2f} MB")
            
            return archive_path
            
        except Exception as e:
            print(f"❌ Failed to create archive: {e}")
            return None
    
    def upload_to_s3(self, local_file: str, s3_key: str) -> bool:
        """
        Upload file to S3.
        
        Args:
            local_file: Path to local file
            s3_key: S3 object key
            
        Returns:
            True if successful, False otherwise
        """
        try:
            file_size = os.path.getsize(local_file)
            print(f"☁️  Uploading to S3: s3://{self.bucket_name}/{s3_key}")
            print(f"   File size: {file_size / (1024*1024):.2f} MB")
            
            # Upload with progress (for large files)
            self.s3_client.upload_file(
                local_file, 
                self.bucket_name, 
                s3_key,
                ExtraArgs={
                    'ServerSideEncryption': 'AES256',
                    'Metadata': {
                        'backup-timestamp': self.timestamp,
                        'backup-source': 'dr-migration-tool'
                    }
                }
            )
            
            print(f"✅ Upload completed: s3://{self.bucket_name}/{s3_key}")
            return True
            
        except Exception as e:
            print(f"❌ Upload failed: {e}")
            return False
    
    def backup_directories(self, directories: dict, prefix: str = "dr-migration-backups") -> bool:
        """
        Backup multiple directories to S3.
        
        Args:
            directories: Dict of {backup_name: [list_of_dirs]}
            prefix: S3 key prefix
            
        Returns:
            True if all backups successful
        """
        success_count = 0
        total_backups = len(directories)
        
        for backup_name, dirs in directories.items():
            print(f"\n{'='*60}")
            print(f"🔄 Starting backup: {backup_name}")
            print(f"{'='*60}")
            
            # Create archive
            archive_path = self.create_backup_archive(dirs, backup_name)
            if not archive_path:
                continue
            
            # Upload to S3
            s3_key = f"{prefix}/{backup_name}/{backup_name}_{self.timestamp}.tar.gz"
            if self.upload_to_s3(archive_path, s3_key):
                success_count += 1
            
            # Cleanup temporary file
            try:
                os.remove(archive_path)
                os.rmdir(os.path.dirname(archive_path))
            except:
                pass
        
        print(f"\n{'='*60}")
        print(f"📊 BACKUP SUMMARY")
        print(f"{'='*60}")
        print(f"Total backups: {total_backups}")
        print(f"Successful: {success_count}")
        print(f"Failed: {total_backups - success_count}")
        print(f"Success rate: {success_count/total_backups*100:.1f}%")
        
        return success_count == total_backups
    
    def list_backups(self, prefix: str = "dr-migration-backups") -> list:
        """List existing backups in S3."""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            backups = []
            for obj in response.get('Contents', []):
                backups.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'modified': obj['LastModified']
                })
            
            return backups
            
        except Exception as e:
            print(f"❌ Failed to list backups: {e}")
            return []

def main():
    """Main backup script."""
    parser = argparse.ArgumentParser(
        description="Backup DR Migration Tool data to S3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --bucket my-backup-bucket --region us-east-1
  %(prog)s --bucket my-backup-bucket --region eu-west-1 --prefix custom-backups
  %(prog)s --bucket my-backup-bucket --list-only
        """
    )
    
    parser.add_argument(
        '--bucket', 
        required=True,
        help='S3 bucket name for backups'
    )
    
    parser.add_argument(
        '--region', 
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    
    parser.add_argument(
        '--prefix', 
        default='dr-migration-backups',
        help='S3 key prefix (default: dr-migration-backups)'
    )
    
    parser.add_argument(
        '--list-only', 
        action='store_true',
        help='Only list existing backups, do not create new ones'
    )
    
    args = parser.parse_args()
    
    # Initialize backup manager
    backup_manager = S3BackupManager(args.bucket, args.region)
    
    # Verify bucket access
    if not backup_manager.verify_bucket_access():
        sys.exit(1)
    
    # List existing backups if requested
    if args.list_only:
        print(f"\n📋 Existing backups in s3://{args.bucket}/{args.prefix}/")
        print("="*80)
        backups = backup_manager.list_backups(args.prefix)
        
        if not backups:
            print("No backups found.")
        else:
            for backup in backups:
                size_mb = backup['size'] / (1024*1024)
                print(f"📦 {backup['key']}")
                print(f"   Size: {size_mb:.2f} MB")
                print(f"   Modified: {backup['modified']}")
                print()
        
        return 0
    
    # Define directories to backup
    backup_directories = {
        'outputs': ['outputs'],           # Exported artifacts
        'logs': ['logs'],                 # All log files
        'state': ['state'],               # State files
        'snapshots': ['snapshots'],       # Snapshot files
        'configs': ['.env', 'requirements.txt', 'dr-tool.py']  # Configuration files
    }
    
    print(f"🚀 Starting DR Migration Tool Backup")
    print(f"📅 Timestamp: {backup_manager.timestamp}")
    print(f"🪣 S3 Bucket: {args.bucket}")
    print(f"🌍 Region: {args.region}")
    print(f"📂 Prefix: {args.prefix}")
    
    # Perform backup
    success = backup_manager.backup_directories(backup_directories, args.prefix)
    
    if success:
        print(f"\n🎉 All backups completed successfully!")
        return 0
    else:
        print(f"\n❌ Some backups failed. Check logs above.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
