"""
General Enrichments migration service for Coralogix DR Tool.

This service handles the migration of general enrichment rules between Team A and Team B.
It supports:
- Fetching enrichment rules from both teams
- Creating new enrichment rules in Team B
- Deleting enrichment rules from Team B
- Dry-run functionality
- Failed operations logging with exponential backoff
- Delete-all + recreate-all strategy
"""

from typing import Dict, List, Any
from pathlib import Path
import json
import time
from datetime import datetime

from core.base_service import BaseService
from core.config import Config
from core.api_client import CoralogixAPIError
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager


class GeneralEnrichmentsService(BaseService):
    """Service for migrating general enrichment rules between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_enrichments_logging()

        # Initialize safety and version managers
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "general-enrichments"

    @property
    def api_endpoint(self) -> str:
        return "/latest/enrichment-rules/enrichment-rules/v1"
    
    def _setup_failed_enrichments_logging(self):
        """Setup logging directory for failed enrichments."""
        self.failed_enrichments_dir = Path("logs/general_enrichments")
        self.failed_enrichments_dir.mkdir(parents=True, exist_ok=True)

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all general enrichment rules from Team A with safety checks."""
        api_error = None
        enrichments = []

        try:
            self.logger.info("Fetching general enrichment rules from Team A")

            # Make direct API call to get enrichments
            response = self.teama_client.get(self.api_endpoint)

            # Extract enrichments from response
            enrichments = response.get('enrichments', [])

            self.logger.info(f"Fetched {len(enrichments)} general enrichment rules from Team A")

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch general enrichment rules from Team A: {e}")
            api_error = e
        except Exception as e:
            self.logger.error(f"Unexpected error fetching general enrichment rules from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            enrichments, api_error, previous_count
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

        return enrichments
    
    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all general enrichment rules from Team B."""
        try:
            self.logger.info("Fetching general enrichment rules from Team B")

            # Make direct API call to get enrichments
            response = self.teamb_client.get(self.api_endpoint)

            # Extract enrichments from response
            enrichments = response.get('enrichments', [])

            self.logger.info(f"Fetched {len(enrichments)} general enrichment rules from Team B")
            return enrichments

        except CoralogixAPIError as e:
            # Handle empty collection gracefully
            if "404" in str(e) or "500" in str(e):
                self.logger.info("No general enrichment rules found in Team B (empty collection)")
                return []
            self.logger.error(f"Failed to fetch general enrichment rules from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching general enrichment rules from Team B: {e}")
            raise
    
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create a general enrichment rule in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_resource_for_creation(resource)
            enrichment_name = create_data.get('enrichedFieldName', 'Unknown')

            self.logger.info(f"Creating general enrichment rule in Team B: {enrichment_name}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Wrap in requestEnrichments array as per API spec
            request_payload = {
                "requestEnrichments": [create_data]
            }

            # Create the enrichment with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=request_payload)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "general_enrichment", enrichment_name, True)

            # Return the enrichment from the response
            return response

        except Exception as e:
            enrichment_name = resource.get('enrichedFieldName', 'Unknown')
            self._log_failed_enrichment(resource, 'create', str(e))
            self.log_resource_action("create", "general_enrichment", enrichment_name, False, str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """
        Delete a single general enrichment rule from Team B.

        Note: This service uses bulk delete strategy, but this method is required
        by the BaseService abstract class for compatibility.
        """
        try:
            self.logger.warning(f"Individual delete called for enrichment ID {resource_id}. "
                              "This service uses bulk delete strategy.")

            # For individual delete, we would need to implement a different endpoint
            # For now, log a warning as this service is designed for bulk operations
            self.logger.info(f"Skipping individual delete - use delete_all_resources_from_teamb() instead")
            return True

        except Exception as e:
            self.logger.error(f"Error in delete_resource_from_teamb: {e}")
            return False

    def delete_all_resources_from_teamb(self) -> bool:
        """Delete all general enrichment rules from Team B using bulk delete."""
        try:
            self.logger.info("Deleting all general enrichment rules from Team B")

            # Delete all enrichments using the DELETE endpoint
            self.teamb_client.delete(self.api_endpoint)

            self.log_resource_action("delete_all", "general_enrichments", "all", True)
            return True

        except Exception as e:
            self.logger.error(f"Failed to delete all enrichments from Team B: {e}")
            self.log_resource_action("delete_all", "general_enrichments", "all", False, str(e))
            raise

    def _add_creation_delay(self):
        """Add a small delay before creation to avoid overwhelming the API."""
        delay_seconds = 0.5  # 500ms delay between creations
        time.sleep(delay_seconds)

    def _retry_with_exponential_backoff(self, operation, max_retries: int = 3):
        """Retry an operation with exponential backoff."""
        for attempt in range(max_retries):
            try:
                return operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise

                wait_time = (2 ** attempt) * 1  # 1s, 2s, 4s
                self.logger.warning(f"Operation failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

    def _log_failed_enrichment(self, enrichment: Dict[str, Any], operation: str, error: str):
        """Log failed enrichment operations to a separate file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.failed_enrichments_dir / f"failed_general_enrichments_{timestamp}.json"

        failed_entry = {
            "timestamp": datetime.now().isoformat(),
            "enrichment_field": enrichment.get('enrichedFieldName', 'Unknown'),
            "operation": operation,
            "error": error,
            "enrichment_data": enrichment
        }

        # Load existing failed entries or create new list
        failed_entries = []
        if failed_log_file.exists():
            try:
                with open(failed_log_file, 'r') as f:
                    existing_data = json.load(f)
                    failed_entries = existing_data.get('failed_enrichments', [])
            except Exception:
                pass

        failed_entries.append(failed_entry)

        # Save updated failed entries
        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "total_failed": len(failed_entries),
            "failed_enrichments": failed_entries
        }

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(failed_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write failed enrichments log: {e}")

    def _prepare_resource_for_creation(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare a general enrichment resource for creation by removing fields that
        shouldn't be included in the create request.
        """
        # Fields to exclude from creation (read-only or system-generated)
        exclude_fields = {
            'id', 'teamId', 'createdAt', 'updatedAt'  # System-generated fields
        }

        # Create a copy without excluded fields
        create_data = {
            k: v for k, v in resource.items()
            if k not in exclude_fields and v is not None
        }

        return create_data

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a general enrichment rule."""
        return resource.get('enrichedFieldName', 'unknown')

    def resources_are_equal(self, resource_a: Dict[str, Any], resource_b: Dict[str, Any]) -> bool:
        """
        Compare two general enrichment rules to see if they are equal.
        """
        # Fields to ignore in comparison (system-generated or metadata)
        ignore_fields = {
            'id', 'teamId', 'createdAt', 'updatedAt'
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
        Perform the actual general enrichments migration using delete & recreate all pattern.

        This approach ensures perfect synchronization by:
        1. Deleting ALL existing enrichments from Team B
        2. Recreating ALL enrichments from Team A

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Fetch resources from both teams
            self.logger.info("Fetching general enrichment rules from Team A...")
            teama_resources = self.fetch_resources_from_teama()  # This includes safety checks

            self.logger.info("Fetching general enrichment rules from Team B...")
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

            # For general-enrichments, we delete ALL TeamB enrichments, so all are "to be deleted"
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
                enrichments_to_delete=len(teamb_resources),
                enrichments_to_create=len(teama_resources),
                total_operations=len(teamb_resources) + len(teama_resources)
            )

            delete_count = 0
            create_success_count = 0
            error_count = 0

            # Step 5: Delete ALL existing enrichments from Team B
            self.logger.info("🗑️ Deleting ALL existing general enrichment rules from Team B...")

            if teamb_resources:
                try:
                    if self.delete_all_resources_from_teamb():
                        delete_count = len(teamb_resources)
                        self.logger.info(f"✅ Successfully deleted all {delete_count} enrichments from Team B")
                except Exception as e:
                    self.logger.error(f"Failed to delete enrichments from Team B: {e}")
                    error_count += 1
                    raise

                # Step 5.1: Verify deletion completed - fetch fresh TeamB state
                self.logger.info("🔍 Verifying all enrichments were deleted from Team B...")
                verification_teamb_resources = self.fetch_resources_from_teamb()

                if verification_teamb_resources:
                    self.logger.error(f"❌ Deletion verification failed: {len(verification_teamb_resources)} enrichments still exist in Team B")
                    raise RuntimeError(f"Failed to delete all enrichments from Team B. {len(verification_teamb_resources)} still remain.")
                else:
                    self.logger.info("✅ Deletion verification passed: Team B is now empty")
            else:
                self.logger.info("ℹ️ Team B already has no enrichments - skipping deletion")

            # Step 6: Create ALL enrichments from Team A
            self.logger.info("📄 Creating ALL general enrichment rules from Team A...")

            if teama_resources:
                for teama_resource in teama_resources:
                    try:
                        resource_name = teama_resource.get('enrichedFieldName', 'Unknown')

                        self.logger.info(f"Creating enrichment: {resource_name}")
                        self.create_resource_in_teamb(teama_resource)
                        create_success_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to create enrichment {teama_resource.get('enrichedFieldName', 'Unknown')}: {e}")
                        error_count += 1

                # Step 6.1: Verify creation completed - fetch final TeamB state
                self.logger.info("🔍 Verifying all enrichments were created in Team B...")
                final_teamb_resources = self.fetch_resources_from_teamb()

                expected_count = len(teama_resources)
                actual_count = len(final_teamb_resources)

                if actual_count != expected_count:
                    self.logger.error(f"❌ Creation verification failed: Expected {expected_count} enrichments, but found {actual_count} in Team B")
                    raise RuntimeError(f"Creation verification failed: Expected {expected_count} enrichments, but found {actual_count}")
                else:
                    self.logger.info(f"✅ Creation verification passed: {actual_count} enrichments successfully created in Team B")

                    # Save final state to outputs
                    self.logger.info("💾 Saving final Team B state to outputs...")
                    self.save_artifacts(final_teamb_resources, "teamb_final")
            else:
                self.logger.info("ℹ️ Team A has no enrichments - skipping creation")
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
            print("MIGRATION RESULTS - GENERAL ENRICHMENT RULES")
            print("=" * 60)
            print(f"📊 Team A enrichments: {len(teama_resources)}")
            print(f"📊 Team B enrichments (before): {len(teamb_resources)}")
            print(f"📊 Team B enrichments (after): {len(final_teamb_resources)}")
            print(f"🗑️  Deleted from Team B: {delete_count}")
            print(f"✅ Successfully created: {create_success_count}")
            if error_count > 0:
                print(f"❌ Failed: {error_count}")
            print(f"📋 Total operations: {delete_count + create_success_count + error_count}")

            if migration_success:
                print("\n✅ Migration completed successfully!")
            else:
                print("\n❌ Migration completed with errors!")
                print(f"   {error_count} enrichment(s) failed to create")

            print("=" * 60 + "\n")

            return migration_success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def dry_run(self) -> bool:
        """Perform a dry run to show what would be migrated."""
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch resources from both teams
            self.logger.info("Fetching general enrichment rules from Team A...")
            teama_enrichments = self.fetch_resources_from_teama()

            # Export Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_enrichments, "teama")

            self.logger.info("Fetching general enrichment rules from Team B...")
            teamb_enrichments = self.fetch_resources_from_teamb()

            # Export Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_enrichments, "teamb")

            # Calculate what would be done
            total_operations = len(teamb_enrichments) + len(teama_enrichments)

            # Print dry-run summary
            print("\n" + "=" * 60)
            print("DRY RUN - GENERAL ENRICHMENT RULES MIGRATION")
            print("=" * 60)
            print(f"📊 Team A enrichments: {len(teama_enrichments)}")
            print(f"📊 Team B enrichments (current): {len(teamb_enrichments)}")
            print("\n🔄 Planned Operations:")
            print(f"   🗑️  Delete ALL {len(teamb_enrichments)} enrichments from Team B")
            print(f"   ✅ Create {len(teama_enrichments)} enrichments from Team A")
            print(f"\n📋 Total operations: {total_operations}")
            print("=" * 60 + "\n")

            # Display sample enrichments
            if teama_enrichments:
                print("Sample enrichments from Team A (first 5):")
                for i, enrichment in enumerate(teama_enrichments[:5], 1):
                    field_name = enrichment.get('enrichedFieldName', 'Unknown')
                    source_field = enrichment.get('fieldName', 'Unknown')
                    enrichment_type = list(enrichment.get('enrichmentType', {}).keys())[0] if enrichment.get('enrichmentType') else 'Unknown'
                    print(f"  {i}. {field_name} (from: {source_field}, type: {enrichment_type})")
                print()

            self.log_migration_complete(self.service_name, True, 0, 0)
            return True

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False
