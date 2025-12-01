"""
Custom Dashboards migration service for Coralogix DR Tool.

This service handles the migration of custom dashboards between Team A and Team B.
It supports:
- Fetching dashboard catalog from both teams
- Creating new dashboards in Team B
- Deleting dashboards from Team B
- Comparing dashboards to detect changes
- Dry-run functionality
- Failed operations logging with exponential backoff
"""

from typing import Dict, List, Any
from pathlib import Path
import uuid
import json
import time

from core.base_service import BaseService
from core.config import Config
from core.api_client import CoralogixAPIError
from core.safety_manager import SafetyManager
from core.version_manager import VersionManager


class CustomDashboardsService(BaseService):
    """Service for migrating custom dashboards between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_dashboards_logging()
        # Initialize safety and version managers
        self.safety_manager = SafetyManager(config, self.service_name)
        self.version_manager = VersionManager(config, self.service_name)

    @property
    def service_name(self) -> str:
        return "custom-dashboards"

    @property
    def api_endpoint(self) -> str:
        return "/v1/dashboards"
    
    def _setup_failed_dashboards_logging(self):
        """Setup logging directory for failed custom dashboards."""
        self.failed_dashboards_dir = Path("logs/custom_dashboards")
        self.failed_dashboards_dir.mkdir(parents=True, exist_ok=True)

        # Dashboard folders API endpoints (correct Coralogix API path)
        self.folders_api_endpoint = "/v1/dashboards/folders"

    def fetch_dashboard_folders_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all dashboard folders from Team A."""
        try:
            self.logger.info("Fetching dashboard folders from Team A")

            response = self.teama_client.get(self.folders_api_endpoint)
            self.logger.debug(f"Team A folders API response: {response}")

            # API returns {"folder": [...]} structure
            folders = response.get('folder', [])

            self.logger.info(f"Found {len(folders)} dashboard folders in Team A")
            if folders:
                self.logger.debug(f"Sample Team A folder: {folders[0]}")
            return folders

        except Exception as e:
            self.logger.error(f"Failed to fetch dashboard folders from Team A: {e}")
            import traceback
            self.logger.debug(f"Full error traceback: {traceback.format_exc()}")
            return []

    def fetch_dashboard_folders_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all dashboard folders from Team B."""
        try:
            self.logger.info("Fetching dashboard folders from Team B")

            response = self.teamb_client.get(self.folders_api_endpoint)
            self.logger.debug(f"Team B folders API response: {response}")

            # API returns {"folder": [...]} structure
            folders = response.get('folder', [])

            self.logger.info(f"Found {len(folders)} dashboard folders in Team B")
            if folders:
                self.logger.debug(f"Sample Team B folder: {folders[0]}")
            return folders

        except Exception as e:
            self.logger.error(f"Failed to fetch dashboard folders from Team B: {e}")
            import traceback
            self.logger.debug(f"Full error traceback: {traceback.format_exc()}")
            return []

    def create_dashboard_folder_in_teamb(self, folder: Dict[str, Any]) -> Dict[str, Any]:
        """Create a dashboard folder in Team B with proper parent ID handling."""
        try:
            folder_name = folder.get('name', 'Unknown')
            parent_info = ""

            # Prepare folder data according to Coralogix API spec
            folder_data = {
                'name': folder['name']
            }

            # Add parentId if present (for nested folders)
            if 'parentId' in folder and folder['parentId']:
                folder_data['parentId'] = folder['parentId']
                parent_info = f" (parent: {folder['parentId']})"

            self.logger.info(f"Creating dashboard folder in Team B: {folder_name}{parent_info}")

            # Create the complete payload with requestId
            import uuid
            payload = {
                'folder': folder_data,
                'requestId': str(uuid.uuid4())
            }

            self.logger.debug(f"Folder creation payload: {payload}")

            response = self.teamb_client.post(self.folders_api_endpoint, json_data=payload)

            self.logger.debug(f"Folder creation response: {response}")

            # Return the folder ID from the response
            folder_id = response.get('folderId')
            if folder_id:
                self.logger.info(f"✅ Successfully created dashboard folder: {folder_name} (ID: {folder_id})")
                return {'id': folder_id, 'name': folder_name}
            else:
                self.logger.warning(f"No folderId returned in response: {response}")
                return response

        except Exception as e:
            folder_name = folder.get('name', 'Unknown')
            self.logger.error(f"❌ Failed to create dashboard folder '{folder_name}': {e}")
            # Log more details for debugging
            import traceback
            self.logger.debug(f"Full error traceback: {traceback.format_exc()}")
            raise

    def _sort_folders_by_hierarchy(self, folders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort folders to ensure parent folders are created before child folders.

        Args:
            folders: List of folder dictionaries

        Returns:
            Sorted list with parent folders first
        """
        # Separate root folders (no parentId) from child folders
        root_folders = []
        child_folders = []

        for folder in folders:
            if folder.get('parentId'):
                child_folders.append(folder)
            else:
                root_folders.append(folder)

        # Start with root folders
        sorted_folders = root_folders[:]
        remaining_folders = child_folders[:]

        # Keep adding folders whose parents have been processed
        max_iterations = len(folders)  # Prevent infinite loops
        iteration = 0

        while remaining_folders and iteration < max_iterations:
            iteration += 1
            folders_added_this_iteration = []

            for folder in remaining_folders[:]:  # Copy list to modify during iteration
                parent_id = folder.get('parentId')

                # Check if parent has been processed (exists in sorted_folders)
                parent_processed = any(f.get('id') == parent_id for f in sorted_folders)

                if parent_processed:
                    sorted_folders.append(folder)
                    folders_added_this_iteration.append(folder)
                    remaining_folders.remove(folder)

            # If no folders were added this iteration, we have orphaned folders
            if not folders_added_this_iteration:
                self.logger.warning(f"Found {len(remaining_folders)} folders with missing parents:")
                for folder in remaining_folders:
                    self.logger.warning(f"  - '{folder.get('name')}' has missing parent: {folder.get('parentId')}")
                # Add remaining folders anyway (they'll be created as root folders)
                sorted_folders.extend(remaining_folders)
                break

        return sorted_folders

    def ensure_folders_exist_in_teamb(self, teama_folders: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Ensure all Team A folders exist in Team B, handling nested folder hierarchy.

        Returns:
            Dictionary mapping Team A folder IDs to Team B folder IDs
        """
        self.logger.info("Ensuring all dashboard folders exist in Team B")

        if not teama_folders:
            self.logger.info("No folders to process")
            return {}

        # Sort folders to handle hierarchy (parents before children)
        sorted_folders = self._sort_folders_by_hierarchy(teama_folders)
        self.logger.info(f"Processing {len(sorted_folders)} folders in hierarchical order")

        # Get existing folders in Team B
        teamb_folders = self.fetch_dashboard_folders_from_teamb()
        teamb_folders_by_name = {folder['name']: folder for folder in teamb_folders}

        self.logger.debug(f"Found {len(teamb_folders)} existing folders in Team B")

        folder_id_mapping = {}
        folders_created = 0
        folders_failed = 0

        for teama_folder in sorted_folders:
            folder_name = teama_folder.get('name', 'Unknown')
            teama_folder_id = teama_folder.get('id')

            if not teama_folder_id:
                self.logger.warning(f"Skipping folder '{folder_name}' - no ID found")
                continue

            if folder_name in teamb_folders_by_name:
                # Folder already exists in Team B
                teamb_folder_id = teamb_folders_by_name[folder_name]['id']
                folder_id_mapping[teama_folder_id] = teamb_folder_id
                self.logger.debug(f"Folder '{folder_name}' already exists in Team B (ID: {teamb_folder_id})")
            else:
                # Create folder in Team B with proper parent mapping
                try:
                    self.logger.info(f"🔄 Creating folder '{folder_name}' in Team B...")

                    # Create a copy and update parentId if needed
                    folder_to_create = teama_folder.copy()
                    if 'parentId' in folder_to_create and folder_to_create['parentId']:
                        teama_parent_id = folder_to_create['parentId']
                        if teama_parent_id in folder_id_mapping:
                            # Map to Team B parent ID
                            folder_to_create['parentId'] = folder_id_mapping[teama_parent_id]
                            self.logger.debug(f"Mapped parent ID: {teama_parent_id} -> {folder_id_mapping[teama_parent_id]}")
                        else:
                            # Parent not found, create as root folder
                            self.logger.warning(f"Parent folder not found for '{folder_name}', creating as root folder")
                            del folder_to_create['parentId']

                    created_folder = self.create_dashboard_folder_in_teamb(folder_to_create)
                    teamb_folder_id = created_folder.get('id')

                    if teamb_folder_id:
                        folder_id_mapping[teama_folder_id] = teamb_folder_id
                        folders_created += 1
                        self.logger.info(f"✅ Created folder '{folder_name}' in Team B (ID: {teamb_folder_id})")

                        # Update our local cache
                        teamb_folders_by_name[folder_name] = {'id': teamb_folder_id, 'name': folder_name}
                    else:
                        self.logger.error(f"❌ Created folder '{folder_name}' but no ID returned")
                        folders_failed += 1

                except Exception as e:
                    self.logger.error(f"❌ Failed to create folder '{folder_name}': {e}")
                    folders_failed += 1
                    # Continue with other folders

        self.logger.info(f"Folder synchronization complete: {folders_created} created, {folders_failed} failed, {len(folder_id_mapping)} mapped")

        if folder_id_mapping:
            self.logger.debug(f"Final folder ID mapping: {dict(list(folder_id_mapping.items())[:5])}{'...' if len(folder_id_mapping) > 5 else ''}")
        else:
            self.logger.warning("No folder ID mappings created!")

        # Store the actual folders created count for statistics
        self._folders_created_count = folders_created
        self._folders_failed_count = folders_failed

        return folder_id_mapping

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all custom dashboards from Team A with safety checks."""
        api_error = None
        full_dashboards = []

        try:
            self.logger.info("Fetching custom dashboards from Team A")

            # Get dashboard catalog first
            catalog_response = self.teama_client.get(f"{self.api_endpoint}/catalog")
            dashboard_items = catalog_response.get('items', [])

            self.logger.info(f"Found {len(dashboard_items)} dashboards in Team A catalog")

            # For each dashboard, get the full dashboard details
            for item in dashboard_items:
                dashboard_id = item.get('id')
                if dashboard_id:
                    try:
                        # Get full dashboard details
                        dashboard_response = self.teama_client.get(f"{self.api_endpoint}/dashboards/{dashboard_id}")
                        if 'dashboard' in dashboard_response:
                            full_dashboards.append(dashboard_response['dashboard'])
                        else:
                            full_dashboards.append(dashboard_response)
                    except Exception as e:
                        self.logger.warning(f"Failed to fetch dashboard {dashboard_id}: {e}")
                        continue

            self.logger.info(f"Fetched {len(full_dashboards)} complete dashboards from Team A")

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch custom dashboards from Team A: {e}")
            api_error = e
        except Exception as e:
            self.logger.error(f"Unexpected error fetching custom dashboards from Team A: {e}")
            api_error = e

        # Get previous count for safety check
        previous_version = self.version_manager.get_current_version()
        previous_count = previous_version.get('teama', {}).get('count') if previous_version else None

        # Perform safety check
        safety_result = self.safety_manager.check_teama_fetch_safety(
            full_dashboards, api_error, previous_count
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

        return full_dashboards

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all custom dashboards from Team B."""
        try:
            self.logger.info("Fetching custom dashboards from Team B")

            # Get dashboard catalog first
            catalog_response = self.teamb_client.get(f"{self.api_endpoint}/catalog")
            dashboard_items = catalog_response.get('items', [])

            self.logger.info(f"Found {len(dashboard_items)} dashboards in Team B catalog")

            # For each dashboard, get the full dashboard details
            full_dashboards = []
            for item in dashboard_items:
                dashboard_id = item.get('id')
                if dashboard_id:
                    try:
                        # Get full dashboard details
                        dashboard_response = self.teamb_client.get(f"{self.api_endpoint}/dashboards/{dashboard_id}")
                        if 'dashboard' in dashboard_response:
                            full_dashboards.append(dashboard_response['dashboard'])
                        else:
                            full_dashboards.append(dashboard_response)
                    except Exception as e:
                        self.logger.warning(f"Failed to fetch dashboard {dashboard_id}: {e}")
                        continue

            self.logger.info(f"Fetched {len(full_dashboards)} complete dashboards from Team B")
            return full_dashboards

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch custom dashboards from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching custom dashboards from Team B: {e}")
            raise
    
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create a custom dashboard in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_dashboard_for_creation(resource)
            dashboard_name = create_data.get('name', 'Unknown')

            # Check if dashboard has a folder assignment
            folder_info = ""
            if 'folderId' in create_data and create_data['folderId']:
                folder_id = create_data['folderId'].get('value') if isinstance(create_data['folderId'], dict) else create_data['folderId']
                folder_info = f" (folder: {folder_id})"
                self.logger.debug(f"Dashboard will be created in folder: {folder_id}")

            self.logger.info(f"Creating custom dashboard in Team B: {dashboard_name}{folder_info}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Create the dashboard with exponential backoff
            def _create_operation():
                # Generate a unique request ID for the creation
                request_id = str(uuid.uuid4())
                payload = {
                    "requestId": request_id,
                    "dashboard": create_data
                }
                return self.teamb_client.post(f"{self.api_endpoint}/dashboards", json_data=payload)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "custom_dashboard", dashboard_name, True)

            # Return the created dashboard
            return response

        except Exception as e:
            dashboard_name = resource.get('name', 'Unknown')
            self._log_failed_dashboard(resource, 'create', str(e))
            self.log_resource_action("create", "custom_dashboard", dashboard_name, False, str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete a custom dashboard from Team B."""
        try:
            self.logger.info(f"Deleting custom dashboard from Team B: {resource_id}")

            # Generate a unique request ID for the deletion
            request_id = str(uuid.uuid4())

            # Delete the dashboard
            self.teamb_client.delete(f"{self.api_endpoint}/dashboards/{resource_id}?requestId={request_id}")

            self.log_resource_action("delete", "custom_dashboard", resource_id, True)
            return True

        except Exception as e:
            self.log_resource_action("delete", "custom_dashboard", resource_id, False, str(e))
            raise
    
    def _add_creation_delay(self):
        """Add a small delay before creation to avoid overwhelming the API."""
        import time
        delay_seconds = 0.5  # 500ms delay between creations
        time.sleep(delay_seconds)

    def _retry_with_exponential_backoff(self, operation, max_retries: int = 3):
        """Retry an operation with exponential backoff."""
        import time

        for attempt in range(max_retries):
            try:
                return operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise

                wait_time = (2 ** attempt) * 1  # 1s, 2s, 4s
                self.logger.warning(f"Operation failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

    def _log_failed_dashboard(self, dashboard: Dict[str, Any], operation: str, error: str):
        """Log failed dashboard operations to a separate file."""
        import json
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.failed_dashboards_dir / f"failed_custom_dashboards_{timestamp}.json"

        failed_entry = {
            "timestamp": datetime.now().isoformat(),
            "dashboard_id": dashboard.get('id', 'Unknown'),
            "dashboard_name": dashboard.get('name', 'Unknown'),
            "operation": operation,
            "error": error,
            "dashboard_data": dashboard
        }

        # Load existing failed entries or create new list
        failed_entries = []
        if failed_log_file.exists():
            try:
                with open(failed_log_file, 'r') as f:
                    existing_data = json.load(f)
                    failed_entries = existing_data.get('failed_custom_dashboards', [])
            except Exception:
                pass

        failed_entries.append(failed_entry)

        # Save updated failed entries
        failed_data = {
            "timestamp": datetime.now().isoformat(),
            "total_failed": len(failed_entries),
            "failed_custom_dashboards": failed_entries
        }

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(failed_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write failed custom dashboards log: {e}")

    def _prepare_dashboard_for_creation(self, dashboard: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare a custom dashboard for creation by removing fields that
        shouldn't be included in the create request.
        """
        # Fields to exclude from creation (read-only or system-generated)
        exclude_fields = {
            'id',  # System-generated field
            'createTime',  # System-generated timestamp
            'updateTime',  # System-generated timestamp
            'authorId',  # System-generated field
            'isLocked',  # May be set by system
            'lockerAuthorId'  # System-generated field
        }

        # Create a copy without excluded fields
        create_data = {
            k: v for k, v in dashboard.items()
            if k not in exclude_fields and v is not None
        }

        # Preserve folderId for proper folder assignment
        if 'folderId' in dashboard and dashboard['folderId']:
            create_data['folderId'] = dashboard['folderId']
            self.logger.debug(f"Preserving folderId for dashboard '{dashboard.get('name', 'Unknown')}': {dashboard['folderId']}")

        # Fix variablesV2 allOption fields - API requires these to be set, not null
        if 'variablesV2' in create_data and create_data['variablesV2']:
            for variable in create_data['variablesV2']:
                if 'source' in variable and 'query' in variable['source']:
                    query = variable['source']['query']
                    if 'allOption' in query and query['allOption']:
                        # Ensure includeAll and label are set (not null)
                        if query['allOption'].get('includeAll') is None:
                            query['allOption']['includeAll'] = False
                        if query['allOption'].get('label') is None:
                            query['allOption']['label'] = "All"
            self.logger.debug(f"Fixed variablesV2 allOption fields for dashboard '{dashboard.get('name', 'Unknown')}'")

        return create_data

    def _update_dashboard_folder_id(self, dashboard: Dict[str, Any], folder_id_mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        Update dashboard folderId to use Team B folder IDs.

        Args:
            dashboard: Dashboard data
            folder_id_mapping: Mapping from Team A folder IDs to Team B folder IDs

        Returns:
            Updated dashboard with Team B folder ID or without folderId if mapping fails
        """
        if 'folderId' in dashboard and dashboard['folderId']:
            folder_id_obj = dashboard['folderId']

            if isinstance(folder_id_obj, dict) and 'value' in folder_id_obj:
                teama_folder_id = folder_id_obj['value']

                if teama_folder_id in folder_id_mapping:
                    teamb_folder_id = folder_id_mapping[teama_folder_id]
                    dashboard['folderId'] = {'value': teamb_folder_id}
                    self.logger.debug(f"Updated folderId: {teama_folder_id} -> {teamb_folder_id}")
                else:
                    self.logger.warning(f"No mapping found for folder ID: {teama_folder_id}. Creating dashboard without folder assignment.")
                    # Remove folderId to create dashboard without folder
                    if 'folderId' in dashboard:
                        del dashboard['folderId']
                        self.logger.info(f"Removed folderId from dashboard '{dashboard.get('name', 'Unknown')}' - will be created in root")

        return dashboard

    def _validate_folder_exists(self, folder_id: str) -> bool:
        """
        Validate that a folder exists in Team B before creating a dashboard in it.

        Args:
            folder_id: The folder ID to validate

        Returns:
            True if folder exists, False otherwise
        """
        try:
            # Use the views API to check if folder exists
            # This is a simple check - in production you might want to cache folder IDs
            response = self.api_client.get(f"/v1/views/folders/{folder_id}")
            return response.status_code == 200
        except Exception as e:
            self.logger.warning(f"Could not validate folder {folder_id}: {e}")
            return False  # Assume folder doesn't exist if we can't check

    def _display_migration_results_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""

        # Table headers
        headers = [
            "Resource Type",
            "Total",
            "Created",
            "Recreated",
            "Deleted",
            "Failed",
            "Success Rate"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['resource_type']) for row in table_data)),
            max(len(headers[1]), max(len(str(row['total'])) for row in table_data)),
            max(len(headers[2]), max(len(str(row['created'])) for row in table_data)),
            max(len(headers[3]), max(len(str(row['recreated'])) for row in table_data)),
            max(len(headers[4]), max(len(str(row['deleted'])) for row in table_data)),
            max(len(headers[5]), max(len(str(row['failed'])) for row in table_data)),
            max(len(headers[6]), max(len(row['success_rate']) for row in table_data))
        ]

        # Create table borders
        total_width = sum(col_widths) + len(col_widths) * 3 + 1
        top_border = "┌" + "─" * (total_width - 2) + "┐"
        middle_border = "├" + "─" * (total_width - 2) + "┤"
        bottom_border = "└" + "─" * (total_width - 2) + "┘"

        print(top_border)

        # Header row
        header_row = "│"
        for i, header in enumerate(headers):
            if i == 0:  # Resource type - left aligned
                header_row += f" {header:<{col_widths[i]}} │"
            else:  # Numbers - right aligned
                header_row += f" {header:>{col_widths[i]}} │"

        print(header_row)
        print(middle_border)

        # Data rows
        for row in table_data:
            data_row = "│"
            values = [
                row['resource_type'],
                str(row['total']),
                str(row['created']),
                str(row['recreated']),
                str(row['deleted']),
                str(row['failed']),
                row['success_rate']
            ]

            for i, value in enumerate(values):
                if i == 0:  # Resource type - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers and percentages - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get a unique identifier for a custom dashboard."""
        # Dashboards are typically identified by name
        return resource.get('name', resource.get('id', ''))

    def resources_are_equal(self, resource_a: Dict[str, Any], resource_b: Dict[str, Any]) -> bool:
        """
        Compare two custom dashboards to see if they are equal.
        """
        # Fields to ignore in comparison (system-generated or metadata)
        ignore_fields = {
            'id',  # System-generated field
            'createTime',  # System-generated timestamp
            'updateTime',  # System-generated timestamp
            'authorId',  # System-generated field
            'isLocked',  # May be set by system
            'lockerAuthorId'  # System-generated field
        }

        def normalize_dashboard(dashboard):
            return {
                k: v for k, v in dashboard.items()
                if k not in ignore_fields
            }

        normalized_a = normalize_dashboard(resource_a)
        normalized_b = normalize_dashboard(resource_b)

        return normalized_a == normalized_b

    def migrate(self) -> bool:
        """
        Perform the actual custom dashboards migration using delete & recreate all pattern.

        This approach ensures perfect synchronization by:
        1. Synchronizing dashboard folders from Team A to Team B
        2. Deleting ALL existing dashboards from Team B
        3. Recreating ALL dashboards from Team A

        This is the same approach as parsing-rules and guarantees consistency.

        Returns:
            True if migration completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Handle dashboard folders first
            self.logger.info("🔄 Step 1: Synchronizing dashboard folders...")
            teama_folders = self.fetch_dashboard_folders_from_teama()

            if teama_folders:
                folder_id_mapping = self.ensure_folders_exist_in_teamb(teama_folders)
                self.logger.info(f"✅ Folder synchronization complete. Mapped {len(folder_id_mapping)} folders")
            else:
                self.logger.warning("⚠️ No folders found in Team A or folder fetching failed. Proceeding without folder management.")
                folder_id_mapping = {}

            # Step 2: Fetch current dashboards from both teams (with safety checks)
            self.logger.info("🔄 Step 2: Fetching dashboards from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            self.logger.info("🔄 Step 3: Fetching dashboards from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Create pre-migration version snapshot
            self.logger.info("📸 Creating pre-migration version snapshot...")
            pre_migration_version = self.version_manager.create_version_snapshot(
                teama_resources, teamb_resources, 'pre_migration'
            )
            self.logger.info(f"Pre-migration snapshot created: {pre_migration_version}")

            # Get previous TeamA count for safety checks
            previous_version = self.version_manager.get_previous_version()
            previous_teama_count = previous_version.get('teama', {}).get('count') if previous_version else None

            # Save artifacts
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # Step 4: Perform mass deletion safety check (deleting ALL TeamB dashboards)
            mass_deletion_check = self.safety_manager.check_mass_deletion_safety(
                teamb_resources, len(teamb_resources), len(teama_resources), previous_teama_count
            )

            if not mass_deletion_check.is_safe:
                self.logger.error(f"Mass deletion safety check failed: {mass_deletion_check.reason}")
                self.logger.error(f"Safety check details: {mass_deletion_check.details}")
                raise RuntimeError(f"Mass deletion safety check failed: {mass_deletion_check.reason}")

            self.logger.info(
                "Migration plan - Delete ALL + Recreate ALL",
                total_teama_dashboards=len(teama_resources),
                total_teamb_dashboards=len(teamb_resources),
                to_delete=len(teamb_resources),
                to_create=len(teama_resources)
            )

            # Initialize counters
            folders_created = getattr(self, '_folders_created_count', 0)
            folders_failed = getattr(self, '_folders_failed_count', 0)
            delete_count = 0
            create_success_count = 0
            error_count = 0

            # Step 5: Delete ALL existing dashboards from Team B
            self.logger.info("🗑️ Deleting ALL existing dashboards from Team B...")

            if teamb_resources:
                for dashboard in teamb_resources:
                    try:
                        dashboard_id = dashboard.get('id')
                        dashboard_name = dashboard.get('name', 'Unknown')

                        if dashboard_id:
                            self.delete_resource_from_teamb(dashboard_id)
                            self.logger.info(f"Deleted dashboard: {dashboard_name}")
                            delete_count += 1
                        else:
                            self.logger.error(f"Failed to delete dashboard: {dashboard_name} - no ID found")
                            error_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to delete dashboard {dashboard.get('name', 'Unknown')}: {e}")
                        error_count += 1

                # Step 5.1: Verify deletion completed
                self.logger.info("🔍 Verifying all dashboards were deleted from Team B...")
                time.sleep(2)  # Brief delay for API consistency
                verification_teamb_resources = self.fetch_resources_from_teamb()

                if verification_teamb_resources:
                    self.logger.error(f"❌ Deletion verification failed: {len(verification_teamb_resources)} dashboards still exist in Team B")
                    for remaining in verification_teamb_resources:
                        self.logger.error(f"   Remaining: {remaining.get('name', 'Unknown')} (ID: {remaining.get('id', 'N/A')})")
                    raise RuntimeError(f"Failed to delete all dashboards from Team B. {len(verification_teamb_resources)} still remain.")
                else:
                    self.logger.info("✅ Deletion verification passed: Team B is now empty")
            else:
                self.logger.info("ℹ️ Team B already has no dashboards - skipping deletion")

            # Step 6: Create ALL dashboards from Team A
            self.logger.info("📄 Creating ALL dashboards from Team A...")

            if teama_resources:
                for dashboard in teama_resources:
                    try:
                        dashboard_name = dashboard.get('name', 'Unknown')

                        self.logger.info(f"Creating dashboard: {dashboard_name}")
                        # Update folder ID mapping and create new resource in Team B
                        updated_resource = self._update_dashboard_folder_id(dashboard.copy(), folder_id_mapping)
                        self.create_resource_in_teamb(updated_resource)
                        create_success_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to create dashboard {dashboard.get('name', 'Unknown')}: {e}")
                        error_count += 1

                # Step 6.1: Verify creation completed
                self.logger.info("🔍 Verifying all dashboards were created in Team B...")
                time.sleep(2)  # Brief delay for API consistency
                final_teamb_resources = self.fetch_resources_from_teamb()

                expected_count = len(teama_resources)
                actual_count = len(final_teamb_resources)

                if actual_count != expected_count:
                    self.logger.error(f"❌ Creation verification failed: Expected {expected_count} dashboards, but found {actual_count} in Team B")
                    raise RuntimeError(f"Creation verification failed: Expected {expected_count} dashboards, but found {actual_count}")
                else:
                    self.logger.info(f"✅ Creation verification passed: {actual_count} dashboards successfully created in Team B")

                    # Save final state to outputs
                    self.logger.info("💾 Saving final Team B state to outputs...")
                    self.save_artifacts(final_teamb_resources, "teamb_final")
            else:
                self.logger.info("ℹ️ Team A has no dashboards - skipping creation")
                final_teamb_resources = []

            # Step 7: Save migration statistics for summary table
            stats_file = self.outputs_dir / f"{self.service_name}_stats_latest.json"
            stats_data = {
                'teama_count': len(teama_resources),
                'teamb_before': len(teamb_resources),
                'teamb_after': len(final_teamb_resources),
                'created': create_success_count,
                'deleted': delete_count,
                'failed': error_count,
                'folders_created': folders_created,
                'folders_failed': folders_failed
            }
            with open(stats_file, 'w') as f:
                json.dump(stats_data, f, indent=2)

            # Step 8: Create post-migration version snapshot
            self.logger.info("📸 Creating post-migration version snapshot...")
            post_migration_version = self.version_manager.create_version_snapshot(
                teama_resources, final_teamb_resources, 'post_migration'
            )
            self.logger.info(f"Post-migration snapshot created: {post_migration_version}")

            # Log completion
            migration_success = error_count == 0
            self.log_migration_complete(
                self.service_name,
                migration_success,
                create_success_count,
                error_count
            )

            # Print user-visible migration summary
            print("\n" + "=" * 80)
            print("🎯 CUSTOM DASHBOARDS MIGRATION RESULTS")
            print("=" * 80)

            # Folders summary
            if folders_created > 0 or folders_failed > 0:
                print(f"📁 Folders:")
                print(f"   Created: {folders_created}")
                if folders_failed > 0:
                    print(f"   Failed: {folders_failed}")

            # Dashboards summary
            print(f"📊 Dashboards:")
            print(f"   Team A dashboards: {len(teama_resources)}")
            print(f"   Team B dashboards (before): {len(teamb_resources)}")
            print(f"   Team B dashboards (after): {len(final_teamb_resources)}")
            print(f"   🗑️  Deleted from Team B: {delete_count}")
            print(f"   ✅ Successfully created: {create_success_count}")
            if error_count > 0:
                print(f"   ❌ Failed: {error_count}")
            print(f"   📋 Total operations: {delete_count + create_success_count + error_count}")

            if migration_success:
                print("\n✅ Migration completed successfully!")
            else:
                print(f"\n⚠️ Migration completed with {error_count} failures")

            print("=" * 80 + "\n")

            return migration_success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def dry_run(self) -> bool:
        """
        Perform a dry run of the custom dashboards migration using delete & recreate all pattern.
        Shows what would be done without making actual changes.

        Returns:
            True if dry run completed successfully
        """
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Check dashboard folders first
            self.logger.info("🔄 Checking dashboard folders...")
            teama_folders = self.fetch_dashboard_folders_from_teama()
            teamb_folders = self.fetch_dashboard_folders_from_teamb()

            folders_to_create = []
            teamb_folder_names = {folder['name'] for folder in teamb_folders}

            for folder in teama_folders:
                if folder['name'] not in teamb_folder_names:
                    folders_to_create.append(folder)

            # Fetch current dashboards from both teams
            self.logger.info("📊 Fetching dashboards from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            self.logger.info("📊 Fetching dashboards from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Save artifacts for comparison
            self.save_artifacts(teama_resources, 'teama')
            self.save_artifacts(teamb_resources, 'teamb')

            # Calculate what would be done (delete all + recreate all)
            total_operations = len(folders_to_create) + len(teamb_resources) + len(teama_resources)

            # Print dry-run summary
            print("\n" + "=" * 80)
            print("DRY RUN - CUSTOM DASHBOARDS MIGRATION")
            print("=" * 80)

            # Folders summary
            if len(teama_folders) > 0 or len(teamb_folders) > 0:
                print(f"📁 Folders:")
                print(f"   Team A folders: {len(teama_folders)}")
                print(f"   Team B folders: {len(teamb_folders)}")
                print(f"   Folders to create: {len(folders_to_create)}")

            # Dashboards summary
            print(f"📊 Dashboards:")
            print(f"   Team A dashboards: {len(teama_resources)}")
            print(f"   Team B dashboards (current): {len(teamb_resources)}")
            print("\n🔄 Planned Operations:")
            print(f"   🗑️  Delete ALL {len(teamb_resources)} dashboards from Team B")
            print(f"   ✅ Create {len(teama_resources)} dashboards from Team A")
            print(f"\n📋 Total operations: {total_operations}")
            print("=" * 80 + "\n")

            # Save migration statistics for summary table
            stats_file = self.outputs_dir / f"{self.service_name}_stats_latest.json"
            stats_data = {
                'teama_count': len(teama_resources),
                'teamb_before': len(teamb_resources),
                'teamb_after': len(teamb_resources),  # No change in dry run
                'created': 0,  # Dry run doesn't create
                'deleted': 0,  # Dry run doesn't delete
                'failed': 0,
                'folders_created': 0,
                'folders_failed': 0
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
        print("DRY RUN RESULTS - CUSTOM DASHBOARDS")
        print("=" * 60)

        print(f"📊 Team A dashboards: {results['teama_count']}")
        print(f"📊 Team B dashboards: {results['teamb_count']}")

        if results['to_create']:
            print(f"✅ New dashboards to create in Team B: {len(results['to_create'])}")
            for resource in results['to_create']:
                print(f"  + {resource.get('name', 'Unknown')} (ID: {resource.get('id', 'N/A')})")

        # Prepare table data for dry run
        table_data = []

        # Folders row (if folder data is available)
        if 'teama_folders_count' in results and 'folders_to_create' in results:
            table_data.append({
                'resource_type': 'Folders',
                'total': results.get('teama_folders_count', 0),
                'created': results.get('folders_to_create', 0),
                'recreated': 0,
                'deleted': 0,
                'failed': 0,
                'success_rate': '100.0%'
            })

        # Dashboards row
        table_data.append({
            'resource_type': 'Dashboards',
            'total': results['teama_count'],
            'created': len(results['to_create']),
            'recreated': len(results['to_recreate']),
            'deleted': len(results['to_delete']),
            'failed': 0,
            'success_rate': '100.0%'
        })

        # Display the table
        if table_data:
            self._display_migration_results_table(table_data)

        if results['to_recreate']:
            print(f"\n🔄 Changed dashboards to recreate in Team B: {len(results['to_recreate'])}")
            for teama_resource, _ in results['to_recreate'][:3]:  # Show first 3
                print(f"  ~ {teama_resource.get('name', 'Unknown')}")
            if len(results['to_recreate']) > 3:
                print(f"  ... and {len(results['to_recreate']) - 3} more")

        if results['to_delete']:
            print(f"\n🗑️ Dashboards to delete from Team B: {len(results['to_delete'])}")
            for resource in results['to_delete'][:3]:  # Show first 3
                print(f"  - {resource.get('name', 'Unknown')}")
            if len(results['to_delete']) > 3:
                print(f"  ... and {len(results['to_delete']) - 3} more")

        if results['total_operations'] > 0:
            print(f"\n📋 Ready to migrate! Run without --dry-run to execute these changes.")
        else:
            print("\n✨ No changes detected - Team B is already in sync with Team A")

        print("=" * 80)

    def _compare_dashboards(self, teama_resources: List[Dict[str, Any]], teamb_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare custom dashboards between Team A and Team B to identify changes.

        Returns:
            Dictionary with:
            - new_in_teama: Resources that exist in Team A but not in Team B
            - changed_resources: Resources that exist in both but are different
            - deleted_from_teama: Resources that exist in Team B but not in Team A
        """
        # Create lookup dictionaries by name (dashboards are identified by name)
        teama_by_name = {resource.get('name'): resource for resource in teama_resources}
        teamb_by_name = {resource.get('name'): resource for resource in teamb_resources}

        new_in_teama = []
        changed_resources = []
        deleted_from_teama = []

        # Find new and changed resources
        for name, teama_resource in teama_by_name.items():
            if name not in teamb_by_name:
                # Resource exists in Team A but not in Team B - new
                new_in_teama.append(teama_resource)
            else:
                # Resource exists in both teams - check if changed
                teamb_resource = teamb_by_name[name]
                if not self.resources_are_equal(teama_resource, teamb_resource):
                    changed_resources.append((teama_resource, teamb_resource))

        # Find deleted resources (exist in Team B but not in Team A)
        for name, teamb_resource in teamb_by_name.items():
            if name not in teama_by_name:
                deleted_from_teama.append(teamb_resource)

        return {
            'new_in_teama': new_in_teama,
            'changed_resources': changed_resources,
            'deleted_from_teama': deleted_from_teama
        }
