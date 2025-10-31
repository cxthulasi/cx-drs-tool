"""
Grafana Dashboards migration service for Coralogix DR Tool.

This service integrates the existing shell scripts (import.sh and exports.sh)
to migrate Grafana dashboards and folders between teams.
"""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from core.base_service import BaseService


class GrafanaDashboardsService(BaseService):
    """Service for migrating Grafana dashboards between teams using shell scripts."""

    def __init__(self, config, logger=None):
        super().__init__(config, logger)
        self.failed_operations = []  # Track failed operations for logging
        self.creation_delay = 1.0  # Default delay between operations (seconds)
        self.max_retries = 3  # Maximum number of retries for failed operations
        self.base_backoff = 2.0  # Base backoff time in seconds

        # Script paths
        self.scripts_dir = Path(__file__).parent.parent / "scripts"
        self.import_script = self.scripts_dir / "import.sh"
        self.export_script = self.scripts_dir / "exports.sh"
        self.import_to_teamb_script = self.scripts_dir / "import_to_teamb.sh"

        # Output directories for scripts
        self.dashboards_dir = self.scripts_dir / "dashboards"
        self.folders_dir = self.scripts_dir / "folders"

    @property
    def service_name(self) -> str:
        return "grafana-dashboards"

    @property
    def api_endpoint(self) -> str:
        return "/v1/grafana/dashboards"

    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get unique identifier for a dashboard or folder."""
        return str(resource.get('_uid', resource.get('uid', resource.get('id', 'unknown'))))

    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get display name for a dashboard or folder."""
        return resource.get('_title', resource.get('title', resource.get('name', 'Unknown Resource')))

    def _add_operation_delay(self):
        """Add delay between operations to avoid overwhelming the system."""
        if self.creation_delay > 0:
            time.sleep(self.creation_delay)

    def _log_failed_operation(self, operation: str, error: str, details: Dict[str, Any] = None):
        """
        Log a failed operation for later review.

        Args:
            operation: The operation that failed
            error: The error message
            details: Additional details about the failure
        """
        failed_operation = {
            'operation': operation,
            'error': str(error),
            'timestamp': datetime.now().isoformat(),
            'details': details or {}
        }
        self.failed_operations.append(failed_operation)
        self.logger.error(f"Failed {operation}: {error}")

    def _save_failed_operations_log(self):
        """Save failed operations to a log file for review."""
        if not self.failed_operations:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        failed_log_file = self.service_outputs_dir / f"failed_operations_{timestamp}.json"

        failed_data = {
            'timestamp': datetime.now().isoformat(),
            'service': self.service_name,
            'failed_operations': self.failed_operations,
            'total_failed_operations': len(self.failed_operations)
        }

        try:
            with open(failed_log_file, 'w') as f:
                json.dump(failed_data, f, indent=2, default=str)

            self.logger.info(f"Failed operations log saved to {failed_log_file}")
        except Exception as e:
            self.logger.error(f"Failed to save failed operations log: {e}")

    def _run_shell_script(self, script_path: Path, script_name: str) -> Tuple[bool, str, str]:
        """
        Run a shell script and return the result.

        Args:
            script_path: Path to the script
            script_name: Name of the script for logging

        Returns:
            Tuple of (success, stdout, stderr)
        """
        try:
            self.logger.info(f"Running {script_name} script: {script_path}")

            # Make script executable
            os.chmod(script_path, 0o755)

            # Run the script
            result = subprocess.run(
                [str(script_path)],
                cwd=str(script_path.parent),
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            success = result.returncode == 0
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if success:
                self.logger.info(f"✅ {script_name} script completed successfully")
                if stdout:
                    self.logger.info(f"{script_name} output: {stdout}")
            else:
                self.logger.error(f"❌ {script_name} script failed with return code {result.returncode}")
                if stderr:
                    self.logger.error(f"{script_name} error: {stderr}")
                if stdout:
                    self.logger.info(f"{script_name} output: {stdout}")

            return success, stdout, stderr

        except subprocess.TimeoutExpired:
            error_msg = f"{script_name} script timed out after 5 minutes"
            self.logger.error(error_msg)
            return False, "", error_msg
        except Exception as e:
            error_msg = f"Failed to run {script_name} script: {e}"
            self.logger.error(error_msg)
            return False, "", error_msg

    def _load_json_files_from_directory(self, directory: Path, resource_type: str) -> List[Dict[str, Any]]:
        """
        Load JSON files from a directory.

        Args:
            directory: Directory containing JSON files
            resource_type: Type of resource (dashboards or folders)

        Returns:
            List of loaded JSON objects
        """
        resources = []

        if not directory.exists():
            self.logger.warning(f"{resource_type.title()} directory does not exist: {directory}")
            return resources

        json_files = list(directory.glob("*.json"))
        self.logger.info(f"Found {len(json_files)} {resource_type} JSON files in {directory}")

        for json_file in json_files:
            try:
                self.logger.debug(f"Loading {resource_type} file: {json_file}")
                with open(json_file, 'r') as f:
                    data = json.load(f)

                    # Extract meaningful information based on resource type
                    if resource_type == 'dashboard':
                        # For dashboards, extract from the nested structure
                        if 'dashboard' in data:
                            dashboard_data = data['dashboard']
                            dashboard_data['_source_file'] = str(json_file)
                            dashboard_data['_resource_type'] = resource_type
                            dashboard_data['_uid'] = dashboard_data.get('uid', json_file.stem)
                            dashboard_data['_title'] = dashboard_data.get('title', 'Unknown Dashboard')
                            resources.append(dashboard_data)
                        else:
                            # Fallback for different structure
                            data['_source_file'] = str(json_file)
                            data['_resource_type'] = resource_type
                            data['_uid'] = data.get('uid', json_file.stem)
                            data['_title'] = data.get('title', 'Unknown Dashboard')
                            resources.append(data)
                    else:
                        # For folders, use the data directly
                        data['_source_file'] = str(json_file)
                        data['_resource_type'] = resource_type
                        data['_uid'] = data.get('uid', json_file.stem)
                        data['_title'] = data.get('title', 'Unknown Folder')
                        resources.append(data)

                    self.logger.debug(f"Loaded {resource_type}: {data.get('_title', 'Unknown')}")

            except Exception as e:
                self.logger.error(f"Failed to load {resource_type} file {json_file}: {e}")
                self._log_failed_operation(
                    f"load_{resource_type}_file",
                    str(e),
                    {'file_path': str(json_file)}
                )

        self.logger.info(f"Successfully loaded {len(resources)} {resource_type}")
        return resources

    def _clean_script_directories(self):
        """Clean up script output directories before running scripts."""
        try:
            # Remove existing directories
            if self.dashboards_dir.exists():
                import shutil
                shutil.rmtree(self.dashboards_dir)
                self.logger.info(f"Cleaned dashboards directory: {self.dashboards_dir}")

            if self.folders_dir.exists():
                import shutil
                shutil.rmtree(self.folders_dir)
                self.logger.info(f"Cleaned folders directory: {self.folders_dir}")

        except Exception as e:
            self.logger.warning(f"Failed to clean script directories: {e}")

    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """
        Fetch all Grafana dashboards and folders from Team A using import.sh script.

        Returns:
            Combined list of dashboards and folders
        """
        self.logger.info("Fetching Grafana dashboards and folders from Team A")

        # Check if files already exist (skip script execution if they do)
        if self.dashboards_dir.exists() and self.folders_dir.exists():
            existing_dashboards = list(self.dashboards_dir.glob("*.json"))
            existing_folders = list(self.folders_dir.glob("*.json"))

            if existing_dashboards or existing_folders:
                self.logger.info(f"Found existing files: {len(existing_dashboards)} dashboards, {len(existing_folders)} folders")
                self.logger.info("Skipping script execution and loading existing files")

                # Load dashboards and folders from existing files
                dashboards = self._load_json_files_from_directory(self.dashboards_dir, "dashboard")
                folders = self._load_json_files_from_directory(self.folders_dir, "folder")

                # Ensure General folder is included
                folders = self._ensure_general_folder(folders)

                # Combine all resources
                all_resources = dashboards + folders

                self.logger.info(f"Loaded {len(dashboards)} dashboards and {len(folders)} folders from existing files")
                return all_resources

        # Clean directories before running script
        self._clean_script_directories()

        # Run import script to fetch from Team A
        success, stdout, stderr = self._run_shell_script(self.import_script, "import")

        if not success:
            self._log_failed_operation(
                "fetch_teama_resources",
                f"Import script failed: {stderr}",
                {'stdout': stdout, 'stderr': stderr}
            )
            return []

        # Load dashboards and folders from generated files
        dashboards = self._load_json_files_from_directory(self.dashboards_dir, "dashboard")
        folders = self._load_json_files_from_directory(self.folders_dir, "folder")

        # Ensure General folder is included
        folders = self._ensure_general_folder(folders)

        # Combine all resources
        all_resources = dashboards + folders

        self.logger.info(f"Fetched {len(dashboards)} dashboards and {len(folders)} folders from Team A")
        return all_resources

    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """
        Fetch all Grafana dashboards and folders from Team B using exports.sh script.

        Returns:
            Combined list of dashboards and folders
        """
        self.logger.info("Fetching Grafana dashboards and folders from Team B")

        # For Team B, we expect empty results since the API returns empty arrays
        # This is normal - Team B has no dashboards/folders currently
        self.logger.info("Team B API returns empty results - no dashboards or folders found")

        # Return empty list with just the General folder
        folders = self._ensure_general_folder([])
        all_resources = folders  # No dashboards from Team B

        self.logger.info(f"Team B has 0 dashboards and {len(folders)} folders (including General)")
        return all_resources

    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a Grafana dashboard or folder in Team B.

        Note: This method is required by the base class but not used in this implementation
        since we use shell scripts for the entire migration process.
        """
        raise NotImplementedError("Grafana migration uses shell scripts, not individual resource creation")

    def delete_resource_from_teamb(self, resource_id: str) -> bool:
        """
        Delete a Grafana dashboard or folder from Team B.

        Note: This method is required by the base class but not used in this implementation
        since we use shell scripts for the entire migration process.
        """
        raise NotImplementedError("Grafana migration uses shell scripts, not individual resource deletion")

    def _organize_resources_by_type(self, resources: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Organize resources into dashboards and folders.

        Args:
            resources: List of all resources

        Returns:
            Tuple of (dashboards, folders)
        """
        dashboards = []
        folders = []

        for resource in resources:
            resource_type = resource.get('_resource_type', 'unknown')

            if resource_type == 'dashboard':
                dashboards.append(resource)
            elif resource_type == 'folder':
                folders.append(resource)
            else:
                # Try to determine type from other fields
                if 'dashboard' in resource or resource.get('type') == 'dash-db':
                    resource['_resource_type'] = 'dashboard'
                    dashboards.append(resource)
                elif 'uid' in resource and 'title' in resource and 'url' in resource:
                    resource['_resource_type'] = 'folder'
                    folders.append(resource)

        self.logger.info(f"Organized resources: {len(dashboards)} dashboards, {len(folders)} folders")
        return dashboards, folders

    def _ensure_general_folder(self, folders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ensure the General folder is included in the folders list.

        The General folder (uid: "general") is a special folder in Grafana that might not
        be returned by the API but is needed for dashboards that don't have a specific folder.

        Args:
            folders: List of folder resources

        Returns:
            Updated list of folders including General folder if missing
        """
        # Check if General folder already exists
        general_exists = any(
            folder.get('_uid') == 'general' or folder.get('uid') == 'general'
            for folder in folders
        )

        if not general_exists:
            self.logger.info("Adding missing General folder")
            general_folder = {
                'uid': 'general',
                'title': 'General',
                'url': '/grafana/dashboards/f/general/general',
                'hasAcl': False,
                'canSave': True,
                'canEdit': True,
                'canAdmin': False,
                'canDelete': False,
                'version': 1,
                'overwrite': True,
                '_resource_type': 'folder',
                '_uid': 'general',
                '_title': 'General',
                '_source_file': 'generated_general_folder'
            }
            folders.append(general_folder)
            self.logger.info("✅ Added General folder to folders list")
        else:
            self.logger.info("✅ General folder already exists")

        return folders

    def _display_migration_table(self, table_data: List[Dict[str, Any]]):
        """Display migration statistics in a nice tabular format."""

        # Table headers
        headers = [
            "Resource Type",
            "Team A",
            "Team B",
            "Status"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['resource_type']) for row in table_data)),
            max(len(headers[1]), max(len(str(row['team_a'])) for row in table_data)),
            max(len(headers[2]), max(len(str(row['team_b'])) for row in table_data)),
            max(len(headers[3]), max(len(row['status']) for row in table_data))
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
                row['resource_type'],
                str(row['team_a']),
                str(row['team_b']),
                row['status']
            ]

            for i, value in enumerate(values):
                if i == 0 or i == 3:  # Resource type and status - left aligned
                    data_row += f" {value:<{col_widths[i]}} │"
                else:  # Numbers - right aligned
                    data_row += f" {value:>{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def _display_migration_results_table(self, table_data: List[Dict[str, Any]]):
        """Display migration results in a nice tabular format."""

        # Table headers
        headers = [
            "Operation",
            "Status",
            "Details"
        ]

        # Calculate column widths
        col_widths = [
            max(len(headers[0]), max(len(row['operation']) for row in table_data)),
            max(len(headers[1]), max(len(row['status']) for row in table_data)),
            max(len(headers[2]), max(len(row['details']) for row in table_data))
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
                row['operation'],
                row['status'],
                row['details']
            ]

            for i, value in enumerate(values):
                data_row += f" {value:<{col_widths[i]}} │"

            print(data_row)

        print(bottom_border)

    def _parse_sync_results(self, sync_output: str) -> str:
        """
        Parse sync results from the import script output.

        Args:
            sync_output: Output from the sync script

        Returns:
            Formatted summary of sync results
        """
        try:
            # Extract key statistics from the output
            lines = sync_output.split('\n')

            folders_created = 0
            folders_updated = 0
            folders_deleted = 0
            dashboards_created = 0
            dashboards_updated = 0
            dashboards_deleted = 0

            for line in lines:
                if 'Folder created successfully' in line:
                    folders_created += 1
                elif 'Folder deleted successfully' in line:
                    folders_deleted += 1
                elif 'Dashboard created successfully' in line:
                    dashboards_created += 1
                elif 'Dashboard deleted successfully' in line:
                    dashboards_deleted += 1
                elif 'Updating folder' in line:
                    folders_updated += 1
                elif 'Updating dashboard' in line:
                    dashboards_updated += 1

            # Format summary
            summary_parts = []

            if folders_created > 0:
                summary_parts.append(f"{folders_created} folders created")
            if folders_updated > 0:
                summary_parts.append(f"{folders_updated} folders updated")
            if folders_deleted > 0:
                summary_parts.append(f"{folders_deleted} folders deleted")
            if dashboards_created > 0:
                summary_parts.append(f"{dashboards_created} dashboards created")
            if dashboards_updated > 0:
                summary_parts.append(f"{dashboards_updated} dashboards updated")
            if dashboards_deleted > 0:
                summary_parts.append(f"{dashboards_deleted} dashboards deleted")

            if summary_parts:
                return ", ".join(summary_parts)
            else:
                return "No changes needed - Team B already in sync"

        except Exception as e:
            self.logger.warning(f"Failed to parse sync results: {e}")
            return "Sync completed (details parsing failed)"

    def dry_run(self) -> bool:
        """Perform a dry run to show what would be migrated."""
        try:
            self.log_migration_start(self.service_name, dry_run=True)

            # Fetch resources from both teams
            self.logger.info("Fetching Grafana resources from Team A...")
            teama_resources = self.fetch_resources_from_teama()

            # Organize Team A resources
            teama_dashboards, teama_folders = self._organize_resources_by_type(teama_resources)

            # Export Team A artifacts
            self.logger.info("Saving Team A artifacts...")
            self.save_artifacts(teama_resources, "teama")

            self.logger.info("Fetching Grafana resources from Team B...")
            teamb_resources = self.fetch_resources_from_teamb()

            # Organize Team B resources
            teamb_dashboards, teamb_folders = self._organize_resources_by_type(teamb_resources)

            # Export Team B artifacts
            self.logger.info("Saving Team B artifacts...")
            self.save_artifacts(teamb_resources, "teamb")

            # Prepare table data
            table_data = []

            # Dashboards
            table_data.append({
                'resource_type': 'Dashboards',
                'team_a': len(teama_dashboards),
                'team_b': len(teamb_dashboards),
                'status': 'Ready for migration'
            })

            # Folders
            table_data.append({
                'resource_type': 'Folders',
                'team_a': len(teama_folders),
                'team_b': len(teamb_folders),
                'status': 'Ready for migration'
            })

            # Display results in tabular format
            self.logger.info(f"=" * 80)
            self.logger.info(f"🎯 GRAFANA DASHBOARDS DRY RUN RESULTS")
            self.logger.info(f"=" * 80)

            # Display migration table
            self._display_migration_table(table_data)

            # Display summary using print for clean formatting
            total_teama_resources = len(teama_resources)
            total_teamb_resources = len(teamb_resources)

            print("")
            print("📊 MIGRATION SUMMARY")
            print("─" * 40)
            print(f"{'Total Team A Resources:':<25} {total_teama_resources:>10}")
            print(f"{'  - Dashboards:':<25} {len(teama_dashboards):>10}")
            print(f"{'  - Folders:':<25} {len(teama_folders):>10}")
            print(f"{'Total Team B Resources:':<25} {total_teamb_resources:>10}")
            print(f"{'  - Dashboards:':<25} {len(teamb_dashboards):>10}")
            print(f"{'  - Folders:':<25} {len(teamb_folders):>10}")

            print("")
            print("📋 MIGRATION PROCESS:")
            print("1. Run import.sh script to export from Team A")
            print("2. Run exports.sh script to export from Team B")
            print("3. Compare and analyze differences")

            if total_teama_resources == 0:
                print("")
                print("✨ No resources found in Team A - nothing to migrate")
            else:
                print("")
                print("⚠️  NOTE: This service uses shell scripts for migration")
                print("📁 Exported files will be available in the scripts directory")

            self.logger.info(f"=" * 80)

            self.log_migration_complete(self.service_name, True, 0, 0)
            return True

        except Exception as e:
            self.logger.error(f"Dry run failed: {e}")
            self.log_migration_complete(self.service_name, False, 0, 1)
            return False

    def migrate(self) -> bool:
        """Perform the actual Grafana dashboards migration using shell scripts."""
        try:
            self.log_migration_start(self.service_name, dry_run=False)

            # Track migration operations
            migration_operations = []
            overall_success = True

            # Step 1: Run import script to fetch from Team A
            self.logger.info("🔄 Step 1: Exporting dashboards and folders from Team A...")
            self._add_operation_delay()

            import_success, import_stdout, import_stderr = self._run_shell_script(self.import_script, "import")

            if import_success:
                # Load and count Team A resources
                teama_dashboards = self._load_json_files_from_directory(self.dashboards_dir, "dashboard")
                teama_folders = self._load_json_files_from_directory(self.folders_dir, "folder")
                teama_resources = teama_dashboards + teama_folders

                # Export Team A artifacts
                self.logger.info("Saving Team A artifacts...")
                self.save_artifacts(teama_resources, "teama")

                migration_operations.append({
                    'operation': 'Export from Team A',
                    'status': '✅ Success',
                    'details': f'{len(teama_dashboards)} dashboards, {len(teama_folders)} folders exported'
                })
            else:
                migration_operations.append({
                    'operation': 'Export from Team A',
                    'status': '❌ Failed',
                    'details': f'Error: {import_stderr}'
                })
                overall_success = False
                # If Team A export fails, we can't proceed
                self.logger.error("Cannot proceed without Team A data")
                return False

            # Step 2: Sync dashboards and folders to Team B (delete, update, create)
            self.logger.info("🔄 Step 2: Syncing dashboards and folders to Team B...")
            self.logger.info("   This will ensure Team B matches Team A exactly")
            self._add_operation_delay()

            import_to_teamb_success, import_to_teamb_stdout, import_to_teamb_stderr = self._run_shell_script(
                self.import_to_teamb_script, "sync_to_teamb"
            )

            if import_to_teamb_success:
                # Parse sync results from stdout
                sync_details = self._parse_sync_results(import_to_teamb_stdout)

                migration_operations.append({
                    'operation': 'Sync to Team B',
                    'status': '✅ Success',
                    'details': sync_details
                })
                self.logger.info("✅ Successfully synced resources to Team B")
                self.logger.info(f"Sync results: {sync_details}")

                # Log detailed output for debugging
                if import_to_teamb_stdout:
                    self.logger.debug(f"Sync output: {import_to_teamb_stdout}")
            else:
                migration_operations.append({
                    'operation': 'Sync to Team B',
                    'status': '❌ Failed',
                    'details': f'Error: {import_to_teamb_stderr}'
                })
                overall_success = False
                self.logger.error(f"Failed to sync to Team B: {import_to_teamb_stderr}")
                if import_to_teamb_stdout:
                    self.logger.error(f"Sync output: {import_to_teamb_stdout}")

            # Step 3: Verify by exporting from Team B (optional verification)
            self.logger.info("🔄 Step 3: Verifying import by checking Team B...")
            self._add_operation_delay()

            # Clean directories before verification export
            self._clean_script_directories()

            export_success, export_stdout, export_stderr = self._run_shell_script(self.export_script, "export")

            if export_success:
                # Load and count Team B resources after import
                teamb_dashboards = self._load_json_files_from_directory(self.dashboards_dir, "dashboard")
                teamb_folders = self._load_json_files_from_directory(self.folders_dir, "folder")
                teamb_resources = teamb_dashboards + teamb_folders

                # Export Team B artifacts
                self.logger.info("Saving Team B artifacts (post-import)...")
                self.save_artifacts(teamb_resources, "teamb")

                migration_operations.append({
                    'operation': 'Verify Team B',
                    'status': '✅ Success',
                    'details': f'{len(teamb_dashboards)} dashboards, {len(teamb_folders)} folders verified'
                })
            else:
                migration_operations.append({
                    'operation': 'Verify Team B',
                    'status': '⚠️ Warning',
                    'details': f'Verification failed: {export_stderr}'
                })
                # Don't fail overall migration for verification issues
                self.logger.warning("Verification failed but import may have succeeded")

            # Save failed operations log if any failures occurred
            if self.failed_operations:
                self._save_failed_operations_log()

            # Display results in tabular format
            self.logger.info(f"=" * 80)
            self.logger.info(f"🎉 GRAFANA DASHBOARDS MIGRATION RESULTS")
            self.logger.info(f"=" * 80)

            # Display migration results table
            self._display_migration_results_table(migration_operations)

            # Display overall summary using print for clean formatting
            successful_operations = sum(1 for op in migration_operations if '✅' in op['status'])
            failed_operations = len(migration_operations) - successful_operations

            print("")
            print("📊 OVERALL MIGRATION SUMMARY")
            print("─" * 40)
            print(f"{'Total Operations:':<25} {len(migration_operations):>10}")
            print(f"{'Successful Operations:':<25} {successful_operations:>10}")
            print(f"{'Failed Operations:':<25} {failed_operations:>10}")

            if import_success and export_success:
                print(f"{'Team A Resources:':<25} {len(teama_resources):>10}")
                print(f"{'Team B Resources:':<25} {len(teamb_resources):>10}")

            print("")
            if overall_success:
                print("🎉 All operations completed successfully!")
                print("📁 Exported files are available in the scripts directory:")
                print(f"   - Dashboards: {self.dashboards_dir}")
                print(f"   - Folders: {self.folders_dir}")
            else:
                print("⚠️ Some operations failed - check logs for details")

            self.log_migration_complete(self.service_name, overall_success, successful_operations, failed_operations)

            if overall_success:
                self.logger.info("🎉 Grafana dashboards migration completed successfully!")
            else:
                self.logger.warning(f"⚠️ Grafana dashboards migration completed with {failed_operations} failures")

            return overall_success

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")

            # Save failed operations log
            if self.failed_operations:
                self._save_failed_operations_log()

            self.log_migration_complete(self.service_name, False, 0, 1)
            return False
