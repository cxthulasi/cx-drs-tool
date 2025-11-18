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
from core.safety_manager import SafetyManager, SafetyCheckResult
from core.version_manager import VersionManager


class ParsingRulesService(BaseService):
    """Service for migrating parsing rule groups between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_rules_logging()

        # Initialize safety and version managers
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

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
        """Fetch all parsing rule groups from Team A with safety checks."""
        api_error = None
        rule_groups = []

        try:
            self.logger.info("Fetching parsing rule groups from Team A")

            # Make direct API call to get rule groups
            response = self.teama_client.get(self.api_endpoint)

            # Extract rule groups from response
            rule_groups = response.get('ruleGroups', [])

            self.logger.info(f"Fetched {len(rule_groups)} parsing rule groups from Team A")

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch parsing rule groups from Team A: {e}")
            api_error = e
        except Exception as e:
            self.logger.error(f"Unexpected error fetching parsing rule groups from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            rule_groups, api_error, previous_count
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

        return rule_groups
    
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
            # Handle 500 gracefully when Team B has no parsing rules
            if "500" in str(e):
                self.logger.info("No parsing rule groups found in Team B (500 response - empty collection)")
                return []
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

            # Validate that the rule group has at least one subgroup with rules
            rule_subgroups = create_data.get('ruleSubgroups', [])
            if not rule_subgroups or len(rule_subgroups) == 0:
                self.logger.warning(f"⚠️  Skipping rule group '{rule_group_name}' - no ruleSubgroups found (API requires at least 1 rule)")
                return {'skipped': True, 'reason': 'no_rules', 'name': rule_group_name}

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

        # Create a copy without excluded fields (only at top level)
        create_data = {
            k: v for k, v in resource.items()
            if k not in exclude_fields and v is not None
        }

        return create_data

    def _sort_resources_by_order(self, resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort resources by their order property to ensure correct creation sequence.

        Args:
            resources: List of rule group resources

        Returns:
            Sorted list of resources
        """
        def get_sort_key(resource):
            # Primary sort by rule group order
            group_order = resource.get('order', 999999)  # Default to high number if no order

            # Secondary sort by name for consistency
            name = resource.get('name', '')

            return (group_order, name)

        sorted_resources = sorted(resources, key=get_sort_key)

        # Also sort rules within each rule group
        for resource in sorted_resources:
            rule_subgroups = resource.get('ruleSubgroups', [])
            if rule_subgroups:
                # Sort subgroups by order
                resource['ruleSubgroups'] = sorted(
                    rule_subgroups,
                    key=lambda sg: (sg.get('order', 999999), sg.get('id', ''))
                )

                # Sort rules within each subgroup
                for subgroup in resource['ruleSubgroups']:
                    rules = subgroup.get('rules', [])
                    if rules:
                        subgroup['rules'] = sorted(
                            rules,
                            key=lambda r: (r.get('order', 999999), r.get('name', ''))
                        )

        return sorted_resources

    def _delete_resource_with_retry(self, resource_id: str, resource_name: str, max_retries: int = 3) -> bool:
        """
        Delete a resource with retry logic.

        Args:
            resource_id: ID of the resource to delete
            resource_name: Name of the resource (for logging)
            max_retries: Maximum number of retry attempts

        Returns:
            True if deletion succeeded, False otherwise
        """
        for attempt in range(max_retries):
            try:
                if self.delete_resource_from_teamb(resource_id):
                    return True
                else:
                    self.logger.warning(f"Deletion attempt {attempt + 1} failed for {resource_name}")
            except Exception as e:
                self.logger.warning(f"Deletion attempt {attempt + 1} failed for {resource_name}: {e}")

            if attempt < max_retries - 1:
                import time
                time.sleep(1)  # Wait 1 second before retry

        return False

    def _verify_basic_safety(self):
        """
        Basic safety check: Ensure we have the required clients.
        """
        if not hasattr(self, 'teamb_client'):
            raise RuntimeError("SAFETY ERROR: TeamB client not available")
        if not hasattr(self, 'teama_client'):
            raise RuntimeError("SAFETY ERROR: TeamA client not available")

        self.logger.info("🛡️ Basic safety check passed: Required clients available")

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a parsing rule group."""
        # For deletion operations, we need the ID, not the name
        return str(resource.get('id', 'unknown'))

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
        Perform the actual parsing rule groups migration using delete & recreate all pattern.

        This approach ensures perfect order synchronization by:
        1. Deleting ALL existing rule groups from Team B
        2. Recreating ALL rule groups from Team A in proper order

        This is the same approach as custom-actions and guarantees order consistency.

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 0: Basic safety verification
            self._verify_basic_safety()

            # Step 1: Fetch resources from both teams
            self.logger.info("Fetching parsing rule groups from Team A...")
            teama_resources = self.fetch_resources_from_teama()  # This includes safety checks

            self.logger.info("Fetching parsing rule groups from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Step 2: Create pre-migration version snapshot
            self.logger.info("Creating pre-migration version snapshot...")
            pre_migration_version = self.version_manager.create_version_snapshot(
                teama_resources, teamb_resources, 'pre_migration'
            )
            self.logger.info(f"Pre-migration snapshot created: {pre_migration_version}")

            # Step 3: Export artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_resources, "teama")

            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_resources, "teamb")

            # Step 4: Perform mass deletion safety check
            # Get previous TeamA count for trend analysis
            current_version = self.version_manager.get_current_version()
            previous_teama_count = current_version.get('teama', {}).get('count') if current_version else None

            # For parsing-rules, we delete ALL TeamB rule groups, so all are "to be deleted"
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_resources, len(teamb_resources), len(teama_resources), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            self.logger.info(
                "Migration plan - Delete & Recreate All",
                total_teama_resources=len(teama_resources),
                total_teamb_resources=len(teamb_resources),
                rule_groups_to_delete=len(teamb_resources),
                rule_groups_to_create=len(teama_resources),
                total_operations=len(teamb_resources) + len(teama_resources)
            )

            delete_count = 0
            create_success_count = 0
            error_count = 0

            # Step 5: Delete ALL existing rule groups from Team B (with verification)
            self.logger.info("🗑️ Deleting ALL existing parsing rule groups from Team B...")

            if teamb_resources:
                # Sort by reverse order for safe deletion (higher order numbers first)
                teamb_resources_sorted = sorted(
                    teamb_resources,
                    key=lambda r: r.get('order', 0),
                    reverse=True
                )

                for teamb_resource in teamb_resources_sorted:
                    try:
                        resource_id = self.get_resource_identifier(teamb_resource)
                        resource_name = teamb_resource.get('name', 'Unknown')
                        resource_order = teamb_resource.get('order', 'N/A')

                        if resource_id and self._delete_resource_with_retry(resource_id, resource_name):
                            self.logger.info(f"Deleted rule group: {resource_name} (order: {resource_order})")
                            delete_count += 1
                        else:
                            self.logger.error(f"Failed to delete rule group: {resource_name} after retries")
                            error_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to delete rule group {teamb_resource.get('name', 'Unknown')}: {e}")
                        error_count += 1

                # Step 5.1: Verify deletion completed - fetch fresh TeamB state
                self.logger.info("🔍 Verifying all rule groups were deleted from Team B...")
                verification_teamb_resources = self.fetch_resources_from_teamb()

                if verification_teamb_resources:
                    self.logger.error(f"❌ Deletion verification failed: {len(verification_teamb_resources)} rule groups still exist in Team B")
                    for remaining in verification_teamb_resources:
                        self.logger.error(f"   Remaining: {remaining.get('name', 'Unknown')} (ID: {remaining.get('id', 'N/A')})")
                    raise RuntimeError(f"Failed to delete all rule groups from Team B. {len(verification_teamb_resources)} still remain.")
                else:
                    self.logger.info("✅ Deletion verification passed: Team B is now empty")
            else:
                self.logger.info("ℹ️ Team B already has no rule groups - skipping deletion")

            # Step 6: Create ALL rule groups from Team A (in proper order)
            self.logger.info("📄 Creating ALL parsing rule groups from Team A...")

            skipped_count = 0

            if teama_resources:
                # Sort resources by order for creation (lower order numbers first)
                teama_resources_sorted = self._sort_resources_by_order(teama_resources)

                for teama_resource in teama_resources_sorted:
                    try:
                        resource_name = teama_resource.get('name', 'Unknown')
                        resource_order = teama_resource.get('order', 'N/A')

                        self.logger.info(f"Creating rule group: {resource_name} (order: {resource_order})")
                        result = self.create_resource_in_teamb(teama_resource)

                        # Check if the rule group was skipped
                        if isinstance(result, dict) and result.get('skipped'):
                            skipped_count += 1
                            self.logger.info(f"⚠️  Skipped rule group '{resource_name}' - {result.get('reason')}")
                        else:
                            create_success_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to create rule group {teama_resource.get('name', 'Unknown')}: {e}")
                        error_count += 1

                # Step 6.1: Verify creation completed - fetch final TeamB state
                self.logger.info("🔍 Verifying all rule groups were created in Team B...")
                final_teamb_resources = self.fetch_resources_from_teamb()

                expected_count = len(teama_resources) - skipped_count  # Adjust for skipped rule groups
                actual_count = len(final_teamb_resources)

                if actual_count != expected_count:
                    self.logger.error(f"❌ Creation verification failed: Expected {expected_count} rule groups (skipped {skipped_count}), but found {actual_count} in Team B")
                    raise RuntimeError(f"Creation verification failed: Expected {expected_count} rule groups, but found {actual_count}")
                else:
                    self.logger.info(f"✅ Creation verification passed: {actual_count} rule groups successfully created in Team B (skipped {skipped_count} empty rule groups)")

                    # Save final state to outputs
                    self.logger.info("💾 Saving final Team B state to outputs...")
                    self.save_artifacts(final_teamb_resources, "teamb_final")
            else:
                self.logger.info("ℹ️ Team A has no rule groups - skipping creation")
                final_teamb_resources = []

            # Step 7: Create post-migration version snapshot
            try:
                self.logger.info("Creating post-migration version snapshot...")
                # Use the already verified final TeamB resources
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
            print("MIGRATION RESULTS - PARSING RULE GROUPS")
            print("=" * 60)
            print(f"📊 Team A rule groups: {len(teama_resources)}")
            print(f"📊 Team B rule groups (before): {len(teamb_resources)}")
            print(f"📊 Team B rule groups (after): {len(final_teamb_resources)}")
            print(f"🗑️  Deleted from Team B: {delete_count}")
            print(f"✅ Successfully created: {create_success_count}")
            if skipped_count > 0:
                print(f"⚠️  Skipped (empty rule groups): {skipped_count}")
            if error_count > 0:
                print(f"❌ Failed: {error_count}")
            print(f"📋 Total operations: {delete_count + create_success_count + skipped_count + error_count}")

            if migration_success:
                print("\n✅ Migration completed successfully!")
                if skipped_count > 0:
                    print(f"   Note: {skipped_count} empty rule group(s) were skipped (no rules to migrate)")
            else:
                print("\n❌ Migration completed with errors!")
                print(f"   {error_count} rule group(s) failed to create")

            print("=" * 60 + "\n")

            return migration_success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def rollback_to_version(self, version_id: str) -> bool:
        """
        Rollback TeamB resources to a specific version.

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
            current_teamb_resources = self.fetch_resources_from_teamb()
            pre_rollback_version = self.version_manager.create_version_snapshot(
                [], current_teamb_resources, 'pre_rollback'
            )
            self.logger.info(f"Pre-rollback snapshot created: {pre_rollback_version}")

            success_count = 0
            error_count = 0

            # Step 1: Delete all current resources in TeamB (in reverse order)
            current_resources_sorted = sorted(
                rollback_plan['resources_to_delete'],
                key=lambda r: r.get('order', 0),
                reverse=True
            )

            for resource in current_resources_sorted:
                try:
                    resource_id = resource.get('id')
                    resource_name = resource.get('name', 'Unknown')
                    if resource_id:
                        self.logger.info(f"Deleting current resource: {resource_name}")
                        self.delete_resource_from_teamb(resource_id)
                        success_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to delete resource {resource.get('name', 'Unknown')}: {e}")
                    error_count += 1

            # Step 2: Create target resources in TeamB (in proper order)
            target_resources_sorted = self._sort_resources_by_order(rollback_plan['resources_to_create'])

            for resource in target_resources_sorted:
                try:
                    resource_name = resource.get('name', 'Unknown')
                    resource_order = resource.get('order', 'N/A')
                    self.logger.info(f"Creating target resource: {resource_name} (order: {resource_order})")
                    self.create_resource_in_teamb(resource)
                    success_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to create resource {resource.get('name', 'Unknown')}: {e}")
                    error_count += 1

            # Create post-rollback snapshot
            try:
                final_teamb_resources = self.fetch_resources_from_teamb()
                post_rollback_version = self.version_manager.create_version_snapshot(
                    [], final_teamb_resources, 'post_rollback'
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

    def dry_run(self) -> Dict[str, Any]:
        """
        Perform a dry run of the parsing rule groups migration using delete & recreate all pattern.
        Shows what would be done without making actual changes.

        Returns:
            Dictionary containing dry run results
        """
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Step 0: Basic safety verification
            self._verify_basic_safety()

            # Fetch current resources from both teams
            self.logger.info("Fetching resources from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            self.logger.info("Fetching resources from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Save artifacts for comparison
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # For delete & recreate all pattern, we delete ALL TeamB and create ALL TeamA
            results = {
                'teama_count': len(teama_resources),
                'teamb_count': len(teamb_resources),
                'to_delete': teamb_resources,  # Delete ALL TeamB rule groups
                'to_create': teama_resources,  # Create ALL TeamA rule groups
                'total_operations': len(teamb_resources) + len(teama_resources)
            }

            # Log summary with new approach
            self.logger.info("DRY RUN RESULTS - PARSING RULE GROUPS")
            self.logger.info("=" * 60)
            self.logger.info(f"📊 Team A rule groups: {len(teama_resources)}")
            self.logger.info(f"📊 Team B rule groups: {len(teamb_resources)}")
            self.logger.info(f"🗑️ Rule groups to delete from Team B: {len(teamb_resources)}")

            if teamb_resources:
                self.logger.info("   Deleting ALL existing rule groups:")
                for resource in sorted(teamb_resources, key=lambda r: r.get('order', 0)):
                    name = resource.get('name', 'Unknown')
                    order = resource.get('order', 'N/A')
                    resource_id = resource.get('id', 'N/A')
                    self.logger.info(f"   - {name} (ID: {resource_id}, Order: {order})")

            self.logger.info(f"📄 Rule groups to create from Team A: {len(teama_resources)}")

            if teama_resources:
                self.logger.info("   Creating ALL rule groups in proper order:")
                for resource in sorted(teama_resources, key=lambda r: r.get('order', 0)):
                    name = resource.get('name', 'Unknown')
                    order = resource.get('order', 'N/A')
                    resource_id = resource.get('id', 'N/A')
                    self.logger.info(f"   + {name} (ID: {resource_id}, Order: {order})")

            self.logger.info(f"📋 Total operations planned: {results['total_operations']}")
            self.logger.info(f"  - Delete: {len(teamb_resources)}")
            self.logger.info(f"  - Create: {len(teama_resources)}")

            if len(teama_resources) == 0 and len(teamb_resources) == 0:
                self.logger.info("✨ No rule groups to migrate - both teams have 0 rule groups")
            elif len(teama_resources) == 0:
                self.logger.info("⚠️  WARNING: Team A has 0 rule groups - this will DELETE all Team B rule groups!")
            else:
                self.logger.info("⚠️  IMPORTANT: ALL existing rule groups in Team B will be DELETED and recreated from Team A")
                self.logger.info("🎯 This ensures perfect order synchronization and rule consistency")

            self.log_migration_complete(self.service_name, True, len(teama_resources), 0)
            return results

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return {
                'teama_count': 0,
                'teamb_count': 0,
                'to_delete': [],
                'to_create': [],
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
        print("DRY RUN RESULTS - PARSING RULE GROUPS (DELETE & RECREATE ALL)")
        print("=" * 60)

        print(f"📊 Team A rule groups: {results['teama_count']}")
        print(f"📊 Team B rule groups: {results['teamb_count']}")

        if results.get('to_delete'):
            print(f"🗑️ Rule groups to delete from Team B: {len(results['to_delete'])}")
            for resource in sorted(results['to_delete'], key=lambda r: r.get('order', 0)):
                name = resource.get('name', 'Unknown')
                order = resource.get('order', 'N/A')
                resource_id = resource.get('id', 'N/A')
                print(f"  - {name} (ID: {resource_id}, Order: {order})")

        if results.get('to_create'):
            print(f"📄 Rule groups to create from Team A: {len(results['to_create'])}")
            for resource in sorted(results['to_create'], key=lambda r: r.get('order', 0)):
                name = resource.get('name', 'Unknown')
                order = resource.get('order', 'N/A')
                resource_id = resource.get('id', 'N/A')
                print(f"  + {name} (ID: {resource_id}, Order: {order})")

        print(f"📋 Total operations planned: {results['total_operations']}")

        if results['total_operations'] > 0:
            print(f"  - Delete: {len(results.get('to_delete', []))}")
            print(f"  - Create: {len(results.get('to_create', []))}")
            print("\n⚠️  IMPORTANT: ALL existing rule groups in Team B will be DELETED and recreated from Team A")
            print("🎯 This ensures perfect order synchronization and rule consistency")
        else:
            print("✨ No operations needed - both teams have 0 rule groups")

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
