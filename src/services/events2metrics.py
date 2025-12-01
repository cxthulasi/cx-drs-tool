"""
Events2Metrics migration service for Coralogix DR Tool.

This service handles the migration of Events2Metrics (E2M) between Team A and Team B.
It supports:
- Fetching E2M definitions from both teams
- Creating new E2M definitions in Team B
- Deleting E2M definitions from Team B
- Comparing E2M definitions to detect changes
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


class Events2MetricsService(BaseService):
    """Service for migrating Events2Metrics (E2M) between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_e2m_logging()

        # Initialize safety manager and version manager
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "events2metrics"

    @property
    def api_endpoint(self) -> str:
        return "/api/v2/events2metrics"

    def _setup_failed_e2m_logging(self):
        """Set up logging directory for failed E2M operations."""
        self.failed_e2m_log_dir = Path("logs/events2metrics")
        self.failed_e2m_log_dir.mkdir(parents=True, exist_ok=True)

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """
        Fetch all Events2Metrics from Team A with safety checks.

        Returns:
            List of E2M definitions from Team A
        """
        api_error = None
        e2m_list = []

        try:
            self.logger.info("Fetching Events2Metrics from Team A...")
            response = self.teama_client.get(self.api_endpoint)

            if not response or 'e2m' not in response:
                self.logger.warning("No Events2Metrics found in Team A or invalid response format")
                e2m_list = []
            else:
                e2m_list = response['e2m']
                self.logger.info(f"Found {len(e2m_list)} Events2Metrics in Team A")

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch Events2Metrics from Team A: {e}")
            api_error = e
        except Exception as e:
            self.logger.error(f"Unexpected error fetching Events2Metrics from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            e2m_list, api_error, previous_count
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

        # Save artifacts for comparison
        if e2m_list:
            self._save_artifacts("teama", e2m_list)

        return e2m_list

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """
        Fetch all Events2Metrics from Team B.

        Returns:
            List of E2M definitions from Team B
        """
        try:
            self.logger.info("Fetching Events2Metrics from Team B...")
            response = self.teamb_client.get(self.api_endpoint)

            if not response or 'e2m' not in response:
                self.logger.warning("No Events2Metrics found in Team B or invalid response format")
                return []

            e2m_list = response['e2m']
            self.logger.info(f"Found {len(e2m_list)} Events2Metrics in Team B")

            # Save artifacts for comparison
            self._save_artifacts("teamb", e2m_list)

            return e2m_list

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch Events2Metrics from Team B: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching Events2Metrics from Team B: {e}")
            return []

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create an Events2Metrics in Team B.

        Args:
            resource: E2M definition to create

        Returns:
            Created E2M definition

        Raises:
            CoralogixAPIError: If creation fails
        """
        # Clean the resource data for creation
        clean_resource = self._clean_e2m_for_creation(resource)

        self.logger.info(f"Creating E2M '{clean_resource.get('name', 'Unknown')}' in Team B...")

        try:
            response = self.teamb_client.post(self.api_endpoint, clean_resource)

            if response and 'e2m' in response:
                created_e2m = response['e2m']
                self.logger.info(f"Successfully created E2M '{created_e2m.get('name', 'Unknown')}' with ID: {created_e2m.get('id', 'Unknown')}")
                return created_e2m
            else:
                raise CoralogixAPIError("Invalid response format from create E2M API")

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to create E2M '{clean_resource.get('name', 'Unknown')}': {e}")
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """
        Delete an Events2Metrics from Team B.

        Args:
            resource_id: ID of the E2M to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            self.logger.info(f"Deleting E2M with ID '{resource_id}' from Team B...")

            delete_endpoint = f"{self.api_endpoint}/{resource_id}"
            response = self.teamb_client.delete(delete_endpoint)

            if response and 'id' in response:
                self.logger.info(f"Successfully deleted E2M with ID: {response['id']}")
                return True
            else:
                self.logger.warning(f"Unexpected response format when deleting E2M {resource_id}")
                return False

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to delete E2M {resource_id}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error deleting E2M {resource_id}: {e}")
            return False

    def _clean_e2m_for_creation(self, e2m: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean E2M data for creation by removing fields that shouldn't be sent.

        Args:
            e2m: Original E2M definition

        Returns:
            Cleaned E2M definition ready for creation
        """
        # Fields to remove for creation
        fields_to_remove = [
            'id',           # Generated by API
            'createTime',   # Generated by API
            'updateTime',   # Generated by API
            'isInternal'    # Internal field
        ]

        clean_e2m = {}
        for key, value in e2m.items():
            if key not in fields_to_remove:
                clean_e2m[key] = value

        return clean_e2m

    def _compare_e2m(self, e2m_a: Dict[str, Any], e2m_b: Dict[str, Any]) -> bool:
        """
        Compare two E2M definitions to check if they are equivalent.

        Args:
            e2m_a: E2M from Team A
            e2m_b: E2M from Team B

        Returns:
            True if E2Ms are equivalent, False otherwise
        """
        # Clean both E2Ms for comparison (remove timestamps and IDs)
        clean_a = self._clean_e2m_for_creation(e2m_a)
        clean_b = self._clean_e2m_for_creation(e2m_b)

        return clean_a == clean_b

    def _find_e2m_by_name(self, e2m_list: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
        """
        Find an E2M by name in a list.

        Args:
            e2m_list: List of E2M definitions
            name: Name to search for

        Returns:
            E2M definition if found, None otherwise
        """
        for e2m in e2m_list:
            if e2m.get('name') == name:
                return e2m
        return None

    def dry_run(self) -> bool:
        """
        Perform a dry run of the Events2Metrics migration using delete & recreate all pattern.
        Shows what would be done without making actual changes.

        Returns:
            True if dry run completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch current resources from both teams
            self.logger.info("Fetching resources from Team A...")
            teama_e2ms = self.fetch_resources_from_teama()

            self.logger.info("Fetching resources from Team B...")
            teamb_e2ms = self.fetch_resources_from_teamb()

            # Save artifacts for comparison
            self.save_artifacts(teama_e2ms, 'teama')
            self.save_artifacts(teamb_e2ms, 'teamb')

            # Calculate what would be done (delete all + recreate all)
            total_operations = len(teamb_e2ms) + len(teama_e2ms)

            # Print dry-run summary
            print("\n" + "=" * 60)
            print("DRY RUN - EVENTS2METRICS MIGRATION")
            print("=" * 60)
            print(f"📊 Team A E2Ms: {len(teama_e2ms)}")
            print(f"📊 Team B E2Ms (current): {len(teamb_e2ms)}")
            print("\n🔄 Planned Operations:")
            print(f"   🗑️  Delete ALL {len(teamb_e2ms)} E2Ms from Team B")
            print(f"   ✅ Create {len(teama_e2ms)} E2Ms from Team A")
            print(f"\n📋 Total operations: {total_operations}")
            print("=" * 60 + "\n")

            # Display sample E2Ms
            if teama_e2ms:
                print("Sample E2Ms from Team A (first 5):")
                for i, e2m in enumerate(teama_e2ms[:5], 1):
                    name = e2m.get('name', 'Unknown')
                    e2m_id = e2m.get('id', 'N/A')
                    print(f"  {i}. {name} (ID: {e2m_id})")
                print()

            # Save migration statistics for summary table
            stats_file = self.outputs_dir / f"{self.service_name}_stats_latest.json"
            stats_data = {
                'teama_count': len(teama_e2ms),
                'teamb_before': len(teamb_e2ms),
                'teamb_after': len(teamb_e2ms),  # No change in dry run
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
        print("DRY RUN RESULTS - EVENTS2METRICS")
        print("=" * 60)

        print(f"📊 Team A E2Ms: {results['teama_count']}")
        print(f"📊 Team B E2Ms: {results['teamb_count']}")

        if results['to_create']:
            print(f"✅ New E2Ms to create in Team B: {len(results['to_create'])}")
            for e2m in results['to_create']:
                print(f"  + {e2m.get('name', 'Unknown')} (ID: {e2m.get('id', 'Unknown')})")

        if results['to_recreate']:
            print(f"🔄 Changed E2Ms to recreate in Team B: {len(results['to_recreate'])}")
            for e2m_a, e2m_b in results['to_recreate']:
                print(f"  ~ {e2m_a.get('name', 'Unknown')} (Team A ID: {e2m_a.get('id', 'Unknown')}, Team B ID: {e2m_b.get('id', 'Unknown')})")

        if results['to_delete']:
            print(f"🗑️ E2Ms to delete from Team B: {len(results['to_delete'])}")
            for e2m in results['to_delete']:
                print(f"  - {e2m.get('name', 'Unknown')} (ID: {e2m.get('id', 'Unknown')})")

        print(f"📋 Total operations planned: {results['total_operations']}")

        if results['total_operations'] > 0:
            print(f"  - Create: {len(results['to_create'])}")
            print(f"  - Recreate: {len(results['to_recreate'])}")
            print(f"  - Delete: {len(results['to_delete'])}")

        print("=" * 60)

    def migrate(self) -> bool:
        """
        Perform the actual Events2Metrics migration using delete & recreate all pattern.

        This approach ensures perfect synchronization by:
        1. Deleting ALL existing E2Ms from Team B
        2. Recreating ALL E2Ms from Team A

        This is the same approach as parsing-rules and guarantees consistency.

        Returns:
            True if migration completed successfully, False otherwise
        """
        self.logger.info("Starting Events2Metrics migration...")

        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Fetch resources from both teams (with safety checks for TeamA)
            self.logger.info("📥 Fetching Events2Metrics from both teams...")
            teama_e2ms = self.fetch_resources_from_teama()  # This includes safety checks
            teamb_e2ms = self.fetch_resources_from_teamb()

            # Step 2: Create pre-migration version snapshot
            self.logger.info("📸 Creating pre-migration version snapshot...")
            pre_migration_version = self.version_manager.create_version_snapshot(
                teama_e2ms, teamb_e2ms, 'pre_migration'
            )
            self.logger.info(f"Pre-migration snapshot created: {pre_migration_version}")

            # Get previous TeamA count for safety checks
            previous_version = self.version_manager.get_previous_version()
            previous_teama_count = previous_version.get('teama', {}).get('count') if previous_version else None

            # Step 3: Save artifacts
            self.save_artifacts(teama_e2ms, 'teama')
            self.save_artifacts(teamb_e2ms, 'teamb')

            # Step 4: Perform mass deletion safety check (deleting ALL TeamB resources)
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_e2ms, len(teamb_e2ms), len(teama_e2ms), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            self.logger.info(
                "Migration plan - Delete ALL + Recreate ALL",
                total_teama_e2ms=len(teama_e2ms),
                total_teamb_e2ms=len(teamb_e2ms),
                to_delete=len(teamb_e2ms),
                to_create=len(teama_e2ms)
            )

            delete_count = 0
            create_success_count = 0
            error_count = 0
            failed_operations = []

            # Step 5: Delete ALL existing E2Ms from Team B
            self.logger.info("🗑️ Deleting ALL existing Events2Metrics from Team B...")

            if teamb_e2ms:
                for e2m in teamb_e2ms:
                    try:
                        e2m_id = e2m.get('id')
                        e2m_name = e2m.get('name', 'Unknown')

                        if e2m_id:
                            self._add_creation_delay()
                            success = self._retry_with_exponential_backoff(
                                lambda: self.delete_resource_from_teamb(e2m_id),
                                f"delete E2M '{e2m_name}'"
                            )
                            if success:
                                self.logger.info(f"Deleted E2M: {e2m_name}")
                                delete_count += 1
                            else:
                                self.logger.error(f"Failed to delete E2M: {e2m_name} after retries")
                                error_count += 1
                                failed_operations.append({
                                    'operation': 'delete',
                                    'e2m_name': e2m_name,
                                    'e2m_id': e2m_id,
                                    'error': 'Delete operation failed after retries'
                                })
                        else:
                            self.logger.error(f"Failed to delete E2M: {e2m_name} - no ID found")
                            error_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to delete E2M {e2m.get('name', 'Unknown')}: {e}")
                        error_count += 1
                        failed_operations.append({
                            'operation': 'delete',
                            'e2m_name': e2m.get('name', 'Unknown'),
                            'e2m_id': e2m.get('id', 'Unknown'),
                            'error': str(e)
                        })

                # Step 5.1: Verify deletion completed
                self.logger.info("🔍 Verifying all E2Ms were deleted from Team B...")
                time.sleep(2)  # Brief delay for API consistency
                verification_teamb_e2ms = self.fetch_resources_from_teamb()

                if verification_teamb_e2ms:
                    self.logger.error(f"❌ Deletion verification failed: {len(verification_teamb_e2ms)} E2Ms still exist in Team B")
                    for remaining in verification_teamb_e2ms:
                        self.logger.error(f"   Remaining: {remaining.get('name', 'Unknown')} (ID: {remaining.get('id', 'N/A')})")
                    raise RuntimeError(f"Failed to delete all E2Ms from Team B. {len(verification_teamb_e2ms)} still remain.")
                else:
                    self.logger.info("✅ Deletion verification passed: Team B is now empty")
            else:
                self.logger.info("ℹ️ Team B already has no E2Ms - skipping deletion")

            # Step 6: Create ALL E2Ms from Team A
            self.logger.info("📄 Creating ALL Events2Metrics from Team A...")

            if teama_e2ms:
                for e2m in teama_e2ms:
                    try:
                        e2m_name = e2m.get('name', 'Unknown')

                        self.logger.info(f"Creating E2M: {e2m_name}")
                        self._add_creation_delay()
                        success = self._retry_with_exponential_backoff(
                            lambda: self.create_resource_in_teamb(e2m),
                            f"create E2M '{e2m_name}'"
                        )
                        if success:
                            create_success_count += 1
                        else:
                            error_count += 1
                            failed_operations.append({
                                'operation': 'create',
                                'e2m_name': e2m_name,
                                'e2m_data': e2m,
                                'error': 'Create operation failed after retries'
                            })

                    except Exception as e:
                        self.logger.error(f"Failed to create E2M {e2m.get('name', 'Unknown')}: {e}")
                        error_count += 1
                        failed_operations.append({
                            'operation': 'create',
                            'e2m_name': e2m.get('name', 'Unknown'),
                            'e2m_data': e2m,
                            'error': str(e)
                        })

                # Step 6.1: Verify creation completed
                self.logger.info("🔍 Verifying all E2Ms were created in Team B...")
                time.sleep(2)  # Brief delay for API consistency
                final_teamb_e2ms = self.fetch_resources_from_teamb()

                expected_count = len(teama_e2ms)
                actual_count = len(final_teamb_e2ms)

                if actual_count != expected_count:
                    self.logger.error(f"❌ Creation verification failed: Expected {expected_count} E2Ms, but found {actual_count} in Team B")
                    raise RuntimeError(f"Creation verification failed: Expected {expected_count} E2Ms, but found {actual_count}")
                else:
                    self.logger.info(f"✅ Creation verification passed: {actual_count} E2Ms successfully created in Team B")

                    # Save final state to outputs
                    self.logger.info("💾 Saving final Team B state to outputs...")
                    self.save_artifacts(final_teamb_e2ms, "teamb_final")
            else:
                self.logger.info("ℹ️ Team A has no E2Ms - skipping creation")
                final_teamb_e2ms = []

            # Log failed operations if any
            if failed_operations:
                self._log_failed_e2ms(failed_operations)

            # Step 7: Save migration statistics for summary table
            stats_file = self.outputs_dir / f"{self.service_name}_stats_latest.json"
            stats_data = {
                'teama_count': len(teama_e2ms),
                'teamb_before': len(teamb_e2ms),
                'teamb_after': len(final_teamb_e2ms),
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
                    teama_e2ms, final_teamb_e2ms, 'post_migration'
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
            print("MIGRATION RESULTS - EVENTS2METRICS")
            print("=" * 60)
            print(f"📊 Team A E2Ms: {len(teama_e2ms)}")
            print(f"📊 Team B E2Ms (before): {len(teamb_e2ms)}")
            print(f"📊 Team B E2Ms (after): {len(final_teamb_e2ms)}")
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
            self.logger.error(f"Events2Metrics migration failed with error: {e}")

            # Log failed operations if any exist
            if 'failed_operations' in locals() and failed_operations:
                self._log_failed_e2ms(failed_operations)

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def _log_failed_e2ms(self, failed_operations: List[Dict[str, Any]]):
        """
        Log failed E2M operations to a JSON file.

        Args:
            failed_operations: List of failed operation details
        """
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.failed_e2m_log_dir / f"failed_events2metrics_{timestamp}.json"

        log_data = {
            "timestamp": datetime.now().isoformat(),
            "total_failed": len(failed_operations),
            "failed_events2metrics": []
        }

        for operation in failed_operations:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "e2m_name": operation.get('e2m_name', 'Unknown'),
                "operation": operation.get('operation', 'unknown'),
                "error": operation.get('error', 'Unknown error')
            }

            # Add E2M data if available
            if 'e2m_data' in operation:
                log_entry['e2m_data'] = operation['e2m_data']

            # Add E2M ID if available
            if 'e2m_id' in operation:
                log_entry['e2m_id'] = operation['e2m_id']

            log_data["failed_events2metrics"].append(log_entry)

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            self.logger.info(f"Failed E2M operations logged to: {failed_log_file}")
        except Exception as e:
            self.logger.error(f"Failed to write failed E2M operations log: {e}")

    def _add_creation_delay(self):
        """Add a delay between E2M operations to avoid overwhelming the API."""
        import time
        time.sleep(0.5)  # 500ms delay

    def _retry_with_exponential_backoff(self, operation, operation_name: str, max_retries: int = 3):
        """
        Retry an operation with exponential backoff.

        Args:
            operation: Function to retry
            operation_name: Name of the operation for logging
            max_retries: Maximum number of retry attempts

        Returns:
            Result of the operation if successful, None if all retries failed
        """
        import time

        for attempt in range(max_retries + 1):
            try:
                result = operation()
                if attempt > 0:
                    self.logger.info(f"Operation '{operation_name}' succeeded on attempt {attempt + 1}")
                return result
            except Exception as e:
                if attempt == max_retries:
                    self.logger.error(f"Operation '{operation_name}' failed after {max_retries + 1} attempts: {e}")
                    return None
                else:
                    delay = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    self.logger.warning(f"Operation '{operation_name}' failed on attempt {attempt + 1}, retrying in {delay}s: {e}")
                    time.sleep(delay)

        return None

    def _save_artifacts(self, team: str, e2m_list: List[Dict[str, Any]]):
        """
        Save E2M artifacts for comparison and debugging.

        Args:
            team: Team name (teama or teamb)
            e2m_list: List of E2M definitions to save
        """
        import json
        from datetime import datetime

        # Create artifacts directory
        artifacts_dir = Path("outputs/events2metrics")
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Save with timestamp and latest
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Timestamped file
        timestamped_file = artifacts_dir / f"events2metrics_{team}_{timestamp}.json"

        # Latest file (for easy access)
        latest_file = artifacts_dir / f"events2metrics_{team}_latest.json"

        artifact_data = {
            "timestamp": datetime.now().isoformat(),
            "team": team,
            "count": len(e2m_list),
            "events2metrics": e2m_list
        }

        try:
            # Save timestamped version
            with open(timestamped_file, 'w') as f:
                json.dump(artifact_data, f, indent=2)

            # Save latest version
            with open(latest_file, 'w') as f:
                json.dump(artifact_data, f, indent=2)

            self.logger.debug(f"Saved {len(e2m_list)} E2Ms from {team} to artifacts")

        except Exception as e:
            self.logger.error(f"Failed to save E2M artifacts for {team}: {e}")
