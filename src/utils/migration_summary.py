"""
Migration Summary Utility for Coralogix DR Tool.

This module provides functionality to collect, aggregate, and display
migration statistics across all services in both tabular and JSON formats.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from tabulate import tabulate


class MigrationSummaryCollector:
    """Collects and aggregates migration statistics from all services."""
    
    def __init__(self, output_dir: str = "outputs/migration-summary"):
        """
        Initialize the migration summary collector.
        
        Args:
            output_dir: Directory to save summary files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.services_stats: List[Dict[str, Any]] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.mode: str = "MIGRATION"  # or "DRY RUN"
        
    def start_collection(self, mode: str = "MIGRATION"):
        """
        Start collecting migration statistics.
        
        Args:
            mode: Either "MIGRATION" or "DRY RUN"
        """
        self.start_time = datetime.now()
        self.mode = mode
        self.services_stats = []
        
    def add_service_stats(self, service_name: str, success: bool, 
                         teama_count: int = 0, teamb_before_count: int = 0,
                         teamb_after_count: int = 0, created: int = 0,
                         updated: int = 0, deleted: int = 0, 
                         failed: int = 0, skipped: int = 0,
                         error_message: Optional[str] = None):
        """
        Add statistics for a service.
        
        Args:
            service_name: Name of the service
            success: Whether the migration/dry-run succeeded
            teama_count: Total resources in Team A
            teamb_before_count: Total resources in Team B before migration
            teamb_after_count: Total resources in Team B after migration
            created: Number of resources created
            updated: Number of resources updated
            deleted: Number of resources deleted
            failed: Number of failed operations
            skipped: Number of skipped operations
            error_message: Error message if failed
        """
        total_operations = created + updated + deleted + skipped
        success_rate = 0.0
        if total_operations > 0:
            success_rate = ((created + updated + deleted) / total_operations) * 100
        
        stats = {
            'service': service_name,
            'status': 'SUCCESS' if success else 'FAILED',
            'teama_count': teama_count,
            'teamb_before': teamb_before_count,
            'teamb_after': teamb_after_count,
            'created': created,
            'updated': updated,
            'deleted': deleted,
            'failed': failed,
            'skipped': skipped,
            'total_operations': total_operations,
            'success_rate': f"{success_rate:.1f}%",
            'error_message': error_message
        }
        
        self.services_stats.append(stats)
        
    def end_collection(self):
        """End collecting migration statistics."""
        self.end_time = datetime.now()
        
    def get_summary(self) -> Dict[str, Any]:
        """
        Get the complete migration summary.
        
        Returns:
            Dictionary containing all migration statistics
        """
        total_services = len(self.services_stats)
        successful_services = sum(1 for s in self.services_stats if s['status'] == 'SUCCESS')
        failed_services = [s['service'] for s in self.services_stats if s['status'] == 'FAILED']
        
        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        
        return {
            'mode': self.mode,
            'timestamp': self.end_time.isoformat() if self.end_time else datetime.now().isoformat(),
            'duration_seconds': duration,
            'summary': {
                'total_services': total_services,
                'successful_services': successful_services,
                'failed_services': len(failed_services),
                'success_rate': f"{(successful_services / total_services * 100):.1f}%" if total_services > 0 else "0%"
            },
            'failed_service_names': failed_services,
            'services': self.services_stats
        }
        
    def display_table(self):
        """Display migration statistics in tabular format."""
        if not self.services_stats:
            print("\n⚠️  No migration statistics collected")
            return
            
        print("\n" + "=" * 120)
        print(f"📊 {self.mode} SUMMARY - ALL SERVICES")
        print("=" * 120)
        
        # Prepare table data
        table_data = []
        for stats in self.services_stats:
            table_data.append([
                stats['service'],
                stats['status'],
                stats['teama_count'],
                stats['teamb_before'],
                stats['teamb_after'],
                stats['created'],
                stats['updated'],
                stats['deleted'],
                stats['failed'],
                stats['skipped'],
                stats['total_operations'],
                stats['success_rate']
            ])
        
        headers = [
            'Service', 'Status', 'Team A', 'Team B\n(Before)', 'Team B\n(After)',
            'Created', 'Updated', 'Deleted', 'Failed', 'Skipped', 'Total Ops', 'Success %'
        ]
        
        print(tabulate(table_data, headers=headers, tablefmt='grid'))

        # Display overall summary
        summary = self.get_summary()
        print("\n" + "─" * 120)
        print("📈 OVERALL STATISTICS")
        print("─" * 120)
        print(f"{'Total Services Processed:':<30} {summary['summary']['total_services']:>10}")
        print(f"{'Successful Services:':<30} {summary['summary']['successful_services']:>10}")
        print(f"{'Failed Services:':<30} {summary['summary']['failed_services']:>10}")
        print(f"{'Overall Success Rate:':<30} {summary['summary']['success_rate']:>10}")

        if summary['duration_seconds']:
            print(f"{'Total Duration:':<30} {summary['duration_seconds']:>9.1f}s")

        if summary['failed_service_names']:
            print(f"\n⚠️  Failed Services: {', '.join(summary['failed_service_names'])}")

        print("=" * 120 + "\n")

    def save_json(self, filename: Optional[str] = None) -> str:
        """
        Save migration statistics to JSON file.

        Args:
            filename: Optional custom filename. If not provided, generates timestamp-based name.

        Returns:
            Path to the saved JSON file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            mode_suffix = "dry-run" if "DRY" in self.mode else "migration"
            filename = f"migration-summary-{mode_suffix}-{timestamp}.json"

        filepath = self.output_dir / filename

        summary = self.get_summary()

        with open(filepath, 'w') as f:
            json.dump(summary, f, indent=2)

        return str(filepath)

    def save_latest_json(self) -> str:
        """
        Save migration statistics to a 'latest' JSON file.

        Returns:
            Path to the saved JSON file
        """
        mode_suffix = "dry-run" if "DRY" in self.mode else "migration"
        filename = f"migration-summary-{mode_suffix}-latest.json"
        return self.save_json(filename)

    def save_coralogix_logs(self) -> str:
        """
        Save migration statistics as individual log entries for Coralogix.
        Each service and summary component is saved as a separate JSON line.

        Returns:
            Path to the saved log file
        """
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        mode_suffix = "dry-run" if "DRY" in self.mode else "migration"
        filename = f"coralogix-logs-{mode_suffix}-{timestamp}.jsonl"
        filepath = self.output_dir / filename

        summary = self.get_summary()

        with open(filepath, 'w') as f:
            # Write overall summary log
            overall_log = {
                "log_type": "migration_summary",
                "mode": summary['mode'],
                "timestamp": summary['timestamp'],
                "duration_seconds": summary['duration_seconds'],
                "total_services": summary['summary']['total_services'],
                "successful_services": summary['summary']['successful_services'],
                "failed_services": summary['summary']['failed_services'],
                "success_rate": summary['summary']['success_rate']
            }
            f.write(json.dumps(overall_log) + '\n')

            # Write failed services log (if any)
            if summary['failed_service_names']:
                failed_log = {
                    "log_type": "failed_services",
                    "mode": summary['mode'],
                    "timestamp": summary['timestamp'],
                    "failed_service_names": summary['failed_service_names'],
                    "failed_count": len(summary['failed_service_names'])
                }
                f.write(json.dumps(failed_log) + '\n')

            # Write individual service logs
            for service_stats in summary['services']:
                service_log = {
                    "log_type": "service_detail",
                    "mode": summary['mode'],
                    "timestamp": summary['timestamp'],
                    **service_stats  # Unpack all service stats
                }
                f.write(json.dumps(service_log) + '\n')

        return str(filepath)

    def save_coralogix_logs_latest(self) -> str:
        """
        Save migration statistics as individual log entries for Coralogix to a 'latest' file.

        Returns:
            Path to the saved log file
        """
        mode_suffix = "dry-run" if "DRY" in self.mode else "migration"
        filename = f"coralogix-logs-{mode_suffix}-latest.jsonl"
        filepath = self.output_dir / filename

        summary = self.get_summary()

        with open(filepath, 'w') as f:
            # Write overall summary log
            overall_log = {
                "log_type": "migration_summary",
                "mode": summary['mode'],
                "timestamp": summary['timestamp'],
                "duration_seconds": summary['duration_seconds'],
                "total_services": summary['summary']['total_services'],
                "successful_services": summary['summary']['successful_services'],
                "failed_services": summary['summary']['failed_services'],
                "success_rate": summary['summary']['success_rate']
            }
            f.write(json.dumps(overall_log) + '\n')

            # Write failed services log (if any)
            if summary['failed_service_names']:
                failed_log = {
                    "log_type": "failed_services",
                    "mode": summary['mode'],
                    "timestamp": summary['timestamp'],
                    "failed_service_names": summary['failed_service_names'],
                    "failed_count": len(summary['failed_service_names'])
                }
                f.write(json.dumps(failed_log) + '\n')

            # Write individual service logs
            for service_stats in summary['services']:
                service_log = {
                    "log_type": "service_detail",
                    "mode": summary['mode'],
                    "timestamp": summary['timestamp'],
                    **service_stats  # Unpack all service stats
                }
                f.write(json.dumps(service_log) + '\n')

        return str(filepath)

    def display_and_save(self):
        """Display table and save JSON files."""
        self.display_table()

        # Save timestamped version
        timestamped_file = self.save_json()
        print(f"📄 Detailed summary saved to: {timestamped_file}")

        # Save latest version
        latest_file = self.save_latest_json()
        print(f"📄 Latest summary saved to: {latest_file}")

        # Save Coralogix-friendly logs
        coralogix_file = self.save_coralogix_logs()
        print(f"📄 Coralogix logs saved to: {coralogix_file}")

        # Save Coralogix-friendly logs (latest)
        coralogix_latest_file = self.save_coralogix_logs_latest()
        print(f"📄 Coralogix logs (latest) saved to: {coralogix_latest_file}")
        print("")

