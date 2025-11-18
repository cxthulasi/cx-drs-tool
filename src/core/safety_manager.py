"""
Central Safety Manager for preventing dangerous operations during migration.

This module provides centralized safety checks to prevent accidental deletion
of resources in TeamB when TeamA has API errors or returns zero results due to
authentication, network, or other issues.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import structlog

from .config import Config
from .api_client import CoralogixAPIError


class SafetyCheckResult:
    """Result of a safety check operation."""
    
    def __init__(self, is_safe: bool, reason: str, details: Optional[Dict] = None):
        self.is_safe = is_safe
        self.reason = reason
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()


class SafetyManager:
    """Central safety manager for migration operations."""
    
    def __init__(self, config: Config, service_name: str):
        self.config = config
        self.service_name = service_name
        self.logger = structlog.get_logger(f"safety_manager_{service_name}")
        
        # Safety configuration
        self.min_resources_threshold = getattr(config, 'min_resources_threshold', 1)
        self.max_zero_results_window_hours = getattr(config, 'max_zero_results_window_hours', 24)
        self.require_confirmation_for_mass_delete = getattr(config, 'require_confirmation_for_mass_delete', True)
        
        # Storage paths
        self.safety_dir = Path(getattr(config, 'safety_storage_path', './safety'))
        self.safety_dir.mkdir(parents=True, exist_ok=True)
        
        self.service_safety_dir = self.safety_dir / service_name
        self.service_safety_dir.mkdir(parents=True, exist_ok=True)
    
    def check_teama_fetch_safety(self, 
                                 teama_resources: List[Dict[str, Any]], 
                                 api_error: Optional[Exception] = None,
                                 previous_count: Optional[int] = None) -> SafetyCheckResult:
        """
        Check if TeamA fetch results are safe for proceeding with migration.
        
        Args:
            teama_resources: Resources fetched from TeamA
            api_error: Any API error that occurred during fetch
            previous_count: Previous known count of resources from TeamA
            
        Returns:
            SafetyCheckResult indicating if it's safe to proceed
        """
        current_count = len(teama_resources)
        
        # Check for API errors
        if api_error:
            return self._handle_api_error(api_error, current_count, previous_count)
        
        # Check for zero results
        if current_count == 0:
            return self._handle_zero_results(previous_count)
        
        # Check for significant drop in resources
        if previous_count and previous_count > 0:
            drop_percentage = ((previous_count - current_count) / previous_count) * 100
            if drop_percentage > 50:  # More than 50% drop
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"Significant drop in TeamA resources: {previous_count} -> {current_count} ({drop_percentage:.1f}% drop)",
                    details={
                        'previous_count': previous_count,
                        'current_count': current_count,
                        'drop_percentage': drop_percentage,
                        'threshold': 50
                    }
                )
        
        # All checks passed
        return SafetyCheckResult(
            is_safe=True,
            reason="TeamA fetch results are safe",
            details={
                'current_count': current_count,
                'previous_count': previous_count,
                'api_error': None
            }
        )
    
    def _handle_api_error(self, api_error: Exception, current_count: int, previous_count: Optional[int]) -> SafetyCheckResult:
        """Handle API error scenarios."""
        error_details = {
            'error_type': type(api_error).__name__,
            'error_message': str(api_error),
            'current_count': current_count,
            'previous_count': previous_count
        }
        
        # Check if it's a CoralogixAPIError with status code
        if isinstance(api_error, CoralogixAPIError):
            status_code = getattr(api_error, 'status_code', None)
            error_details['status_code'] = status_code
            
            # Specific handling for different error types
            if status_code in [401, 403]:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"Authentication/Authorization error (HTTP {status_code}): Cannot proceed with migration as TeamA data is inaccessible",
                    details=error_details
                )
            elif status_code in [404]:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"TeamA endpoint not found (HTTP {status_code}): API endpoint may have changed or service may be unavailable",
                    details=error_details
                )
            elif status_code in [500, 502, 503, 504]:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"TeamA server error (HTTP {status_code}): Server is experiencing issues, cannot trust zero results",
                    details=error_details
                )
        
        # Generic error handling
        return SafetyCheckResult(
            is_safe=False,
            reason=f"TeamA fetch failed with error: {api_error}",
            details=error_details
        )
    
    def _handle_zero_results(self, previous_count: Optional[int]) -> SafetyCheckResult:
        """Handle zero results scenarios."""
        # If we've never seen resources before, zero might be legitimate
        if previous_count is None:
            return SafetyCheckResult(
                is_safe=True,
                reason="Zero results from TeamA, but no previous count available - assuming legitimate empty state",
                details={
                    'current_count': 0,
                    'previous_count': None,
                    'assumption': 'legitimate_empty_state'
                }
            )
        
        # If we previously had resources, zero is suspicious
        if previous_count > 0:
            # Check recent zero results history
            recent_zeros = self._get_recent_zero_results_count()
            
            if recent_zeros >= 3:  # Multiple consecutive zero results
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"Multiple consecutive zero results from TeamA ({recent_zeros} times) - likely API issue",
                    details={
                        'current_count': 0,
                        'previous_count': previous_count,
                        'recent_zero_count': recent_zeros,
                        'threshold': 3
                    }
                )
        
        # Record this zero result
        self._record_zero_result()
        
        return SafetyCheckResult(
            is_safe=False,
            reason=f"TeamA returned zero resources but previously had {previous_count} - potential API issue",
            details={
                'current_count': 0,
                'previous_count': previous_count,
                'recommendation': 'verify_teama_manually'
            }
        )

    def check_mass_deletion_safety(self,
                                   resources_to_delete: List[Dict[str, Any]],
                                   total_teamb_resources: int,
                                   teama_resource_count: Optional[int] = None,
                                   previous_teama_count: Optional[int] = None) -> SafetyCheckResult:
        """
        Check if mass deletion operation is safe based on TeamA resource count trends.

        The key safety principle: Block deletion only if current TeamA count is significantly
        less than previous TeamA count (indicating API issues), not based on TeamA vs TeamB comparison.

        Args:
            resources_to_delete: List of resources that would be deleted
            total_teamb_resources: Total number of resources in TeamB
            teama_resource_count: Current number of resources in TeamA
            previous_teama_count: Previous number of resources in TeamA

        Returns:
            SafetyCheckResult indicating if mass deletion is safe
        """
        delete_count = len(resources_to_delete)

        if delete_count == 0:
            return SafetyCheckResult(
                is_safe=True,
                reason="No resources to delete",
                details={'delete_count': 0}
            )

        # Handle backward compatibility
        if teama_resource_count is None:
            teama_resource_count = 0

        # PRIMARY SAFETY CHECK: Compare current TeamA count with previous TeamA count
        if previous_teama_count is not None and previous_teama_count > 0:
            if teama_resource_count == 0:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"CRITICAL: TeamA dropped from {previous_teama_count} to 0 resources - likely API issue",
                    details={
                        'delete_count': delete_count,
                        'total_resources': total_teamb_resources,
                        'teama_count': teama_resource_count,
                        'previous_teama_count': previous_teama_count,
                        'drop_percentage': 100,
                        'recommendation': 'verify_teama_api_status'
                    }
                )

            # Check for significant drop in TeamA resources (>70% drop)
            drop_percentage = ((previous_teama_count - teama_resource_count) / previous_teama_count) * 100
            if drop_percentage > 70:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"CRITICAL: TeamA resources dropped {drop_percentage:.1f}% ({previous_teama_count} → {teama_resource_count}) - likely API issue",
                    details={
                        'delete_count': delete_count,
                        'total_resources': total_teamb_resources,
                        'teama_count': teama_resource_count,
                        'previous_teama_count': previous_teama_count,
                        'drop_percentage': drop_percentage,
                        'threshold': 70,
                        'recommendation': 'verify_teama_api_status'
                    }
                )

        # SECONDARY SAFETY CHECK: Only for extreme cases where TeamA is 0 and we're deleting many
        if teama_resource_count == 0 and total_teamb_resources > 10:
            return SafetyCheckResult(
                is_safe=False,
                reason=f"Suspicious: TeamA has 0 resources but attempting to delete {total_teamb_resources} from TeamB",
                details={
                    'delete_count': delete_count,
                    'total_resources': total_teamb_resources,
                    'teama_count': teama_resource_count,
                    'previous_teama_count': previous_teama_count,
                    'recommendation': 'verify_teama_api_status'
                }
            )

        # LEGITIMATE SCENARIOS - Allow these common migration patterns:
        # 1. TeamA and TeamB have similar counts (normal sync)
        # 2. TeamA has more resources than TeamB (initial sync or updates)
        # 3. Delete & recreate pattern (custom-actions style)

        scenario_type = "unknown"
        if teama_resource_count > 0 and total_teamb_resources > 0:
            ratio = teama_resource_count / total_teamb_resources
            if 0.5 <= ratio <= 2.0:  # Similar counts (within 2x of each other)
                scenario_type = "normal_sync"
            elif ratio > 2.0:  # TeamA has significantly more
                scenario_type = "initial_sync_or_update"
            else:  # TeamA has significantly less, but we already checked for drops above
                scenario_type = "partial_sync"
        elif teama_resource_count > 0 and total_teamb_resources == 0:
            scenario_type = "initial_deployment"

        return SafetyCheckResult(
            is_safe=True,
            reason=f"Safe migration: TeamA={teama_resource_count}, TeamB={total_teamb_resources}, Delete={delete_count} ({scenario_type})",
            details={
                'delete_count': delete_count,
                'total_resources': total_teamb_resources,
                'teama_count': teama_resource_count,
                'previous_teama_count': previous_teama_count,
                'scenario_type': scenario_type,
                'percentage': (delete_count / total_teamb_resources * 100) if total_teamb_resources > 0 else 0
            }
        )

    def _get_recent_zero_results_count(self) -> int:
        """Get count of recent zero results."""
        zero_results_file = self.service_safety_dir / 'zero_results.json'

        if not zero_results_file.exists():
            return 0

        try:
            with open(zero_results_file, 'r') as f:
                data = json.load(f)

            # Count zero results in the last 24 hours
            cutoff_time = datetime.now() - timedelta(hours=self.max_zero_results_window_hours)
            recent_count = 0

            for timestamp_str in data.get('zero_results', []):
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp > cutoff_time:
                        recent_count += 1
                except ValueError:
                    continue

            return recent_count

        except Exception as e:
            self.logger.warning(f"Failed to read zero results history: {e}")
            return 0

    def _record_zero_result(self):
        """Record a zero result occurrence."""
        zero_results_file = self.service_safety_dir / 'zero_results.json'

        try:
            # Load existing data
            if zero_results_file.exists():
                with open(zero_results_file, 'r') as f:
                    data = json.load(f)
            else:
                data = {'zero_results': []}

            # Add current timestamp
            data['zero_results'].append(datetime.now().isoformat())

            # Keep only recent entries (last 7 days)
            cutoff_time = datetime.now() - timedelta(days=7)
            data['zero_results'] = [
                ts for ts in data['zero_results']
                if datetime.fromisoformat(ts) > cutoff_time
            ]

            # Save updated data
            with open(zero_results_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.warning(f"Failed to record zero result: {e}")

    def create_safety_checkpoint(self,
                                 teama_resources: List[Dict[str, Any]],
                                 teamb_resources: List[Dict[str, Any]]) -> str:
        """
        Create a safety checkpoint with current state of both teams.

        Args:
            teama_resources: Current TeamA resources
            teamb_resources: Current TeamB resources

        Returns:
            Path to the created checkpoint file
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        checkpoint_file = self.service_safety_dir / f'checkpoint_{timestamp}.json'

        checkpoint_data = {
            'timestamp': datetime.now().isoformat(),
            'service': self.service_name,
            'teama': {
                'count': len(teama_resources),
                'resources': teama_resources
            },
            'teamb': {
                'count': len(teamb_resources),
                'resources': teamb_resources
            },
            'metadata': {
                'created_by': 'safety_manager',
                'purpose': 'pre_migration_checkpoint'
            }
        }

        try:
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint_data, f, indent=2, default=str)

            self.logger.info(f"Safety checkpoint created: {checkpoint_file}")
            return str(checkpoint_file)

        except Exception as e:
            self.logger.error(f"Failed to create safety checkpoint: {e}")
            raise

    def get_last_known_good_state(self) -> Optional[Dict[str, Any]]:
        """
        Get the last known good state (checkpoint with resources > 0).

        Returns:
            Last known good checkpoint data or None
        """
        try:
            # Find all checkpoint files
            checkpoint_files = list(self.service_safety_dir.glob('checkpoint_*.json'))

            if not checkpoint_files:
                return None

            # Sort by timestamp (newest first)
            checkpoint_files.sort(reverse=True)

            # Find the most recent checkpoint with resources
            for checkpoint_file in checkpoint_files:
                try:
                    with open(checkpoint_file, 'r') as f:
                        data = json.load(f)

                    teama_count = data.get('teama', {}).get('count', 0)
                    if teama_count > 0:
                        return data

                except Exception as e:
                    self.logger.warning(f"Failed to read checkpoint {checkpoint_file}: {e}")
                    continue

            return None

        except Exception as e:
            self.logger.error(f"Failed to get last known good state: {e}")
            return None
