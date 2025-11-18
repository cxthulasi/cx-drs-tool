"""
SLO migration service for Coralogix DR Tool.
"""

import time
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

from core.base_service import BaseService
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager


class SLOService(BaseService):
    """Service for migrating SLOs between teams."""

    def __init__(self, config, logger=None):
        super().__init__(config, logger)

        # Initialize safety manager and version manager
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "slo"

    @property
    def api_endpoint(self) -> str:
        return "/v1/slo/slos"

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all SLOs from Team A with safety checks."""
        api_error = None
        slos = []

        try:
            self.logger.info("Fetching SLOs from Team A")
            data = self.teama_client.get("/v1/slo/slos")

            if data and 'slos' in data:
                slos = data.get('slos', [])
                self.logger.info(f"Fetched {len(slos)} SLOs from Team A")

                # Debug: Log SLO structure to understand ID field location
                if slos:
                    sample_slo = slos[0]
                    self.logger.debug(f"🔍 SLO Debug - Sample Team A SLO structure:")
                    self.logger.debug(f"🔍 SLO Debug - Keys: {list(sample_slo.keys())}")
                    if 'id' in sample_slo:
                        self.logger.debug(f"🔍 SLO Debug - Direct ID: {sample_slo.get('id')}")
                    if 'slo' in sample_slo and isinstance(sample_slo['slo'], dict):
                        self.logger.debug(f"🔍 SLO Debug - Nested SLO keys: {list(sample_slo['slo'].keys())}")
                        if 'id' in sample_slo['slo']:
                            self.logger.debug(f"🔍 SLO Debug - Nested ID: {sample_slo['slo'].get('id')}")
            else:
                self.logger.warning("No SLOs found in Team A or invalid response format")
                slos = []

        except Exception as e:
            self.logger.error(f"Error fetching SLOs from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            slos, api_error, previous_count
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

        return slos

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all SLOs from Team B."""
        try:
            self.logger.info("Fetching SLOs from Team B")
            data = self.teamb_client.get("/v1/slo/slos")

            if data and 'slos' in data:
                slos = data.get('slos', [])
                self.logger.info(f"Fetched {len(slos)} SLOs from Team B")

                # Debug: Log SLO structure to understand ID field location
                if slos:
                    sample_slo = slos[0]
                    self.logger.debug(f"🔍 SLO Debug - Sample Team B SLO structure:")
                    self.logger.debug(f"🔍 SLO Debug - Keys: {list(sample_slo.keys())}")
                    if 'id' in sample_slo:
                        self.logger.debug(f"🔍 SLO Debug - Direct ID: {sample_slo.get('id')}")
                    if 'slo' in sample_slo and isinstance(sample_slo['slo'], dict):
                        self.logger.debug(f"🔍 SLO Debug - Nested SLO keys: {list(sample_slo['slo'].keys())}")
                        if 'id' in sample_slo['slo']:
                            self.logger.debug(f"🔍 SLO Debug - Nested ID: {sample_slo['slo'].get('id')}")

                return slos
            else:
                self.logger.warning("No SLOs found in Team B or invalid response format")
                return []

        except Exception as e:
            self.logger.error(f"Error fetching SLOs from Team B: {e}")
            return []

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for an SLO."""
        return resource.get('name', '')

    def get_slo_id(self, slo: Dict[str, Any]) -> Optional[str]:
        """
        Extract SLO ID from SLO object, handling both direct and nested structures.

        Args:
            slo: SLO object from API response

        Returns:
            SLO ID string or None if not found
        """
        # Try direct ID first
        if 'id' in slo and slo['id']:
            return slo['id']

        # Try nested SLO structure
        if 'slo' in slo and isinstance(slo['slo'], dict):
            nested_slo = slo['slo']
            if 'id' in nested_slo and nested_slo['id']:
                return nested_slo['id']

        # Log warning if no ID found
        slo_name = slo.get('name', 'Unknown')
        self.logger.warning(f"⚠️ No ID found for SLO '{slo_name}'. Available keys: {list(slo.keys())}")
        return None

    def delete_all_slos_from_teamb(self, teamb_slos: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Delete all SLOs from Team B.

        Args:
            teamb_slos: List of SLO objects from Team B

        Returns:
            Dictionary with deletion statistics
        """
        stats = {
            'total': len(teamb_slos),
            'deleted': 0,
            'failed': 0
        }

        if not teamb_slos:
            self.logger.info("No SLOs to delete from Team B")
            return stats

        self.logger.info(f"Deleting {len(teamb_slos)} SLOs from Team B...")

        for slo in teamb_slos:
            try:
                slo_id = self.get_slo_id(slo)
                slo_name = slo.get('name', 'Unknown')

                if slo_id:
                    if self.delete_resource_from_teamb(slo_id):
                        stats['deleted'] += 1
                        self.logger.debug(f"✅ Deleted SLO: {slo_name}")
                    else:
                        stats['failed'] += 1
                        self.logger.error(f"❌ Failed to delete SLO: {slo_name}")
                else:
                    stats['failed'] += 1
                    self.logger.error(f"❌ Could not extract ID for SLO: {slo_name}")

                # Add delay between deletions
                self._add_creation_delay()

            except Exception as e:
                stats['failed'] += 1
                self.logger.error(f"❌ Exception deleting SLO {slo.get('name', 'Unknown')}: {e}")

        self.logger.info(f"Deletion complete: {stats['deleted']}/{stats['total']} deleted, {stats['failed']} failed")
        return stats

    def _clean_slo_for_creation(self, slo: Dict[str, Any]) -> Dict[str, Any]:
        """Clean SLO data for creation by removing fields that shouldn't be included."""
        import json

        slo_name = slo.get('name', 'Unknown')
        self.logger.debug(f"🔍 SLO Debug - Cleaning SLO '{slo_name}' for creation")

        # Log original SLO structure
        self.logger.debug(f"🔍 SLO Debug - ORIGINAL SLO from Team A:")
        self.logger.debug(f"🔍 SLO Debug - {json.dumps(slo, indent=2, default=str)}")

        cleaned_slo = slo.copy()  # Start with full copy

        # Remove fields that shouldn't be included in create requests
        fields_to_remove = [
            'id',           # SLO ID is auto-generated
            'revision',     # Revision is managed by the API
            'groping',      # Typo field that sometimes appears
            'grouping',     # Grouping field causes validation errors
            'createTime',   # Creation time is auto-generated
            'updateTime',   # Update time is auto-generated
            'createdAt',    # Alternative creation time field
            'updatedAt',    # Alternative update time field
            'status',       # Status is managed by the API
            'errorBudget',  # Error budget is calculated by the API
            'burnRate',     # Burn rate is calculated by the API
            'sloStatus',    # SLO status is calculated by the API
            'currentHealth', # Current health is calculated by the API
        ]

        # Note: 'creator' is kept as it's allowed in the API (per your curl example)

        # Log which fields are present before removal
        present_fields = [field for field in fields_to_remove if field in cleaned_slo]
        if present_fields:
            self.logger.debug(f"🔍 SLO Debug - Fields to remove: {present_fields}")

        for field in fields_to_remove:
            if field in cleaned_slo:
                removed_value = cleaned_slo.pop(field)
                self.logger.debug(f"🔍 SLO Debug - Removed field '{field}': {removed_value}")

        # Also clean nested slo object if it exists
        if 'slo' in cleaned_slo and isinstance(cleaned_slo['slo'], dict):
            self.logger.debug(f"🔍 SLO Debug - Found nested 'slo' object, cleaning it too")
            for field in fields_to_remove:
                if field in cleaned_slo['slo']:
                    removed_value = cleaned_slo['slo'].pop(field)
                    self.logger.debug(f"🔍 SLO Debug - Removed nested field 'slo.{field}': {removed_value}")

        # Ensure required fields are present
        if 'name' not in cleaned_slo:
            raise ValueError("SLO name is required for creation")
        if 'targetThresholdPercentage' not in cleaned_slo:
            raise ValueError("SLO targetThresholdPercentage is required for creation")

        # Validate target threshold
        target = cleaned_slo.get('targetThresholdPercentage')
        if not isinstance(target, (int, float)) or target < 0 or target > 100:
            raise ValueError(f"Invalid targetThresholdPercentage: {target}. Must be between 0 and 100")

        # Set default values for optional fields if not present
        if 'sloTimeFrame' not in cleaned_slo:
            cleaned_slo['sloTimeFrame'] = 'SLO_TIME_FRAME_UNSPECIFIED'
            self.logger.debug(f"🔍 SLO Debug - Set default sloTimeFrame: SLO_TIME_FRAME_UNSPECIFIED")

        # Validate SLI configuration (but allow multiple SLI types as per API docs)
        self._validate_sli_configuration_flexible(cleaned_slo)

        # Log the final cleaned payload
        self.logger.debug(f"🔍 SLO Debug - CLEANED SLO payload for creation:")
        self.logger.debug(f"🔍 SLO Debug - {json.dumps(cleaned_slo, indent=2, default=str)}")

        # Log expected structure for comparison (based on user's working curl example)
        expected_structure = {
            "name": "API Availability SLO",
            "description": "Monitors the availability of our critical API endpoints",
            "creator": "sre-team@example.com",
            "targetThresholdPercentage": 99.95,
            "sloTimeFrame": "SLO_TIME_FRAME_28_DAYS",
            "windowBasedMetricSli": {
                "query": {
                    "query": "avg(product_latency_by_country) by (country) < 500"
                },
                "window": "WINDOW_SLO_WINDOW_1_MINUTE",
                "comparisonOperator": "COMPARISON_OPERATOR_GREATER_THAN",
                "threshold": 65
            }
        }
        self.logger.debug(f"🔍 SLO Debug - EXPECTED structure from your curl example:")
        self.logger.debug(f"🔍 SLO Debug - {json.dumps(expected_structure, indent=2)}")

        return cleaned_slo

    def _validate_sli_configuration_flexible(self, slo: Dict[str, Any]):
        """Validate SLI configuration - allows multiple SLI types as per API docs."""
        sli_types = ['windowBasedMetricSli', 'requestBasedMetricSli', 'requestBasedLogSli']
        found_sli_types = [sli_type for sli_type in sli_types if sli_type in slo]

        if len(found_sli_types) == 0:
            raise ValueError("SLO must have at least one SLI configuration")

        # API documentation shows multiple SLI types are allowed, so don't restrict this
        self.logger.debug(f"SLO has {len(found_sli_types)} SLI types: {found_sli_types}")

        # Validate each SLI type present
        for sli_type in found_sli_types:
            sli_config = slo[sli_type]

            if sli_type == 'windowBasedMetricSli':
                required_fields = ['query', 'window', 'comparisonOperator', 'threshold']
                for field in required_fields:
                    if field not in sli_config:
                        raise ValueError(f"windowBasedMetricSli missing required field: {field}")

            elif sli_type == 'requestBasedMetricSli':
                required_fields = ['goodEvents', 'totalEvents']
                for field in required_fields:
                    if field not in sli_config:
                        raise ValueError(f"requestBasedMetricSli missing required field: {field}")
                    if not isinstance(sli_config[field], dict) or 'query' not in sli_config[field]:
                        raise ValueError(f"requestBasedMetricSli {field} must have a query")

            elif sli_type == 'requestBasedLogSli':
                required_fields = ['goodEvents', 'totalEvents']
                for field in required_fields:
                    if field not in sli_config:
                        raise ValueError(f"requestBasedLogSli missing required field: {field}")

    def _log_failed_slo(self, slo: Dict[str, Any], operation: str, error: str):
        """Log failed SLO operation to a separate file."""
        try:
            # Create logs directory if it doesn't exist
            logs_dir = os.path.join("logs", "slo")
            os.makedirs(logs_dir, exist_ok=True)

            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"failed_slos_{timestamp}.json"
            filepath = os.path.join(logs_dir, filename)

            # Prepare log entry
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "operation": operation,
                "error": error,
                "slo_data": slo
            }

            # Write to file (append if exists)
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    existing_data = json.load(f)
                existing_data.append(log_entry)
            else:
                existing_data = [log_entry]

            with open(filepath, 'w') as f:
                json.dump(existing_data, f, indent=2)

            self.logger.info(f"Failed SLO logged to {filepath}")

        except Exception as e:
            self.logger.error(f"Failed to log failed SLO: {e}")

    def _add_creation_delay(self):
        """Add delay between SLO creations to avoid overwhelming the API."""
        delay = 0.5  # 500ms delay
        self.logger.debug(f"Adding {delay}s delay between SLO operations")
        time.sleep(delay)

    def _retry_with_exponential_backoff(self, operation_func, *args, **kwargs):
        """Retry operation with exponential backoff."""
        max_retries = 3
        base_delay = 1  # Start with 1 second

        for attempt in range(max_retries):
            try:
                return operation_func(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise e

                delay = base_delay * (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                self.logger.warning(f"Operation failed (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {e}")
                time.sleep(delay)

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create an SLO in Team B with retry logic."""
        def _create_slo():
            slo_name = resource.get('name', 'Unknown')
            self.logger.info(f"Creating SLO in Team B: {slo_name}")

            # Clean the SLO data for creation
            cleaned_slo = self._clean_slo_for_creation(resource)

            self.logger.debug(f"🔍 SLO Debug - Making POST request to: /v1/slo/slos")

            # Add silenceDataValidations parameter to bypass validation issues
            params = {
                'silenceDataValidations': 'true'
            }
            self.logger.debug(f"🔍 SLO Debug - Using query parameters: {params}")
            self.logger.debug(f"🔍 SLO Debug - Full URL: https://api.eu2.coralogix.com/mgmt/openapi/v1/slo/slos?silenceDataValidations=true")

            try:
                response = self.teamb_client.post("/v1/slo/slos", json_data=cleaned_slo, params=params)

                self.logger.debug(f"🔍 SLO Debug - Response received successfully")
                self.logger.debug(f"🔍 SLO Debug - Response keys: {list(response.keys()) if isinstance(response, dict) else 'Not a dict'}")

                if response and 'slo' in response:
                    created_slo = response['slo']
                    self.logger.info(f"✅ Successfully created SLO: {slo_name}")
                    self.log_resource_action("create", "slo", slo_name, True)
                    return created_slo
                else:
                    error_msg = f"Failed to create SLO {slo_name}: Invalid response format - {response}"
                    self.logger.error(error_msg)
                    self.log_resource_action("create", "slo", slo_name, False, error_msg)
                    raise Exception(error_msg)

            except Exception as e:
                self.logger.error(f"🔍 SLO Debug - Request failed with exception: {e}")
                self.logger.error(f"🔍 SLO Debug - Exception type: {type(e).__name__}")

                # Try to get more details from the HTTP error
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    self.logger.error(f"🔍 SLO Debug - HTTP status code: {e.response.status_code}")
                    self.logger.error(f"🔍 SLO Debug - HTTP response headers: {dict(e.response.headers)}")
                    self.logger.error(f"🔍 SLO Debug - HTTP response text: {e.response.text}")

                    # Try to parse JSON error response
                    try:
                        error_json = e.response.json()
                        self.logger.error(f"🔍 SLO Debug - JSON error response: {error_json}")
                    except:
                        self.logger.error(f"🔍 SLO Debug - Could not parse response as JSON")

                raise

        try:
            return self._retry_with_exponential_backoff(_create_slo)
        except Exception as e:
            slo_name = resource.get('name', 'Unknown')
            self.logger.error(f"❌ Failed to create SLO '{slo_name}': {e}")
            self._log_failed_slo(resource, 'create', str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete an SLO from Team B with retry logic."""
        def _delete_slo():
            self.logger.info(f"Deleting SLO from Team B: {resource_id}")

            # Add debug logging for the delete request
            delete_url = f"/v1/slo/slos/{resource_id}"
            self.logger.debug(f"🔍 SLO Debug - DELETE request URL: {delete_url}")
            self.logger.debug(f"🔍 SLO Debug - SLO ID to delete: {resource_id}")

            try:
                response = self.teamb_client.delete(delete_url)

                # Log the response for debugging
                self.logger.debug(f"🔍 SLO Debug - DELETE response type: {type(response)}")
                self.logger.debug(f"🔍 SLO Debug - DELETE response: {response}")

                # For DELETE operations, success can be indicated by:
                # 1. None response (204 No Content)
                # 2. Empty dict {}
                # 3. Dict with success message
                # 4. Dict with 'effectedSloAlertIds' (valid SLO deletion response)
                # 5. HTTP 200/204 status (handled by client)
                if response is None or response == {} or (isinstance(response, dict) and (
                    'message' in response or
                    response.get('success') == True or
                    'effectedSloAlertIds' in response or  # Valid SLO deletion response
                    len(response) == 0
                )):
                    self.logger.info(f"✅ Successfully deleted SLO: {resource_id}")
                    self.log_resource_action("delete", "slo", resource_id, True)
                    return True
                else:
                    error_msg = f"Failed to delete SLO {resource_id}: Unexpected response format - {response}"
                    self.logger.error(error_msg)
                    self.log_resource_action("delete", "slo", resource_id, False, error_msg)
                    raise Exception(error_msg)

            except Exception as e:
                # Enhanced error logging for delete operations
                self.logger.error(f"🔍 SLO Debug - DELETE request failed: {e}")
                self.logger.error(f"🔍 SLO Debug - Exception type: {type(e).__name__}")

                # Try to get more details from the HTTP error
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    self.logger.error(f"🔍 SLO Debug - DELETE HTTP status: {e.response.status_code}")
                    self.logger.error(f"🔍 SLO Debug - DELETE response headers: {dict(e.response.headers)}")
                    self.logger.error(f"🔍 SLO Debug - DELETE response text: {e.response.text}")

                    # Check if it's a 404 (SLO not found) - this might be acceptable
                    if e.response.status_code == 404:
                        self.logger.warning(f"⚠️ SLO {resource_id} not found (404) - may have been already deleted")
                        self.log_resource_action("delete", "slo", resource_id, True, "SLO not found (already deleted)")
                        return True

                raise

        try:
            return self._retry_with_exponential_backoff(_delete_slo)
        except Exception as e:
            self.logger.error(f"❌ Error deleting SLO {resource_id}: {e}")
            return False

    def _compare_slos(self, teama_slos: List[Dict[str, Any]], teamb_slos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare SLOs between teams to identify changes."""
        # Create lookup dictionaries by name
        teama_lookup = {slo.get('name', ''): slo for slo in teama_slos}
        teamb_lookup = {slo.get('name', ''): slo for slo in teamb_slos}

        # Find new SLOs (in Team A but not in Team B)
        new_in_teama = []
        for name, slo in teama_lookup.items():
            if name not in teamb_lookup:
                new_in_teama.append(slo)

        # Find deleted SLOs (in Team B but not in Team A)
        deleted_from_teama = []
        for name, slo in teamb_lookup.items():
            if name not in teama_lookup:
                deleted_from_teama.append(slo)

        # Find changed SLOs (exist in both but are different)
        changed_resources = []
        for name in teama_lookup:
            if name in teamb_lookup:
                teama_slo = teama_lookup[name]
                teamb_slo = teamb_lookup[name]

                # Compare SLOs (excluding metadata fields)
                teama_clean = self._clean_slo_for_creation(teama_slo)
                teamb_clean = self._clean_slo_for_creation(teamb_slo)

                if teama_clean != teamb_clean:
                    changed_resources.append((teama_slo, teamb_slo))

        return {
            'new_in_teama': new_in_teama,
            'deleted_from_teama': deleted_from_teama,
            'changed_resources': changed_resources
        }

    def dry_run(self) -> Dict[str, Any]:
        """
        Perform a dry run of the SLO migration.
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

            # Prepare results using delete-all-and-recreate-all strategy
            results = {
                'teama_count': len(teama_resources),
                'teamb_count': len(teamb_resources),
                'to_delete_all': teamb_resources,  # Delete ALL from Team B
                'to_create_all': teama_resources,  # Create ALL from Team A
                'total_operations': len(teamb_resources) + len(teama_resources)  # Delete all + Create all
            }

            # Log summary with new strategy
            self.logger.info("=" * 60)
            self.logger.info("SLO DRY RUN RESULTS - Delete All + Recreate All Strategy")
            self.logger.info("=" * 60)
            self.logger.info(f"Team A SLOs: {len(teama_resources)}")
            self.logger.info(f"Team B SLOs (current): {len(teamb_resources)}")
            self.logger.info("")
            self.logger.info("PLANNED OPERATIONS:")
            self.logger.info(f"  Step 1: Delete ALL {len(teamb_resources)} SLOs from Team B")
            self.logger.info(f"  Step 2: Create ALL {len(teama_resources)} SLOs from Team A")
            self.logger.info(f"  Total operations: {results['total_operations']}")
            self.logger.info("")
            self.logger.info(f"EXPECTED RESULT: Team B will have {len(teama_resources)} SLOs (same as Team A)")

            # Show some sample SLOs that will be affected
            if teamb_resources:
                self.logger.info(f"\nSample SLOs to be DELETED from Team B:")
                for i, slo in enumerate(teamb_resources[:3]):  # Show first 3
                    slo_id = self.get_slo_id(slo) or 'N/A'
                    self.logger.info(f"  - {slo.get('name', 'Unknown')} (ID: {slo_id})")
                if len(teamb_resources) > 3:
                    self.logger.info(f"  ... and {len(teamb_resources) - 3} more")

            if teama_resources:
                self.logger.info(f"\nSample SLOs to be CREATED in Team B:")
                for i, slo in enumerate(teama_resources[:3]):  # Show first 3
                    self.logger.info(f"  + {slo.get('name', 'Unknown')}")
                if len(teama_resources) > 3:
                    self.logger.info(f"  ... and {len(teama_resources) - 3} more")

            self.log_migration_complete(self.service_name, True, len(teama_resources), 0)
            return results

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return {
                'teama_count': 0,
                'teamb_count': 0,
                'to_delete_all': [],
                'to_create_all': [],
                'total_operations': 0,
                'error': str(e)
            }

    def display_dry_run_results(self, results: Dict[str, Any]):
        """
        Display formatted dry run results using delete-all-and-recreate-all strategy.

        Args:
            results: Dry run results dictionary
        """
        print("\n" + "=" * 60)
        print("DRY RUN RESULTS - SLOS (Delete All + Recreate All Strategy)")
        print("=" * 60)

        print(f"📊 Team A SLOs: {results['teama_count']}")
        print(f"📊 Team B SLOs: {results['teamb_count']}")
        print("")

        # Show planned operations
        to_delete_all = results.get('to_delete_all', [])
        to_create_all = results.get('to_create_all', [])

        print("🎯 PLANNED OPERATIONS:")
        print(f"  Step 1: Delete ALL {len(to_delete_all)} SLOs from Team B")
        print(f"  Step 2: Create ALL {len(to_create_all)} SLOs from Team A")
        print(f"  Total operations: {results['total_operations']}")
        print("")

        # Show sample SLOs to be deleted
        if to_delete_all:
            print(f"🗑️ Sample SLOs to be DELETED from Team B (showing first 5):")
            for i, resource in enumerate(to_delete_all[:5]):
                slo_id = self.get_slo_id(resource) or 'N/A'
                print(f"  - {resource.get('name', 'Unknown')} (ID: {slo_id})")
            if len(to_delete_all) > 5:
                print(f"  ... and {len(to_delete_all) - 5} more SLOs")
            print("")

        # Show sample SLOs to be created
        if to_create_all:
            print(f"✅ Sample SLOs to be CREATED in Team B (showing first 5):")
            for i, resource in enumerate(to_create_all[:5]):
                print(f"  + {resource.get('name', 'Unknown')}")
            if len(to_create_all) > 5:
                print(f"  ... and {len(to_create_all) - 5} more SLOs")
            print("")

        # Show expected result
        expected_final_count = len(to_create_all)
        print(f"🎯 EXPECTED RESULT:")
        print(f"  Team B will have {expected_final_count} SLOs (same as Team A)")

        if results['teama_count'] == results['teamb_count']:
            print("  ✨ Teams are already in sync, but migration will ensure consistency")
        elif results['teama_count'] > results['teamb_count']:
            print(f"  📈 Team B will gain {results['teama_count'] - results['teamb_count']} SLOs")
        else:
            print(f"  📉 Team B will lose {results['teamb_count'] - results['teama_count']} SLOs")

        print("=" * 60)

    def migrate(self) -> bool:
        """
        Perform the actual SLO migration with enhanced safety checks.

        Returns:
            True if migration completed successfully, False otherwise
        """
        try:
            self.log_migration_start(self.service_name)

            # Step 1: Fetch resources from both teams (with safety checks for TeamA)
            self.logger.info("📥 Fetching SLOs from both teams...")
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

            # Save artifacts for comparison
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # Check if any operations are needed
            total_operations = len(teama_resources)

            if total_operations == 0:
                self.logger.info("No SLO migration needed - Team A has no SLOs")

                # Display migration results even when no operations are needed
                print("\n" + "=" * 60)
                print("🎉 SLO MIGRATION RESULTS")
                print("=" * 60)
                print(f"Team A SLOs: {len(teama_resources)}")
                print(f"Team B SLOs (before): {len(teamb_resources)}")
                print(f"Deleted from Team B: 0")
                print(f"Created in Team B: 0")
                print(f"Failed operations: 0")
                print(f"Success rate: 100.0%")
                print(f"✅ SUCCESS: Team B should now have 0 SLOs (same as Team A)")
                print("=" * 60)

                # Still create post-migration snapshot for consistency
                self.version_manager.create_version_snapshot(
                    teama_resources, teamb_resources, 'post_migration'
                )
                self.log_migration_complete(self.service_name, True, 0, 0)
                return True

            # Step 3: Perform mass deletion safety check
            # SLO uses delete-all + recreate-all strategy, so all TeamB SLOs would be deleted
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_resources, len(teamb_resources), len(teama_resources), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            # Track migration statistics
            deleted_count = 0
            created_count = 0
            failed_count = 0

            self.logger.info("=" * 60)
            self.logger.info("SLO MIGRATION STRATEGY: Delete All + Recreate All")
            self.logger.info("=" * 60)

            # Step 1: Delete ALL existing SLOs from Team B
            self.logger.info(f"Step 1: Deleting ALL existing SLOs from Team B ({len(teamb_resources)} SLOs)")

            deletion_stats = self.delete_all_slos_from_teamb(teamb_resources)
            deleted_count = deletion_stats['deleted']
            failed_count += deletion_stats['failed']

            self.logger.info(f"Step 1 Complete: Deleted {deleted_count}/{len(teamb_resources)} SLOs (Failed: {deletion_stats['failed']})")

            # Step 2: Create ALL SLOs from Team A
            self.logger.info(f"Step 2: Creating ALL SLOs from Team A ({len(teama_resources)} SLOs)")

            for slo in teama_resources:
                try:
                    slo_name = slo.get('name', 'Unknown')
                    self.create_resource_in_teamb(slo)
                    created_count += 1
                    self.logger.debug(f"✅ Created SLO: {slo_name}")
                    self._add_creation_delay()
                except Exception as e:
                    self.logger.error(f"❌ Failed to create SLO {slo.get('name', 'Unknown')}: {e}")
                    failed_count += 1

            self.logger.info(f"Step 2 Complete: Created {created_count}/{len(teama_resources)} SLOs")

            # Log final results
            total_operations = created_count + deleted_count
            success_rate = (total_operations / (total_operations + failed_count) * 100) if (total_operations + failed_count) > 0 else 100

            print("\n" + "=" * 60)
            print("🎉 SLO MIGRATION RESULTS")
            print("=" * 60)
            print(f"Team A SLOs: {len(teama_resources)}")
            print(f"Team B SLOs (before): {len(teamb_resources)}")
            print(f"Deleted from Team B: {deleted_count}")
            print(f"Created in Team B: {created_count}")
            print(f"Failed operations: {failed_count}")
            print(f"Success rate: {success_rate:.1f}%")

            # Expected final count should equal Team A count
            expected_final_count = len(teama_resources)
            actual_successful_creates = created_count

            if actual_successful_creates == expected_final_count:
                print(f"✅ SUCCESS: Team B should now have {expected_final_count} SLOs (same as Team A)")
            else:
                print(f"❌ MISMATCH: Team B should have {expected_final_count} SLOs, but only {actual_successful_creates} were created successfully")

            print("=" * 60)

            # Step 4: Create post-migration version snapshot
            self.logger.info("📸 Creating post-migration version snapshot...")
            try:
                # Fetch updated resources from both teams for post-migration snapshot
                updated_teama_resources = self.fetch_resources_from_teama()
                updated_teamb_resources = self.fetch_resources_from_teamb()

                post_migration_version = self.version_manager.create_version_snapshot(
                    updated_teama_resources, updated_teamb_resources, 'post_migration'
                )
                self.logger.info(f"Post-migration snapshot created: {post_migration_version}")
            except Exception as e:
                self.logger.warning(f"Failed to create post-migration snapshot: {e}")

            # Log migration completion
            success = failed_count == 0 and created_count == len(teama_resources)
            self.log_migration_complete(self.service_name, success, len(teama_resources), failed_count)

            if success:
                self.logger.info("🎉 SLO migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ SLO migration completed with {failed_count} failures")

            return success

        except Exception as e:
            self.logger.error(f"SLO migration failed: {e}")

            # Display migration results even when migration fails
            if 'teama_resources' in locals() and 'teamb_resources' in locals():
                print("\n" + "=" * 60)
                print("❌ SLO MIGRATION RESULTS (FAILED)")
                print("=" * 60)
                print(f"Team A SLOs: {len(teama_resources)}")
                print(f"Team B SLOs (before): {len(teamb_resources)}")
                print(f"Deleted from Team B: {locals().get('deleted_count', 0)}")
                print(f"Created in Team B: {locals().get('created_count', 0)}")
                print(f"Failed operations: {locals().get('failed_count', 0)}")
                print(f"❌ MIGRATION FAILED: {e}")
                print("=" * 60)

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False
