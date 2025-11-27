#!/usr/bin/env python3
"""
Coralogix Disaster Recovery (DR) Migration Tool

Main entry point for the DR tool that keeps Team B in sync with Team A.
Supports modular migration of various Coralogix resources.
"""

import argparse
import sys
import os
import json
from datetime import datetime
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.config import Config
from core.logger import setup_logger
from utils.migration_summary import MigrationSummaryCollector
from services.parsing_rules import ParsingRulesService
from services.recording_rules import RecordingRulesService
from services.enrichments import EnrichmentsService
from services.general_enrichments import GeneralEnrichmentsService
from services.events2metrics import Events2MetricsService
from services.custom_dashboards import CustomDashboardsService
from services.grafana_dashboards import GrafanaDashboardsService
from services.views import ViewsService
from services.custom_actions import CustomActionsService
from services.webhooks import WebhooksService
from services.alerts import AlertsService
from services.slo import SLOService
from services.slo_grpc_simple import SLOGRPCService
from services.tco import TCOService


def create_service(service_name: str, config: Config, logger):
    """Factory function to create service instances."""
    services = {
        'parsing-rules': ParsingRulesService,
        'recording-rules': RecordingRulesService,
        'enrichments': EnrichmentsService,
        'general-enrichments': GeneralEnrichmentsService,
        'events2metrics': Events2MetricsService,
        'custom-dashboards': CustomDashboardsService,
        'grafana-dashboards': GrafanaDashboardsService,
        'views': ViewsService,
        'custom-actions': CustomActionsService,
        'webhooks': WebhooksService,
        'alerts': AlertsService,
        'slo': SLOService,
        'slo-grpc': SLOGRPCService,
        'tco': TCOService,
    }

    if service_name not in services:
        raise ValueError(f"Unknown service: {service_name}")

    return services[service_name](config, logger)


def extract_service_statistics(service, service_name: str, result, success: bool) -> dict:
    """
    Extract statistics from a service after migration/dry-run.

    Args:
        service: The service instance
        service_name: Name of the service
        result: Result from dry_run() or migrate()
        success: Whether the operation succeeded

    Returns:
        Dictionary with service statistics
    """
    stats = {
        'service_name': service_name,
        'success': success,
        'teama_count': 0,
        'teamb_before_count': 0,
        'teamb_after_count': 0,
        'created': 0,
        'updated': 0,
        'deleted': 0,
        'failed': 0,
        'skipped': 0,
        'error_message': None
    }

    try:
        # Get the outputs directory path
        outputs_dir = Path("outputs") / service_name

        # Try to get counts from artifact files
        if outputs_dir.exists():
            # Team A count
            teama_file = outputs_dir / f"{service_name}_teama_latest.json"
            if teama_file.exists():
                with open(teama_file, 'r') as f:
                    teama_data = json.load(f)
                    if isinstance(teama_data, list):
                        stats['teama_count'] = len(teama_data)
                    elif isinstance(teama_data, dict):
                        stats['teama_count'] = teama_data.get('count', len(teama_data.get('resources', [])))

            # Team B count (before)
            teamb_file = outputs_dir / f"{service_name}_teamb_latest.json"
            if teamb_file.exists():
                with open(teamb_file, 'r') as f:
                    teamb_data = json.load(f)
                    if isinstance(teamb_data, list):
                        stats['teamb_before_count'] = len(teamb_data)
                    elif isinstance(teamb_data, dict):
                        stats['teamb_before_count'] = teamb_data.get('count', len(teamb_data.get('resources', [])))

            # Team B count (after) - for actual migrations
            teamb_after_file = outputs_dir / f"{service_name}_teamb_final_latest.json"
            if teamb_after_file.exists():
                with open(teamb_after_file, 'r') as f:
                    teamb_after_data = json.load(f)
                    if isinstance(teamb_after_data, list):
                        stats['teamb_after_count'] = len(teamb_after_data)
                    elif isinstance(teamb_after_data, dict):
                        stats['teamb_after_count'] = teamb_after_data.get('count', len(teamb_after_data.get('resources', [])))
            else:
                # If no after file, use before count for dry runs
                stats['teamb_after_count'] = stats['teamb_before_count']

        # Try to extract from result if it's a dictionary (dry_run returns dict)
        if isinstance(result, dict):
            # Override with result data if available
            if 'teama_count' in result:
                stats['teama_count'] = result['teama_count']
            if 'teamb_count' in result:
                stats['teamb_before_count'] = result['teamb_count']

            # Handle different result formats for operations
            if 'to_create' in result:
                stats['created'] = len(result['to_create']) if isinstance(result['to_create'], list) else result['to_create']
            if 'to_update' in result:
                stats['updated'] = len(result['to_update']) if isinstance(result['to_update'], list) else result['to_update']
            if 'to_delete' in result:
                stats['deleted'] = len(result['to_delete']) if isinstance(result['to_delete'], list) else result['to_delete']
            if 'to_recreate' in result:
                stats['updated'] += len(result['to_recreate']) if isinstance(result['to_recreate'], list) else result['to_recreate']

        # For migrate() which returns bool, calculate operations from counts
        elif isinstance(result, bool) and result:
            # Calculate operations based on count changes
            if stats['teamb_after_count'] > stats['teamb_before_count']:
                stats['created'] = stats['teamb_after_count'] - stats['teamb_before_count']
            elif stats['teamb_after_count'] < stats['teamb_before_count']:
                stats['deleted'] = stats['teamb_before_count'] - stats['teamb_after_count']

            # For delete-all + recreate-all pattern (parsing-rules, recording-rules, slo, custom-actions, views)
            if service_name in ['parsing-rules', 'recording-rules', 'slo', 'custom-actions', 'views']:
                stats['deleted'] = stats['teamb_before_count']
                stats['created'] = stats['teamb_after_count']
                stats['updated'] = 0

        # Adjust teama_count for parsing-rules to exclude default Quota rule group
        if service_name == 'parsing-rules' and stats['teama_count'] > 0:
            stats['teama_count'] -= 1

    except Exception as e:
        stats['error_message'] = f"Failed to extract statistics: {str(e)}"

    return stats


def run_all_services(config: Config, logger, dry_run: bool = False, force: bool = False, exclude_services: list = None):
    """Run migration for all services with meaningful separation."""
    all_services = [
        'parsing-rules', 'recording-rules',  'general-enrichments', 'events2metrics', 'custom-dashboards',
         'grafana-dashboards', 'views', 'custom-actions', 'slo'
    ]

    # Filter out excluded services
    if exclude_services:
        excluded = [service for service in exclude_services if service in all_services]
        services = [service for service in all_services if service not in excluded]

        if excluded:
            logger.info(f"🚫 Excluding services: {', '.join(excluded)}")

        # Warn about invalid exclusions
        invalid_exclusions = [service for service in exclude_services if service not in all_services]
        if invalid_exclusions:
            logger.warning(f"⚠️  Invalid service names to exclude (ignored): {', '.join(invalid_exclusions)}")
    else:
        services = all_services

    total_services = len(services)
    successful_services = 0
    failed_services = []

    mode = "DRY RUN" if dry_run else "MIGRATION"

    # Initialize migration summary collector
    summary_collector = MigrationSummaryCollector()
    summary_collector.start_collection(mode=mode)

    logger.info("=" * 80)
    logger.info(f"🚀 STARTING {mode} FOR ALL SERVICES")
    logger.info(f"📊 Total services to process: {total_services}")
    logger.info("=" * 80)

    for index, service_name in enumerate(services, 1):
        result = None
        success = False
        error_message = None

        try:
            # Create service-specific logger for better organization
            service_logger = setup_logger(service_name, 'main', config.log_level)

            logger.info("")
            logger.info("─" * 80)
            logger.info(f"🔧 SERVICE {index}/{total_services}: {service_name.upper()}")
            logger.info("─" * 80)

            # Create and run service
            service = create_service(service_name, config, service_logger)

            if dry_run:
                result = service.dry_run()
                # Display formatted dry run results for services that support it
                if hasattr(service, 'display_dry_run_results') and isinstance(result, dict):
                    service.display_dry_run_results(result)
                # Note: Some services like grafana-dashboards have built-in display in their dry_run method
                # and return True instead of dict, so they don't need additional display calls
            else:
                result = service.migrate()

            if result:
                successful_services += 1
                success = True
                logger.info(f"✅ {service_name} {mode.lower()} completed successfully")
            else:
                failed_services.append(service_name)
                error_message = f"{mode.lower()} returned False"
                logger.error(f"❌ {service_name} {mode.lower()} failed")

        except Exception as e:
            failed_services.append(service_name)
            error_message = str(e)
            logger.error(f"❌ {service_name} {mode.lower()} failed with exception: {e}")

        # Extract and add service statistics to summary collector
        try:
            stats = extract_service_statistics(service, service_name, result, success)
            summary_collector.add_service_stats(
                service_name=stats['service_name'],
                success=stats['success'],
                teama_count=stats['teama_count'],
                teamb_before_count=stats['teamb_before_count'],
                teamb_after_count=stats['teamb_after_count'],
                created=stats['created'],
                updated=stats['updated'],
                deleted=stats['deleted'],
                failed=stats['failed'],
                skipped=stats['skipped'],
                error_message=error_message or stats.get('error_message')
            )
        except Exception as e:
            logger.warning(f"⚠️  Failed to collect statistics for {service_name}: {e}")
            # Add minimal stats if extraction failed
            summary_collector.add_service_stats(
                service_name=service_name,
                success=success,
                error_message=error_message or f"Statistics extraction failed: {str(e)}"
            )

    # End collection and display summary
    summary_collector.end_collection()

    # Final summary (old format for compatibility)
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"📋 {mode} SUMMARY FOR ALL SERVICES")
    logger.info("=" * 80)
    logger.info(f"📊 Total services processed: {total_services}")
    logger.info(f"✅ Successful: {successful_services}")
    logger.info(f"❌ Failed: {len(failed_services)}")
    logger.info(f"📈 Success rate: {(successful_services / total_services * 100):.1f}%")

    if failed_services:
        logger.warning(f"⚠️ Failed services: {', '.join(failed_services)}")

    logger.info("=" * 80)

    # Display detailed summary table and save JSON
    summary_collector.display_and_save()

    return len(failed_services) == 0


def main():
    """Main entry point for the DR tool."""
    parser = argparse.ArgumentParser(
        description="Coralogix DR Migration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s parsing-rules --dry-run              # Dry run for parsing rules (exports artifacts)
  %(prog)s parsing-rules                        # Migrate parsing rules
  %(prog)s all --dry-run                        # Dry run for all services
  %(prog)s all                                  # Migrate all services
  %(prog)s all --exclude grafana-dashboards    # Migrate all services except grafana-dashboards
  %(prog)s all --exclude alerts slo tco        # Migrate all services except alerts, slo, and tco
  %(prog)s compare parsing-rules                # Compare artifacts between teams
  %(prog)s status                               # Show status of last run
  %(prog)s apply snapshot.json                  # Apply specific snapshot
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Service commands
    services = [
        'parsing-rules', 'recording-rules', 'enrichments', 'general-enrichments', 'events2metrics',
        'custom-dashboards', 'grafana-dashboards', 'views', 'custom-actions',
        'webhooks', 'alerts', 'slo', 'slo-grpc', 'tco'
    ]
    
    for service in services:
        service_parser = subparsers.add_parser(service, help=f'Migrate {service}')
        service_parser.add_argument(
            '--dry-run', 
            action='store_true', 
            help='Show what would be done without making changes'
        )
        service_parser.add_argument(
            '--force', 
            action='store_true', 
            help='Force migration even if no changes detected'
        )
    
    # All services command
    all_parser = subparsers.add_parser('all', help='Migrate all services')
    all_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done for all services without making changes'
    )
    all_parser.add_argument(
        '--force',
        action='store_true',
        help='Force migration for all services even if no changes detected'
    )
    all_parser.add_argument(
        '--exclude',
        nargs='+',
        metavar='SERVICE',
        help='Exclude specific services from migration (e.g., --exclude grafana-dashboards alerts)'
    )

    # Status command
    status_parser = subparsers.add_parser('status', help='Show status of last run')

    # Compare command
    compare_parser = subparsers.add_parser('compare', help='Compare artifacts between teams')
    compare_parser.add_argument('service', choices=services, help='Service to compare')

    # Apply command
    apply_parser = subparsers.add_parser('apply', help='Apply specific snapshot')
    apply_parser.add_argument('snapshot_file', help='Path to snapshot file')
    apply_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        # Load configuration
        config = Config()
        
        # Setup logging with service-specific name
        if args.command in services:
            service_name = args.command
        elif args.command == 'compare' and hasattr(args, 'service'):
            service_name = args.service
        elif args.command == 'all':
            service_name = 'all-services'
        else:
            service_name = 'dr-tool'
        logger = setup_logger(service_name, 'main', config.log_level)
        
        logger.info(f"Starting DR tool - Command: {args.command}")
        logger.info(f"Dry run: {getattr(args, 'dry_run', False)}")
        
        if args.command == 'status':
            # TODO: Implement status command
            logger.info("Status command not yet implemented")
            return 0
        
        elif args.command == 'compare':
            # Handle artifact comparison
            service = create_service(args.service, config, logger)
            comparison = service.compare_team_artifacts()

            logger.info("=== Artifact Comparison Results ===")
            logger.info(f"Team A artifacts: {comparison['teama_count']} (last updated: {comparison['teama_timestamp']})")
            logger.info(f"Team B artifacts: {comparison['teamb_count']} (last updated: {comparison['teamb_timestamp']})")
            logger.info(f"Resources only in Team A: {len(comparison['only_in_teama'])}")
            logger.info(f"Resources only in Team B: {len(comparison['only_in_teamb'])}")
            logger.info(f"Resources with differences: {len(comparison['different_resources'])}")
            logger.info(f"Sync needed: {comparison['sync_needed']}")

            if comparison['only_in_teama']:
                logger.info("Resources only in Team A:")
                for resource in comparison['only_in_teama']:
                    logger.info(f"  - {service.get_resource_identifier(resource)}")

            if comparison['different_resources']:
                logger.info("Resources with differences:")
                for diff in comparison['different_resources']:
                    logger.info(f"  - {diff['resource_id']}")

            return 0

        elif args.command == 'all':
            # Handle all services migration
            # Combine command line exclusions with environment variable exclusions
            cmd_exclude = getattr(args, 'exclude', None) or []
            env_exclude = []

            if config.exclude_services:
                env_exclude = [s.strip() for s in config.exclude_services.split(',') if s.strip()]

            # Combine both exclusion sources
            all_exclusions = list(set(cmd_exclude + env_exclude))

            if all_exclusions:
                logger.info(f"📋 Services to exclude: {', '.join(all_exclusions)}")

            result = run_all_services(
                config,
                logger,
                dry_run=getattr(args, 'dry_run', False),
                force=getattr(args, 'force', False),
                exclude_services=all_exclusions if all_exclusions else None
            )

            if result:
                logger.info("🎉 Successfully completed migration for all services")
                return 0
            else:
                logger.error("❌ Failed to complete migration for all services")
                return 1

        elif args.command == 'apply':
            # TODO: Implement apply command
            logger.info(f"Apply command not yet implemented for file: {args.snapshot_file}")
            return 0

        elif args.command in services:
            # Handle service migration
            service = create_service(args.command, config, logger)

            if args.dry_run:
                result = service.dry_run()
                # Display formatted dry run results for specific services
                if hasattr(service, 'display_dry_run_results') and isinstance(result, dict):
                    service.display_dry_run_results(result)
            else:
                result = service.migrate()

            if result:
                logger.info(f"Successfully completed {args.command} migration")
                return 0
            else:
                logger.error(f"Failed to complete {args.command} migration")
                return 1
        
        else:
            logger.error(f"Unknown command: {args.command}")
            return 1
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
