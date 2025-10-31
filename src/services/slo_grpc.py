#!/usr/bin/env python3
"""
SLO gRPC Service for Coralogix DR Migration Tool.
Handles SLO migration using gRPC calls via grpcurl subprocess.
"""

import json
import os
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from core.base_service import BaseService
from core.grpcurl_client import CoralogixGRPCClient, GRPCConfig, GRPCError


class SLOGRPCService(BaseService):
    """SLO service using gRPC calls for migration operations."""
    
    def __init__(self, config):
        """Initialize the SLO gRPC service."""
        super().__init__(config)

        # Check if grpcurl is available
        import shutil
        if not shutil.which("grpcurl"):
            error_msg = "grpcurl is required for SLO gRPC service but is not installed."
            print(f"\n❌ {error_msg}")
            print("📦 Please install grpcurl:")
            print("   macOS: brew install grpcurl")
            print("   Linux: Download from https://github.com/fullstorydev/grpcurl/releases")
            print("   Windows: Download from https://github.com/fullstorydev/grpcurl/releases")
            raise ValueError(error_msg)

        try:
            print("🔍 Initializing gRPC clients...")

            # Initialize gRPC clients for both teams
            print("🔍 Creating Team A gRPC client...")
            self.teama_grpc_client = self._create_grpc_client("TEAMA")
            print("✅ Team A gRPC client created")

            print("🔍 Creating Team B gRPC client...")
            self.teamb_grpc_client = self._create_grpc_client("TEAMB")
            print("✅ Team B gRPC client created")

            # Track failed operations for logging
            self.failed_slos = []

            print("✅ SLO gRPC service initialized successfully")

        except Exception as e:
            print(f"❌ Failed to initialize SLO gRPC service: {e}")
            raise
    
    def _create_grpc_client(self, team: str) -> CoralogixGRPCClient:
        """
        Create a gRPC client for the specified team.
        
        Args:
            team: Team identifier ("TEAMA" or "TEAMB")
            
        Returns:
            Configured CoralogixGRPCClient
        """
        domain_key = f"CX_DOMAIN_{team}"
        api_key_key = f"CX_API_KEY_{team}"
        
        domain = os.getenv(domain_key)
        api_key = os.getenv(api_key_key)
        
        if not domain:
            raise ValueError(f"Environment variable {domain_key} is required")
        if not api_key:
            raise ValueError(f"Environment variable {api_key_key} is required")
        
        grpc_config = GRPCConfig(
            domain=domain,
            api_key=api_key,
            timeout=int(os.getenv("GRPC_TIMEOUT", "30")),
            max_retries=int(os.getenv("GRPC_MAX_RETRIES", "3")),
            debug=os.getenv("GRPC_DEBUG", "false").lower() == "true"
        )
        
        return CoralogixGRPCClient(grpc_config)
    
    def get_service_name(self) -> str:
        """Get the service name."""
        return "slo-grpc"

    @property
    def service_name(self) -> str:
        """Service name property (required by BaseService)."""
        return "slo-grpc"

    @property
    def api_endpoint(self) -> str:
        """API endpoint property (required by BaseService)."""
        return "/v1/slo/slos"  # Not used in gRPC service but required by base class
    
    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get the name of an SLO resource."""
        return resource.get('name', 'Unknown SLO')
    
    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get the unique identifier of an SLO resource."""
        return resource.get('id', 'Unknown ID')
    
    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """
        Fetch all SLOs from Team A using gRPC.
        
        Returns:
            List of SLO resources from Team A
        """
        try:
            self.logger.info("🔄 Fetching SLOs from Team A via gRPC...")
            
            response = self.teama_grpc_client.list_slos()
            slos = response.get('slos', [])
            
            self.logger.info(f"✅ Fetched {len(slos)} SLOs from Team A")
            
            # Log sample SLO structure for debugging
            if slos and self.logger.isEnabledFor(10):  # DEBUG level
                sample_slo = slos[0]
                self.logger.debug(f"🔍 Sample SLO structure from Team A:")
                self.logger.debug(f"🔍 {json.dumps(sample_slo, indent=2, default=str)}")
            
            return slos
            
        except GRPCError as e:
            self.logger.error(f"❌ Failed to fetch SLOs from Team A: {e}")
            raise
        except Exception as e:
            self.logger.error(f"❌ Unexpected error fetching SLOs from Team A: {e}")
            raise
    
    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """
        Fetch all SLOs from Team B using gRPC.
        
        Returns:
            List of SLO resources from Team B
        """
        try:
            self.logger.info("🔄 Fetching SLOs from Team B via gRPC...")
            
            response = self.teamb_grpc_client.list_slos()
            slos = response.get('slos', [])
            
            self.logger.info(f"✅ Fetched {len(slos)} SLOs from Team B")
            return slos
            
        except GRPCError as e:
            self.logger.error(f"❌ Failed to fetch SLOs from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"❌ Unexpected error fetching SLOs from Team B: {e}")
            raise
    
    def _clean_slo_for_creation(self, slo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean SLO data for creation by removing read-only fields.
        
        Args:
            slo: Original SLO data from Team A
            
        Returns:
            Cleaned SLO data ready for creation in Team B
        """
        slo_name = slo.get('name', 'Unknown')
        self.logger.debug(f"🔍 Cleaning SLO '{slo_name}' for creation")
        
        # Fields to remove for creation (read-only or auto-generated fields)
        fields_to_remove = [
            'id',           # Auto-generated by API
            'revision',     # Auto-generated by API
            'createTime',   # Auto-generated timestamp
            'updateTime',   # Auto-generated timestamp
            'createdAt',    # Alternative timestamp field
            'updatedAt',    # Alternative timestamp field
            'status',       # Calculated by API
            'sloStatus',    # Calculated by API
            'errorBudget',  # Calculated by API
            'burnRate',     # Calculated by API
            'currentHealth',# Calculated by API
            'groping',      # Typo field that sometimes appears
            'grouping',     # Can cause validation errors
        ]
        
        cleaned_slo = {}
        removed_fields = []
        
        for key, value in slo.items():
            if key not in fields_to_remove:
                cleaned_slo[key] = value
            else:
                removed_fields.append(key)
        
        if removed_fields:
            self.logger.debug(f"🔍 Removed fields from SLO '{slo_name}': {removed_fields}")
        
        # Validate required fields
        if 'name' not in cleaned_slo:
            raise ValueError(f"SLO name is required for creation")
        if 'targetThresholdPercentage' not in cleaned_slo and 'target_threshold_percentage' not in cleaned_slo:
            raise ValueError(f"SLO target threshold percentage is required for creation")
        
        self.logger.debug(f"✅ Cleaned SLO '{slo_name}' ready for creation")
        return cleaned_slo
    
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create an SLO in Team B using gRPC.
        
        Args:
            resource: SLO data to create
            
        Returns:
            Created SLO response
        """
        slo_name = self.get_resource_name(resource)
        
        try:
            self.logger.info(f"🔄 Creating SLO in Team B via gRPC: {slo_name}")
            
            # Clean the SLO data for creation
            cleaned_slo = self._clean_slo_for_creation(resource)
            
            # Log the cleaned payload for debugging
            if self.logger.isEnabledFor(10):  # DEBUG level
                self.logger.debug(f"🔍 Creating SLO with payload:")
                self.logger.debug(f"🔍 {json.dumps(cleaned_slo, indent=2, default=str)}")
            
            # Create SLO via gRPC
            response = self.teamb_grpc_client.create_slo(cleaned_slo)
            
            self.logger.info(f"✅ Successfully created SLO: {slo_name}")
            return response
            
        except GRPCError as e:
            self.logger.error(f"❌ Failed to create SLO '{slo_name}' via gRPC: {e}")
            self._log_failed_slo(resource, 'create', str(e))
            raise
        except Exception as e:
            self.logger.error(f"❌ Unexpected error creating SLO '{slo_name}': {e}")
            self._log_failed_slo(resource, 'create', str(e))
            raise
    
    def delete_resource_in_teamb(self, resource: Dict[str, Any]) -> bool:
        """
        Delete an SLO in Team B using gRPC.
        
        Args:
            resource: SLO data to delete (must contain 'id')
            
        Returns:
            True if deletion was successful
        """
        slo_name = self.get_resource_name(resource)
        slo_id = self.get_resource_identifier(resource)
        
        try:
            self.logger.info(f"🔄 Deleting SLO in Team B via gRPC: {slo_name} (ID: {slo_id})")
            
            # Delete SLO via gRPC
            response = self.teamb_grpc_client.delete_slo(slo_id)
            
            self.logger.info(f"✅ Successfully deleted SLO: {slo_name}")
            return True
            
        except GRPCError as e:
            self.logger.error(f"❌ Failed to delete SLO '{slo_name}' via gRPC: {e}")
            self._log_failed_slo(resource, 'delete', str(e))
            return False
        except Exception as e:
            self.logger.error(f"❌ Unexpected error deleting SLO '{slo_name}': {e}")
            self._log_failed_slo(resource, 'delete', str(e))
            return False

    def delete_resource_from_teamb(self, resource: Dict[str, Any]) -> bool:
        """
        Delete an SLO from Team B (required by BaseService).
        This is an alias for delete_resource_in_teamb.

        Args:
            resource: SLO data to delete

        Returns:
            True if deletion was successful
        """
        return self.delete_resource_in_teamb(resource)

    def _log_failed_slo(self, slo: Dict[str, Any], operation: str, error: str):
        """
        Log a failed SLO operation for later analysis.
        
        Args:
            slo: SLO data that failed
            operation: Operation that failed ('create', 'delete', 'update')
            error: Error message
        """
        failed_entry = {
            'timestamp': datetime.now().isoformat(),
            'operation': operation,
            'slo_name': self.get_resource_name(slo),
            'slo_id': self.get_resource_identifier(slo),
            'error': error,
            'slo_data': slo
        }
        
        self.failed_slos.append(failed_entry)
        
        # Log to file for persistence
        self.log_resource_action(operation, "slo", self.get_resource_name(slo), False, error)

    def compare_resources(self, teama_resources: List[Dict[str, Any]],
                         teamb_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare SLOs between Team A and Team B.

        Args:
            teama_resources: SLOs from Team A
            teamb_resources: SLOs from Team B

        Returns:
            Dictionary with comparison results
        """
        self.logger.info("🔍 Comparing SLOs between Team A and Team B...")

        # Create lookup dictionaries by name (SLOs are typically identified by name)
        teama_by_name = {slo.get('name'): slo for slo in teama_resources if slo.get('name')}
        teamb_by_name = {slo.get('name'): slo for slo in teamb_resources if slo.get('name')}

        # Find new SLOs (in Team A but not in Team B)
        new_in_teama = []
        for name, slo in teama_by_name.items():
            if name not in teamb_by_name:
                new_in_teama.append(slo)

        # Find deleted SLOs (in Team B but not in Team A)
        deleted_from_teama = []
        for name, slo in teamb_by_name.items():
            if name not in teama_by_name:
                deleted_from_teama.append(slo)

        # Find changed SLOs (exist in both but are different)
        changed_resources = []
        for name in teama_by_name:
            if name in teamb_by_name:
                teama_slo = teama_by_name[name]
                teamb_slo = teamb_by_name[name]

                # Compare SLOs (excluding metadata fields)
                if self._slos_are_different(teama_slo, teamb_slo):
                    changed_resources.append((teama_slo, teamb_slo))

        comparison_result = {
            'new_in_teama': new_in_teama,
            'deleted_from_teama': deleted_from_teama,
            'changed_resources': changed_resources,
            'total_teama': len(teama_resources),
            'total_teamb': len(teamb_resources)
        }

        self.logger.info(f"📊 Comparison results:")
        self.logger.info(f"  📊 Team A SLOs: {comparison_result['total_teama']}")
        self.logger.info(f"  📊 Team B SLOs: {comparison_result['total_teamb']}")
        self.logger.info(f"  ➕ New SLOs to create: {len(new_in_teama)}")
        self.logger.info(f"  🔄 Changed SLOs to recreate: {len(changed_resources)}")
        self.logger.info(f"  ➖ SLOs to delete: {len(deleted_from_teama)}")

        return comparison_result

    def _slos_are_different(self, teama_slo: Dict[str, Any], teamb_slo: Dict[str, Any]) -> bool:
        """
        Compare two SLOs to determine if they are different.

        Args:
            teama_slo: SLO from Team A
            teamb_slo: SLO from Team B

        Returns:
            True if SLOs are different and need to be updated
        """
        # Fields to ignore when comparing (metadata/calculated fields)
        ignore_fields = {
            'id', 'revision', 'createTime', 'updateTime', 'createdAt', 'updatedAt',
            'status', 'sloStatus', 'errorBudget', 'burnRate', 'currentHealth'
        }

        # Clean both SLOs for comparison
        clean_teama = {k: v for k, v in teama_slo.items() if k not in ignore_fields}
        clean_teamb = {k: v for k, v in teamb_slo.items() if k not in ignore_fields}

        # Convert to JSON strings for comparison (handles nested objects)
        teama_json = json.dumps(clean_teama, sort_keys=True, default=str)
        teamb_json = json.dumps(clean_teamb, sort_keys=True, default=str)

        are_different = teama_json != teamb_json

        if are_different:
            slo_name = teama_slo.get('name', 'Unknown')
            self.logger.debug(f"🔍 SLO '{slo_name}' has changes between Team A and Team B")

        return are_different

    def migrate(self, dry_run: bool = False) -> bool:
        """
        Migrate SLOs from Team A to Team B using gRPC.

        Args:
            dry_run: If True, only show what would be migrated without making changes

        Returns:
            True if migration was successful
        """
        try:
            self.logger.info(f"🚀 Starting SLO gRPC migration (dry_run={dry_run})")

            # Step 1: Fetch resources from both teams
            self.logger.info("📥 Step 1: Fetching SLOs from both teams...")
            teama_slos = self.fetch_resources_from_teama()
            teamb_slos = self.fetch_resources_from_teamb()

            # Step 2: Compare resources
            self.logger.info("🔍 Step 2: Comparing SLOs...")
            comparison = self.compare_resources(teama_slos, teamb_slos)

            # Step 3: Show migration plan
            total_operations = (len(comparison['new_in_teama']) +
                              len(comparison['changed_resources']) +
                              len(comparison['deleted_from_teama']))

            if total_operations == 0:
                self.logger.info("✅ No changes needed - all SLOs are already synchronized!")
                return True

            if dry_run:
                return self._display_dry_run_results(comparison)

            # Step 4: Perform actual migration
            self.logger.info("🔄 Step 3: Performing migration...")
            return self._perform_migration(comparison)

        except Exception as e:
            self.logger.error(f"❌ Migration failed: {e}")
            return False

    def _display_dry_run_results(self, comparison: Dict[str, Any]) -> bool:
        """
        Display dry run results in a formatted way.

        Args:
            comparison: Comparison results from compare_resources

        Returns:
            True (dry run always succeeds)
        """
        print("\n" + "=" * 80)
        print("DRY RUN RESULTS - SLO gRPC MIGRATION")
        print("=" * 80)

        # Display statistics table
        self._display_migration_results_table([{
            'resource_type': 'SLOs',
            'total': comparison['total_teama'],
            'created': len(comparison['new_in_teama']),
            'recreated': len(comparison['changed_resources']),
            'deleted': len(comparison['deleted_from_teama']),
            'failed': 0,
            'success_rate': '100.0%'
        }])

        # Show details for new SLOs
        if comparison['new_in_teama']:
            print(f"\n✅ New SLOs to create in Team B: {len(comparison['new_in_teama'])}")
            for slo in comparison['new_in_teama'][:5]:  # Show first 5
                print(f"  + {self.get_resource_name(slo)}")
            if len(comparison['new_in_teama']) > 5:
                print(f"  ... and {len(comparison['new_in_teama']) - 5} more")

        # Show details for changed SLOs
        if comparison['changed_resources']:
            print(f"\n🔄 Changed SLOs to recreate in Team B: {len(comparison['changed_resources'])}")
            for teama_slo, teamb_slo in comparison['changed_resources'][:5]:  # Show first 5
                print(f"  ~ {self.get_resource_name(teama_slo)}")
            if len(comparison['changed_resources']) > 5:
                print(f"  ... and {len(comparison['changed_resources']) - 5} more")

        # Show details for deleted SLOs
        if comparison['deleted_from_teama']:
            print(f"\n🗑️ SLOs to delete from Team B: {len(comparison['deleted_from_teama'])}")
            for slo in comparison['deleted_from_teama'][:5]:  # Show first 5
                print(f"  - {self.get_resource_name(slo)}")
            if len(comparison['deleted_from_teama']) > 5:
                print(f"  ... and {len(comparison['deleted_from_teama']) - 5} more")

        total_operations = (len(comparison['new_in_teama']) +
                          len(comparison['changed_resources']) +
                          len(comparison['deleted_from_teama']))

        if total_operations > 0:
            print(f"\n📋 Ready to migrate! Run without --dry-run to execute these changes.")
        else:
            print("\n✨ No changes detected - Team B is already in sync with Team A")

        print("=" * 80)
        return True

    def _display_migration_results_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""

        # Table headers
        headers = [
            "Resource Type",
            "Total",
            "Created",
            "Recreated",
            "Deleted",
            "Failed",
            "Success Rate"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['resource_type']) for row in table_data)),
            max(len(headers[1]), max(len(str(row['total'])) for row in table_data)),
            max(len(headers[2]), max(len(str(row['created'])) for row in table_data)),
            max(len(headers[3]), max(len(str(row['recreated'])) for row in table_data)),
            max(len(headers[4]), max(len(str(row['deleted'])) for row in table_data)),
            max(len(headers[5]), max(len(str(row['failed'])) for row in table_data)),
            max(len(headers[6]), max(len(row['success_rate']) for row in table_data))
        ]

        # Create table borders
        total_width = sum(col_widths) + len(col_widths) * 3 + 1
        top_border = "┌" + "─" * (total_width - 2) + "┐"
        middle_border = "├" + "─" * (total_width - 2) + "┤"
        bottom_border = "└" + "─" * (total_width - 2) + "┘"

        print(top_border)

        # Header row
        header_row = "│"
        for i, header in enumerate(headers):
            if i == 0:  # Resource type - left aligned
                header_row += f" {header:<{col_widths[i]}} │"
            else:  # Numbers - right aligned
                header_row += f" {header:>{col_widths[i]}} │"

        print(header_row)
        print(middle_border)

        # Data rows
        for row in table_data:
            data_row = "│"
            values = [
                row['resource_type'],
                str(row['total']),
                str(row['created']),
                str(row['recreated']),
                str(row['deleted']),
                str(row['failed']),
                row['success_rate']
            ]

            for i, value in enumerate(values):
                if i == 0:  # Resource type - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers and percentages - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def _perform_migration(self, comparison: Dict[str, Any]) -> bool:
        """
        Perform the actual migration based on comparison results.

        Args:
            comparison: Comparison results from compare_resources

        Returns:
            True if migration was successful
        """
        success_count = 0
        error_count = 0

        # Initialize counters for detailed statistics
        slos_created = 0
        slos_recreated = 0
        slos_deleted = 0

        try:
            # Step 1: Delete SLOs that exist in Team B but not in Team A
            if comparison['deleted_from_teama']:
                self.logger.info(f"🗑️ Deleting {len(comparison['deleted_from_teama'])} SLOs from Team B...")
                for slo in comparison['deleted_from_teama']:
                    try:
                        if self.delete_resource_in_teamb(slo):
                            success_count += 1
                            slos_deleted += 1
                        else:
                            error_count += 1
                    except Exception as e:
                        self.logger.error(f"❌ Failed to delete SLO: {e}")
                        error_count += 1

            # Step 2: Delete and recreate changed SLOs
            if comparison['changed_resources']:
                self.logger.info(f"🔄 Recreating {len(comparison['changed_resources'])} changed SLOs...")
                for teama_slo, teamb_slo in comparison['changed_resources']:
                    try:
                        # Delete the existing SLO in Team B
                        if self.delete_resource_in_teamb(teamb_slo):
                            # Create the updated SLO from Team A
                            self.create_resource_in_teamb(teama_slo)
                            success_count += 2  # Delete + Create
                            slos_recreated += 1
                        else:
                            error_count += 1
                    except Exception as e:
                        self.logger.error(f"❌ Failed to recreate SLO: {e}")
                        error_count += 1

            # Step 3: Create new SLOs
            if comparison['new_in_teama']:
                self.logger.info(f"➕ Creating {len(comparison['new_in_teama'])} new SLOs in Team B...")
                for slo in comparison['new_in_teama']:
                    try:
                        self.create_resource_in_teamb(slo)
                        success_count += 1
                        slos_created += 1
                    except Exception as e:
                        self.logger.error(f"❌ Failed to create SLO: {e}")
                        error_count += 1

            # Display comprehensive completion statistics in tabular format
            migration_success = error_count == 0

            print("\n" + "=" * 80)
            print("🎯 SLO gRPC MIGRATION RESULTS")
            print("=" * 80)

            # Prepare table data
            total_operations = success_count + error_count
            success_rate = (success_count / total_operations * 100) if total_operations > 0 else 0

            table_data = [{
                'resource_type': 'SLOs',
                'total': total_operations,
                'created': slos_created,
                'recreated': slos_recreated,
                'deleted': slos_deleted,
                'failed': error_count,
                'success_rate': f"{success_rate:.1f}%"
            }]

            # Display the table
            self._display_migration_results_table(table_data)

            # Summary message
            if migration_success:
                print("🎉 Migration completed successfully!")
                if slos_created > 0:
                    print(f"   ➕ {slos_created} new SLOs created")
                if slos_recreated > 0:
                    print(f"   🔄 {slos_recreated} SLOs recreated (updated)")
                if slos_deleted > 0:
                    print(f"   🗑️ {slos_deleted} SLOs deleted")
                if slos_created + slos_recreated + slos_deleted == 0:
                    print("   ✅ All resources were already synchronized")
            else:
                print(f"❌ Migration completed with {error_count} errors")
                print("   Check the logs above for detailed error information")

            print("=" * 80)

            # Log failed SLOs if any
            if self.failed_slos:
                self.logger.warning(f"⚠️ {len(self.failed_slos)} SLO operations failed:")
                for failed in self.failed_slos[:5]:  # Show first 5
                    self.logger.warning(f"  - {failed['slo_name']}: {failed['error']}")
                if len(self.failed_slos) > 5:
                    self.logger.warning(f"  ... and {len(self.failed_slos) - 5} more failures")

            # Log completion
            self.log_migration_complete(self.service_name, migration_success,
                                      len(comparison['new_in_teama']) + len(comparison['changed_resources']),
                                      error_count)

            return migration_success

        except Exception as e:
            self.logger.error(f"❌ Migration failed with unexpected error: {e}")
            return False

    def dry_run(self) -> bool:
        """
        Perform a dry run of the migration.

        Returns:
            True if dry run completed successfully
        """
        return self.migrate(dry_run=True)

    def run(self) -> bool:
        """
        Perform the actual migration.

        Returns:
            True if migration was successful
        """
        return self.migrate(dry_run=False)
