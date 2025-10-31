"""
Alerts migration service for Coralogix DR Tool.
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any

from core.base_service import BaseService
from core.api_client import CoralogixAPIError


class AlertsService(BaseService):
    """Service for migrating alerts between teams."""

    def __init__(self, config, logger=None):
        super().__init__(config, logger)
        self.failed_alerts = []  # Track failed alerts for logging
        self.creation_delay = 0.5  # Default delay between alert creations (seconds)
        self.max_retries = 3  # Maximum number of retries for failed operations
        self.base_backoff = 1.0  # Base backoff time in seconds

    @property
    def service_name(self) -> str:
        return "alerts"

    @property
    def api_endpoint(self) -> str:
        return "/v3/alert-defs"

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all alerts from Team A."""
        try:
            self.logger.info("Fetching alerts from Team A")

            # Use paginated request to get all alerts
            alerts = self.teama_client.get_paginated(self.api_endpoint)

            self.logger.info(f"Fetched {len(alerts)} alerts from Team A")
            return alerts

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch alerts from Team A: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching alerts from Team A: {e}")
            raise

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all alerts from Team B."""
        try:
            self.logger.info("Fetching alerts from Team B")

            # Use paginated request to get all alerts
            alerts = self.teamb_client.get_paginated(self.api_endpoint)

            self.logger.info(f"Fetched {len(alerts)} alerts from Team B")
            return alerts

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch alerts from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching alerts from Team B: {e}")
            raise

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create an alert in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_resource_for_creation(resource)
            alert_name = create_data.get('name', 'Unknown')

            self.logger.info(f"Creating alert in Team B: {alert_name}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Create the alert with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=create_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "alert", alert_name, True)

            # Return the alert from the response
            return response.get('alertDef', response)

        except Exception as e:
            alert_name = resource.get('alertDefProperties', {}).get('name', 'Unknown')
            self._log_failed_alert(resource, 'create', str(e))
            self.log_resource_action("create", "alert", alert_name, False, str(e))
            raise

    def update_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Update an alert in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in update
            update_data = self._prepare_resource_for_update(resource)
            alert_id = resource.get('id')
            alert_name = update_data.get('alertDefProperties', {}).get('name', 'Unknown')

            if not alert_id:
                raise ValueError("Alert ID is required for update")

            self.logger.info(f"Updating alert in Team B: {alert_name}")

            # Add delay before update to avoid overwhelming the API
            self._add_creation_delay()

            # Update the alert with exponential backoff
            def _update_operation():
                return self.teamb_client.put(self.api_endpoint, json_data=update_data)

            response = self._retry_with_exponential_backoff(_update_operation)

            self.log_resource_action("update", "alert", alert_name, True)

            # Return the alert from the response
            return response.get('alertDef', response)

        except Exception as e:
            alert_name = resource.get('alertDefProperties', {}).get('name', 'Unknown')
            self._log_failed_alert(resource, 'update', str(e))
            self.log_resource_action("update", "alert", alert_name, False, str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete an alert from Team B."""
        try:
            self.logger.info(f"Deleting alert from Team B: {resource_id}")

            # Delete the alert
            self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self.log_resource_action("delete", "alert", resource_id, True)
            return True

        except CoralogixAPIError as e:
            self.log_resource_action("delete", "alert", resource_id, False, str(e))
            raise
        except Exception as e:
            self.log_resource_action("delete", "alert", resource_id, False, str(e))
            raise

    def _prepare_resource_for_creation(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare alert data for creation by removing read-only fields."""
        # Extract the alert properties
        alert_props = resource.get('alertDefProperties', {}).copy()

        # Remove read-only fields that shouldn't be included in creation
        fields_to_remove = [
            'webhooks',  # Remove webhooks as specified
        ]

        # Remove notification group webhooks if they exist
        if 'notificationGroup' in alert_props:
            notification_group = alert_props['notificationGroup'].copy()
            if 'webhooks' in notification_group:
                del notification_group['webhooks']
            alert_props['notificationGroup'] = notification_group

        # Remove notification group excess webhooks if they exist
        if 'notificationGroupExcess' in alert_props:
            excess_groups = []
            for group in alert_props['notificationGroupExcess']:
                group_copy = group.copy()
                if 'webhooks' in group_copy:
                    del group_copy['webhooks']
                excess_groups.append(group_copy)
            alert_props['notificationGroupExcess'] = excess_groups

        # Remove any other specified fields
        for field in fields_to_remove:
            if field in alert_props:
                del alert_props[field]

        return alert_props

    def _prepare_resource_for_update(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare alert data for update by removing read-only fields."""
        # Start with the creation preparation
        alert_props = self._prepare_resource_for_creation(resource)

        # For updates, we need to include the ID and wrap in the expected format
        alert_id = resource.get('id')
        if not alert_id:
            raise ValueError("Alert ID is required for update")

        return {
            'alertDefProperties': alert_props,
            'id': alert_id
        }

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get unique identifier for an alert."""
        return resource.get('id', '')

    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get display name for an alert."""
        return resource.get('alertDefProperties', {}).get('name', 'Unknown Alert')

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

    def _log_failed_alert(self, alert: Dict[str, Any], operation: str, error: str):
        """
        Log a failed alert operation for later review.

        Args:
            alert: The alert that failed
            operation: The operation that failed (create, update, delete)
            error: The error message
        """
        failed_alert = {
            'alert_id': self.get_resource_identifier(alert),
            'alert_name': self.get_resource_name(alert),
            'operation': operation,
            'error': str(error),
            'timestamp': datetime.now().isoformat(),
            'alert_data': alert
        }

        self.failed_alerts.append(failed_alert)
        self.logger.error(
            f"Failed {operation} operation for alert '{failed_alert['alert_name']}' "
            f"(ID: {failed_alert['alert_id']}): {error}"
        )

    def _save_failed_alerts_log(self):
        """Save failed alerts to a log file for review."""
        if not self.failed_alerts:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_alerts_file = f"logs/alerts/failed_alerts_{timestamp}.json"

        # Ensure the logs directory exists
        import os
        os.makedirs(os.path.dirname(failed_alerts_file), exist_ok=True)

        try:
            with open(failed_alerts_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'total_failed': len(self.failed_alerts),
                    'failed_alerts': self.failed_alerts
                }, f, indent=2)

            self.logger.info(f"Failed alerts log saved to: {failed_alerts_file}")

        except Exception as e:
            self.logger.error(f"Failed to save failed alerts log: {e}")

    def _add_creation_delay(self):
        """Add a delay between alert creations to avoid overwhelming the API."""
        if self.creation_delay > 0:
            time.sleep(self.creation_delay)

    def migrate(self) -> bool:
        """
        Perform the actual alerts migration.

        This method:
        1. Fetches all alerts from Team A
        2. Fetches all alerts from Team B
        3. Compares and identifies changes
        4. Creates new alerts in Team B
        5. Updates changed alerts in Team B
        6. Optionally deletes alerts that no longer exist in Team A

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Fetch current resources from Team A
            self.logger.info("Fetching alerts from Team A...")
            teama_alerts = self.fetch_resources_from_teama()

            # Save Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_alerts, 'teama')

            # Fetch current resources from Team B
            self.logger.info("Fetching alerts from Team B...")
            teamb_alerts = self.fetch_resources_from_teamb()

            # Save Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_alerts, 'teamb')

            # Create lookup dictionaries for comparison
            teama_by_id = {self.get_resource_identifier(alert): alert for alert in teama_alerts}
            teamb_by_id = {self.get_resource_identifier(alert): alert for alert in teamb_alerts}

            # Track migration statistics
            created_count = 0
            updated_count = 0
            errors_count = 0
            total_alerts = len(teama_by_id)

            self.logger.info(f"Starting migration of {total_alerts} alerts...")

            # Process each alert from Team A
            for index, (alert_id, teama_alert) in enumerate(teama_by_id.items(), 1):
                alert_name = self.get_resource_name(teama_alert)

                try:
                    self.logger.info(f"Processing alert {index}/{total_alerts}: {alert_name}")

                    if alert_id not in teamb_by_id:
                        # Alert doesn't exist in Team B, create it
                        self.logger.info(f"Creating new alert: {alert_name}")
                        self.create_resource_in_teamb(teama_alert)
                        created_count += 1
                        self.logger.info(f"✅ Successfully created alert: {alert_name}")

                    else:
                        # Alert exists in Team B, check if it needs updating
                        teamb_alert = teamb_by_id[alert_id]

                        if not self.resources_are_equal(teama_alert, teamb_alert):
                            self.logger.info(f"Updating changed alert: {alert_name}")
                            # Copy the ID from Team B alert for update
                            teama_alert_with_id = teama_alert.copy()
                            teama_alert_with_id['id'] = teamb_alert.get('id')
                            self.update_resource_in_teamb(teama_alert_with_id)
                            updated_count += 1
                            self.logger.info(f"✅ Successfully updated alert: {alert_name}")
                        else:
                            self.logger.debug(f"Alert unchanged: {alert_name}")

                except Exception as e:
                    self.logger.error(f"❌ Failed to process alert {alert_name}: {e}")
                    errors_count += 1
                    # Failed alert is already logged by _log_failed_alert in create/update methods
                    continue

            # Save failed alerts log if there were any failures
            if self.failed_alerts:
                self.logger.warning(f"Saving log of {len(self.failed_alerts)} failed alerts...")
                self._save_failed_alerts_log()

            # Update state with current resources
            state = {
                "last_run": datetime.now().isoformat(),
                "resources": {self.get_resource_identifier(alert): alert for alert in teama_alerts},
                "mappings": {},  # Could be used for ID mappings between teams
                "migration_stats": {
                    "total_alerts": total_alerts,
                    "created": created_count,
                    "updated": updated_count,
                    "failed": errors_count,
                    "success_rate": f"{((total_alerts - errors_count) / total_alerts * 100):.1f}%" if total_alerts > 0 else "0%"
                }
            }
            self.save_state(state)

            # Log completion with detailed statistics
            total_processed = created_count + updated_count
            success = errors_count == 0

            self.logger.info(f"Migration Summary:")
            self.logger.info(f"  Total alerts processed: {total_alerts}")
            self.logger.info(f"  Successfully created: {created_count}")
            self.logger.info(f"  Successfully updated: {updated_count}")
            self.logger.info(f"  Failed operations: {errors_count}")
            self.logger.info(f"  Success rate: {((total_alerts - errors_count) / total_alerts * 100):.1f}%" if total_alerts > 0 else "0%")

            self.log_migration_complete(self.service_name, success, total_processed, errors_count)

            if success:
                self.logger.info("🎉 Alerts migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ Alerts migration completed with {errors_count} errors. Check failed alerts log for details.")

            return success

        except Exception as e:
            self.logger.error(f"❌ Alerts migration failed: {e}")

            # Save failed alerts log if there were any failures
            if self.failed_alerts:
                self.logger.warning(f"Saving log of {len(self.failed_alerts)} failed alerts...")
                self._save_failed_alerts_log()

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False
