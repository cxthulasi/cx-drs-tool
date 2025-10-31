"""
Views migration service for Coralogix DR Tool.

This service handles the migration of views and view folders between Team A and Team B.
It follows the same proven pattern as custom-dashboards service:
- Delete all existing views and folders from Team B
- Recreate all views and folders from Team A
- Proper folder ID mapping
- Sanitized payload creation
- Tabular statistics display
"""

from typing import Dict, List, Any
from pathlib import Path
import json
import time

from core.base_service import BaseService
from core.config import Config
from core.api_client import CoralogixAPIError


class ViewsService(BaseService):
    """Service for migrating views and view folders between teams."""

    def __init__(self, config: Config, logger):
        super().__init__(config, logger)
        self._setup_failed_views_logging()

    @property
    def service_name(self) -> str:
        return "views"

    @property
    def api_endpoint(self) -> str:
        return "/latest/v1/views"

    @property
    def folders_api_endpoint(self) -> str:
        return "/latest/v1/view_folders"

    def _setup_failed_views_logging(self):
        """Setup logging directory for failed views."""
        self.failed_views_dir = Path("logs/views")
        self.failed_views_dir.mkdir(parents=True, exist_ok=True)

    def fetch_view_folders_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all view folders from Team A."""
        try:
            self.logger.info("Fetching view folders from Team A")
            response = self.teama_client.get(self.folders_api_endpoint)

            # API returns {"folders": [...]} structure
            folders = response.get('folders', [])

            self.logger.info(f"Found {len(folders)} view folders in Team A")
            return folders

        except Exception as e:
            self.logger.error(f"Failed to fetch view folders from Team A: {e}")
            return []

    def fetch_view_folders_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all view folders from Team B."""
        try:
            self.logger.info("Fetching view folders from Team B")
            response = self.teamb_client.get(self.folders_api_endpoint)

            # API returns {"folders": [...]} structure
            folders = response.get('folders', [])

            self.logger.info(f"Found {len(folders)} view folders in Team B")
            return folders

        except Exception as e:
            self.logger.error(f"Failed to fetch view folders from Team B: {e}")
            return []

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all views from Team A."""
        try:
            self.logger.info("Fetching views from Team A")

            # Get all views (both in folders and standalone)
            response = self.teama_client.get(self.api_endpoint)
            views = response.get('views', [])

            self.logger.info(f"Found {len(views)} total views in Team A")

            # Separate views by type for debugging
            folder_views = [v for v in views if v.get('folderId')]
            standalone_views = [v for v in views if not v.get('folderId')]

            self.logger.info(f"  - {len(folder_views)} views in folders")
            self.logger.info(f"  - {len(standalone_views)} standalone views")

            return views

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch views from Team A: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching views from Team A: {e}")
            raise

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all views from Team B."""
        try:
            self.logger.info("Fetching views from Team B")

            # Get all views (both in folders and standalone)
            response = self.teamb_client.get(self.api_endpoint)
            views = response.get('views', [])

            self.logger.info(f"Found {len(views)} total views in Team B")

            # Separate views by type for debugging
            folder_views = [v for v in views if v.get('folderId')]
            standalone_views = [v for v in views if not v.get('folderId')]

            self.logger.info(f"  - {len(folder_views)} views in folders")
            self.logger.info(f"  - {len(standalone_views)} standalone views")

            return views

        except CoralogixAPIError as e:
            self.logger.error(f"Failed to fetch views from Team B: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error fetching views from Team B: {e}")
            raise

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create a view in Team B with exponential backoff and delay."""
        try:
            # Remove fields that shouldn't be included in creation
            create_data = self._prepare_view_for_creation(resource)
            view_name = create_data.get('name', 'Unknown')

            # Check if view has a folder assignment
            folder_info = ""
            if 'folderId' in create_data and create_data['folderId']:
                folder_id = create_data['folderId']
                folder_info = f" (folder: {folder_id})"
                self.logger.debug(f"View will be created in folder: {folder_id}")

            self.logger.info(f"Creating view in Team B: {view_name}{folder_info}")

            # Add delay before creation to avoid overwhelming the API
            self._add_creation_delay()

            # Create the view with exponential backoff
            def _create_operation():
                return self.teamb_client.post(self.api_endpoint, json_data=create_data)

            response = self._retry_with_exponential_backoff(_create_operation)

            self.log_resource_action("create", "view", view_name, True)
            return response

        except Exception as e:
            view_name = resource.get('name', 'Unknown')
            self._log_failed_view(resource, 'create', str(e))
            self.log_resource_action("create", "view", view_name, False, str(e))
            raise

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """Delete a view from Team B."""
        try:
            self.logger.info(f"Deleting view from Team B: {resource_id}")

            # Delete the view
            self.teamb_client.delete(f"{self.api_endpoint}/{resource_id}")

            self.log_resource_action("delete", "view", resource_id, True)
            return True

        except Exception as e:
            self.log_resource_action("delete", "view", resource_id, False, str(e))
            raise

    def _add_creation_delay(self):
        """Add a small delay before creation to avoid overwhelming the API."""
        delay_seconds = 0.5  # 500ms delay between creations
        time.sleep(delay_seconds)

    def _retry_with_exponential_backoff(self, operation, max_retries=3):
        """Retry an operation with exponential backoff."""
        last_exception = None
        base_backoff = 2.0  # Base backoff time in seconds

        for attempt in range(max_retries):
            try:
                result = operation()
                if attempt > 0:
                    self.logger.info(f"Operation succeeded on attempt {attempt + 1}")
                return result

            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    backoff_time = base_backoff * (2 ** attempt)
                    self.logger.warning(f"Operation failed on attempt {attempt + 1}/{max_retries}: {e}. Retrying in {backoff_time} seconds...")
                    time.sleep(backoff_time)
                else:
                    self.logger.error(f"Operation failed after {max_retries} attempts: {e}")

        raise last_exception

    def _prepare_view_for_creation(self, view: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare view data for creation by removing system fields and sanitizing."""
        # Fields to remove (similar to custom-dashboards sanitization)
        fields_to_remove = [
            'id', 'createdAt', 'updatedAt', 'createdBy', 'updatedBy',
            'created_at', 'updated_at', 'created_time', 'updated_time',
            'creation_time', 'update_time', 'version',
            'isCompactMode',  # This field causes API errors - not supported in create requests
            '_is_standalone', '_resource_type'  # Internal fields added by the service
        ]

        # Create sanitized copy
        sanitized_view = {}
        for key, value in view.items():
            if key not in fields_to_remove:
                sanitized_view[key] = value

        return sanitized_view

    def migrate(self) -> bool:
        """Perform the actual views migration using delete-and-recreate approach."""
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Step 1: Fetch folders from Team A
            self.logger.info("📁 Fetching view folders from Team A...")
            teama_folders = self.fetch_view_folders_from_teama()

            # Step 2: Fetch views from Team A
            self.logger.info("📄 Fetching views from Team A...")
            teama_views = self.fetch_resources_from_teama()

            # Step 3: Fetch folders from Team B (for deletion)
            self.logger.info("📁 Fetching view folders from Team B...")
            teamb_folders = self.fetch_view_folders_from_teamb()

            # Step 4: Fetch views from Team B (for deletion)
            self.logger.info("📄 Fetching views from Team B...")
            teamb_views = self.fetch_resources_from_teamb()

            # Step 5: Delete all existing views from Team B
            self.logger.info("🗑️ Deleting existing views from Team B...")
            deleted_views = 0
            for view in teamb_views:
                view_id = view.get('id')
                if view_id:
                    try:
                        self.delete_resource_from_teamb(view_id)
                        deleted_views += 1
                    except Exception as e:
                        self.logger.warning(f"Failed to delete view {view_id}: {e}")

            # Step 6: Delete all existing folders from Team B
            self.logger.info("🗑️ Deleting existing folders from Team B...")
            deleted_folders = 0
            for folder in teamb_folders:
                folder_id = folder.get('id')
                if folder_id:
                    try:
                        self.teamb_client.delete(f"{self.folders_api_endpoint}/{folder_id}")
                        deleted_folders += 1
                    except Exception as e:
                        self.logger.warning(f"Failed to delete folder {folder_id}: {e}")

            self.logger.info(f"🗑️ Deleted {deleted_views} views and {deleted_folders} folders from Team B")

            # Step 7: Create folders in Team B first (needed for views with folders)
            self.logger.info("📁 Creating view folders in Team B...")
            folder_id_mapping = {}  # Map Team A folder IDs to Team B folder IDs
            created_folders = 0
            failed_folders = 0

            for folder in teama_folders:
                try:
                    # Prepare folder data
                    folder_data = {
                        'name': folder['name']
                    }
                    if 'description' in folder and folder['description']:
                        folder_data['description'] = folder['description']

                    # Create folder
                    response = self.teamb_client.post(self.folders_api_endpoint, json_data=folder_data)

                    # Debug: Log the actual response structure (temporarily using info level)
                    self.logger.info(f"🔍 DEBUG - Folder creation response for '{folder['name']}': {response}")

                    # Store mapping - try different possible response structures
                    teama_folder_id = folder.get('id')
                    teamb_folder_id = None

                    # Try different response structures based on API patterns
                    if isinstance(response, dict):
                        # Try folderId field first (most likely based on custom-dashboards pattern)
                        teamb_folder_id = response.get('folderId')

                        # Try direct id field
                        if not teamb_folder_id:
                            teamb_folder_id = response.get('id')

                        # Try nested folder structure
                        if not teamb_folder_id and 'folder' in response:
                            folder_obj = response['folder']
                            if isinstance(folder_obj, dict):
                                teamb_folder_id = folder_obj.get('id') or folder_obj.get('folderId')

                        # Try viewFolder structure (similar to other APIs)
                        if not teamb_folder_id and 'viewFolder' in response:
                            view_folder_obj = response['viewFolder']
                            if isinstance(view_folder_obj, dict):
                                teamb_folder_id = view_folder_obj.get('id') or view_folder_obj.get('folderId')

                        # Try folders array (if API returns array with single item)
                        if not teamb_folder_id and 'folders' in response:
                            folders_array = response['folders']
                            if isinstance(folders_array, list) and len(folders_array) > 0:
                                first_folder = folders_array[0]
                                if isinstance(first_folder, dict):
                                    teamb_folder_id = first_folder.get('id') or first_folder.get('folderId')

                    if teama_folder_id and teamb_folder_id:
                        folder_id_mapping[teama_folder_id] = teamb_folder_id
                        created_folders += 1
                        self.logger.info(f"✅ Created folder: {folder['name']} (ID: {teamb_folder_id})")
                    else:
                        failed_folders += 1
                        self.logger.error(f"❌ Failed to get folder ID for: {folder['name']} - Response: {response}")

                except Exception as e:
                    failed_folders += 1
                    self.logger.error(f"❌ Failed to create folder {folder.get('name', 'Unknown')}: {e}")

            # Step 8: Separate views by type
            folder_views = [v for v in teama_views if v.get('folderId')]
            standalone_views = [v for v in teama_views if not v.get('folderId')]

            self.logger.info(f"📄 Creating {len(folder_views)} views in folders...")
            created_folder_views = 0
            failed_folder_views = 0

            # Create views that belong to folders
            for view in folder_views:
                try:
                    # Prepare view data
                    view_data = self._prepare_view_for_creation(view)

                    # Map folder ID
                    teama_folder_id = view['folderId']
                    if teama_folder_id in folder_id_mapping:
                        view_data['folderId'] = folder_id_mapping[teama_folder_id]

                        # Create view
                        response = self.create_resource_in_teamb(view_data)
                        created_folder_views += 1
                        self.logger.debug(f"✅ Created folder view: {view.get('name', 'Unknown')}")
                    else:
                        failed_folder_views += 1
                        self.logger.error(f"❌ No folder mapping found for view {view.get('name', 'Unknown')}")

                except Exception as e:
                    failed_folder_views += 1
                    self.logger.error(f"❌ Failed to create folder view {view.get('name', 'Unknown')}: {e}")

            # Step 9: Create standalone views
            self.logger.info(f"📄 Creating {len(standalone_views)} standalone views...")
            created_standalone_views = 0
            failed_standalone_views = 0

            for view in standalone_views:
                try:
                    # Prepare view data (ensure no folderId)
                    view_data = self._prepare_view_for_creation(view)
                    view_data.pop('folderId', None)  # Remove any folderId for standalone views

                    # Create standalone view
                    response = self.create_resource_in_teamb(view_data)
                    created_standalone_views += 1
                    self.logger.debug(f"✅ Created standalone view: {view.get('name', 'Unknown')}")

                except Exception as e:
                    failed_standalone_views += 1
                    self.logger.error(f"❌ Failed to create standalone view {view.get('name', 'Unknown')}: {e}")

            # Calculate totals
            created_views = created_folder_views + created_standalone_views
            failed_views = failed_folder_views + failed_standalone_views

            # Display results in tabular format
            self._display_migration_results_table({
                'folders': {'total': len(teama_folders), 'created': created_folders, 'failed': failed_folders},
                'folder_views': {'total': len(folder_views), 'created': created_folder_views, 'failed': failed_folder_views},
                'standalone_views': {'total': len(standalone_views), 'created': created_standalone_views, 'failed': failed_standalone_views},
                'deleted_folders': deleted_folders,
                'deleted_views': deleted_views
            })

            # Calculate success
            total_created = created_folders + created_views
            total_failed = failed_folders + failed_views
            success = total_failed == 0

            self.log_migration_complete(self.service_name, success, total_created, total_failed)

            if success:
                self.logger.info("🎉 Views migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ Views migration completed with {total_failed} failures")

            return success

        except Exception as e:
            self.logger.error(f"Views migration failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False


    def dry_run(self) -> bool:
        """Perform a dry run to show what would be migrated."""
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch resources from both teams
            self.logger.info("📁 Fetching view folders from Team A...")
            teama_folders = self.fetch_view_folders_from_teama()

            self.logger.info("📄 Fetching views from Team A...")
            teama_views = self.fetch_resources_from_teama()

            self.logger.info("📁 Fetching view folders from Team B...")
            teamb_folders = self.fetch_view_folders_from_teamb()

            self.logger.info("📄 Fetching views from Team B...")
            teamb_views = self.fetch_resources_from_teamb()

            # Display dry run results
            self.logger.info("📋 DRY RUN RESULTS - Views Migration Plan (Delete & Recreate):")
            self.logger.info("=" * 80)

            self.logger.info("🗑️ DELETION PHASE:")
            self.logger.info(f"  📄 Will delete: {len(teamb_views)} existing views from Team B")
            self.logger.info(f"  📁 Will delete: {len(teamb_folders)} existing folders from Team B")

            self.logger.info("")
            self.logger.info("✅ CREATION PHASE:")
            self.logger.info(f"  📁 Will create: {len(teama_folders)} folders from Team A")
            if teama_folders and len(teama_folders) <= 10:
                for folder in teama_folders:
                    self.logger.info(f"    - {folder.get('name', 'Unknown')}")
            elif teama_folders:
                sample_folders = teama_folders[:5]
                for folder in sample_folders:
                    self.logger.info(f"    - {folder.get('name', 'Unknown')}")
                self.logger.info(f"    ... and {len(teama_folders) - 5} more")

            # Separate views by type for dry run display
            folder_views = [v for v in teama_views if v.get('folderId')]
            standalone_views = [v for v in teama_views if not v.get('folderId')]

            self.logger.info(f"  📄 Will create: {len(folder_views)} views in folders")
            if folder_views and len(folder_views) <= 10:
                for view in folder_views:
                    self.logger.info(f"    - {view.get('name', 'Unknown')} (folder: {view.get('folderId')})")
            elif folder_views:
                sample_views = folder_views[:5]
                for view in sample_views:
                    self.logger.info(f"    - {view.get('name', 'Unknown')} (folder: {view.get('folderId')})")
                self.logger.info(f"    ... and {len(folder_views) - 5} more")

            self.logger.info(f"  📄 Will create: {len(standalone_views)} standalone views")
            if standalone_views and len(standalone_views) <= 10:
                for view in standalone_views:
                    self.logger.info(f"    - {view.get('name', 'Unknown')} (standalone)")
            elif standalone_views:
                sample_views = standalone_views[:5]
                for view in sample_views:
                    self.logger.info(f"    - {view.get('name', 'Unknown')} (standalone)")
                self.logger.info(f"    ... and {len(standalone_views) - 5} more")

            # Summary
            total_to_delete = len(teamb_views) + len(teamb_folders)
            total_to_create = len(teama_folders) + len(folder_views) + len(standalone_views)
            total_operations = total_to_delete + total_to_create

            self.logger.info("=" * 80)
            self.logger.info(f"📊 SUMMARY: {total_operations} total operations planned")
            self.logger.info(f"  🗑️ Delete: {len(teamb_views)} views + {len(teamb_folders)} folders = {total_to_delete} deletions")
            self.logger.info(f"  ✅ Create: {len(teama_folders)} folders + {len(folder_views)} folder views + {len(standalone_views)} standalone views = {total_to_create} creations")

            if total_to_create == 0:
                self.logger.info("⚠️ No resources to migrate from Team A!")
            else:
                self.logger.info("🚀 Run without --dry-run to execute this migration plan")
                self.logger.info("⚠️ This will completely replace Team B views and folders with Team A's")

            self.log_migration_complete(self.service_name, True, total_operations, 0)

            # Return data for tabular display
            return {
                'teama_folders': teama_folders,
                'teama_views': teama_views,
                'teamb_folders': teamb_folders,
                'teamb_views': teamb_views,
                'total_operations': total_operations
            }

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return {
                'teama_folders': [],
                'teama_views': [],
                'teamb_folders': [],
                'teamb_views': [],
                'total_operations': 0,
                'error': str(e)
            }

    def _display_migration_results_table(self, migration_stats: Dict):
        """Display migration results in a nice tabular format."""
        # Use print() to bypass JSON logging and show clean table
        print("\n" + "=" * 80)
        print("🎉 VIEWS & FOLDERS MIGRATION RESULTS")
        print("=" * 80)

        # Prepare migration results table
        migration_table_data = []

        # Add folders
        if migration_stats['folders']['total'] > 0:
            folder_success_rate = (migration_stats['folders']['created'] / migration_stats['folders']['total'] * 100)
            migration_table_data.append({
                'resource_type': 'View Folders',
                'total': migration_stats['folders']['total'],
                'created': migration_stats['folders']['created'],
                'failed': migration_stats['folders']['failed'],
                'success_rate': f"{folder_success_rate:.1f}%"
            })

        # Add folder views
        if migration_stats.get('folder_views', {}).get('total', 0) > 0:
            folder_view_success_rate = (migration_stats['folder_views']['created'] / migration_stats['folder_views']['total'] * 100)
            migration_table_data.append({
                'resource_type': 'Views in Folders',
                'total': migration_stats['folder_views']['total'],
                'created': migration_stats['folder_views']['created'],
                'failed': migration_stats['folder_views']['failed'],
                'success_rate': f"{folder_view_success_rate:.1f}%"
            })

        # Add standalone views
        if migration_stats.get('standalone_views', {}).get('total', 0) > 0:
            standalone_success_rate = (migration_stats['standalone_views']['created'] / migration_stats['standalone_views']['total'] * 100)
            migration_table_data.append({
                'resource_type': 'Standalone Views',
                'total': migration_stats['standalone_views']['total'],
                'created': migration_stats['standalone_views']['created'],
                'failed': migration_stats['standalone_views']['failed'],
                'success_rate': f"{standalone_success_rate:.1f}%"
            })

        # Display migration results table
        if migration_table_data:
            self._display_table(migration_table_data)

        # Display overall summary
        total_created = (migration_stats['folders']['created'] +
                        migration_stats.get('folder_views', {}).get('created', 0) +
                        migration_stats.get('standalone_views', {}).get('created', 0))
        total_failed = (migration_stats['folders']['failed'] +
                       migration_stats.get('folder_views', {}).get('failed', 0) +
                       migration_stats.get('standalone_views', {}).get('failed', 0))
        total_processed = total_created + total_failed
        overall_success_rate = (total_created / total_processed * 100) if total_processed > 0 else 100

        print("")
        print("📊 OVERALL MIGRATION SUMMARY")
        print("─" * 40)
        print(f"{'Total Resources Processed:':<25} {total_processed:>10}")
        print(f"{'Successfully Created:':<25} {total_created:>10}")
        print(f"{'Failed Operations:':<25} {total_failed:>10}")
        print(f"{'Resources Deleted:':<25} {migration_stats['deleted_folders'] + migration_stats['deleted_views']:>10}")
        print(f"{'Overall Success Rate:':<25} {overall_success_rate:>9.1f}%")
        print("=" * 80)

    def display_dry_run_results(self, results: Dict[str, Any]):
        """
        Display formatted dry run results for views migration.

        Args:
            results: Dry run results dictionary
        """
        print("\n" + "=" * 70)
        print("DRY RUN RESULTS - VIEWS & FOLDERS (Delete All + Recreate All Strategy)")
        print("=" * 70)

        # Display counts
        teama_folders = results.get('teama_folders', [])
        teama_views = results.get('teama_views', [])
        teamb_folders = results.get('teamb_folders', [])
        teamb_views = results.get('teamb_views', [])

        print(f"📊 Team A Resources:")
        print(f"   📁 Folders: {len(teama_folders)}")
        print(f"   📄 Views: {len(teama_views)}")
        print(f"📊 Team B Resources:")
        print(f"   📁 Folders: {len(teamb_folders)}")
        print(f"   📄 Views: {len(teamb_views)}")
        print("")

        # Show planned operations
        total_operations = len(teamb_folders) + len(teamb_views) + len(teama_folders) + len(teama_views)

        print("🎯 PLANNED OPERATIONS:")
        print(f"  Step 1: Delete ALL {len(teamb_views)} views from Team B")
        print(f"  Step 2: Delete ALL {len(teamb_folders)} folders from Team B")
        print(f"  Step 3: Create ALL {len(teama_folders)} folders from Team A")
        print(f"  Step 4: Create ALL {len(teama_views)} views from Team A")
        print(f"  Total operations: {total_operations}")
        print("")

        # Show sample resources
        if teamb_views:
            print(f"🗑️ Sample views to be DELETED from Team B (showing first 5):")
            for i, view in enumerate(teamb_views[:5]):
                view_name = view.get('name', 'Unknown')
                view_id = view.get('id', 'N/A')
                print(f"  - {view_name} (ID: {view_id})")
            if len(teamb_views) > 5:
                print(f"  ... and {len(teamb_views) - 5} more views")
            print("")

        if teama_views:
            print(f"✨ Sample views to be CREATED in Team B (showing first 5):")
            for i, view in enumerate(teama_views[:5]):
                view_name = view.get('name', 'Unknown')
                print(f"  - {view_name}")
            if len(teama_views) > 5:
                print(f"  ... and {len(teama_views) - 5} more views")
            print("")

        print("🎯 EXPECTED RESULT:")
        print(f"  Team B will have {len(teama_folders)} folders and {len(teama_views)} views (same as Team A)")
        print("=" * 70)

    def _display_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""
        # Table headers
        headers = [
            "Resource Type",
            "Total",
            "Created",
            "Failed",
            "Success Rate"
        ]

        # Calculate column widths
        col_widths = []
        for i, header in enumerate(headers):
            max_width = len(header)
            for row in table_data:
                if i == 0:
                    max_width = max(max_width, len(row['resource_type']))
                elif i == 1:
                    max_width = max(max_width, len(str(row['total'])))
                elif i == 2:
                    max_width = max(max_width, len(str(row['created'])))
                elif i == 3:
                    max_width = max(max_width, len(str(row['failed'])))
                elif i == 4:
                    max_width = max(max_width, len(row['success_rate']))
            col_widths.append(max_width)

        # Create table borders
        top_border = "┌"
        header_border = "├"
        bottom_border = "└"

        for i, width in enumerate(col_widths):
            if i > 0:
                top_border += "┬"
                header_border += "┼"
                bottom_border += "┴"
            top_border += "─" * (width + 2)
            header_border += "─" * (width + 2)
            bottom_border += "─" * (width + 2)

        top_border += "┐"
        header_border += "┤"
        bottom_border += "┘"

        # Use print() to bypass JSON logging and show clean table
        print(top_border)

        # Print headers
        header_row = "│"
        for i, header in enumerate(headers):
            if i == 0:  # Resource type - left aligned
                header_row += f" {header:<{col_widths[i]}} │"
            else:  # Numbers and percentages - right aligned
                header_row += f" {header:>{col_widths[i]}} │"

        print(header_row)
        print(header_border)

        # Print data rows
        for row in table_data:
            data_row = "│"
            values = [
                row['resource_type'],
                str(row['total']),
                str(row['created']),
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

    def _log_failed_view(self, view: Dict[str, Any], operation: str, error: str):
        """Log a failed view operation."""
        failed_view_data = {
            'name': view.get('name', 'Unknown'),
            'operation': operation,
            'error': error,
            'view_data': view
        }

        # Save to failed views log file
        try:
            import json
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y-%m-%d-%H")
            failed_log_file = self.failed_views_dir / f"failed-views-{timestamp}.json"

            # Load existing failed views or create new list
            failed_views = []
            if failed_log_file.exists():
                with open(failed_log_file, 'r') as f:
                    failed_views = json.load(f)

            failed_views.append(failed_view_data)

            # Save updated failed views
            with open(failed_log_file, 'w') as f:
                json.dump(failed_views, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to log failed view operation: {e}")


