"""
Recording Rules migration service for Coralogix DR Tool.

This service handles the migration of recording rule group sets between Team A and Team B.
It supports:
- Fetching rule group sets from both teams
- Creating new rule group sets in Team B
- Deleting rule group sets from Team B
- Comparing rule group sets to detect changes
- Dry-run functionality
- Failed operations logging with exponential backoff
"""

from typing import Dict, List, Any
from pathlib import Path
import json
import time

from core.base_service import BaseService
from core.config import Config
from core.api_client import CoralogixAPIError
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager


class RecordingRulesService(BaseService):
    """Service for migrating recording rule group sets between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_rules_logging()

        # Initialize safety manager and version manager
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "recording-rules"

    @property
    def api_endpoint(self) -> str:
        return "/latest/v1/rule-group-sets"
    
    def _setup_failed_rules_logging(self):
        """Setup logging directory for failed recording rules."""
        self.failed_rules_dir = Path("logs/recording_rules")
        self.failed_rules_dir.mkdir(parents=True, exist_ok=True)

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all recording rule group sets from Team A with safety checks."""
        api_error = None
        rule_group_sets = []

        try:
            self.logger.info("Fetching recording rule group sets from Team A")

            # Make direct API call to get rule group sets
            response = self.teama_client.get(self.api_endpoint)

            # Extract rule group sets from response
            rule_group_sets = response.get('sets', [])

            self.logger.info(f"Fetched {len(rule_group_sets)} recording rule group sets from Team A")

        except CoralogixAPIError as e:
            # Handle 404 gracefully - it means no recording rules exist
            if "404" in str(e):
                self.logger.info("No recording rule group sets found in Team A (404 response)")
                rule_group_sets = []
            else:
                self.logger.error(f"Failed to fetch recording rule group sets from Team A: {e}")
                api_error = e
        except Exception as e:
            self.logger.error(f"Unexpected error fetching recording rule group sets from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            rule_group_sets, api_error, previous_count
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

        return rule_group_sets

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all recording rule group sets from Team B."""
        try:
            self.logger.info("Fetching recording rule group sets from Team B")

            # Make direct API call to get rule group sets
            response = self.teamb_client.get(self.api_endpoint)

            # Extract rule group sets from response
            rule_group_sets = response.get('sets', [])

            self.logger.info(f"Fetched {len(rule_group_sets)} recording rule group sets from Team B")
            return rule_group_sets

        except CoralogixAPIError as e:
            # Handle 404 gracefully - it means no recording rules exist
            if "404" in str(e):
                self.logger.info("No recording rule group sets found in Team B (404 response)")
                return []
            self.logger.error(f"Failed to fetch recording rule group sets from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching recording rule group sets from Team B: {e}")
            raise
    
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create a recording rule group set in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_resource_for_creation(resource)
            rule_group_set_name = create_data.get('name', 'Unknown')

            self.logger.info(f"Creating recording rule group set in Team B: {rule_group_set_name}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Create the rule group set with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=create_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "recording_rule_group_set", rule_group_set_name, True)

            # Return the created rule group set
            return response

        except Exception as e:
            rule_group_set_name = resource.get('name', 'Unknown')
            self._log_failed_rule_group_set(resource, 'create', str(e))
            self.log_resource_action("create", "recording_rule_group_set", rule_group_set_name, False, str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete a recording rule group set from Team B."""
        try:
            self.logger.info(f"Deleting recording rule group set from Team B: {resource_id}")

            # Delete the rule group set
            self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self.log_resource_action("delete", "recording_rule_group_set", resource_id, True)
            return True

        except Exception as e:
            self.log_resource_action("delete", "recording_rule_group_set", resource_id, False, str(e))
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

    def _log_failed_rule_group_set(self, rule_group_set: Dict[str, Any], operation: str, error: str):
        """Log failed rule group set operations to a separate file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.failed_rules_dir / f"failed_recording_rules_{timestamp}.json"

        failed_entry = {
            "timestamp": datetime.now().isoformat(),
            "rule_group_set_id": rule_group_set.get('id', 'Unknown'),
            "rule_group_set_name": rule_group_set.get('name', 'Unknown'),
            "operation": operation,
            "error": error,
            "rule_group_set_data": rule_group_set
        }

        # Load existing failed entries or create new list
        failed_entries = []
        if failed_log_file.exists():
            try:
                with open(failed_log_file, 'r') as f:
                    existing_data = json.load(f)
                    failed_entries = existing_data.get('failed_rule_group_sets', [])
            except Exception:
                pass

        failed_entries.append(failed_entry)

        # Save updated failed entries
        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "total_failed": len(failed_entries),
            "failed_rule_group_sets": failed_entries
        }

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(failed_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write failed rule group sets log: {e}")

    def _prepare_resource_for_creation(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare a recording rule group set resource for creation by removing fields that
        shouldn't be included in the create request.
        """
        # Fields to exclude from creation (read-only or system-generated)
        exclude_fields = {
            'id',  # System-generated field
            'lastEvalDurationMs',  # Read-only field that causes 400 Bad Request (in rules)
            'lastEvalAt',  # Read-only field that causes 400 Bad Request (in groups)
            'lastEvalTime',  # Read-only field
            'createdAt',  # System-generated timestamp
            'updatedAt',  # System-generated timestamp
            'createdBy',  # System-generated field
            'updatedBy'   # System-generated field
        }

        # Create a copy without excluded fields
        create_data = {
            k: v for k, v in resource.items()
            if k not in exclude_fields and v is not None
        }

        # Also clean up nested groups and rules if they exist
        if 'groups' in create_data and isinstance(create_data['groups'], list):
            cleaned_groups = []
            for group in create_data['groups']:
                if isinstance(group, dict):
                    # Remove read-only fields from each group
                    cleaned_group = {
                        k: v for k, v in group.items()
                        if k not in exclude_fields and v is not None
                    }

                    # Clean up rules within each group
                    if 'rules' in cleaned_group and isinstance(cleaned_group['rules'], list):
                        cleaned_rules = []
                        for rule in cleaned_group['rules']:
                            if isinstance(rule, dict):
                                # Remove read-only fields from each rule
                                cleaned_rule = {
                                    k: v for k, v in rule.items()
                                    if k not in exclude_fields and v is not None
                                }
                                cleaned_rules.append(cleaned_rule)
                            else:
                                cleaned_rules.append(rule)
                        cleaned_group['rules'] = cleaned_rules

                    cleaned_groups.append(cleaned_group)
                else:
                    cleaned_groups.append(group)
            create_data['groups'] = cleaned_groups

        return create_data

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a recording rule group set."""
        # Rule group sets are typically identified by name
        return resource.get('name', resource.get('id', ''))

    def resources_are_equal(self, resource_a: Dict[str, Any], resource_b: Dict[str, Any]) -> bool:
        """
        Compare two recording rule group sets to see if they are equal.
        """
        # Fields to ignore in comparison (system-generated or metadata)
        ignore_fields = {
            'id',  # System-generated field
            'lastEvalDurationMs',  # Read-only field (in rules)
            'lastEvalAt',  # Read-only field (in groups)
            'lastEvalTime',  # Read-only field
            'createdAt',  # System-generated timestamp
            'updatedAt',  # System-generated timestamp
            'createdBy',  # System-generated field
            'updatedBy'   # System-generated field
        }

        def normalize_resource(resource):
            normalized = {}
            for k, v in resource.items():
                if k not in ignore_fields:
                    if k == 'groups' and isinstance(v, list):
                        # Normalize groups by removing ignored fields from each group and rule
                        normalized_groups = []
                        for group in v:
                            if isinstance(group, dict):
                                normalized_group = {
                                    gk: gv for gk, gv in group.items()
                                    if gk not in ignore_fields
                                }

                                # Also normalize rules within each group
                                if 'rules' in normalized_group and isinstance(normalized_group['rules'], list):
                                    normalized_rules = []
                                    for rule in normalized_group['rules']:
                                        if isinstance(rule, dict):
                                            normalized_rule = {
                                                rk: rv for rk, rv in rule.items()
                                                if rk not in ignore_fields
                                            }
                                            normalized_rules.append(normalized_rule)
                                        else:
                                            normalized_rules.append(rule)
                                    normalized_group['rules'] = normalized_rules

                                normalized_groups.append(normalized_group)
                            else:
                                normalized_groups.append(group)
                        normalized[k] = normalized_groups
                    else:
                        normalized[k] = v
            return normalized

        normalized_a = normalize_resource(resource_a)
        normalized_b = normalize_resource(resource_b)

        return normalized_a == normalized_b

    def migrate(self) -> bool:
        """
        Perform the actual recording rule group sets migration using delete & recreate all pattern.

        This approach ensures perfect synchronization by:
        1. Deleting ALL existing rule group sets from Team B
        2. Recreating ALL rule group sets from Team A

        This is the same approach as parsing-rules and guarantees consistency.

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Fetch resources from both teams (with safety checks for TeamA)
            self.logger.info("📥 Fetching recording rule group sets from both teams...")
            teama_resources = self.fetch_resources_from_teama()  # This includes safety checks
            teamb_resources = self.fetch_resources_from_teamb()

            # Step 2: Create pre-migration version snapshot
            self.logger.info("📸 Creating pre-migration version snapshot...")
            pre_migration_version = self.version_manager.create_version_snapshot(
                teama_resources, teamb_resources, 'pre_migration'
            )
            self.logger.info(f"Pre-migration snapshot created: {pre_migration_version}")

            # Get previous TeamA count for safety checks
            previous_version = self.version_manager.get_previous_version()
            previous_teama_count = previous_version.get('teama', {}).get('count') if previous_version else None

            # Step 3: Save artifacts
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # Step 4: Perform mass deletion safety check (deleting ALL TeamB resources)
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_resources, len(teamb_resources), len(teama_resources), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            self.logger.info(
                "Migration plan - Delete ALL + Recreate ALL",
                total_teama_resources=len(teama_resources),
                total_teamb_resources=len(teamb_resources),
                to_delete=len(teamb_resources),
                to_create=len(teama_resources)
            )

            delete_count = 0
            create_success_count = 0
            error_count = 0

            # Step 5: Delete ALL existing rule group sets from Team B
            self.logger.info("🗑️ Deleting ALL existing recording rule group sets from Team B...")

            if teamb_resources:
                for teamb_resource in teamb_resources:
                    try:
                        resource_id = teamb_resource.get('id')
                        resource_name = teamb_resource.get('name', 'Unknown')

                        if resource_id:
                            self.delete_resource_from_teamb(resource_id)
                            self.logger.info(f"Deleted rule group set: {resource_name}")
                            delete_count += 1
                        else:
                            self.logger.error(f"Failed to delete rule group set: {resource_name} - no ID found")
                            error_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to delete rule group set {teamb_resource.get('name', 'Unknown')}: {e}")
                        error_count += 1

                # Step 5.1: Verify deletion completed
                self.logger.info("🔍 Verifying all rule group sets were deleted from Team B...")
                time.sleep(2)  # Brief delay for API consistency
                verification_teamb_resources = self.fetch_resources_from_teamb()

                if verification_teamb_resources:
                    self.logger.error(f"❌ Deletion verification failed: {len(verification_teamb_resources)} rule group sets still exist in Team B")
                    for remaining in verification_teamb_resources:
                        self.logger.error(f"   Remaining: {remaining.get('name', 'Unknown')} (ID: {remaining.get('id', 'N/A')})")
                    raise RuntimeError(f"Failed to delete all rule group sets from Team B. {len(verification_teamb_resources)} still remain.")
                else:
                    self.logger.info("✅ Deletion verification passed: Team B is now empty")
            else:
                self.logger.info("ℹ️ Team B already has no rule group sets - skipping deletion")

            # Step 6: Create ALL rule group sets from Team A
            self.logger.info("📄 Creating ALL recording rule group sets from Team A...")

            if teama_resources:
                for teama_resource in teama_resources:
                    try:
                        resource_name = teama_resource.get('name', 'Unknown')

                        self.logger.info(f"Creating rule group set: {resource_name}")
                        self.create_resource_in_teamb(teama_resource)
                        create_success_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to create rule group set {teama_resource.get('name', 'Unknown')}: {e}")
                        error_count += 1

                # Step 6.1: Verify creation completed
                self.logger.info("🔍 Verifying all rule group sets were created in Team B...")
                time.sleep(2)  # Brief delay for API consistency
                final_teamb_resources = self.fetch_resources_from_teamb()

                expected_count = len(teama_resources)
                actual_count = len(final_teamb_resources)

                if actual_count != expected_count:
                    self.logger.error(f"❌ Creation verification failed: Expected {expected_count} rule group sets, but found {actual_count} in Team B")
                    raise RuntimeError(f"Creation verification failed: Expected {expected_count} rule group sets, but found {actual_count}")
                else:
                    self.logger.info(f"✅ Creation verification passed: {actual_count} rule group sets successfully created in Team B")

                    # Save final state to outputs
                    self.logger.info("💾 Saving final Team B state to outputs...")
                    self.save_artifacts(final_teamb_resources, "teamb_final")
            else:
                self.logger.info("ℹ️ Team A has no rule group sets - skipping creation")
                final_teamb_resources = []

            # Step 7: Save migration statistics for summary table
            stats_file = self.outputs_dir / f"{self.service_name}_stats_latest.json"
            stats_data = {
                'teama_count': len(teama_resources),
                'teamb_before': len(teamb_resources),
                'teamb_after': len(final_teamb_resources),
                'created': create_success_count,
                'deleted': delete_count,
                'failed': error_count
            }
            with open(stats_file, 'w') as f:
                json.dump(stats_data, f, indent=2)

            # Step 8: Create post-migration version snapshot
            self.logger.info("📸 Creating post-migration version snapshot...")
            try:
                post_migration_version = self.version_manager.create_version_snapshot(
                    teama_resources, final_teamb_resources, 'post_migration'
                )
                self.logger.info(f"Post-migration snapshot created: {post_migration_version}")
            except Exception as e:
                self.logger.warning(f"Failed to create post-migration snapshot: {e}")

            # Log completion
            migration_success = error_count == 0
            self.log_migration_complete(
                self.service_name,
                migration_success,
                create_success_count,
                error_count
            )

            # Print user-visible migration summary
            print("\n" + "=" * 60)
            print("MIGRATION RESULTS - RECORDING RULE GROUP SETS")
            print("=" * 60)
            print(f"📊 Team A rule group sets: {len(teama_resources)}")
            print(f"📊 Team B rule group sets (before): {len(teamb_resources)}")
            print(f"📊 Team B rule group sets (after): {len(final_teamb_resources)}")
            print(f"🗑️  Deleted from Team B: {delete_count}")
            print(f"✅ Successfully created: {create_success_count}")
            if error_count > 0:
                print(f"❌ Failed: {error_count}")
            print(f"📋 Total operations: {delete_count + create_success_count + error_count}")

            if migration_success:
                print("\n✅ Migration completed successfully!")
            else:
                print(f"\n⚠️ Migration completed with {error_count} failures")

            print("=" * 60 + "\n")

            return migration_success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def dry_run(self) -> bool:
        """
        Perform a dry run of the recording rule group sets migration using delete & recreate all pattern.
        Shows what would be done without making actual changes.

        Returns:
            True if dry run completed successfully
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

            # Calculate what would be done (delete all + recreate all)
            total_operations = len(teamb_resources) + len(teama_resources)

            # Print dry-run summary
            print("\n" + "=" * 60)
            print("DRY RUN - RECORDING RULE GROUP SETS MIGRATION")
            print("=" * 60)
            print(f"📊 Team A rule group sets: {len(teama_resources)}")
            print(f"📊 Team B rule group sets (current): {len(teamb_resources)}")
            print("\n🔄 Planned Operations:")
            print(f"   🗑️  Delete ALL {len(teamb_resources)} rule group sets from Team B")
            print(f"   ✅ Create {len(teama_resources)} rule group sets from Team A")
            print(f"\n📋 Total operations: {total_operations}")
            print("=" * 60 + "\n")

            # Display sample rule group sets
            if teama_resources:
                print("Sample rule group sets from Team A (first 5):")
                for i, resource in enumerate(teama_resources[:5], 1):
                    name = resource.get('name', 'Unknown')
                    resource_id = resource.get('id', 'N/A')
                    print(f"  {i}. {name} (ID: {resource_id})")
                print()

            # Save migration statistics for summary table
            stats_file = self.outputs_dir / f"{self.service_name}_stats_latest.json"
            stats_data = {
                'teama_count': len(teama_resources),
                'teamb_before': len(teamb_resources),
                'teamb_after': len(teamb_resources),  # No change in dry run
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

    def display_dry_run_results(self, results: Dict[str, Any]):
        """
        Display formatted dry run results.

        Args:
            results: Dry run results dictionary
        """
        print("\n" + "=" * 60)
        print("DRY RUN RESULTS - RECORDING RULE GROUP SETS")
        print("=" * 60)

        print(f"📊 Team A rule group sets: {results['teama_count']}")
        print(f"📊 Team B rule group sets: {results['teamb_count']}")

        if results['to_create']:
            print(f"✅ New rule group sets to create in Team B: {len(results['to_create'])}")
            for resource in results['to_create']:
                print(f"  + {resource.get('name', 'Unknown')} (ID: {resource.get('id', 'N/A')})")

        if results['to_recreate']:
            print(f"🔄 Changed rule group sets to recreate in Team B: {len(results['to_recreate'])}")
            for teama_resource, teamb_resource in results['to_recreate']:
                print(f"  ~ {teama_resource.get('name', 'Unknown')} (Team A ID: {teama_resource.get('id', 'N/A')}, Team B ID: {teamb_resource.get('id', 'N/A')})")

        if results['to_delete']:
            print(f"🗑️ Rule group sets to delete from Team B: {len(results['to_delete'])}")
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

    def _display_migration_results_table(self, migration_stats: Dict):
        """Display migration results in a nice tabular format."""
        # Use print() to bypass JSON logging and show clean table
        print("\n" + "=" * 80)
        print("🎉 RECORDING RULES MIGRATION RESULTS")
        print("=" * 80)

        # Prepare migration results table
        migration_table_data = []

        # Add operations breakdown
        if migration_stats['new_resources'] > 0:
            success_rate = (migration_stats['successful_operations'] / migration_stats['total_operations'] * 100) if migration_stats['total_operations'] > 0 else 100
            migration_table_data.append({
                'operation_type': 'New Rule Group Sets',
                'planned': migration_stats['new_resources'],
                'successful': min(migration_stats['new_resources'], migration_stats['successful_operations']),
                'failed': max(0, migration_stats['new_resources'] - migration_stats['successful_operations']),
                'success_rate': f"{success_rate:.1f}%"
            })

        if migration_stats['changed_resources'] > 0:
            success_rate = (migration_stats['successful_operations'] / migration_stats['total_operations'] * 100) if migration_stats['total_operations'] > 0 else 100
            migration_table_data.append({
                'operation_type': 'Changed Rule Group Sets',
                'planned': migration_stats['changed_resources'],
                'successful': min(migration_stats['changed_resources'], migration_stats['successful_operations']),
                'failed': max(0, migration_stats['changed_resources'] - migration_stats['successful_operations']),
                'success_rate': f"{success_rate:.1f}%"
            })

        if migration_stats['deleted_resources'] > 0:
            success_rate = (migration_stats['successful_operations'] / migration_stats['total_operations'] * 100) if migration_stats['total_operations'] > 0 else 100
            migration_table_data.append({
                'operation_type': 'Deleted Rule Group Sets',
                'planned': migration_stats['deleted_resources'],
                'successful': min(migration_stats['deleted_resources'], migration_stats['successful_operations']),
                'failed': max(0, migration_stats['deleted_resources'] - migration_stats['successful_operations']),
                'success_rate': f"{success_rate:.1f}%"
            })

        # Display migration results table
        if migration_table_data:
            self._display_table(migration_table_data)

        # Display overall summary
        overall_success_rate = (migration_stats['successful_operations'] / migration_stats['total_operations'] * 100) if migration_stats['total_operations'] > 0 else 100

        print("")
        print("📊 OVERALL MIGRATION SUMMARY")
        print("─" * 40)
        print(f"{'Team A Rule Group Sets:':<25} {migration_stats['total_teama_resources']:>10}")
        print(f"{'Team B Rule Group Sets:':<25} {migration_stats['total_teamb_resources']:>10}")
        print(f"{'Total Operations:':<25} {migration_stats['total_operations']:>10}")
        print(f"{'Successful Operations:':<25} {migration_stats['successful_operations']:>10}")
        print(f"{'Failed Operations:':<25} {migration_stats['failed_operations']:>10}")
        print(f"{'Overall Success Rate:':<25} {overall_success_rate:>9.1f}%")
        print("=" * 80)

    def _display_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""
        # Table headers
        headers = [
            "Operation Type",
            "Planned",
            "Successful",
            "Failed",
            "Success Rate"
        ]

        # Calculate column widths
        col_widths = []
        for i, header in enumerate(headers):
            max_width = len(header)
            for row in table_data:
                if i == 0:
                    max_width = max(max_width, len(row['operation_type']))
                elif i == 1:
                    max_width = max(max_width, len(str(row['planned'])))
                elif i == 2:
                    max_width = max(max_width, len(str(row['successful'])))
                elif i == 3:
                    max_width = max(max_width, len(str(row['failed'])))
                elif i == 4:
                    max_width = max(max_width, len(row['success_rate']))
            col_widths.append(max_width)

        # Create table borders
        top_border = "┌"
        header_border = "├"
        bottom_border = "└"

        for i, width in enumerate(col_widths):
            if i > 0:
                top_border += "┬"
                header_border += "┼"
                bottom_border += "┴"
            top_border += "─" * (width + 2)
            header_border += "─" * (width + 2)
            bottom_border += "─" * (width + 2)

        top_border += "┐"
        header_border += "┤"
        bottom_border += "┘"

        # Use print() to bypass JSON logging and show clean table
        print(top_border)

        # Print headers
        header_row = "│"
        for i, header in enumerate(headers):
            if i == 0:  # Operation type - left aligned
                header_row += f" {header:<{col_widths[i]}} │"
            else:  # Numbers and percentages - right aligned
                header_row += f" {header:>{col_widths[i]}} │"

        print(header_row)
        print(header_border)

        # Print data rows
        for row in table_data:
            data_row = "│"
            values = [
                row['operation_type'],
                str(row['planned']),
                str(row['successful']),
                str(row['failed']),
                row['success_rate']
            ]

            for i, value in enumerate(values):
                if i == 0:  # Operation type - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers and percentages - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def _compare_rule_group_sets(self, teama_resources: List[Dict[str, Any]], teamb_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare rule group sets between Team A and Team B to identify changes.

        Returns:
            Dictionary with:
            - new_in_teama: Resources that exist in Team A but not in Team B
            - changed_resources: Resources that exist in both but are different
            - deleted_from_teama: Resources that exist in Team B but not in Team A
        """
        # Create lookup dictionaries by name (rule group sets are identified by name)
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
