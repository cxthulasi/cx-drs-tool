"""
Version Manager for maintaining versioned snapshots and rollback capabilities.

This module provides versioning functionality to maintain multiple versions
of resource states, enabling quick rollback when issues are detected.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import structlog

from .config import Config


class VersionManager:
    """Manages versioned snapshots of resources for rollback capabilities."""
    
    def __init__(self, config: Config, service_name: str):
        self.config = config
        self.service_name = service_name
        self.logger = structlog.get_logger(f"version_manager_{service_name}")
        
        # Version storage configuration
        self.max_versions = getattr(config, 'max_versions_to_keep', 10)
        
        # Storage paths
        self.versions_dir = Path(getattr(config, 'versions_storage_path', './versions'))
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        
        self.service_versions_dir = self.versions_dir / service_name
        self.service_versions_dir.mkdir(parents=True, exist_ok=True)
    
    def create_version_snapshot(self, 
                               teama_resources: List[Dict[str, Any]], 
                               teamb_resources: List[Dict[str, Any]],
                               version_type: str = 'auto') -> str:
        """
        Create a versioned snapshot of current resources.
        
        Args:
            teama_resources: Current TeamA resources
            teamb_resources: Current TeamB resources
            version_type: Type of version ('auto', 'manual', 'pre_migration', 'post_migration')
            
        Returns:
            Version identifier (timestamp-based)
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        version_id = f"v_{timestamp}"
        
        version_data = {
            'version_id': version_id,
            'timestamp': datetime.now().isoformat(),
            'service': self.service_name,
            'version_type': version_type,
            'teama': {
                'count': len(teama_resources),
                'resources': teama_resources,
                'resource_identifiers': [self._get_resource_identifier(r) for r in teama_resources]
            },
            'teamb': {
                'count': len(teamb_resources),
                'resources': teamb_resources,
                'resource_identifiers': [self._get_resource_identifier(r) for r in teamb_resources]
            },
            'metadata': {
                'created_by': 'version_manager',
                'purpose': f'{version_type}_snapshot'
            }
        }
        
        # Save version snapshot
        version_file = self.service_versions_dir / f'{version_id}.json'
        
        try:
            with open(version_file, 'w') as f:
                json.dump(version_data, f, indent=2, default=str)
            
            # Update current and previous version links
            self._update_version_links(version_id)
            
            # Clean up old versions
            self._cleanup_old_versions()
            
            self.logger.info(f"Version snapshot created: {version_id}")
            return version_id
            
        except Exception as e:
            self.logger.error(f"Failed to create version snapshot: {e}")
            raise
    
    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific version by ID.
        
        Args:
            version_id: Version identifier
            
        Returns:
            Version data or None if not found
        """
        version_file = self.service_versions_dir / f'{version_id}.json'
        
        if not version_file.exists():
            return None
        
        try:
            with open(version_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load version {version_id}: {e}")
            return None
    
    def get_current_version(self) -> Optional[Dict[str, Any]]:
        """Get the current version (latest snapshot)."""
        current_link = self.service_versions_dir / 'current.json'
        
        if not current_link.exists():
            return None
        
        try:
            with open(current_link, 'r') as f:
                link_data = json.load(f)
            
            version_id = link_data.get('version_id')
            if version_id:
                return self.get_version(version_id)
            
        except Exception as e:
            self.logger.error(f"Failed to get current version: {e}")
        
        return None
    
    def get_previous_version(self) -> Optional[Dict[str, Any]]:
        """Get the previous version (v-1)."""
        previous_link = self.service_versions_dir / 'previous.json'
        
        if not previous_link.exists():
            return None
        
        try:
            with open(previous_link, 'r') as f:
                link_data = json.load(f)
            
            version_id = link_data.get('version_id')
            if version_id:
                return self.get_version(version_id)
            
        except Exception as e:
            self.logger.error(f"Failed to get previous version: {e}")
        
        return None
    
    def list_versions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        List available versions.
        
        Args:
            limit: Maximum number of versions to return
            
        Returns:
            List of version metadata (sorted by timestamp, newest first)
        """
        try:
            version_files = list(self.service_versions_dir.glob('v_*.json'))
            versions = []
            
            for version_file in version_files:
                try:
                    with open(version_file, 'r') as f:
                        data = json.load(f)
                    
                    # Extract metadata for listing
                    versions.append({
                        'version_id': data.get('version_id'),
                        'timestamp': data.get('timestamp'),
                        'version_type': data.get('version_type'),
                        'teama_count': data.get('teama', {}).get('count', 0),
                        'teamb_count': data.get('teamb', {}).get('count', 0),
                        'file_path': str(version_file)
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to read version file {version_file}: {e}")
                    continue
            
            # Sort by timestamp (newest first)
            versions.sort(key=lambda x: x['timestamp'], reverse=True)
            
            return versions[:limit]
            
        except Exception as e:
            self.logger.error(f"Failed to list versions: {e}")
            return []
    
    def create_rollback_plan(self, target_version_id: str) -> Optional[Dict[str, Any]]:
        """
        Create a rollback plan to restore a specific version.
        
        Args:
            target_version_id: Version to rollback to
            
        Returns:
            Rollback plan with resources to create/delete
        """
        target_version = self.get_version(target_version_id)
        current_version = self.get_current_version()
        
        if not target_version:
            self.logger.error(f"Target version {target_version_id} not found")
            return None
        
        if not current_version:
            self.logger.warning("No current version found, rollback plan will be based on target version only")
            current_teamb_resources = []
        else:
            current_teamb_resources = current_version.get('teamb', {}).get('resources', [])
        
        target_teamb_resources = target_version.get('teamb', {}).get('resources', [])
        
        # Create rollback plan
        rollback_plan = {
            'target_version_id': target_version_id,
            'target_timestamp': target_version.get('timestamp'),
            'current_version_id': current_version.get('version_id') if current_version else None,
            'resources_to_create': target_teamb_resources,
            'resources_to_delete': current_teamb_resources,
            'summary': {
                'target_count': len(target_teamb_resources),
                'current_count': len(current_teamb_resources),
                'create_count': len(target_teamb_resources),
                'delete_count': len(current_teamb_resources)
            }
        }
        
        return rollback_plan
    
    def _get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a resource."""
        # Try common identifier fields
        for field in ['name', 'id', 'title']:
            if field in resource and resource[field]:
                return str(resource[field])
        
        # Fallback to hash of resource
        return str(hash(json.dumps(resource, sort_keys=True)))
    
    def _update_version_links(self, new_version_id: str):
        """Update current and previous version links."""
        current_link = self.service_versions_dir / 'current.json'
        previous_link = self.service_versions_dir / 'previous.json'
        
        try:
            # Move current to previous
            if current_link.exists():
                with open(current_link, 'r') as f:
                    current_data = json.load(f)
                
                with open(previous_link, 'w') as f:
                    json.dump(current_data, f, indent=2)
            
            # Set new current
            current_data = {
                'version_id': new_version_id,
                'updated_at': datetime.now().isoformat()
            }
            
            with open(current_link, 'w') as f:
                json.dump(current_data, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Failed to update version links: {e}")
    
    def _cleanup_old_versions(self):
        """Clean up old versions beyond the retention limit."""
        try:
            versions = self.list_versions(limit=100)  # Get all versions
            
            if len(versions) <= self.max_versions:
                return
            
            # Keep the most recent versions, delete the rest
            versions_to_delete = versions[self.max_versions:]
            
            for version in versions_to_delete:
                version_file = Path(version['file_path'])
                if version_file.exists():
                    version_file.unlink()
                    self.logger.info(f"Deleted old version: {version['version_id']}")
                    
        except Exception as e:
            self.logger.error(f"Failed to cleanup old versions: {e}")
