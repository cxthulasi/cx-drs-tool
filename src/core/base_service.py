"""
Base service class for all migration services.
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import structlog

from .config import Config
from .api_client import APIClient, CoralogixAPIError
from .logger import LoggerMixin


class BaseService(LoggerMixin, ABC):
    """Base class for all migration services."""
    
    def __init__(self, config: Config, logger: Optional[structlog.stdlib.BoundLogger] = None):
        """
        Initialize base service.
        
        Args:
            config: Configuration object
            logger: Optional logger instance
        """
        self.config = config
        
        if logger:
            self.logger = logger
        else:
            # Initialize logger using LoggerMixin
            super().__init__(self.service_name, self.service_name)
        
        # Initialize API clients
        self.teama_client = APIClient(config, 'teama')
        self.teamb_client = APIClient(config, 'teamb')
        
        # State management
        self.state_dir = Path(config.state_storage_path)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.snapshots_dir = Path(config.snapshots_storage_path)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Outputs management for artifact export
        self.outputs_dir = Path(getattr(config, 'outputs_storage_path', './outputs'))
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # Create service-specific output directories
        self.service_outputs_dir = self.outputs_dir / self.service_name
        self.service_outputs_dir.mkdir(parents=True, exist_ok=True)
    
    @property
    @abstractmethod
    def service_name(self) -> str:
        """Return the service name."""
        pass
    
    @property
    @abstractmethod
    def api_endpoint(self) -> str:
        """Return the API endpoint for this service."""
        pass
    
    def get_state_file_path(self) -> Path:
        """Get the path to the state file for this service."""
        return self.state_dir / f"{self.service_name}_state.json"
    
    def get_snapshot_file_path(self, timestamp: Optional[str] = None) -> Path:
        """Get the path to a snapshot file."""
        if not timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.snapshots_dir / f"snapshot_{self.service_name}_{timestamp}.json"

    def get_artifact_file_path(self, team: str, timestamp: Optional[str] = None) -> Path:
        """Get the path to an artifact export file."""
        if not timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.service_outputs_dir / f"{self.service_name}_{team}_{timestamp}.json"

    def get_latest_artifact_file_path(self, team: str) -> Path:
        """Get the path to the latest artifact export file."""
        return self.service_outputs_dir / f"{self.service_name}_{team}_latest.json"
    
    def load_state(self) -> Dict[str, Any]:
        """Load the last known state."""
        state_file = self.get_state_file_path()
        
        if not state_file.exists():
            return {
                "last_run": None,
                "resources": {},
                "mappings": {}  # teama_id -> teamb_id mappings
            }
        
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load state file: {e}")
            return {
                "last_run": None,
                "resources": {},
                "mappings": {}
            }
    
    def save_state(self, state: Dict[str, Any]):
        """Save the current state."""
        state_file = self.get_state_file_path()
        
        try:
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            
            self.logger.info(f"State saved to {state_file}")
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            raise
    
    def save_snapshot(self, resources: List[Dict[str, Any]], timestamp: Optional[str] = None) -> Path:
        """Save a snapshot of resources."""
        snapshot_file = self.get_snapshot_file_path(timestamp)

        snapshot_data = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "resources": resources,
            "count": len(resources)
        }

        try:
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot_data, f, indent=2, default=str)

            self.logger.info(f"Snapshot saved to {snapshot_file}")
            return snapshot_file
        except Exception as e:
            self.logger.error(f"Failed to save snapshot: {e}")
            raise

    def save_artifacts(self, resources: List[Dict[str, Any]], team: str, timestamp: Optional[str] = None) -> Path:
        """Save artifacts to outputs directory for periodic comparison."""
        artifact_file = self.get_artifact_file_path(team, timestamp)
        latest_artifact_file = self.get_latest_artifact_file_path(team)

        artifact_data = {
            "timestamp": datetime.now().isoformat(),
            "service": self.service_name,
            "team": team,
            "resources": resources,
            "count": len(resources),
            "resource_identifiers": [self.get_resource_identifier(r) for r in resources]
        }

        try:
            # Save timestamped version
            with open(artifact_file, 'w') as f:
                json.dump(artifact_data, f, indent=2, default=str)

            # Save latest version (for easy comparison)
            with open(latest_artifact_file, 'w') as f:
                json.dump(artifact_data, f, indent=2, default=str)

            self.logger.info(f"Artifacts saved to {artifact_file}")
            self.logger.info(f"Latest artifacts saved to {latest_artifact_file}")
            return artifact_file
        except Exception as e:
            self.logger.error(f"Failed to save artifacts: {e}")
            raise
    
    @abstractmethod
    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all resources from Team A."""
        pass
    
    @abstractmethod
    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all resources from Team B."""
        pass
    
    @abstractmethod
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create a resource in Team B."""
        pass
    
    @abstractmethod
    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete a resource from Team B."""
        pass
    
    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a resource (usually name or id)."""
        return resource.get('name', resource.get('id', ''))
    
    def resources_are_equal(self, resource_a: Dict[str, Any], resource_b: Dict[str, Any]) -> bool:
        """
        Compare two resources to see if they are equal.
        Override this method for service-specific comparison logic.
        """
        # Remove volatile fields that shouldn't be compared
        volatile_fields = {'id', 'created_at', 'updated_at', 'created_time', 'updated_time'}
        
        def clean_resource(resource):
            return {k: v for k, v in resource.items() if k not in volatile_fields}
        
        return clean_resource(resource_a) == clean_resource(resource_b)
    
    def detect_changes(self, current_resources: List[Dict[str, Any]], 
                      previous_resources: Dict[str, Any]) -> Tuple[List[Dict], List[Dict], List[str]]:
        """
        Detect changes between current and previous resources.
        
        Returns:
            Tuple of (new_resources, changed_resources, deleted_resource_ids)
        """
        new_resources = []
        changed_resources = []
        deleted_resource_ids = []
        
        # Create lookup dictionaries
        current_by_id = {self.get_resource_identifier(r): r for r in current_resources}
        previous_by_id = previous_resources
        
        # Find new and changed resources
        for resource_id, current_resource in current_by_id.items():
            if resource_id not in previous_by_id:
                new_resources.append(current_resource)
            else:
                previous_resource = previous_by_id[resource_id]
                if not self.resources_are_equal(current_resource, previous_resource):
                    changed_resources.append(current_resource)
        
        # Find deleted resources
        for resource_id in previous_by_id:
            if resource_id not in current_by_id:
                deleted_resource_ids.append(resource_id)
        
        return new_resources, changed_resources, deleted_resource_ids

    def load_artifacts(self, team: str) -> Dict[str, Any]:
        """Load the latest artifacts for a team."""
        artifact_file = self.get_latest_artifact_file_path(team)

        if not artifact_file.exists():
            return {
                "timestamp": None,
                "service": self.service_name,
                "team": team,
                "resources": [],
                "count": 0,
                "resource_identifiers": []
            }

        try:
            with open(artifact_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load artifacts for {team}: {e}")
            return {
                "timestamp": None,
                "service": self.service_name,
                "team": team,
                "resources": [],
                "count": 0,
                "resource_identifiers": []
            }

    def compare_team_artifacts(self) -> Dict[str, Any]:
        """Compare artifacts between Team A and Team B."""
        teama_artifacts = self.load_artifacts('teama')
        teamb_artifacts = self.load_artifacts('teamb')

        teama_resources = {self.get_resource_identifier(r): r for r in teama_artifacts.get('resources', [])}
        teamb_resources = {self.get_resource_identifier(r): r for r in teamb_artifacts.get('resources', [])}

        # Find differences
        only_in_teama = []
        only_in_teamb = []
        different_resources = []

        # Resources only in Team A
        for resource_id, resource in teama_resources.items():
            if resource_id not in teamb_resources:
                only_in_teama.append(resource)
            else:
                # Check if resources are different
                if not self.resources_are_equal(resource, teamb_resources[resource_id]):
                    different_resources.append({
                        'resource_id': resource_id,
                        'teama_resource': resource,
                        'teamb_resource': teamb_resources[resource_id]
                    })

        # Resources only in Team B
        for resource_id, resource in teamb_resources.items():
            if resource_id not in teama_resources:
                only_in_teamb.append(resource)

        return {
            'teama_count': teama_artifacts.get('count', 0),
            'teamb_count': teamb_artifacts.get('count', 0),
            'teama_timestamp': teama_artifacts.get('timestamp'),
            'teamb_timestamp': teamb_artifacts.get('timestamp'),
            'only_in_teama': only_in_teama,
            'only_in_teamb': only_in_teamb,
            'different_resources': different_resources,
            'sync_needed': len(only_in_teama) > 0 or len(different_resources) > 0
        }
    
    def dry_run(self) -> bool:
        """
        Perform a dry run - show what would be done without making changes.
        Also saves artifacts for comparison.

        Returns:
            True if dry run completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch current resources from Team A
            self.logger.info("Fetching resources from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            # Save Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_resources, 'teama')

            # Fetch current resources from Team B for comparison
            self.logger.info("Fetching resources from Team B...")
            try:
                teamb_resources = self.fetch_resources_from_teamb()
                # Save Team B artifacts
                self.logger.info("Saving Team B artifacts...")
                self.save_artifacts(teamb_resources, 'teamb')
            except Exception as e:
                self.logger.warning(f"Could not fetch Team B resources: {e}")
                teamb_resources = []

            # Load previous state
            state = self.load_state()
            previous_resources = state.get('resources', {})

            # Detect changes
            new_resources, changed_resources, deleted_resource_ids = self.detect_changes(
                teama_resources, previous_resources
            )

            # Compare artifacts between teams
            self.logger.info("Comparing artifacts between teams...")
            comparison = self.compare_team_artifacts()

            # Log what would be done
            self.logger.info(
                "Dry run results",
                total_resources=len(teama_resources),
                new_resources=len(new_resources),
                changed_resources=len(changed_resources),
                deleted_resources=len(deleted_resource_ids)
            )

            # Log team comparison results
            self.logger.info(
                "Team comparison results",
                teama_count=comparison['teama_count'],
                teamb_count=comparison['teamb_count'],
                only_in_teama=len(comparison['only_in_teama']),
                only_in_teamb=len(comparison['only_in_teamb']),
                different_resources=len(comparison['different_resources']),
                sync_needed=comparison['sync_needed']
            )

            if new_resources:
                self.logger.info("New resources to create:")
                for resource in new_resources:
                    self.logger.info(f"  - {self.get_resource_identifier(resource)}")

            if changed_resources:
                self.logger.info("Changed resources to update:")
                for resource in changed_resources:
                    self.logger.info(f"  - {self.get_resource_identifier(resource)}")

            if deleted_resource_ids:
                self.logger.info("Resources to delete:")
                for resource_id in deleted_resource_ids:
                    self.logger.info(f"  - {resource_id}")

            if comparison['only_in_teama']:
                self.logger.info("Resources only in Team A (need to sync to Team B):")
                for resource in comparison['only_in_teama']:
                    self.logger.info(f"  - {self.get_resource_identifier(resource)}")

            if comparison['different_resources']:
                self.logger.info("Resources with differences between teams:")
                for diff in comparison['different_resources']:
                    self.logger.info(f"  - {diff['resource_id']}")

            self.log_migration_complete(self.service_name, True, len(teama_resources))
            return True

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False
    
    @abstractmethod
    def migrate(self) -> bool:
        """
        Perform the actual migration.
        
        Returns:
            True if migration completed successfully
        """
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.teama_client.close()
        self.teamb_client.close()
