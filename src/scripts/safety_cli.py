#!/usr/bin/env python3
"""
Safety CLI for managing rollbacks, version snapshots, and safety operations.

This script provides command-line interface for:
- Creating manual version snapshots
- Rolling back to previous versions
- Listing available versions
- Checking safety status
- Managing safety configurations
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager
from services.parsing_rules import ParsingRulesService


def load_config() -> Config:
    """Load configuration from environment."""
    try:
        return Config()
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        sys.exit(1)


def create_service(config: Config, service_name: str):
    """Create service instance based on service name."""
    import structlog
    logger = structlog.get_logger("safety_cli")

    if service_name == 'parsing-rules':
        return ParsingRulesService(config, logger)
    elif service_name == 'custom-actions':
        from services.custom_actions import CustomActionsService
        return CustomActionsService(config, logger)
    else:
        print(f"❌ Unsupported service: {service_name}")
        print(f"📋 Supported services: parsing-rules, custom-actions")
        sys.exit(1)


def cmd_list_versions(args):
    """List available versions for a service."""
    config = load_config()
    version_manager = VersionManager(config, args.service)
    
    print(f"📋 Available versions for {args.service}:")
    print("=" * 60)
    
    versions = version_manager.list_versions(limit=args.limit)
    
    if not versions:
        print("No versions found.")
        return
    
    for version in versions:
        print(f"🔖 Version: {version['version_id']}")
        print(f"   Timestamp: {version['timestamp']}")
        print(f"   Type: {version['version_type']}")
        print(f"   TeamA Count: {version['teama_count']}")
        print(f"   TeamB Count: {version['teamb_count']}")
        print()


def cmd_create_snapshot(args):
    """Create a manual version snapshot."""
    config = load_config()
    service = create_service(config, args.service)
    
    print(f"📸 Creating manual snapshot for {args.service}...")
    
    try:
        # Fetch current resources
        teama_resources = service.fetch_resources_from_teama()
        teamb_resources = service.fetch_resources_from_teamb()
        
        # Create snapshot
        version_id = service.version_manager.create_version_snapshot(
            teama_resources, teamb_resources, 'manual'
        )
        
        print(f"✅ Manual snapshot created: {version_id}")
        print(f"   TeamA resources: {len(teama_resources)}")
        print(f"   TeamB resources: {len(teamb_resources)}")
        
    except Exception as e:
        print(f"❌ Failed to create snapshot: {e}")
        sys.exit(1)


def cmd_rollback(args):
    """Rollback to a specific version."""
    config = load_config()
    service = create_service(config, args.service)
    
    print(f"🔄 Rolling back {args.service} to version: {args.version_id}")
    
    # Confirm rollback unless --force is used
    if not args.force:
        response = input("⚠️  This will delete all current resources in TeamB and restore from the specified version. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Rollback cancelled.")
            return
    
    try:
        success = service.rollback_to_version(args.version_id)
        
        if success:
            print(f"✅ Rollback completed successfully!")
        else:
            print(f"❌ Rollback failed. Check logs for details.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        sys.exit(1)


def cmd_safety_status(args):
    """Check safety status for a service."""
    config = load_config()
    service = create_service(config, args.service)
    
    print(f"🛡️  Safety status for {args.service}:")
    print("=" * 60)
    
    try:
        # Get current and previous versions
        current_version = service.version_manager.get_current_version()
        previous_version = service.version_manager.get_previous_version()
        
        if current_version:
            print(f"📊 Current Version:")
            print(f"   Version ID: {current_version.get('version_id', 'N/A')}")
            print(f"   Timestamp: {current_version.get('timestamp', 'N/A')}")
            print(f"   TeamA Count: {current_version.get('teama', {}).get('count', 0)}")
            print(f"   TeamB Count: {current_version.get('teamb', {}).get('count', 0)}")
        else:
            print("📊 Current Version: None")
        
        print()
        
        if previous_version:
            print(f"📋 Previous Version (v-1):")
            print(f"   Version ID: {previous_version.get('version_id', 'N/A')}")
            print(f"   Timestamp: {previous_version.get('timestamp', 'N/A')}")
            print(f"   TeamA Count: {previous_version.get('teama', {}).get('count', 0)}")
            print(f"   TeamB Count: {previous_version.get('teamb', {}).get('count', 0)}")
        else:
            print("📋 Previous Version (v-1): None")
        
        print()
        
        # Try to fetch current resources and perform safety check
        try:
            teama_resources = service.fetch_resources_from_teama()
            previous_count = current_version.get('teama', {}).get('count') if current_version else None
            
            safety_result = service.safety_manager.check_teama_fetch_safety(
                teama_resources, None, previous_count
            )
            
            if safety_result.is_safe:
                print(f"✅ Safety Check: PASSED")
                print(f"   Reason: {safety_result.reason}")
            else:
                print(f"❌ Safety Check: FAILED")
                print(f"   Reason: {safety_result.reason}")
                print(f"   Details: {safety_result.details}")
                
        except Exception as e:
            print(f"⚠️  Safety Check: ERROR")
            print(f"   Error: {e}")
        
    except Exception as e:
        print(f"❌ Failed to get safety status: {e}")
        sys.exit(1)


def cmd_quick_rollback(args):
    """Quick rollback to previous version (v-1)."""
    config = load_config()
    service = create_service(config, args.service)
    
    print(f"⚡ Quick rollback {args.service} to previous version (v-1)...")
    
    # Get previous version
    previous_version = service.version_manager.get_previous_version()
    if not previous_version:
        print("❌ No previous version (v-1) available for rollback.")
        sys.exit(1)
    
    version_id = previous_version.get('version_id')
    print(f"🔄 Rolling back to: {version_id}")
    
    # Confirm rollback unless --force is used
    if not args.force:
        response = input("⚠️  This will delete all current resources in TeamB and restore from v-1. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Quick rollback cancelled.")
            return
    
    try:
        success = service.rollback_to_version(version_id)
        
        if success:
            print(f"✅ Quick rollback completed successfully!")
        else:
            print(f"❌ Quick rollback failed. Check logs for details.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Quick rollback failed: {e}")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Safety CLI for managing rollbacks and version snapshots",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List versions command
    list_parser = subparsers.add_parser('list', help='List available versions')
    list_parser.add_argument('service', choices=['parsing-rules', 'custom-actions'], help='Service name')
    list_parser.add_argument('--limit', type=int, default=10, help='Maximum number of versions to show')
    list_parser.set_defaults(func=cmd_list_versions)

    # Create snapshot command
    snapshot_parser = subparsers.add_parser('snapshot', help='Create manual version snapshot')
    snapshot_parser.add_argument('service', choices=['parsing-rules', 'custom-actions'], help='Service name')
    snapshot_parser.set_defaults(func=cmd_create_snapshot)

    # Rollback command
    rollback_parser = subparsers.add_parser('rollback', help='Rollback to specific version')
    rollback_parser.add_argument('service', choices=['parsing-rules', 'custom-actions'], help='Service name')
    rollback_parser.add_argument('version_id', help='Version ID to rollback to')
    rollback_parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    rollback_parser.set_defaults(func=cmd_rollback)

    # Quick rollback command
    quick_parser = subparsers.add_parser('quick-rollback', help='Quick rollback to previous version (v-1)')
    quick_parser.add_argument('service', choices=['parsing-rules', 'custom-actions'], help='Service name')
    quick_parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    quick_parser.set_defaults(func=cmd_quick_rollback)

    # Safety status command
    status_parser = subparsers.add_parser('status', help='Check safety status')
    status_parser.add_argument('service', choices=['parsing-rules', 'custom-actions'], help='Service name')
    status_parser.set_defaults(func=cmd_safety_status)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == '__main__':
    main()
