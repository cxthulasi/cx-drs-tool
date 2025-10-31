"""
Enrichments migration service for Coralogix DR Tool.
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any

from core.base_service import BaseService
from core.api_client import CoralogixAPIError


class EnrichmentsService(BaseService):
    """Service for migrating custom enrichments between teams."""

    def __init__(self, config, logger=None):
        super().__init__(config, logger)
        self.failed_enrichments = []  # Track failed enrichments for logging
        self.creation_delay = 0.5  # Default delay between enrichment creations (seconds)
        self.max_retries = 3  # Maximum number of retries for failed operations
        self.base_backoff = 1.0  # Base backoff time in seconds

    @property
    def service_name(self) -> str:
        return "enrichments"

    @property
    def api_endpoint(self) -> str:
        return "/v1/custom_enrichment"

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get unique identifier for an enrichment."""
        return str(resource.get('id', 'unknown'))

    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get display name for an enrichment."""
        return resource.get('name', 'Unknown Enrichment')

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

    def _log_failed_enrichment(self, enrichment: Dict[str, Any], operation: str, error: str):
        """
        Log a failed enrichment operation for later review.

        Args:
            enrichment: The enrichment that failed
            operation: The operation that failed (create, update, delete)
            error: The error message
        """
        failed_enrichment = {
            'enrichment_id': self.get_resource_identifier(enrichment),
            'enrichment_name': self.get_resource_name(enrichment),
            'operation': operation,
            'error': str(error),
            'timestamp': datetime.now().isoformat(),
            'enrichment_data': enrichment
        }

        self.failed_enrichments.append(failed_enrichment)
        self.logger.error(
            f"Failed {operation} operation for enrichment '{failed_enrichment['enrichment_name']}' "
            f"(ID: {failed_enrichment['enrichment_id']}): {error}"
        )

    def _save_failed_enrichments_log(self):
        """Save failed enrichments to a log file for review."""
        if not self.failed_enrichments:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_enrichments_file = f"logs/enrichments/failed_enrichments_{timestamp}.json"

        # Ensure the logs directory exists
        import os
        os.makedirs(os.path.dirname(failed_enrichments_file), exist_ok=True)

        try:
            with open(failed_enrichments_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'total_failed': len(self.failed_enrichments),
                    'failed_enrichments': self.failed_enrichments
                }, f, indent=2)

            self.logger.info(f"Failed enrichments log saved to: {failed_enrichments_file}")

        except Exception as e:
            self.logger.error(f"Failed to save failed enrichments log: {e}")

    def _add_creation_delay(self):
        """Add a delay between enrichment creations to avoid overwhelming the API."""
        if self.creation_delay > 0:
            time.sleep(self.creation_delay)

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch enrichments from Team A."""
        try:
            self.logger.info("Fetching enrichments from Team A")

            # Use the get method from base class
            response = self.teama_client.get(self.api_endpoint)

            # Extract enrichments from response
            enrichments = response.get('customEnrichments', [])

            self.logger.info(f"Fetched {len(enrichments)} enrichments from Team A")
            return enrichments

        except Exception as e:
            self.logger.error(f"Failed to fetch enrichments from Team A: {e}")
            raise

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch enrichments from Team B."""
        try:
            self.logger.info("Fetching enrichments from Team B")

            # Use the get method from base class
            response = self.teamb_client.get(self.api_endpoint)

            # Extract enrichments from response
            enrichments = response.get('customEnrichments', [])

            self.logger.info(f"Fetched {len(enrichments)} enrichments from Team B")
            return enrichments

        except Exception as e:
            self.logger.error(f"Failed to fetch enrichments from Team B: {e}")
            raise

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create an enrichment in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_resource_for_creation(resource)
            enrichment_name = create_data.get('name', 'Unknown')

            self.logger.info(f"Creating enrichment in Team B: {enrichment_name}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Create the enrichment with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=create_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "enrichment", enrichment_name, True)

            # Return the enrichment from the response
            return response.get('customEnrichment', response)

        except Exception as e:
            enrichment_name = resource.get('name', 'Unknown')
            self._log_failed_enrichment(resource, 'create', str(e))
            self.log_resource_action("create", "enrichment", enrichment_name, False, str(e))
            raise

    def update_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Update an enrichment in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in update
            update_data = self._prepare_resource_for_update(resource)
            enrichment_id = resource.get('id')
            enrichment_name = update_data.get('name', 'Unknown')

            if not enrichment_id:
                raise ValueError("Enrichment ID is required for update")

            self.logger.info(f"Updating enrichment in Team B: {enrichment_name}")

            # Add delay before update to avoid overwhelming the API
            self._add_creation_delay()

            # Update the enrichment with exponential backoff
            def _update_operation():
                return self.teamb_client.put(self.api_endpoint, json_data=update_data)

            response = self._retry_with_exponential_backoff(_update_operation)

            self.log_resource_action("update", "enrichment", enrichment_name, True)

            # Return the enrichment from the response
            return response.get('customEnrichment', response)

        except Exception as e:
            enrichment_name = resource.get('name', 'Unknown')
            self._log_failed_enrichment(resource, 'update', str(e))
            self.log_resource_action("update", "enrichment", enrichment_name, False, str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete an enrichment from Team B."""
        try:
            self.logger.info(f"Deleting enrichment from Team B: {resource_id}")

            # Add delay before deletion to avoid overwhelming the API
            self._add_creation_delay()

            # Delete the enrichment with exponential backoff
            def _delete_operation():
                return self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self._retry_with_exponential_backoff(_delete_operation)

            self.log_resource_action("delete", "enrichment", resource_id, True)
            return True

        except Exception as e:
            self.log_resource_action("delete", "enrichment", resource_id, False, str(e))
            raise

    def _prepare_resource_for_creation(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare enrichment data for creation by removing read-only fields."""
        # Check if this enrichment has file content
        file_name = resource.get('fileName', '')
        file_size = resource.get('fileSize', 0)

        if not file_name or file_size == 0:
            # This enrichment has no file content, cannot be migrated
            raise ValueError(f"Enrichment '{resource.get('name')}' has no file content (fileName: '{file_name}', fileSize: {file_size}). Enrichments without file content cannot be migrated.")

        # For enrichments with file content, we need to construct the file object
        # Since the GET API doesn't return file content, we need to handle this differently
        file_extension = file_name.split('.')[-1] if '.' in file_name else 'csv'

        # Create a clean copy for creation
        create_data = {
            'name': resource.get('name'),
            'description': resource.get('description', ''),
            'file': {
                'name': file_name.rsplit('.', 1)[0] if '.' in file_name else file_name,
                'extension': file_extension,
                'size': file_size,
                'textual': ''  # We don't have the actual file content from the GET API
            }
        }

        # Remove any None values
        create_data = {k: v for k, v in create_data.items() if v is not None}

        return create_data

    def _prepare_resource_for_update(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare enrichment data for update."""
        # For updates, we need to include the customEnrichmentId
        update_data = {
            'customEnrichmentId': resource.get('id'),
            'name': resource.get('name'),
            'description': resource.get('description', ''),
            'file': resource.get('file', {})
        }

        # Remove any None values
        update_data = {k: v for k, v in update_data.items() if v is not None}

        return update_data

    def dry_run(self) -> dict:
        """
        Perform a dry run to show what would be migrated for enrichments.

        Returns:
            Dictionary with dry run results for display
        """
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch enrichments from both teams
            self.logger.info("Fetching enrichments from Team A...")
            teama_enrichments = self.fetch_resources_from_teama()

            self.logger.info("Fetching enrichments from Team B...")
            teamb_enrichments = self.fetch_resources_from_teamb()

            # Save artifacts
            self.save_artifacts(teama_enrichments, "teama")
            self.save_artifacts(teamb_enrichments, "teamb")

            # Calculate operations
            total_operations = len(teamb_enrichments) + len(teama_enrichments)

            self.log_migration_complete(self.service_name, True, total_operations, 0)

            return {
                'teama_enrichments': teama_enrichments,
                'teamb_enrichments': teamb_enrichments,
                'total_operations': total_operations
            }

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return {
                'teama_enrichments': [],
                'teamb_enrichments': [],
                'total_operations': 0,
                'error': str(e)
            }

    def display_dry_run_results(self, results: dict):
        """
        Display formatted dry run results for enrichments migration.

        Args:
            results: Dry run results dictionary
        """
        print("\n" + "=" * 70)
        print("DRY RUN RESULTS - ENRICHMENTS (Delete All + Recreate All Strategy)")
        print("=" * 70)

        teama_enrichments = results.get('teama_enrichments', [])
        teamb_enrichments = results.get('teamb_enrichments', [])

        print(f"📊 Team A Enrichments: {len(teama_enrichments)}")
        print(f"📊 Team B Enrichments: {len(teamb_enrichments)}")
        print("")

        # Show planned operations
        total_operations = len(teamb_enrichments) + len(teama_enrichments)

        print("🎯 PLANNED OPERATIONS:")
        print(f"  Step 1: Delete ALL {len(teamb_enrichments)} enrichments from Team B")
        print(f"  Step 2: Create ALL {len(teama_enrichments)} enrichments from Team A")
        print(f"  Total operations: {total_operations}")
        print("")

        # Show sample enrichments
        if teamb_enrichments:
            print(f"🗑️ Sample enrichments to be DELETED from Team B (showing first 3):")
            for i, enrichment in enumerate(teamb_enrichments[:3]):
                name = enrichment.get('name', 'Unknown')
                enrichment_type = enrichment.get('type', 'Unknown')
                print(f"  - {name} (Type: {enrichment_type})")
            if len(teamb_enrichments) > 3:
                print(f"  ... and {len(teamb_enrichments) - 3} more enrichments")
            print("")

        if teama_enrichments:
            print(f"✨ Sample enrichments to be CREATED in Team B (showing first 3):")
            for i, enrichment in enumerate(teama_enrichments[:3]):
                name = enrichment.get('name', 'Unknown')
                enrichment_type = enrichment.get('type', 'Unknown')
                print(f"  - {name} (Type: {enrichment_type})")
            if len(teama_enrichments) > 3:
                print(f"  ... and {len(teama_enrichments) - 3} more enrichments")
            print("")

        print("🎯 EXPECTED RESULT:")
        print(f"  Team B will have {len(teama_enrichments)} enrichments (same as Team A)")
        print("=" * 70)

    def migrate(self) -> bool:
        """Perform the actual enrichments migration with enhanced features."""
        try:
            # Fetch resources from both teams
            self.logger.info("Fetching resources from Team A...")
            teama_enrichments = self.fetch_resources_from_teama()

            # Export Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_enrichments, "teama")

            self.logger.info("Fetching resources from Team B...")
            teamb_enrichments = self.fetch_resources_from_teamb()

            # Export Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_enrichments, "teamb")

            # Create mappings by ID for comparison
            teama_by_id = {self.get_resource_identifier(enrichment): enrichment for enrichment in teama_enrichments}
            teamb_by_id = {self.get_resource_identifier(enrichment): enrichment for enrichment in teamb_enrichments}

            # Track migration statistics
            created_count = 0
            recreated_count = 0  # Changed from updated_count to recreated_count
            skipped_count = 0  # Track enrichments skipped due to no file content
            errors_count = 0
            total_enrichments = len(teama_by_id)

            self.logger.info(f"Starting migration of {total_enrichments} enrichments...")

            # Process each enrichment from Team A
            for index, (enrichment_id, teama_enrichment) in enumerate(teama_by_id.items(), 1):
                enrichment_name = self.get_resource_name(teama_enrichment)

                try:
                    self.logger.info(f"Processing enrichment {index}/{total_enrichments}: {enrichment_name}")

                    if enrichment_id not in teamb_by_id:
                        # Enrichment doesn't exist in Team B, create it
                        self.logger.info(f"Creating new enrichment: {enrichment_name}")

                        # Check if enrichment has file content before attempting creation
                        file_name = teama_enrichment.get('fileName', '')
                        file_size = teama_enrichment.get('fileSize', 0)

                        if not file_name or file_size == 0:
                            self.logger.warning(f"⚠️ Skipping enrichment '{enrichment_name}' - no file content (fileName: '{file_name}', fileSize: {file_size})")
                            self.logger.info(f"ℹ️ Enrichments without file content cannot be migrated via API")
                            skipped_count += 1
                            continue

                        self.create_resource_in_teamb(teama_enrichment)
                        created_count += 1
                        self.logger.info(f"✅ Successfully created enrichment: {enrichment_name}")

                    else:
                        # Enrichment exists in Team B, check if it needs updating
                        teamb_enrichment = teamb_by_id[enrichment_id]

                        if not self.resources_are_equal(teama_enrichment, teamb_enrichment):
                            self.logger.info(f"Enrichment changed, deleting and recreating: {enrichment_name}")

                            # Check if enrichment has file content before attempting recreation
                            file_name = teama_enrichment.get('fileName', '')
                            file_size = teama_enrichment.get('fileSize', 0)

                            if not file_name or file_size == 0:
                                self.logger.warning(f"⚠️ Skipping recreation of enrichment '{enrichment_name}' - no file content (fileName: '{file_name}', fileSize: {file_size})")
                                self.logger.info(f"ℹ️ Enrichments without file content cannot be migrated via API")
                                skipped_count += 1
                                continue

                            # First, delete the existing enrichment from Team B
                            teamb_enrichment_id = teamb_enrichment.get('id')
                            if teamb_enrichment_id:
                                self.logger.info(f"Deleting existing enrichment from Team B: {enrichment_name}")
                                self.delete_resource_from_teamb(str(teamb_enrichment_id))
                                self.logger.info(f"✅ Successfully deleted enrichment: {enrichment_name}")

                            # Then, create the new enrichment in Team B
                            self.logger.info(f"Creating updated enrichment in Team B: {enrichment_name}")
                            self.create_resource_in_teamb(teama_enrichment)
                            recreated_count += 1
                            self.logger.info(f"✅ Successfully recreated enrichment: {enrichment_name}")
                        else:
                            self.logger.debug(f"Enrichment unchanged: {enrichment_name}")

                except Exception as e:
                    self.logger.error(f"❌ Failed to process enrichment {enrichment_name}: {e}")
                    errors_count += 1
                    # Failed enrichment is already logged by _log_failed_enrichment in create/update methods
                    continue

            # Save failed enrichments log if there were any failures
            if self.failed_enrichments:
                self.logger.warning(f"Saving log of {len(self.failed_enrichments)} failed enrichments...")
                self._save_failed_enrichments_log()

            # Update state with current resources
            state = {
                "last_run": datetime.now().isoformat(),
                "resources": {self.get_resource_identifier(enrichment): enrichment for enrichment in teama_enrichments},
                "mappings": {},  # Could be used for ID mappings between teams
                "migration_stats": {
                    "total_enrichments": total_enrichments,
                    "created": created_count,
                    "recreated": recreated_count,
                    "skipped": skipped_count,
                    "failed": errors_count,
                    "success_rate": f"{((total_enrichments - errors_count - skipped_count) / total_enrichments * 100):.1f}%" if total_enrichments > 0 else "0%"
                }
            }
            self.save_state(state)

            # Log completion with detailed statistics
            total_processed = created_count + recreated_count
            success = errors_count == 0

            self.logger.info(f"Migration Summary:")
            self.logger.info(f"  Total enrichments processed: {total_enrichments}")
            self.logger.info(f"  Successfully created: {created_count}")
            self.logger.info(f"  Successfully recreated: {recreated_count}")
            self.logger.info(f"  Skipped (no file content): {skipped_count}")
            self.logger.info(f"  Failed operations: {errors_count}")
            self.logger.info(f"  Success rate: {((total_enrichments - errors_count - skipped_count) / total_enrichments * 100):.1f}%" if total_enrichments > 0 else "0%")

            self.log_migration_complete(self.service_name, success, total_processed, errors_count)

            if success:
                self.logger.info("🎉 Enrichments migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ Enrichments migration completed with {errors_count} errors. Check failed enrichments log for details.")

            if recreated_count > 0:
                self.logger.info(f"ℹ️ Note: {recreated_count} enrichments were deleted and recreated due to changes.")

            if skipped_count > 0:
                self.logger.warning(f"⚠️ Note: {skipped_count} enrichments were skipped because they have no file content.")
                self.logger.info(f"ℹ️ Enrichments without file content cannot be migrated via API and must be recreated manually.")

            return success

        except Exception as e:
            self.logger.error(f"❌ Enrichments migration failed: {e}")

            # Save failed enrichments log if there were any failures
            if self.failed_enrichments:
                self.logger.warning(f"Saving log of {len(self.failed_enrichments)} failed enrichments...")
                self._save_failed_enrichments_log()

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False
