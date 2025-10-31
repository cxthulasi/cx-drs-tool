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

from core.base_service import BaseService
from core.config import Config
from core.api_client import CoralogixAPIError


class Events2MetricsService(BaseService):
    """Service for migrating Events2Metrics (E2M) between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_e2m_logging()

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
        Fetch all Events2Metrics from Team A.

        Returns:
            List of E2M definitions from Team A
        """
        try:
            self.logger.info("Fetching Events2Metrics from Team A...")
            response = self.teama_client.get(self.api_endpoint)

            if not response or 'e2m' not in response:
                self.logger.warning("No Events2Metrics found in Team A or invalid response format")
                return []

            e2m_list = response['e2m']
            self.logger.info(f"Found {len(e2m_list)} Events2Metrics in Team A")

            # Save artifacts for comparison
            self._save_artifacts("teama", e2m_list)

            return e2m_list

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch Events2Metrics from Team A: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching Events2Metrics from Team A: {e}")
            return []

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

    def dry_run(self) -> Dict[str, Any]:
        """
        Perform a dry run to show what would be migrated without making changes.

        Returns:
            Dictionary containing dry run results
        """
        self.logger.info("Starting Events2Metrics dry run...")

        # Fetch E2Ms from both teams
        teama_e2ms = self.fetch_resources_from_teama()
        teamb_e2ms = self.fetch_resources_from_teamb()

        # Analyze what needs to be done
        to_create = []
        to_recreate = []
        to_delete = []

        # Create name-to-E2M mappings for easier lookup
        teamb_e2ms_by_name = {e2m.get('name'): e2m for e2m in teamb_e2ms}
        teama_e2ms_by_name = {e2m.get('name'): e2m for e2m in teama_e2ms}

        # Check what needs to be created or recreated
        for e2m_a in teama_e2ms:
            name = e2m_a.get('name')
            if not name:
                continue

            e2m_b = teamb_e2ms_by_name.get(name)
            if not e2m_b:
                # E2M doesn't exist in Team B, needs to be created
                to_create.append(e2m_a)
            elif not self._compare_e2m(e2m_a, e2m_b):
                # E2M exists but is different, needs to be recreated
                to_recreate.append((e2m_a, e2m_b))

        # Check what needs to be deleted (exists in Team B but not in Team A)
        for e2m_b in teamb_e2ms:
            name = e2m_b.get('name')
            if name and name not in teama_e2ms_by_name:
                to_delete.append(e2m_b)

        # Calculate total operations
        total_operations = len(to_create) + len(to_recreate) + len(to_delete)

        # Prepare results
        results = {
            'teama_count': len(teama_e2ms),
            'teamb_count': len(teamb_e2ms),
            'to_create': to_create,
            'to_recreate': to_recreate,
            'to_delete': to_delete,
            'total_operations': total_operations
        }

        # Log summary
        self.logger.info(f"Dry run completed:")
        self.logger.info(f"  Team A E2Ms: {len(teama_e2ms)}")
        self.logger.info(f"  Team B E2Ms: {len(teamb_e2ms)}")
        self.logger.info(f"  New E2Ms to create: {len(to_create)}")
        self.logger.info(f"  Changed E2Ms to recreate: {len(to_recreate)}")
        self.logger.info(f"  E2Ms to delete: {len(to_delete)}")
        self.logger.info(f"  Total operations: {total_operations}")

        return results

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
        Perform the actual Events2Metrics migration.

        Returns:
            True if migration completed successfully, False otherwise
        """
        self.logger.info("Starting Events2Metrics migration...")

        try:
            # Get dry run results to know what to do
            dry_run_results = self.dry_run()

            if dry_run_results['total_operations'] == 0:
                self.logger.info("No Events2Metrics migration needed - teams are in sync")
                return True

            # Track migration statistics
            stats = {
                'created': 0,
                'recreated': 0,
                'deleted': 0,
                'failed': 0
            }

            failed_operations = []

            # Delete E2Ms that exist in Team B but not in Team A
            for e2m_to_delete in dry_run_results['to_delete']:
                try:
                    self._add_creation_delay()
                    success = self._retry_with_exponential_backoff(
                        lambda: self.delete_resource_from_teamb(e2m_to_delete['id']),
                        f"delete E2M '{e2m_to_delete.get('name', 'Unknown')}'"
                    )
                    if success:
                        stats['deleted'] += 1
                    else:
                        stats['failed'] += 1
                        failed_operations.append({
                            'operation': 'delete',
                            'e2m_name': e2m_to_delete.get('name', 'Unknown'),
                            'e2m_id': e2m_to_delete.get('id', 'Unknown'),
                            'error': 'Delete operation failed after retries'
                        })
                except Exception as e:
                    stats['failed'] += 1
                    failed_operations.append({
                        'operation': 'delete',
                        'e2m_name': e2m_to_delete.get('name', 'Unknown'),
                        'e2m_id': e2m_to_delete.get('id', 'Unknown'),
                        'error': str(e)
                    })

            # Recreate changed E2Ms (delete + create)
            for e2m_a, e2m_b in dry_run_results['to_recreate']:
                try:
                    # First delete the existing E2M
                    self._add_creation_delay()
                    delete_success = self._retry_with_exponential_backoff(
                        lambda: self.delete_resource_from_teamb(e2m_b['id']),
                        f"delete E2M '{e2m_b.get('name', 'Unknown')}' for recreation"
                    )

                    if delete_success:
                        # Then create the new version
                        self._add_creation_delay()
                        create_success = self._retry_with_exponential_backoff(
                            lambda: self.create_resource_in_teamb(e2m_a),
                            f"recreate E2M '{e2m_a.get('name', 'Unknown')}'"
                        )

                        if create_success:
                            stats['recreated'] += 1
                        else:
                            stats['failed'] += 1
                            failed_operations.append({
                                'operation': 'recreate',
                                'e2m_name': e2m_a.get('name', 'Unknown'),
                                'e2m_data': e2m_a,
                                'error': 'Create operation failed after retries during recreation'
                            })
                    else:
                        stats['failed'] += 1
                        failed_operations.append({
                            'operation': 'recreate',
                            'e2m_name': e2m_a.get('name', 'Unknown'),
                            'e2m_data': e2m_a,
                            'error': 'Delete operation failed during recreation'
                        })

                except Exception as e:
                    stats['failed'] += 1
                    failed_operations.append({
                        'operation': 'recreate',
                        'e2m_name': e2m_a.get('name', 'Unknown'),
                        'e2m_data': e2m_a,
                        'error': str(e)
                    })

            # Create new E2Ms
            for e2m_to_create in dry_run_results['to_create']:
                try:
                    self._add_creation_delay()
                    success = self._retry_with_exponential_backoff(
                        lambda: self.create_resource_in_teamb(e2m_to_create),
                        f"create E2M '{e2m_to_create.get('name', 'Unknown')}'"
                    )
                    if success:
                        stats['created'] += 1
                    else:
                        stats['failed'] += 1
                        failed_operations.append({
                            'operation': 'create',
                            'e2m_name': e2m_to_create.get('name', 'Unknown'),
                            'e2m_data': e2m_to_create,
                            'error': 'Create operation failed after retries'
                        })
                except Exception as e:
                    stats['failed'] += 1
                    failed_operations.append({
                        'operation': 'create',
                        'e2m_name': e2m_to_create.get('name', 'Unknown'),
                        'e2m_data': e2m_to_create,
                        'error': str(e)
                    })

            # Log failed operations if any
            if failed_operations:
                self._log_failed_e2ms(failed_operations)

            # Log final statistics
            total_attempted = stats['created'] + stats['recreated'] + stats['deleted'] + stats['failed']
            success_rate = ((total_attempted - stats['failed']) / total_attempted * 100) if total_attempted > 0 else 100

            self.logger.info("Events2Metrics migration completed:")
            self.logger.info(f"  Created: {stats['created']}")
            self.logger.info(f"  Recreated: {stats['recreated']}")
            self.logger.info(f"  Deleted: {stats['deleted']}")
            self.logger.info(f"  Failed: {stats['failed']}")
            self.logger.info(f"  Success rate: {success_rate:.1f}%")

            return stats['failed'] == 0

        except Exception as e:
            self.logger.error(f"Events2Metrics migration failed with error: {e}")
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
