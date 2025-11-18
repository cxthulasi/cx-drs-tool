"""
TCO (Total Cost of Ownership) migration service for Coralogix DR Tool.
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum

from core.base_service import BaseService
from core.api_client import CoralogixAPIError
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager


class SourceType(Enum):
    """Source types for TCO policies."""
    UNSPECIFIED = "SOURCE_TYPE_UNSPECIFIED"
    LOGS = "SOURCE_TYPE_LOGS"
    SPANS = "SOURCE_TYPE_SPANS"


class TCOService(BaseService):
    """Service for migrating TCO policies between teams."""

    def __init__(self, config, logger=None):
        super().__init__(config, logger)
        self.failed_policies = []  # Track failed policies for logging
        self.creation_delay = 1.0  # Default delay between policy operations (seconds)
        self.max_retries = 3  # Maximum number of retries for failed operations
        self.base_backoff = 2.0  # Base backoff time in seconds

        # Archive retention mappings (Team A name/id -> Team B id)
        self.retention_name_to_id_teama = {}  # Team A retention name -> Team A retention id
        self.retention_name_to_id_teamb = {}  # Team A retention name -> Team B retention id
        self.retention_id_mapping = {}  # Team A retention id -> Team B retention id

        # Initialize safety manager and version manager
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "tco"

    @property
    def api_endpoint(self) -> str:
        return "/latest/v1/policies"

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get unique identifier for a policy."""
        return str(resource.get('id', 'unknown'))

    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get display name for a policy."""
        return resource.get('name', 'Unknown Policy')

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

    def _log_failed_policy(self, policy: Dict[str, Any], operation: str, error: str, source_type: str = ""):
        """
        Log a failed policy operation for later review.

        Args:
            policy: The policy that failed
            operation: The operation that failed (create, delete, batch_create)
            error: The error message
            source_type: The source type of the policy
        """
        failed_policy = {
            'policy_id': self.get_resource_identifier(policy),
            'policy_name': self.get_resource_name(policy),
            'source_type': source_type,
            'operation': operation,
            'error': str(error),
            'timestamp': datetime.now().isoformat(),
            'policy_data': policy
        }

        self.failed_policies.append(failed_policy)
        self.logger.error(
            f"Failed {operation} operation for {source_type} policy '{failed_policy['policy_name']}' "
            f"(ID: {failed_policy['policy_id']}): {error}"
        )

    def _save_failed_policies_log(self):
        """Save failed policies to a log file for review."""
        if not self.failed_policies:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_policies_file = f"logs/tco/failed_policies_{timestamp}.json"

        # Ensure the logs directory exists
        import os
        os.makedirs(os.path.dirname(failed_policies_file), exist_ok=True)

        try:
            with open(failed_policies_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'total_failed': len(self.failed_policies),
                    'failed_policies': self.failed_policies
                }, f, indent=2)

            self.logger.info(f"Failed policies log saved to: {failed_policies_file}")

        except Exception as e:
            self.logger.error(f"Failed to save failed policies log: {e}")

    def _add_operation_delay(self):
        """Add a delay between policy operations to avoid overwhelming the API."""
        if self.creation_delay > 0:
            time.sleep(self.creation_delay)

    def fetch_policies_by_source_type(self, team_client, source_type: SourceType) -> List[Dict[str, Any]]:
        """
        Fetch policies from a team for a specific source type.
        
        Args:
            team_client: API client for the team
            source_type: The source type to fetch policies for
            
        Returns:
            List of policies for the specified source type
        """
        try:
            self.logger.info(f"Fetching {source_type.value} policies")
            
            params = {
                'enabledOnly': False,  # Get all policies, not just enabled ones
                'sourceType': source_type.value
            }
            
            response = team_client.get(self.api_endpoint, params=params)
            policies = response.get('policies', [])

            self.logger.info(f"Fetched {len(policies)} {source_type.value} policies")

            # Debug: Log sample policy structure from Team A
            if policies:
                sample_policy = policies[0]
                policy_name = sample_policy.get('name', 'Unknown')
                self.logger.debug(f"🔍 TCO Debug - Sample {source_type.value} policy from Team A: '{policy_name}'")
                self.logger.debug(f"🔍 TCO Debug - Team A policy keys: {list(sample_policy.keys())}")

                # Log the complete structure of the first policy for debugging
                import json
                self.logger.debug(f"🔍 TCO Debug - COMPLETE Team A policy structure:")
                self.logger.debug(f"🔍 TCO Debug - {json.dumps(sample_policy, indent=2, default=str)}")

            return policies

        except Exception as e:
            self.logger.error(f"Failed to fetch {source_type.value} policies: {e}")
            raise

    def fetch_all_policies_from_team(self, team_client) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch all policies from a team, organized by source type.
        
        Args:
            team_client: API client for the team
            
        Returns:
            Dictionary with source types as keys and policy lists as values
        """
        all_policies = {}
        
        for source_type in SourceType:
            try:
                policies = self.fetch_policies_by_source_type(team_client, source_type)
                all_policies[source_type.value] = policies
            except Exception as e:
                self.logger.error(f"Failed to fetch {source_type.value} policies: {e}")
                all_policies[source_type.value] = []
        
        return all_policies

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all policies from Team A with safety checks."""
        api_error = None
        flattened_policies = []

        try:
            self.logger.info("Fetching policies from Team A")
            all_policies = self.fetch_all_policies_from_team(self.teama_client)

            # Flatten the policies for compatibility with base service
            for source_type, policies in all_policies.items():
                for policy in policies:
                    # Add source type to policy for tracking
                    policy['_source_type'] = source_type
                    flattened_policies.append(policy)

            total_count = len(flattened_policies)
            self.logger.info(f"Fetched {total_count} total policies from Team A")

            # Log breakdown by source type
            for source_type, policies in all_policies.items():
                self.logger.info(f"  {source_type}: {len(policies)} policies")

        except Exception as e:
            self.logger.error(f"Failed to fetch policies from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            flattened_policies, api_error, previous_count
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

        return flattened_policies

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all policies from Team B, organized by source type."""
        try:
            self.logger.info("Fetching policies from Team B")
            all_policies = self.fetch_all_policies_from_team(self.teamb_client)
            
            # Flatten the policies for compatibility with base service
            flattened_policies = []
            for source_type, policies in all_policies.items():
                for policy in policies:
                    # Add source type to policy for tracking
                    policy['_source_type'] = source_type
                    flattened_policies.append(policy)
            
            total_count = len(flattened_policies)
            self.logger.info(f"Fetched {total_count} total policies from Team B")
            
            # Log breakdown by source type
            for source_type, policies in all_policies.items():
                self.logger.info(f"  {source_type}: {len(policies)} policies")
            
            return flattened_policies

        except Exception as e:
            self.logger.error(f"Failed to fetch policies from Team B: {e}")
            raise

    def fetch_archive_retentions_from_team(self, team_client) -> List[Dict[str, Any]]:
        """
        Fetch archive retentions from a team.

        Args:
            team_client: API client for the team

        Returns:
            List of archive retention configurations
        """
        try:
            self.logger.info("Fetching archive retentions...")
            response = team_client.get("/v1/retentions")

            retentions = response.get('retentions', [])
            self.logger.info(f"Found {len(retentions)} archive retentions")

            # Log retention details for debugging
            for retention in retentions:
                retention_name = retention.get('name', 'Unknown')
                retention_id = retention.get('id', 'Unknown')
                self.logger.debug(f"  - {retention_name} (ID: {retention_id})")

            return retentions

        except Exception as e:
            self.logger.error(f"Failed to fetch archive retentions: {e}")
            return []

    def create_archive_retention_in_teamb(self, retention: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create an archive retention in Team B.

        Args:
            retention: Archive retention configuration from Team A

        Returns:
            Created retention configuration or None if failed
        """
        try:
            # Prepare retention data for creation
            retention_data = self._prepare_retention_for_creation(retention)

            self.logger.info(f"Creating archive retention: {retention_data.get('name', 'Unknown')}")

            # Add delay before creation
            self._add_operation_delay()

            # Create retention with exponential backoff
            def _create_operation():
                return self.teamb_client.put("/v1/retentions", json_data=retention_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            if response:
                self.logger.info(f"✅ Created archive retention: {retention_data.get('name', 'Unknown')}")
                return response
            else:
                self.logger.error(f"❌ Failed to create archive retention: {retention_data.get('name', 'Unknown')}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to create archive retention '{retention.get('name', 'Unknown')}': {e}")
            return None

    def _prepare_retention_for_creation(self, retention: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare archive retention data for creation by removing read-only fields.

        Args:
            retention: Original retention configuration

        Returns:
            Cleaned retention data for creation
        """
        # Fields to exclude from creation (read-only or system-generated)
        exclude_fields = {
            'id',  # System-generated field
            'createdAt',  # System-generated timestamp
            'updatedAt',  # System-generated timestamp
            'createdBy',  # System-generated field
            'updatedBy'   # System-generated field
        }

        # Create cleaned retention data
        cleaned_retention = {
            k: v for k, v in retention.items()
            if k not in exclude_fields and v is not None
        }

        return cleaned_retention

    def build_retention_mappings(self, teama_retentions: List[Dict[str, Any]], teamb_retentions: List[Dict[str, Any]]):
        """
        Build mappings between Team A and Team B archive retentions.

        Args:
            teama_retentions: Archive retentions from Team A
            teamb_retentions: Archive retentions from Team B
        """
        # Build Team A retention name -> id mapping
        self.retention_name_to_id_teama = {
            retention.get('name'): retention.get('id')
            for retention in teama_retentions
            if retention.get('name') and retention.get('id')
        }

        # Build Team B retention name -> id mapping
        self.retention_name_to_id_teamb = {
            retention.get('name'): retention.get('id')
            for retention in teamb_retentions
            if retention.get('name') and retention.get('id')
        }

        # Build Team A id -> Team B id mapping based on matching names
        self.retention_id_mapping = {}
        for retention_name, teama_id in self.retention_name_to_id_teama.items():
            teamb_id = self.retention_name_to_id_teamb.get(retention_name)
            if teamb_id:
                self.retention_id_mapping[teama_id] = teamb_id
                self.logger.debug(f"Retention mapping: '{retention_name}' {teama_id} -> {teamb_id}")
            else:
                self.logger.warning(f"No matching retention found in Team B for '{retention_name}' (Team A ID: {teama_id})")

        self.logger.info(f"Built {len(self.retention_id_mapping)} retention ID mappings")

    def map_archive_retention_id(self, teama_retention_id: str) -> Optional[str]:
        """
        Map a Team A archive retention ID to the corresponding Team B retention ID.

        Args:
            teama_retention_id: Archive retention ID from Team A

        Returns:
            Corresponding Team B retention ID or None if not found
        """
        teamb_retention_id = self.retention_id_mapping.get(teama_retention_id)
        if not teamb_retention_id:
            self.logger.warning(f"No retention mapping found for Team A retention ID: {teama_retention_id}")
        return teamb_retention_id

    def _prepare_policy_for_creation(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare policy data for creation by creating a source-type specific payload.
        The API uses "oneof" fields, so only logRules OR spanRules can be present, not both.

        Args:
            policy: The original policy data

        Returns:
            Cleaned policy data ready for creation
        """
        policy_name = policy.get('name', 'Unknown')
        source_type = policy.get('_source_type', 'SOURCE_TYPE_UNSPECIFIED')

        self.logger.debug(f"Preparing policy '{policy_name}' for creation (source: {source_type})")

        # Create base payload structure
        cleaned_policy = {}

        # Required fields - preserve original values
        cleaned_policy['name'] = policy.get('name', 'Migrated Policy')
        cleaned_policy['description'] = policy.get('description', 'Migrated from Team A')

        # Priority - preserve original value, use valid default if missing
        priority = policy.get('priority', 'PRIORITY_TYPE_MEDIUM')
        # Ensure priority is valid
        valid_priorities = [
            'PRIORITY_TYPE_UNSPECIFIED', 'PRIORITY_TYPE_LOW',
            'PRIORITY_TYPE_MEDIUM', 'PRIORITY_TYPE_HIGH'
        ]
        if priority not in valid_priorities:
            priority = 'PRIORITY_TYPE_MEDIUM'
        cleaned_policy['priority'] = priority

        # Transform enabled field to disabled field with opposite value
        # If enabled: true in Team A → disabled: false in Team B
        # If enabled: false in Team A → disabled: true in Team B
        if 'enabled' in policy:
            enabled_value = policy['enabled']
            cleaned_policy['disabled'] = not enabled_value
            self.logger.debug(f"Transformed enabled={enabled_value} to disabled={not enabled_value} for policy '{policy_name}'")

        # Application Rule - ONLY include if present in original policy
        if 'applicationRule' in policy and isinstance(policy['applicationRule'], dict):
            app_rule = policy['applicationRule']
            cleaned_policy['applicationRule'] = {
                'ruleTypeId': app_rule.get('ruleTypeId'),  # Preserve original ruleTypeId exactly
                'name': app_rule.get('name')  # Preserve original name exactly
            }

        # Subsystem Rule - ONLY include if present in original policy
        if 'subsystemRule' in policy and isinstance(policy['subsystemRule'], dict):
            sub_rule = policy['subsystemRule']
            cleaned_policy['subsystemRule'] = {
                'ruleTypeId': sub_rule.get('ruleTypeId'),  # Preserve original ruleTypeId exactly
                'name': sub_rule.get('name')  # Preserve original name exactly
            }

        # Archive Retention - Map Team A retention ID to Team B retention ID
        if 'archiveRetention' in policy and isinstance(policy['archiveRetention'], dict):
            teama_retention_id = policy['archiveRetention'].get('id')
            if teama_retention_id:
                teamb_retention_id = self.map_archive_retention_id(teama_retention_id)
                if teamb_retention_id:
                    cleaned_policy['archiveRetention'] = {
                        'id': teamb_retention_id
                    }
                    self.logger.debug(f"Mapped archive retention: {teama_retention_id} -> {teamb_retention_id}")
                else:
                    self.logger.warning(f"Could not map archive retention ID {teama_retention_id}, excluding from policy")
            else:
                self.logger.debug("Archive retention found but no ID, excluding from policy")

        # CRITICAL: Only include logRules OR spanRules based on source type
        # The API uses "oneof" field, so both cannot be present

        if source_type == 'SOURCE_TYPE_SPANS':
            # For SPANS source type, only include spanRules
            self.logger.debug(f"Creating SPANS policy with spanRules only")

            if 'spanRules' in policy and isinstance(policy['spanRules'], dict):
                span_rules = policy['spanRules']
                cleaned_span_rules = {}

                # Service Rule - ONLY include if present in original policy
                if 'serviceRule' in span_rules and isinstance(span_rules['serviceRule'], dict):
                    service_rule = span_rules['serviceRule']
                    cleaned_span_rules['serviceRule'] = {
                        'ruleTypeId': service_rule.get('ruleTypeId'),  # Preserve original ruleTypeId exactly
                        'name': service_rule.get('name')  # Preserve original name exactly
                    }

                # Action Rule - ONLY include if present in original policy
                if 'actionRule' in span_rules and isinstance(span_rules['actionRule'], dict):
                    action_rule = span_rules['actionRule']
                    cleaned_span_rules['actionRule'] = {
                        'ruleTypeId': action_rule.get('ruleTypeId'),  # Preserve original ruleTypeId exactly
                        'name': action_rule.get('name')  # Preserve original name exactly
                    }

                # Tag Rules - ONLY include if present in original policy
                if 'tagRules' in span_rules and isinstance(span_rules['tagRules'], list):
                    cleaned_tag_rules = []
                    for tag_rule in span_rules['tagRules']:
                        if isinstance(tag_rule, dict):
                            cleaned_tag_rules.append({
                                'ruleTypeId': tag_rule.get('ruleTypeId'),  # Preserve original ruleTypeId exactly
                                'tagName': tag_rule.get('tagName'),  # Preserve original tagName
                                'tagValue': tag_rule.get('tagValue')  # Preserve original tagValue
                            })
                    if cleaned_tag_rules:  # Only add if we have actual tag rules
                        cleaned_span_rules['tagRules'] = cleaned_tag_rules

                # Only add spanRules if we have actual span rule content
                if cleaned_span_rules:
                    cleaned_policy['spanRules'] = cleaned_span_rules

            # DO NOT include logRules for SPANS policies

        else:
            # For LOGS source type (or UNSPECIFIED), only include logRules
            self.logger.debug(f"Creating LOGS policy with logRules only")

            if 'logRules' in policy and isinstance(policy['logRules'], dict):
                log_rules = policy['logRules']
                if 'severities' in log_rules and isinstance(log_rules['severities'], list):
                    cleaned_policy['logRules'] = {
                        'severities': log_rules['severities']
                    }
                else:
                    cleaned_policy['logRules'] = {
                        'severities': ['SEVERITY_UNSPECIFIED']
                    }
            else:
                cleaned_policy['logRules'] = {
                    'severities': ['SEVERITY_UNSPECIFIED']
                }

            # DO NOT include spanRules for LOGS policies

        self.logger.debug(f"Created sanitized payload for '{policy_name}' ({source_type})")
        return cleaned_policy

    # Removed _convert_rule_type_id method - we now preserve original ruleTypeId values exactly



    def delete_all_policies_by_source_type(self, source_type: SourceType) -> bool:
        """
        Delete all policies of a specific source type from Team B.

        Args:
            source_type: The source type to delete policies for

        Returns:
            True if all deletions were successful, False otherwise
        """
        try:
            self.logger.info(f"Deleting all {source_type.value} policies from Team B")

            # Fetch current policies of this source type from Team B
            current_policies = self.fetch_policies_by_source_type(self.teamb_client, source_type)

            if not current_policies:
                self.logger.info(f"No {source_type.value} policies found in Team B to delete")
                return True

            deletion_count = 0
            failed_deletions = 0

            for policy in current_policies:
                policy_id = policy.get('id')
                policy_name = self.get_resource_name(policy)

                if not policy_id:
                    self.logger.warning(f"Policy '{policy_name}' has no ID, skipping deletion")
                    continue

                try:
                    self.logger.info(f"Deleting {source_type.value} policy: {policy_name} (ID: {policy_id})")

                    # Add delay before deletion
                    self._add_operation_delay()

                    # Delete with exponential backoff using correct delete endpoint format
                    def _delete_operation():
                        return self.teamb_client.delete(f"{self.api_endpoint}/{policy_id}")

                    self._retry_with_exponential_backoff(_delete_operation)

                    deletion_count += 1
                    self.logger.info(f"✅ Successfully deleted {source_type.value} policy: {policy_name}")

                except Exception as e:
                    failed_deletions += 1
                    self._log_failed_policy(policy, 'delete', str(e), source_type.value)
                    self.logger.error(f"❌ Failed to delete {source_type.value} policy {policy_name}: {e}")

            self.logger.info(f"Deletion summary for {source_type.value}: {deletion_count} successful, {failed_deletions} failed")
            return failed_deletions == 0

        except Exception as e:
            self.logger.error(f"Failed to delete {source_type.value} policies: {e}")
            return False

    def batch_create_policies(self, policies: List[Dict[str, Any]], source_type: SourceType) -> bool:
        """
        Create multiple policies using individual API calls (bulk create is not working).

        Args:
            policies: List of policies to create
            source_type: The source type of the policies

        Returns:
            True if all policy creations were successful, False otherwise
        """
        if not policies:
            self.logger.info(f"No {source_type.value} policies to create")
            return True

        self.logger.info(f"🔄 Creating {len(policies)} {source_type.value} policies individually in Team B")

        success_count = 0
        failed_count = 0

        for i, policy in enumerate(policies, 1):
            policy_name = self.get_resource_name(policy)

            try:
                self.logger.info(f"Creating policy {i}/{len(policies)}: {policy_name}")

                # Prepare policy for creation with comprehensive sanitization
                cleaned_policy = self._prepare_policy_for_creation(policy)

                # Log payload details at debug level (only for first policy to avoid spam)
                if i == 1:
                    import json
                    self.logger.debug(f"🔍 Sample payload structure for first policy:")
                    self.logger.debug(f"🔍 {json.dumps(cleaned_policy, indent=2, default=str)[:500]}...")
                    self.logger.debug(f"🔍 Full URL: https://api.eu2.coralogix.com/mgmt/openapi{self.api_endpoint}")

                # Add delay between policy creations to avoid rate limiting
                if i > 1:  # No delay for first policy
                    self._add_operation_delay()

                # Create individual policy with retry logic
                def _individual_create_operation():
                    return self.teamb_client.post(self.api_endpoint, json_data=cleaned_policy)

                response = self._retry_with_exponential_backoff(_individual_create_operation)

                success_count += 1
                self.logger.info(f"✅ Successfully created policy: {policy_name}")

                # Log response details for first successful policy (debugging)
                if success_count == 1:
                    self.logger.debug(f"🔍 TCO Debug - Sample creation response keys: {list(response.keys()) if isinstance(response, dict) else 'Not a dict'}")

            except Exception as e:
                failed_count += 1
                self.logger.error(f"❌ Failed to create policy '{policy_name}': {e}")
                self._log_failed_policy(policy, 'individual_create', str(e), source_type.value)

                # Log error details at appropriate level
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    status_code = e.response.status_code
                    if status_code >= 500:
                        # Server errors - log as error
                        self.logger.error(f"Server error ({status_code}) creating policy '{policy_name}': {e.response.text}")
                    elif status_code >= 400:
                        # Client errors - log as warning with details
                        self.logger.warning(f"Client error ({status_code}) creating policy '{policy_name}': {e.response.text}")
                    else:
                        # Other HTTP errors
                        self.logger.error(f"HTTP error ({status_code}) creating policy '{policy_name}': {e.response.text}")
                else:
                    # Non-HTTP errors
                    self.logger.error(f"Error creating policy '{policy_name}': {str(e)}")

        # Log final results
        total_policies = len(policies)
        success_rate = (success_count / total_policies * 100) if total_policies > 0 else 0

        self.logger.info(f"📊 Policy creation results for {source_type.value}:")
        self.logger.info(f"  ✅ Successful: {success_count}/{total_policies} ({success_rate:.1f}%)")
        self.logger.info(f"  ❌ Failed: {failed_count}/{total_policies}")

        return failed_count == 0

    def migrate_policies_by_source_type(self, teama_policies: Dict[str, List[Dict[str, Any]]],
                                      source_type: SourceType) -> Dict[str, int]:
        """
        Migrate policies for a specific source type.

        Args:
            teama_policies: All policies from Team A organized by source type
            source_type: The source type to migrate

        Returns:
            Dictionary with migration statistics
        """
        stats = {
            'total': 0,
            'deleted': 0,
            'created': 0,
            'failed': 0
        }

        source_type_key = source_type.value
        policies_to_migrate = teama_policies.get(source_type_key, [])
        stats['total'] = len(policies_to_migrate)

        if not policies_to_migrate:
            self.logger.info(f"No {source_type.value} policies to migrate from Team A")
            return stats

        self.logger.info(f"Starting migration of {stats['total']} {source_type.value} policies")

        # Step 1: Delete all existing policies of this source type from Team B
        self.logger.info(f"Step 1: Deleting existing {source_type.value} policies from Team B")
        deletion_success = self.delete_all_policies_by_source_type(source_type)

        if deletion_success:
            self.logger.info(f"✅ Successfully deleted all existing {source_type.value} policies from Team B")
        else:
            self.logger.warning(f"⚠️ Some {source_type.value} policy deletions failed, but continuing with creation")

        # Step 2: Batch create all policies from Team A
        self.logger.info(f"Step 2: Batch creating {source_type.value} policies in Team B")
        creation_success = self.batch_create_policies(policies_to_migrate, source_type)

        if creation_success:
            stats['created'] = stats['total']
            self.logger.info(f"✅ Successfully created all {stats['total']} {source_type.value} policies")
        else:
            stats['failed'] = stats['total']
            self.logger.error(f"❌ Failed to create {source_type.value} policies")

        return stats

    def migrate(self) -> bool:
        """Perform the actual TCO policies migration with enhanced safety checks."""
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Fetch resources from both teams (with safety checks for TeamA)
            self.logger.info("📥 Fetching policies from both teams...")
            teama_policies_flat = self.fetch_resources_from_teama()  # This includes safety checks
            teamb_policies_flat = self.fetch_resources_from_teamb()

            # Step 2: Create pre-migration version snapshot
            self.logger.info("📸 Creating pre-migration version snapshot...")
            pre_migration_version = self.version_manager.create_version_snapshot(
                teama_policies_flat, teamb_policies_flat, 'pre_migration'
            )
            self.logger.info(f"Pre-migration snapshot created: {pre_migration_version}")

            # Get previous TeamA count for safety checks
            previous_version = self.version_manager.get_previous_version()
            previous_teama_count = previous_version.get('teama', {}).get('count') if previous_version else None

            # Organize Team A policies by source type
            teama_policies = {}
            for source_type in SourceType:
                teama_policies[source_type.value] = [
                    policy for policy in teama_policies_flat
                    if policy.get('_source_type') == source_type.value
                ]

            # Check if any operations are needed
            total_operations = len(teama_policies_flat)

            if total_operations == 0:
                self.logger.info("No TCO policies migration needed - Team A has no policies")
                # Still create post-migration snapshot for consistency
                self.version_manager.create_version_snapshot(
                    teama_policies_flat, teamb_policies_flat, 'post_migration'
                )
                self.log_migration_complete(self.service_name, True, 0, 0)
                return True

            # Step 3: Perform mass deletion safety check
            # TCO uses delete-all + recreate-all strategy, so all TeamB policies would be deleted
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_policies_flat, len(teamb_policies_flat), len(teama_policies_flat), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            # Export Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_policies_flat, "teama")

            # Export Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_policies_flat, "teamb")

            # Handle archive retentions first (required for policy creation)
            self.logger.info("=" * 60)
            self.logger.info("Handling Archive Retentions")
            self.logger.info("=" * 60)

            # Fetch archive retentions from both teams
            self.logger.info("Fetching archive retentions from Team A...")
            teama_retentions = self.fetch_archive_retentions_from_team(self.teama_client)

            self.logger.info("Fetching archive retentions from Team B...")
            teamb_retentions = self.fetch_archive_retentions_from_team(self.teamb_client)

            # Create missing retentions in Team B
            created_retentions = 0
            failed_retentions = 0

            for teama_retention in teama_retentions:
                retention_name = teama_retention.get('name', 'Unknown')

                # Check if retention already exists in Team B
                existing_retention = next(
                    (r for r in teamb_retentions if r.get('name') == retention_name),
                    None
                )

                if not existing_retention:
                    self.logger.info(f"Creating missing archive retention: {retention_name}")
                    created_retention = self.create_archive_retention_in_teamb(teama_retention)
                    if created_retention:
                        teamb_retentions.append(created_retention)
                        created_retentions += 1
                    else:
                        failed_retentions += 1
                else:
                    self.logger.debug(f"Archive retention already exists: {retention_name}")

            # Build retention mappings
            self.build_retention_mappings(teama_retentions, teamb_retentions)

            # Log retention migration results
            self.logger.info(f"Archive retention migration complete:")
            self.logger.info(f"  ✅ Created: {created_retentions}")
            self.logger.info(f"  ❌ Failed: {failed_retentions}")
            self.logger.info(f"  📊 Total mappings: {len(self.retention_id_mapping)}")

            # Track overall migration statistics
            total_stats = {
                'total_policies': 0,
                'total_created': 0,
                'total_failed': 0,
                'by_source_type': {}
            }

            # Migrate policies for each source type
            for source_type in SourceType:
                self.logger.info(f"=" * 60)
                self.logger.info(f"Migrating {source_type.value} policies")
                self.logger.info(f"=" * 60)

                source_stats = self.migrate_policies_by_source_type(teama_policies, source_type)
                total_stats['by_source_type'][source_type.value] = source_stats
                total_stats['total_policies'] += source_stats['total']
                total_stats['total_created'] += source_stats['created']
                total_stats['total_failed'] += source_stats['failed']

            # Save failed policies log if there were any failures
            if self.failed_policies:
                self.logger.warning(f"Saving log of {len(self.failed_policies)} failed policies...")
                self._save_failed_policies_log()

            # Update state with current resources
            state = {
                "last_run": datetime.now().isoformat(),
                "resources": {self.get_resource_identifier(policy): policy for policy in teama_policies_flat},
                "migration_stats": total_stats
            }
            self.save_state(state)

            # Log completion with detailed statistics in tabular format
            success = total_stats['total_failed'] == 0

            self.logger.info(f"=" * 80)
            self.logger.info(f"🎉 TCO POLICIES MIGRATION RESULTS")
            self.logger.info(f"=" * 80)

            # Prepare migration results table
            migration_table_data = []
            for source_type, stats in total_stats['by_source_type'].items():
                if stats['total'] > 0:
                    success_rate = (stats['created'] / stats['total'] * 100) if stats['total'] > 0 else 0
                    migration_table_data.append({
                        'source_type': source_type,
                        'total': stats['total'],
                        'created': stats['created'],
                        'failed': stats['failed'],
                        'success_rate': f"{success_rate:.1f}%"
                    })

            # Display migration results table
            if migration_table_data:
                self._display_migration_results_table(migration_table_data)

            # Display overall summary using print for clean formatting
            overall_success_rate = (total_stats['total_created'] / total_stats['total_policies'] * 100) if total_stats['total_policies'] > 0 else 100

            print("")
            print("📊 OVERALL MIGRATION SUMMARY")
            print("─" * 40)
            print(f"{'Total Policies Processed:':<25} {total_stats['total_policies']:>10}")
            print(f"{'Successfully Created:':<25} {total_stats['total_created']:>10}")
            print(f"{'Failed Operations:':<25} {total_stats['total_failed']:>10}")
            print(f"{'Overall Success Rate:':<25} {overall_success_rate:>9.1f}%")

            # Step 4: Create post-migration version snapshot
            self.logger.info("📸 Creating post-migration version snapshot...")
            try:
                # Fetch updated resources from both teams for post-migration snapshot
                updated_teama_policies = self.fetch_resources_from_teama()
                updated_teamb_policies = self.fetch_resources_from_teamb()

                post_migration_version = self.version_manager.create_version_snapshot(
                    updated_teama_policies, updated_teamb_policies, 'post_migration'
                )
                self.logger.info(f"Post-migration snapshot created: {post_migration_version}")
            except Exception as e:
                self.logger.warning(f"Failed to create post-migration snapshot: {e}")

            self.log_migration_complete(self.service_name, success, total_stats['total_created'], total_stats['total_failed'])

            if success:
                self.logger.info("🎉 TCO policies migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ TCO policies migration completed with {total_stats['total_failed']} errors. Check failed policies log for details.")

            return success

        except Exception as e:
            self.logger.error(f"❌ TCO policies migration failed: {e}")

            # Save failed policies log if there were any failures
            if self.failed_policies:
                self.logger.warning(f"Saving log of {len(self.failed_policies)} failed policies...")
                self._save_failed_policies_log()

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def dry_run(self) -> bool:
        """Perform a dry run to show what would be migrated."""
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch resources from both teams
            self.logger.info("Fetching policies from Team A...")
            teama_policies_flat = self.fetch_resources_from_teama()

            # Organize Team A policies by source type
            teama_policies = {}
            for source_type in SourceType:
                teama_policies[source_type.value] = [
                    policy for policy in teama_policies_flat
                    if policy.get('_source_type') == source_type.value
                ]

            # Export Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_policies_flat, "teama")

            self.logger.info("Fetching policies from Team B...")
            teamb_policies_flat = self.fetch_resources_from_teamb()

            # Organize Team B policies by source type
            teamb_policies = {}
            for source_type in SourceType:
                teamb_policies[source_type.value] = [
                    policy for policy in teamb_policies_flat
                    if policy.get('_source_type') == source_type.value
                ]

            # Export Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_policies_flat, "teamb")

            # Analyze archive retentions
            self.logger.info("Analyzing archive retentions...")
            teama_retentions = self.fetch_archive_retentions_from_team(self.teama_client)
            teamb_retentions = self.fetch_archive_retentions_from_team(self.teamb_client)

            # Find missing retentions
            teamb_retention_names = {r.get('name') for r in teamb_retentions if r.get('name')}
            missing_retentions = [
                r for r in teama_retentions
                if r.get('name') and r.get('name') not in teamb_retention_names
            ]

            # Build retention mappings for dry run
            self.build_retention_mappings(teama_retentions, teamb_retentions)

            # Calculate what would be done and prepare table data
            total_operations = 0
            table_data = []

            for source_type in SourceType:
                teama_count = len(teama_policies.get(source_type.value, []))
                teamb_count = len(teamb_policies.get(source_type.value, []))

                operations = teama_count + teamb_count if teama_count > 0 else 0
                total_operations += operations

                table_data.append({
                    'source_type': source_type.value,
                    'team_a': teama_count,
                    'team_b': teamb_count,
                    'to_delete': teamb_count if teama_count > 0 else 0,
                    'to_create': teama_count,
                    'operations': operations
                })

            # Display results in tabular format
            self.logger.info(f"=" * 80)
            self.logger.info(f"🎯 TCO POLICIES DRY RUN RESULTS")
            self.logger.info(f"=" * 80)

            # Display policy counts table
            self._display_policy_table(table_data)

            # Display summary using print for clean formatting
            total_teama_policies = len(teama_policies_flat)
            total_teamb_policies = len(teamb_policies_flat)

            print("")
            print("📊 MIGRATION SUMMARY")
            print("─" * 40)
            print(f"{'Archive Retentions:':<25}")
            print(f"{'  Team A Retentions:':<25} {len(teama_retentions):>10}")
            print(f"{'  Team B Retentions:':<25} {len(teamb_retentions):>10}")
            print(f"{'  Missing in Team B:':<25} {len(missing_retentions):>10}")
            print(f"{'  Retention Mappings:':<25} {len(self.retention_id_mapping):>10}")
            print("")
            print(f"{'TCO Policies:':<25}")
            print(f"{'  Total Team A Policies:':<25} {total_teama_policies:>10}")
            print(f"{'  Total Team B Policies:':<25} {total_teamb_policies:>10}")
            print(f"{'  Policies to Delete:':<25} {total_teamb_policies:>10}")
            print(f"{'  Policies to Create:':<25} {total_teama_policies:>10}")
            print(f"{'  Total Operations:':<25} {total_operations:>10}")

            if total_operations == 0:
                print("")
                print("✨ No policies to migrate - both teams have 0 policies")
            else:
                print("")
                print("⚠️  IMPORTANT: ALL existing policies in Team B will be DELETED and recreated from Team A")

            self.logger.info(f"=" * 80)

            self.log_migration_complete(self.service_name, True, 0, 0)
            return True

        except Exception as e:
            self.logger.error(f"❌ TCO policies dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def _display_policy_table(self, table_data: List[Dict[str, Any]]):
        """Display policy statistics in a nice tabular format."""

        # Table headers
        headers = [
            "Source Type",
            "Team A",
            "Team B",
            "To Delete",
            "To Create",
            "Operations"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['source_type']) for row in table_data)),
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
                row['source_type'],
                str(row['team_a']),
                str(row['team_b']),
                str(row['to_delete']),
                str(row['to_create']),
                str(row['operations'])
            ]

            for i, value in enumerate(values):
                if i == 0:  # Source type - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def _display_migration_results_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""

        # Table headers
        headers = [
            "Source Type",
            "Total",
            "Created",
            "Failed",
            "Success Rate"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['source_type']) for row in table_data)),
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
                row['source_type'],
                str(row['total']),
                str(row['created']),
                str(row['failed']),
                row['success_rate']
            ]

            for i, value in enumerate(values):
                if i == 0:  # Source type - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers and percentages - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a single policy in Team B with proper payload sanitization.
        """
        policy_name = self.get_resource_name(resource)

        try:
            self.logger.info(f"Creating individual policy in Team B: {policy_name}")

            # Prepare policy for creation with comprehensive sanitization
            cleaned_policy = self._prepare_policy_for_creation(resource)

            # Log payload details at debug level
            self.logger.debug(f"Creating policy with sanitized payload: {policy_name}")
            self.logger.debug(f"Payload keys: {list(cleaned_policy.keys())}")

            # Add delay before creation
            self._add_operation_delay()

            # Create policy with retry logic
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=cleaned_policy)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.logger.info(f"✅ Successfully created policy: {policy_name}")
            return response

        except Exception as e:
            self.logger.error(f"❌ Failed to create policy '{policy_name}': {e}")

            # Log error details appropriately
            if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                status_code = e.response.status_code
                if status_code >= 500:
                    self.logger.error(f"Server error ({status_code}): {e.response.text}")
                elif status_code >= 400:
                    self.logger.warning(f"Client error ({status_code}): {e.response.text}")
                else:
                    self.logger.error(f"HTTP error ({status_code}): {e.response.text}")

            raise Exception(f"Failed to create policy {policy_name}: {e}")

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """
        Delete a single policy from Team B.
        Note: This method is required by BaseService but TCO uses batch operations.
        """
        try:
            self.logger.info(f"Deleting policy from Team B: {resource_id}")

            # Add delay before deletion
            self._add_operation_delay()

            # Delete with exponential backoff
            def _delete_operation():
                return self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self._retry_with_exponential_backoff(_delete_operation)

            self.logger.info(f"✅ Successfully deleted policy: {resource_id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to delete policy {resource_id}: {e}")
            return False
