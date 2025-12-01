"""
Custom Actions migration service for Coralogix DR Tool.

This service handles migration of custom actions between teams using
the delete & recreate pattern for reliable migration.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from core.base_service import BaseService
from core.api_client import CoralogixAPIError
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager


class CustomActionsService(BaseService):
    """Service for migrating custom actions between teams."""

    def __init__(self, config, logger=None):
        super().__init__(config, logger)
        self.failed_actions = []  # Track failed actions for logging
        self.creation_delay = 1.0  # Default delay between operations (seconds)
        self.max_retries = 3  # Maximum number of retries for failed operations
        self.base_backoff = 2.0  # Base backoff time in seconds
        # Initialize safety and version managers
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "custom-actions"

    @property
    def api_endpoint(self) -> str:
        return "/v2/actions"

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get unique identifier for a custom action."""
        return str(resource.get('id', 'unknown'))

    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get display name for a custom action."""
        return resource.get('name', 'Unknown Action')

    def _retry_with_exponential_backoff(self, operation, *args, **kwargs):
        """
        Retry an operation with exponential backoff.

        Args:
            operation: The function to retry
            *args: Arguments to pass to the operation
            **kwargs: Keyword arguments to pass to the operation

        Returns:
            The result of the operation if successful

        Raises:
            The last exception if all retries fail
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                result = operation(*args, **kwargs)
                if attempt > 0:
                    self.logger.info(f"Operation succeeded on attempt {attempt + 1}")
                return result

            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff_time = self.base_backoff * (2 ** attempt)
                    self.logger.warning(
                        f"Operation failed on attempt {attempt + 1}/{self.max_retries}: {e}. "
                        f"Retrying in {backoff_time} seconds..."
                    )
                    time.sleep(backoff_time)
                else:
                    self.logger.error(f"Operation failed after {self.max_retries} attempts: {e}")

        raise last_exception

    def _add_operation_delay(self):
        """Add delay between operations to avoid overwhelming the API."""
        if self.creation_delay > 0:
            time.sleep(self.creation_delay)

    def _log_failed_action(self, action: Dict[str, Any], operation: str, error: str):
        """
        Log a failed action operation for later review.

        Args:
            action: The action that failed
            operation: The operation that failed (create, delete)
            error: The error message
        """
        failed_action = {
            'action_id': self.get_resource_identifier(action),
            'action_name': self.get_resource_name(action),
            'operation': operation,
            'error': str(error),
            'timestamp': datetime.now().isoformat(),
            'action_data': action
        }
        self.failed_actions.append(failed_action)
        self.logger.error(f"Failed {operation} for action {self.get_resource_name(action)}: {error}")

    def _save_failed_actions_log(self):
        """Save failed actions to a log file for review."""
        if not self.failed_actions:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.service_outputs_dir / f"failed_actions_{timestamp}.json"

        failed_data = {
            'timestamp': datetime.now().isoformat(),
            'service': self.service_name,
            'failed_actions': self.failed_actions,
            'total_failed_actions': len(self.failed_actions)
        }

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(failed_data, f, indent=2, default=str)

            self.logger.info(f"Failed actions log saved to {failed_log_file}")
        except Exception as e:
            self.logger.error(f"Failed to save failed actions log: {e}")

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all custom actions from Team A with safety checks."""
        api_error = None
        actions = []

        try:
            self.logger.info("Fetching custom actions from Team A")
            response = self.teama_client.get(self.api_endpoint)
            actions = response.get('actions', [])
            self.logger.info(f"Fetched {len(actions)} custom actions from Team A")

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch custom actions from Team A: {e}")
            api_error = e
        except Exception as e:
            self.logger.error(f"Unexpected error fetching custom actions from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            actions, api_error, previous_count
        )

        if not safety_result.is_safe:
            self.logger.error(f"TeamA fetch safety check failed: {safety_result.reason}")
            self.logger.error(f"Safety check details: {safety_result.details}")

            # If we have an API error, raise it
            if api_error:
                raise api_error

            # If it's a safety issue without API error, raise a custom exception
            raise RuntimeError(f"Safety check failed: {safety_result.reason}")

        # If we had an API error but safety check passed, still raise the error
        if api_error:
            raise api_error

        return actions

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all custom actions from Team B."""
        try:
            self.logger.info("Fetching custom actions from Team B")
            response = self.teamb_client.get(self.api_endpoint)
            actions = response.get('actions', [])
            self.logger.info(f"Fetched {len(actions)} custom actions from Team B")
            return actions
        except Exception as e:
            self.logger.error(f"Failed to fetch custom actions from Team B: {e}")
            return []

    def _replace_team_urls(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace Team A URLs with Team B URLs in action data.

        Args:
            action: The action data to process

        Returns:
            Action data with URLs replaced
        """
        # Get Team A and Team B URLs from environment variables
        teama_url = os.getenv('CX_TEAMA_URL', 'https://onlineboutique.coralogix.com')
        teamb_url = os.getenv('CX_TEAMB_URL', 'https://cx-coe-dr-test.app.eu2.coralogix.com')

        if not teama_url or not teamb_url:
            self.logger.warning("Team A or Team B URL not configured in environment variables")
            return action

        # Create a deep copy to avoid modifying the original
        import copy
        processed_action = copy.deepcopy(action)

        # Track if any URLs were replaced
        urls_replaced = 0

        def replace_urls_in_value(value):
            """Recursively replace URLs in any string value."""
            nonlocal urls_replaced

            if isinstance(value, str):
                if teama_url in value:
                    original_value = value
                    new_value = value.replace(teama_url, teamb_url)
                    if new_value != original_value:
                        urls_replaced += 1
                        self.logger.debug(f"Replaced URL: {original_value} -> {new_value}")
                    return new_value
                return value
            elif isinstance(value, dict):
                return {k: replace_urls_in_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [replace_urls_in_value(item) for item in value]
            else:
                return value

        # Process the entire action recursively
        processed_action = replace_urls_in_value(processed_action)

        if urls_replaced > 0:
            action_name = self.get_resource_name(action)
            self.logger.info(f"Replaced {urls_replaced} Team A URL(s) with Team B URL in action: {action_name}")

        return processed_action

    def _clean_action_for_creation(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean an action for creation by removing system-generated fields and replacing URLs.

        Args:
            action: The action to clean

        Returns:
            Cleaned action ready for creation
        """
        # First, replace Team A URLs with Team B URLs
        action_with_replaced_urls = self._replace_team_urls(action)

        # Then remove system-generated fields
        fields_to_remove = [
            'id', 'createdAt', 'updatedAt', 'createdBy', 'updatedBy',
            'created_at', 'updated_at', 'created_time', 'updated_time',
            'creation_time', 'update_time', 'version'
        ]

        cleaned_action = {k: v for k, v in action_with_replaced_urls.items() if k not in fields_to_remove}
        return cleaned_action

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a custom action in Team B.

        Args:
            resource: The action to create

        Returns:
            Created action data

        Raises:
            Exception: If creation fails
        """
        try:
            self.logger.info(f"Creating custom action in Team B: {self.get_resource_name(resource)}")

            # Add delay before creation
            self._add_operation_delay()

            # Clean action data for creation
            action_data = self._clean_action_for_creation(resource)

            # Create action with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=action_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.logger.info(f"✅ Successfully created action: {self.get_resource_name(resource)}")
            return response.get('action', response)

        except Exception as e:
            self._log_failed_action(resource, "create", str(e))
            raise Exception(f"Failed to create action {self.get_resource_name(resource)}: {e}")

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """
        Delete a custom action from Team B.

        Args:
            resource_id: ID of the action to delete

        Returns:
            True if deletion was successful
        """
        try:
            self.logger.info(f"Deleting custom action from Team B: {resource_id}")

            # Add delay before deletion
            self._add_operation_delay()

            # Delete action with exponential backoff
            def _delete_operation():
                return self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self._retry_with_exponential_backoff(_delete_operation)

            self.logger.info(f"✅ Successfully deleted action: {resource_id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to delete action {resource_id}: {e}")
            return False

    def _display_migration_table(self, table_data: List[Dict[str, Any]]):
        """Display migration statistics in a nice tabular format."""

        # Table headers
        headers = [
            "Resource Type",
            "Team A",
            "Team B",
            "To Delete",
            "To Create",
            "Operations"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['resource_type']) for row in table_data)),
            max(len(headers[1]), max(len(str(row['team_a'])) for row in table_data)),
            max(len(headers[2]), max(len(str(row['team_b'])) for row in table_data)),
            max(len(headers[3]), max(len(str(row['to_delete'])) for row in table_data)),
            max(len(headers[4]), max(len(str(row['to_create'])) for row in table_data)),
            max(len(headers[5]), max(len(str(row['operations'])) for row in table_data))
        ]

        # Ensure minimum width for readability
        col_widths = [max(width, len(header)) for width, header in zip(col_widths, headers)]

        # Create table separator
        separator = "┼".join("─" * (width + 2) for width in col_widths)
        top_border = "┌" + separator.replace("┼", "┬") + "┐"
        middle_border = "├" + separator + "┤"
        bottom_border = "└" + separator.replace("┼", "┴") + "┘"

        # Display table using print to avoid JSON formatting interference
        print(top_border)

        # Header row
        header_row = "│"
        for i, header in enumerate(headers):
            header_row += f" {header:<{col_widths[i]}} │"
        print(header_row)

        print(middle_border)

        # Data rows
        for row in table_data:
            data_row = "│"
            values = [
                row['resource_type'],
                str(row['team_a']),
                str(row['team_b']),
                str(row['to_delete']),
                str(row['to_create']),
                str(row['operations'])
            ]

            for i, value in enumerate(values):
                if i == 0:  # Resource type - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def _display_migration_results_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""

        # Table headers
        headers = [
            "Resource Type",
            "Total",
            "Created",
            "Failed",
            "Success Rate"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['resource_type']) for row in table_data)),
            max(len(headers[1]), max(len(str(row['total'])) for row in table_data)),
            max(len(headers[2]), max(len(str(row['created'])) for row in table_data)),
            max(len(headers[3]), max(len(str(row['failed'])) for row in table_data)),
            max(len(headers[4]), max(len(row['success_rate']) for row in table_data))
        ]

        # Ensure minimum width for readability
        col_widths = [max(width, len(header)) for width, header in zip(col_widths, headers)]

        # Create table separator
        separator = "┼".join("─" * (width + 2) for width in col_widths)
        top_border = "┌" + separator.replace("┼", "┬") + "┐"
        middle_border = "├" + separator + "┤"
        bottom_border = "└" + separator.replace("┼", "┴") + "┘"

        # Display table using print to avoid JSON formatting interference
        print(top_border)

        # Header row
        header_row = "│"
        for i, header in enumerate(headers):
            header_row += f" {header:<{col_widths[i]}} │"
        print(header_row)

        print(middle_border)

        # Data rows
        for row in table_data:
            data_row = "│"
            values = [
                row['resource_type'],
                str(row['total']),
                str(row['created']),
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

    def dry_run(self) -> bool:
        """Perform a dry run to show what would be migrated."""
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch resources from both teams
            self.logger.info("Fetching custom actions from Team A...")
            teama_actions = self.fetch_resources_from_teama()

            # Export Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_actions, "teama")

            self.logger.info("Fetching custom actions from Team B...")
            teamb_actions = self.fetch_resources_from_teamb()

            # Export Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_actions, "teamb")

            # Calculate what would be done and prepare table data
            total_operations = 0
            table_data = []

            # Custom Actions
            teama_action_count = len(teama_actions)
            teamb_action_count = len(teamb_actions)
            action_operations = teama_action_count + teamb_action_count
            total_operations += action_operations

            table_data.append({
                'resource_type': 'Custom Actions',
                'team_a': teama_action_count,
                'team_b': teamb_action_count,
                'to_delete': teamb_action_count,
                'to_create': teama_action_count,
                'operations': action_operations
            })

            # Display results in tabular format
            self.logger.info(f"=" * 80)
            self.logger.info(f"🎯 CUSTOM ACTIONS DRY RUN RESULTS")
            self.logger.info(f"=" * 80)

            # Display migration table
            self._display_migration_table(table_data)

            # Display summary using print for clean formatting
            total_teama_resources = len(teama_actions)
            total_teamb_resources = len(teamb_actions)

            print("")
            print("📊 MIGRATION SUMMARY")
            print("─" * 40)
            print(f"{'Total Team A Actions:':<25} {total_teama_resources:>10}")
            print(f"{'Total Team B Actions:':<25} {total_teamb_resources:>10}")
            print(f"{'Actions to Delete:':<25} {total_teamb_resources:>10}")
            print(f"{'Actions to Create:':<25} {total_teama_resources:>10}")
            print(f"{'Total Operations:':<25} {total_operations:>10}")

            if total_operations == 0:
                print("")
                print("✨ No actions to migrate - both teams have 0 actions")
            else:
                print("")
                print("⚠️  IMPORTANT: ALL existing custom actions in Team B will be DELETED and recreated from Team A")

            self.logger.info(f"=" * 80)

            # Save migration statistics for summary table
            import json
            from pathlib import Path
            stats_file = Path("outputs") / self.service_name / f"{self.service_name}_stats_latest.json"
            stats_file.parent.mkdir(parents=True, exist_ok=True)
            stats_data = {
                'teama_count': len(teama_actions),
                'teamb_before': len(teamb_actions),
                'teamb_after': len(teamb_actions),  # No change in dry run
                'created': 0,  # Dry run doesn't create
                'deleted': 0,  # Dry run doesn't delete
                'failed': 0
            }
            with open(stats_file, 'w') as f:
                json.dump(stats_data, f, indent=2)

            self.log_migration_complete(self.service_name, True, 0, 0)
            return True

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def migrate(self) -> bool:
        """
        Perform the actual custom actions migration with enhanced safety checks.

        Enhanced Implementation:
        1. Create pre-migration version snapshot
        2. Fetch custom actions from Team A and Team B with safety checks
        3. Perform mass deletion safety check
        4. Delete all existing actions in Team B
        5. Create all actions from Team A in Team B
        6. Create post-migration version snapshot

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Fetch resources from both teams
            self.logger.info("Fetching custom actions from Team A...")
            teama_actions = self.fetch_resources_from_teama()  # This now includes safety checks

            self.logger.info("Fetching custom actions from Team B...")
            teamb_actions = self.fetch_resources_from_teamb()

            # Step 2: Create pre-migration version snapshot
            self.logger.info("Creating pre-migration version snapshot...")
            pre_migration_version = self.version_manager.create_version_snapshot(
                teama_actions, teamb_actions, 'pre_migration'
            )
            self.logger.info(f"Pre-migration snapshot created: {pre_migration_version}")

            # Step 3: Export artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_actions, "teama")

            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_actions, "teamb")

            # Step 4: Perform mass deletion safety check
            # Get previous TeamA count for trend analysis (from current version before this migration)
            current_version = self.version_manager.get_current_version()
            previous_teama_count = current_version.get('teama', {}).get('count') if current_version else None

            # For custom-actions, we delete ALL TeamB actions, so all are "to be deleted"
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_actions, len(teamb_actions), len(teama_actions), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            # Track migration statistics
            migration_stats = {
                'actions': {'total': len(teama_actions), 'created': 0, 'failed': 0},
                'deleted_actions': 0
            }

            # Step 1: Delete all existing actions in Team B
            self.logger.info("🗑️ Deleting existing custom actions from Team B...")

            for action in teamb_actions:
                action_id = self.get_resource_identifier(action)
                if self.delete_resource_from_teamb(action_id):
                    migration_stats['deleted_actions'] += 1

            # Step 2: Create all actions from Team A in Team B
            self.logger.info("📄 Creating custom actions in Team B...")

            for action in teama_actions:
                try:
                    self.create_resource_in_teamb(action)
                    migration_stats['actions']['created'] += 1
                except Exception as e:
                    migration_stats['actions']['failed'] += 1

            # Save failed actions log
            if self.failed_actions:
                self._save_failed_actions_log()

            # Step 5: Create post-migration version snapshot
            try:
                self.logger.info("Creating post-migration version snapshot...")
                # Fetch updated TeamB resources
                updated_teamb_actions = self.fetch_resources_from_teamb()
                post_migration_version = self.version_manager.create_version_snapshot(
                    teama_actions, updated_teamb_actions, 'post_migration'
                )
                self.logger.info(f"Post-migration snapshot created: {post_migration_version}")
            except Exception as e:
                self.logger.warning(f"Failed to create post-migration snapshot: {e}")
                updated_teamb_actions = []

            # Step 6: Save migration statistics for summary table
            import json
            from pathlib import Path
            stats_file = Path("outputs") / self.service_name / f"{self.service_name}_stats_latest.json"
            stats_file.parent.mkdir(parents=True, exist_ok=True)
            stats_data = {
                'teama_count': len(teama_actions),
                'teamb_before': len(teamb_actions),
                'teamb_after': len(updated_teamb_actions),
                'created': migration_stats['actions']['created'],
                'deleted': migration_stats['deleted_actions'],
                'failed': migration_stats['actions']['failed']
            }
            with open(stats_file, 'w') as f:
                json.dump(stats_data, f, indent=2)

            # Calculate totals
            total_created = migration_stats['actions']['created']
            total_failed = migration_stats['actions']['failed']
            total_processed = total_created + total_failed

            # Display results in tabular format
            self.logger.info(f"=" * 80)
            self.logger.info(f"🎉 CUSTOM ACTIONS MIGRATION RESULTS")
            self.logger.info(f"=" * 80)

            # Prepare migration results table
            migration_table_data = []

            if migration_stats['actions']['total'] > 0:
                action_success_rate = (migration_stats['actions']['created'] / migration_stats['actions']['total'] * 100)
                migration_table_data.append({
                    'resource_type': 'Custom Actions',
                    'total': migration_stats['actions']['total'],
                    'created': migration_stats['actions']['created'],
                    'failed': migration_stats['actions']['failed'],
                    'success_rate': f"{action_success_rate:.1f}%"
                })

            # Display migration results table
            if migration_table_data:
                self._display_migration_results_table(migration_table_data)

            # Display overall summary using print for clean formatting
            overall_success_rate = (total_created / total_processed * 100) if total_processed > 0 else 100

            print("")
            print("📊 OVERALL MIGRATION SUMMARY")
            print("─" * 40)
            print(f"{'Total Actions Processed:':<25} {total_processed:>10}")
            print(f"{'Successfully Created:':<25} {total_created:>10}")
            print(f"{'Failed Operations:':<25} {total_failed:>10}")
            print(f"{'Actions Deleted:':<25} {migration_stats['deleted_actions']:>10}")
            print(f"{'Overall Success Rate:':<25} {overall_success_rate:>9.1f}%")

            self.log_migration_complete(self.service_name, total_failed == 0, total_created, total_failed)

            success = total_failed == 0
            if success:
                self.logger.info("🎉 Custom actions migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ Custom actions migration completed with {total_failed} failures")

            return success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")

            # Save failed actions log
            if self.failed_actions:
                self._save_failed_actions_log()

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def rollback_to_version(self, version_id: str) -> bool:
        """
        Rollback TeamB custom actions to a specific version.

        Args:
            version_id: Version identifier to rollback to

        Returns:
            True if rollback completed successfully
        """
        try:
            self.logger.info(f"Starting rollback to version: {version_id}")

            # Get rollback plan
            rollback_plan = self.version_manager.create_rollback_plan(version_id)
            if not rollback_plan:
                self.logger.error(f"Failed to create rollback plan for version: {version_id}")
                return False

            self.logger.info(f"Rollback plan: {rollback_plan['summary']}")

            # Create pre-rollback snapshot
            current_teamb_actions = self.fetch_resources_from_teamb()
            pre_rollback_version = self.version_manager.create_version_snapshot(
                [], current_teamb_actions, 'pre_rollback'
            )
            self.logger.info(f"Pre-rollback snapshot created: {pre_rollback_version}")

            success_count = 0
            error_count = 0

            # Step 1: Delete all current actions in TeamB
            self.logger.info("🗑️ Deleting current custom actions from Team B...")
            for action in rollback_plan['resources_to_delete']:
                try:
                    action_id = self.get_resource_identifier(action)
                    action_name = self.get_resource_name(action)
                    if action_id and self.delete_resource_from_teamb(action_id):
                        self.logger.info(f"Deleted current action: {action_name}")
                        success_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to delete action {action.get('name', 'Unknown')}: {e}")
                    error_count += 1

            # Step 2: Create target actions in TeamB
            self.logger.info("📄 Creating target custom actions in Team B...")
            for action in rollback_plan['resources_to_create']:
                try:
                    action_name = self.get_resource_name(action)
                    self.logger.info(f"Creating target action: {action_name}")
                    self.create_resource_in_teamb(action)
                    success_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to create action {action.get('name', 'Unknown')}: {e}")
                    error_count += 1

            # Create post-rollback snapshot
            try:
                final_teamb_actions = self.fetch_resources_from_teamb()
                post_rollback_version = self.version_manager.create_version_snapshot(
                    [], final_teamb_actions, 'post_rollback'
                )
                self.logger.info(f"Post-rollback snapshot created: {post_rollback_version}")
            except Exception as e:
                self.logger.warning(f"Failed to create post-rollback snapshot: {e}")

            rollback_success = error_count == 0
            self.logger.info(f"Rollback completed. Success: {rollback_success}, Operations: {success_count}, Errors: {error_count}")

            return rollback_success

        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return False
