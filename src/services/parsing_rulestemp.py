"""
Parsing Rules migration service for Coralogix DR Tool.

This service handles the migration of parsing rule groups between Team A and Team B.
It supports:
- Fetching rule groups from both teams
- Creating new rule groups in Team B
- Deleting rule groups from Team B
- Comparing rule groups to detect changes
- Dry-run functionality
- Failed operations logging with exponential backoff
"""

from typing import Dict, List, Any
from pathlib import Path

from core.base_service import BaseService
from core.config import Config
from core.api_client import CoralogixAPIError


class ParsingRulesService(BaseService):
    """Service for migrating parsing rule groups between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_rules_logging()

    @property
    def service_name(self) -> str:
        return "parsing-rules"

    @property
    def api_endpoint(self) -> str:
        return "/api/v1/rulegroups"
    
    def _setup_failed_rules_logging(self):
        """Setup logging directory for failed parsing rules."""
        self.failed_rules_dir = Path("logs/parsing_rules")
        self.failed_rules_dir.mkdir(parents=True, exist_ok=True)

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all parsing rule groups from Team A."""
        try:
            self.logger.info("Fetching parsing rule groups from Team A")

            # Make direct API call to get rule groups
            response = self.teama_client.get(self.api_endpoint)

            # Extract rule groups from response
            rule_groups = response.get('ruleGroups', [])

            self.logger.info(f"Fetched {len(rule_groups)} parsing rule groups from Team A")
            return rule_groups

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch parsing rule groups from Team A: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching parsing rule groups from Team A: {e}")
            raise
    
    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all parsing rule groups from Team B."""
        try:
            self.logger.info("Fetching parsing rule groups from Team B")

            # Make direct API call to get rule groups
            response = self.teamb_client.get(self.api_endpoint)

            # Extract rule groups from response
            rule_groups = response.get('ruleGroups', [])

            self.logger.info(f"Fetched {len(rule_groups)} parsing rule groups from Team B")
            return rule_groups

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch parsing rule groups from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching parsing rule groups from Team B: {e}")
            raise
    
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create a parsing rule group in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_resource_for_creation(resource)
            rule_group_name = create_data.get('name', 'Unknown')

            self.logger.info(f"Creating parsing rule group in Team B: {rule_group_name}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Create the rule group with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=create_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "parsing_rule_group", rule_group_name, True)

            # Return the rule group from the response
            return response.get('ruleGroup', response)

        except Exception as e:
            rule_group_name = resource.get('name', 'Unknown')
            self._log_failed_rule_group(resource, 'create', str(e))
            self.log_resource_action("create", "parsing_rule_group", rule_group_name, False, str(e))
            raise
    
    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete a parsing rule group from Team B."""
        try:
            self.logger.info(f"Deleting parsing rule group from Team B: {resource_id}")

            # Delete the rule group
            self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self.log_resource_action("delete", "parsing_rule_group", resource_id, True)
            return True

        except Exception as e:
            self.log_resource_action("delete", "parsing_rule_group", resource_id, False, str(e))
            raise
    
    def _add_creation_delay(self):
        """Add a small delay before creation to avoid overwhelming the API."""
        import time
        delay_seconds = 0.5  # 500ms delay between creations
        time.sleep(delay_seconds)

    def _retry_with_exponential_backoff(self, operation, max_retries: int = 3):
        """Retry an operation with exponential backoff."""
        import time

        for attempt in range(max_retries):
            try:
                return operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise

                wait_time = (2 ** attempt) * 1  # 1s, 2s, 4s
                self.logger.warning(f"Operation failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

    def _log_failed_rule_group(self, rule_group: Dict[str, Any], operation: str, error: str):
        """Log failed rule group operations to a separate file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.failed_rules_dir / f"failed_parsing_rules_{timestamp}.json"

        failed_entry = {
            "timestamp": datetime.now().isoformat(),
            "rule_group_id": rule_group.get('id', 'Unknown'),
            "rule_group_name": rule_group.get('name', 'Unknown'),
            "operation": operation,
            "error": error,
            "rule_group_data": rule_group
        }

        # Load existing failed entries or create new list
        failed_entries = []
        if failed_log_file.exists():
            try:
                with open(failed_log_file, 'r') as f:
                    existing_data = json.load(f)
                    failed_entries = existing_data.get('failed_rule_groups', [])
            except Exception:
                pass

        failed_entries.append(failed_entry)

        # Save updated failed entries
        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "total_failed": len(failed_entries),
            "failed_rule_groups": failed_entries
        }

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(failed_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write failed rule groups log: {e}")

    def _prepare_resource_for_creation(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare a parsing rule group resource for creation by removing fields that
        shouldn't be included in the create request.
        """
        # Fields to exclude from creation (read-only or system-generated)
        exclude_fields = {
            'id', 'teamId'  # These are system-generated
        }

        # Create a copy without excluded fields
        create_data = {
            k: v for k, v in resource.items()
            if k not in exclude_fields and v is not None
        }

        return create_data
    
    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a parsing rule group."""
        # Rule groups are typically identified by name
        return resource.get('name', resource.get('id', ''))

    def resources_are_equal(self, resource_a: Dict[str, Any], resource_b: Dict[str, Any]) -> bool:
        """
        Compare two parsing rule groups to see if they are equal.
        """
        # Fields to ignore in comparison (system-generated or metadata)
        ignore_fields = {
            'id', 'teamId'  # System-generated fields
        }

        def normalize_resource(resource):
            return {
                k: v for k, v in resource.items()
                if k not in ignore_fields
            }

        normalized_a = normalize_resource(resource_a)
        normalized_b = normalize_resource(resource_b)

        return normalized_a == normalized_b
    
    def migrate(self) -> bool:
        """
        Perform the actual parsing rule groups migration.

        Implementation:
        1. Fetch rule groups from Team A and Team B
        2. Compare to identify new, changed, and deleted rule groups
        3. Delete changed/deleted rule groups from Team B
        4. Create new/changed rule groups in Team B

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Fetch current resources from both teams
            self.logger.info("Fetching resources from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            self.logger.info("Fetching resources from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Save artifacts
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # Compare resources to identify changes
            comparison = self._compare_rule_groups(teama_resources, teamb_resources)

            self.logger.info(
                "Migration plan",
                total_teama_resources=len(teama_resources),
                total_teamb_resources=len(teamb_resources),
                new_resources=len(comparison['new_in_teama']),
                changed_resources=len(comparison['changed_resources']),
                deleted_resources=len(comparison['deleted_from_teama'])
            )

            success_count = 0
            error_count = 0

            # Handle deleted resources (exist in Team B but not in Team A)
            for teamb_resource in comparison['deleted_from_teama']:
                try:
                    resource_id = teamb_resource.get('id')
                    if resource_id:
                        self.delete_resource_from_teamb(resource_id)
                        success_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to delete resource {teamb_resource.get('name', 'Unknown')}: {e}")
                    error_count += 1

            # Handle changed resources (delete and recreate)
            for teama_resource, teamb_resource in comparison['changed_resources']:
                resource_name = teama_resource.get('name', 'Unknown')

                try:
                    # Delete existing resource in Team B
                    teamb_id = teamb_resource.get('id')
                    if teamb_id:
                        self.delete_resource_from_teamb(teamb_id)

                    # Create new resource in Team B
                    self.create_resource_in_teamb(teama_resource)
                    success_count += 1

                except Exception as e:
                    self.logger.error(f"Failed to recreate changed resource {resource_name}: {e}")
                    error_count += 1

            # Handle new resources (exist in Team A but not in Team B)
            for teama_resource in comparison['new_in_teama']:
                resource_name = teama_resource.get('name', 'Unknown')

                try:
                    self.create_resource_in_teamb(teama_resource)
                    success_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to create new resource {resource_name}: {e}")
                    error_count += 1

            # Log completion
            migration_success = error_count == 0
            self.log_migration_complete(
                self.service_name,
                migration_success,
                success_count,
                error_count
            )

            return migration_success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def dry_run(self) -> Dict[str, Any]:
        """
        Perform a dry run of the parsing rule groups migration.
        Shows what would be done without making actual changes.

        Returns:
            Dictionary containing dry run results
        """
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch current resources from both teams
            self.logger.info("Fetching resources from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            self.logger.info("Fetching resources from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Save artifacts for comparison
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # Compare resources to identify changes
            comparison = self._compare_rule_groups(teama_resources, teamb_resources)

            # Prepare results
            results = {
                'teama_count': len(teama_resources),
                'teamb_count': len(teamb_resources),
                'to_create': comparison['new_in_teama'],
                'to_recreate': comparison['changed_resources'],
                'to_delete': comparison['deleted_from_teama'],
                'total_operations': len(comparison['new_in_teama']) + len(comparison['changed_resources']) + len(comparison['deleted_from_teama'])
            }

            # Log summary
            self.logger.info(f"Dry run completed:")
            self.logger.info(f"  Team A rule groups: {len(teama_resources)}")
            self.logger.info(f"  Team B rule groups: {len(teamb_resources)}")
            self.logger.info(f"  New rule groups to create: {len(comparison['new_in_teama'])}")
            self.logger.info(f"  Changed rule groups to recreate: {len(comparison['changed_resources'])}")
            self.logger.info(f"  Rule groups to delete: {len(comparison['deleted_from_teama'])}")
            self.logger.info(f"  Total operations: {results['total_operations']}")

            self.log_migration_complete(self.service_name, True, len(teama_resources), 0)
            return results

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return {
                'teama_count': 0,
                'teamb_count': 0,
                'to_create': [],
                'to_recreate': [],
                'to_delete': [],
                'total_operations': 0,
                'error': str(e)
            }

    def display_dry_run_results(self, results: Dict[str, Any]):
        """
        Display formatted dry run results.

        Args:
            results: Dry run results dictionary
        """
        print("\n" + "=" * 60)
        print("DRY RUN RESULTS - PARSING RULE GROUPS")
        print("=" * 60)

        print(f"📊 Team A rule groups: {results['teama_count']}")
        print(f"📊 Team B rule groups: {results['teamb_count']}")

        if results['to_create']:
            print(f"✅ New rule groups to create in Team B: {len(results['to_create'])}")
            for resource in results['to_create']:
                print(f"  + {resource.get('name', 'Unknown')} (ID: {resource.get('id', 'N/A')})")

        if results['to_recreate']:
            print(f"🔄 Changed rule groups to recreate in Team B: {len(results['to_recreate'])}")
            for teama_resource, teamb_resource in results['to_recreate']:
                print(f"  ~ {teama_resource.get('name', 'Unknown')} (Team A ID: {teama_resource.get('id', 'N/A')}, Team B ID: {teamb_resource.get('id', 'N/A')})")

        if results['to_delete']:
            print(f"🗑️ Rule groups to delete from Team B: {len(results['to_delete'])}")
            for resource in results['to_delete']:
                print(f"  - {resource.get('name', 'Unknown')} (ID: {resource.get('id', 'N/A')})")

        print(f"📋 Total operations planned: {results['total_operations']}")

        if results['total_operations'] > 0:
            print(f"  - Create: {len(results['to_create'])}")
            print(f"  - Recreate: {len(results['to_recreate'])}")
            print(f"  - Delete: {len(results['to_delete'])}")
        else:
            print("✨ No changes detected - Team B is already in sync with Team A")

        print("=" * 60)

    def _compare_rule_groups(self, teama_resources: List[Dict[str, Any]], teamb_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare rule groups between Team A and Team B to identify changes.

        Returns:
            Dictionary with:
            - new_in_teama: Resources that exist in Team A but not in Team B
            - changed_resources: Resources that exist in both but are different
            - deleted_from_teama: Resources that exist in Team B but not in Team A
        """
        # Create lookup dictionaries by name (rule groups are identified by name)
        teama_by_name = {resource.get('name'): resource for resource in teama_resources}
        teamb_by_name = {resource.get('name'): resource for resource in teamb_resources}

        new_in_teama = []
        changed_resources = []
        deleted_from_teama = []

        # Find new and changed resources
        for name, teama_resource in teama_by_name.items():
            if name not in teamb_by_name:
                # Resource exists in Team A but not in Team B - new
                new_in_teama.append(teama_resource)
            else:
                # Resource exists in both teams - check if changed
                teamb_resource = teamb_by_name[name]
                if not self.resources_are_equal(teama_resource, teamb_resource):
                    changed_resources.append((teama_resource, teamb_resource))

        # Find deleted resources (exist in Team B but not in Team A)
        for name, teamb_resource in teamb_by_name.items():
            if name not in teama_by_name:
                deleted_from_teama.append(teamb_resource)

        return {
            'new_in_teama': new_in_teama,
            'changed_resources': changed_resources,
            'deleted_from_teama': deleted_from_teama
        }