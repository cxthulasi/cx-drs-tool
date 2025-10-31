#!/usr/bin/env python3
"""
Production-ready gRPC client using grpcurl subprocess calls.
Provides import, delete, and create operations for Coralogix API without protobuf files.

This module is part of the Coralogix migration tool and should be used via the SLO gRPC service.
"""

import subprocess
import json
import os
import shutil
from typing import Dict, Any, List, Optional, Union
import logging
from dataclasses import dataclass
from enum import Enum


class GRPCError(Exception):
    """Custom exception for gRPC operation errors."""
    
    def __init__(self, message: str, exit_code: int = None, stderr: str = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class ServiceType(Enum):
    """Supported Coralogix gRPC services."""
    SLO = "com.coralogixapis.slo.v1.SlosService"
    ALERTS = "com.coralogixapis.alerts.v1.AlertsService"
    DASHBOARDS = "com.coralogixapis.dashboards.v1.DashboardsService"


@dataclass
class GRPCConfig:
    """Configuration for gRPC client."""
    domain: str
    api_key: str
    timeout: int = 30
    max_retries: int = 3
    debug: bool = False


class CoralogixGRPCClient:
    """Production-ready gRPC client using grpcurl subprocess calls."""
    
    def __init__(self, config: GRPCConfig):
        """
        Initialize the gRPC client.
        
        Args:
            config: GRPCConfig object with connection details
        """
        self.config = config
        self.endpoint = f"ng-api-grpc.{config.domain}:443"
        self.logger = self._setup_logger()
        
        # Verify grpcurl is available
        if not self._check_grpcurl_available():
            raise GRPCError("grpcurl is not available. Please install it first.")
    
    def _setup_logger(self) -> logging.Logger:
        """Setup logger for the client."""
        logger = logging.getLogger(f"grpcurl_client_{self.config.domain}")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        logger.setLevel(logging.DEBUG if self.config.debug else logging.INFO)
        return logger
    
    def _check_grpcurl_available(self) -> bool:
        """Check if grpcurl is available in PATH."""
        return shutil.which("grpcurl") is not None
    
    def _build_base_command(self, service: ServiceType, method: str) -> List[str]:
        """
        Build the base grpcurl command.
        
        Args:
            service: The gRPC service to call
            method: The method to call
            
        Returns:
            Base command as list of strings
        """
        return [
            "grpcurl",
            "-H", f"Authorization: Bearer {self.config.api_key}",
            "-format", "json",
            "-emit-defaults",
            self.endpoint,
            f"{service.value}/{method}"
        ]
    
    def _execute_grpcurl(self, command: List[str], input_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute grpcurl command with proper error handling.
        
        Args:
            command: grpcurl command as list
            input_data: Optional input data to send
            
        Returns:
            Parsed JSON response
            
        Raises:
            GRPCError: If the command fails
        """
        try:
            # Prepare input
            stdin_input = None
            if input_data:
                stdin_input = json.dumps(input_data, indent=2).encode('utf-8')
                command.extend(["-d", "@"])
            
            if self.config.debug:
                self.logger.debug(f"Executing command: {' '.join(command)}")
                if input_data:
                    self.logger.debug(f"Input data: {json.dumps(input_data, indent=2)}")
            
            # Execute command
            result = subprocess.run(
                command,
                input=stdin_input,
                capture_output=True,
                timeout=self.config.timeout,
                check=False
            )
            
            # Handle response
            if result.returncode == 0:
                if result.stdout:
                    try:
                        response = json.loads(result.stdout.decode('utf-8'))
                        if self.config.debug:
                            self.logger.debug(f"Response: {json.dumps(response, indent=2)}")
                        return response
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Failed to parse JSON response: {e}")
                        return {"raw_output": result.stdout.decode('utf-8')}
                else:
                    return {"success": True}
            else:
                error_msg = result.stderr.decode('utf-8') if result.stderr else "Unknown error"
                self.logger.error(f"grpcurl failed with exit code {result.returncode}: {error_msg}")
                raise GRPCError(
                    f"grpcurl command failed: {error_msg}",
                    exit_code=result.returncode,
                    stderr=error_msg
                )
                
        except subprocess.TimeoutExpired:
            raise GRPCError(f"grpcurl command timed out after {self.config.timeout} seconds")
        except Exception as e:
            raise GRPCError(f"Failed to execute grpcurl: {str(e)}")
    
    def create_slo(self, slo_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create an SLO using grpcurl.
        
        Args:
            slo_data: SLO data dictionary
            
        Returns:
            Created SLO response
        """
        self.logger.info(f"Creating SLO: {slo_data.get('name', 'Unknown')}")
        
        command = self._build_base_command(ServiceType.SLO, "CreateSlo")
        payload = {"slo": slo_data}
        
        try:
            response = self._execute_grpcurl(command, payload)
            self.logger.info(f"✅ Successfully created SLO: {slo_data.get('name')}")
            return response
        except GRPCError as e:
            self.logger.error(f"❌ Failed to create SLO: {e}")
            raise
    
    def get_slo(self, slo_id: str) -> Dict[str, Any]:
        """
        Get an SLO by ID using grpcurl.
        
        Args:
            slo_id: SLO ID to retrieve
            
        Returns:
            SLO data
        """
        self.logger.info(f"Getting SLO: {slo_id}")
        
        command = self._build_base_command(ServiceType.SLO, "GetSlo")
        payload = {"id": slo_id}
        
        try:
            response = self._execute_grpcurl(command, payload)
            self.logger.info(f"✅ Successfully retrieved SLO: {slo_id}")
            return response
        except GRPCError as e:
            self.logger.error(f"❌ Failed to get SLO: {e}")
            raise
    
    def list_slos(self) -> Dict[str, Any]:
        """
        List all SLOs using grpcurl.
        
        Returns:
            List of SLOs
        """
        self.logger.info("Listing all SLOs")
        
        command = self._build_base_command(ServiceType.SLO, "ListSlos")
        payload = {}  # Empty payload for list operation
        
        try:
            response = self._execute_grpcurl(command, payload)
            slo_count = len(response.get('slos', []))
            self.logger.info(f"✅ Successfully listed {slo_count} SLOs")
            return response
        except GRPCError as e:
            self.logger.error(f"❌ Failed to list SLOs: {e}")
            raise
    
    def delete_slo(self, slo_id: str) -> Dict[str, Any]:
        """
        Delete an SLO by ID using grpcurl.
        
        Args:
            slo_id: SLO ID to delete
            
        Returns:
            Delete response
        """
        self.logger.info(f"Deleting SLO: {slo_id}")
        
        command = self._build_base_command(ServiceType.SLO, "DeleteSlo")
        payload = {"id": slo_id}
        
        try:
            response = self._execute_grpcurl(command, payload)
            self.logger.info(f"✅ Successfully deleted SLO: {slo_id}")
            return response
        except GRPCError as e:
            self.logger.error(f"❌ Failed to delete SLO: {e}")
            raise
    
    def update_slo(self, slo_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an SLO using grpcurl.

        Args:
            slo_data: Updated SLO data dictionary (must include 'id')

        Returns:
            Updated SLO response
        """
        slo_id = slo_data.get('id')
        if not slo_id:
            raise GRPCError("SLO data must include 'id' field for update")

        self.logger.info(f"Updating SLO: {slo_id}")

        command = self._build_base_command(ServiceType.SLO, "UpdateSlo")
        payload = {"slo": slo_data}

        try:
            response = self._execute_grpcurl(command, payload)
            self.logger.info(f"✅ Successfully updated SLO: {slo_id}")
            return response
        except GRPCError as e:
            self.logger.error(f"❌ Failed to update SLO: {e}")
            raise

    def import_slos_from_source(self, source_client: 'CoralogixGRPCClient') -> List[Dict[str, Any]]:
        """
        Import all SLOs from a source Coralogix instance.

        Args:
            source_client: Another CoralogixGRPCClient instance (source)

        Returns:
            List of imported SLO data
        """
        self.logger.info("Starting SLO import from source instance")

        try:
            # Get all SLOs from source
            source_response = source_client.list_slos()
            source_slos = source_response.get('slos', [])

            if not source_slos:
                self.logger.info("No SLOs found in source instance")
                return []

            self.logger.info(f"Found {len(source_slos)} SLOs in source instance")

            imported_slos = []
            failed_imports = []

            for slo in source_slos:
                try:
                    # Clean SLO data for import (remove read-only fields)
                    clean_slo = self._clean_slo_for_import(slo)

                    # Create SLO in target instance
                    response = self.create_slo(clean_slo)
                    imported_slos.append(response)

                except Exception as e:
                    slo_name = slo.get('name', 'Unknown')
                    self.logger.error(f"Failed to import SLO '{slo_name}': {e}")
                    failed_imports.append({'slo': slo, 'error': str(e)})

            self.logger.info(f"✅ Import completed: {len(imported_slos)} successful, {len(failed_imports)} failed")

            if failed_imports:
                self.logger.warning("Failed imports:")
                for failed in failed_imports:
                    self.logger.warning(f"  - {failed['slo'].get('name', 'Unknown')}: {failed['error']}")

            return imported_slos

        except Exception as e:
            self.logger.error(f"❌ Import operation failed: {e}")
            raise GRPCError(f"Failed to import SLOs: {e}")

    def _clean_slo_for_import(self, slo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean SLO data for import by removing read-only fields.

        Args:
            slo: Original SLO data

        Returns:
            Cleaned SLO data ready for creation
        """
        # Fields to remove for import/creation
        fields_to_remove = [
            'id',           # Will be auto-generated
            'revision',     # Will be auto-generated
            'createTime',   # Will be auto-generated
            'updateTime',   # Will be auto-generated
            'createdAt',    # Alternative timestamp field
            'updatedAt',    # Alternative timestamp field
            'status',       # Calculated by API
            'sloStatus',    # Calculated by API
            'errorBudget',  # Calculated by API
            'burnRate',     # Calculated by API
            'currentHealth' # Calculated by API
        ]

        cleaned_slo = {}
        for key, value in slo.items():
            if key not in fields_to_remove:
                cleaned_slo[key] = value

        return cleaned_slo

    def batch_delete_slos(self, slo_ids: List[str]) -> Dict[str, Any]:
        """
        Delete multiple SLOs in batch.

        Args:
            slo_ids: List of SLO IDs to delete

        Returns:
            Batch operation results
        """
        self.logger.info(f"Starting batch delete of {len(slo_ids)} SLOs")

        successful_deletes = []
        failed_deletes = []

        for slo_id in slo_ids:
            try:
                response = self.delete_slo(slo_id)
                successful_deletes.append({'id': slo_id, 'response': response})
            except Exception as e:
                self.logger.error(f"Failed to delete SLO {slo_id}: {e}")
                failed_deletes.append({'id': slo_id, 'error': str(e)})

        results = {
            'total': len(slo_ids),
            'successful': len(successful_deletes),
            'failed': len(failed_deletes),
            'successful_deletes': successful_deletes,
            'failed_deletes': failed_deletes
        }

        self.logger.info(f"✅ Batch delete completed: {results['successful']} successful, {results['failed']} failed")
        return results

    def export_slos_to_file(self, filename: str) -> int:
        """
        Export all SLOs to a JSON file.

        Args:
            filename: Output filename

        Returns:
            Number of SLOs exported
        """
        self.logger.info(f"Exporting SLOs to file: {filename}")

        try:
            response = self.list_slos()
            slos = response.get('slos', [])

            # Clean SLOs for export (remove instance-specific data)
            cleaned_slos = []
            for slo in slos:
                cleaned_slo = self._clean_slo_for_import(slo)
                cleaned_slos.append(cleaned_slo)

            # Write to file
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    'export_info': {
                        'source_domain': self.config.domain,
                        'export_time': subprocess.run(['date', '-Iseconds'], capture_output=True, text=True).stdout.strip(),
                        'total_slos': len(cleaned_slos)
                    },
                    'slos': cleaned_slos
                }, f, indent=2, ensure_ascii=False)

            self.logger.info(f"✅ Exported {len(cleaned_slos)} SLOs to {filename}")
            return len(cleaned_slos)

        except Exception as e:
            self.logger.error(f"❌ Failed to export SLOs: {e}")
            raise GRPCError(f"Export failed: {e}")

    def import_slos_from_file(self, filename: str) -> Dict[str, Any]:
        """
        Import SLOs from a JSON file.

        Args:
            filename: Input filename

        Returns:
            Import results
        """
        self.logger.info(f"Importing SLOs from file: {filename}")

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)

            slos = data.get('slos', [])
            if not slos:
                self.logger.warning("No SLOs found in import file")
                return {'total': 0, 'successful': 0, 'failed': 0}

            self.logger.info(f"Found {len(slos)} SLOs in import file")

            successful_imports = []
            failed_imports = []

            for slo in slos:
                try:
                    response = self.create_slo(slo)
                    successful_imports.append(response)
                except Exception as e:
                    slo_name = slo.get('name', 'Unknown')
                    self.logger.error(f"Failed to import SLO '{slo_name}': {e}")
                    failed_imports.append({'slo': slo, 'error': str(e)})

            results = {
                'total': len(slos),
                'successful': len(successful_imports),
                'failed': len(failed_imports),
                'successful_imports': successful_imports,
                'failed_imports': failed_imports
            }

            self.logger.info(f"✅ Import completed: {results['successful']} successful, {results['failed']} failed")
            return results

        except Exception as e:
            self.logger.error(f"❌ Failed to import SLOs from file: {e}")
            raise GRPCError(f"Import from file failed: {e}")


def create_client_from_env(env_prefix: str = "CX", debug: bool = False) -> CoralogixGRPCClient:
    """
    Create a gRPC client from environment variables.

    Args:
        env_prefix: Environment variable prefix (default: "CX")
        debug: Enable debug logging

    Returns:
        Configured CoralogixGRPCClient

    Environment variables expected:
        {env_prefix}_DOMAIN: Coralogix domain (e.g., 'eu2.coralogix.com')
        {env_prefix}_API_KEY: Coralogix API key
    """
    domain = os.getenv(f"{env_prefix}_DOMAIN")
    api_key = os.getenv(f"{env_prefix}_API_KEY")

    if not domain:
        raise GRPCError(f"Environment variable {env_prefix}_DOMAIN is required")
    if not api_key:
        raise GRPCError(f"Environment variable {env_prefix}_API_KEY is required")

    config = GRPCConfig(
        domain=domain,
        api_key=api_key,
        debug=debug
    )

    return CoralogixGRPCClient(config)


def migrate_slos_between_instances(source_env_prefix: str, target_env_prefix: str,
                                 dry_run: bool = False) -> Dict[str, Any]:
    """
    Migrate SLOs between two Coralogix instances.

    Args:
        source_env_prefix: Environment variable prefix for source instance
        target_env_prefix: Environment variable prefix for target instance
        dry_run: If True, only show what would be migrated

    Returns:
        Migration results
    """
    print(f"🚀 Starting SLO migration: {source_env_prefix} → {target_env_prefix}")

    try:
        # Create clients
        source_client = create_client_from_env(source_env_prefix)
        target_client = create_client_from_env(target_env_prefix)

        # Get source SLOs
        source_response = source_client.list_slos()
        source_slos = source_response.get('slos', [])

        print(f"📊 Found {len(source_slos)} SLOs in source instance")

        if dry_run:
            print("🔍 DRY RUN - SLOs that would be migrated:")
            for slo in source_slos:
                print(f"  - {slo.get('name', 'Unknown')} (ID: {slo.get('id', 'N/A')})")
            return {
                'dry_run': True,
                'total_slos': len(source_slos),
                'slos': source_slos
            }

        # Perform actual migration
        results = target_client.import_slos_from_source(source_client)

        print(f"✅ Migration completed: {len(results)} SLOs migrated")
        return {
            'dry_run': False,
            'total_slos': len(source_slos),
            'migrated_slos': len(results),
            'results': results
        }

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise


# Example usage and testing functions
def test_slo_operations():
    """Test basic SLO operations."""
    print("🧪 Testing SLO Operations")
    print("=" * 50)

    try:
        # Create client from environment
        client = create_client_from_env("CX_TEAMB", debug=True)

        # Test SLO data based on your grpcurl example
        test_slo = {
            "name": "Test API Availability SLO",
            "description": "Test SLO for API availability monitoring",
            "creator": "migration-tool@example.com",
            "target_threshold_percentage": 99.95,
            "slo_time_frame": "SLO_TIME_FRAME_28_DAYS",
            "request_based_metric_sli": {
                "good_events": {
                    "query": "sum(rate(http_requests_total{status=~\"2..\"})) by(service_name)"
                },
                "total_events": {
                    "query": "sum(rate(http_requests_total)) by(service_name)"
                }
            }
        }

        print("\n1. Creating test SLO...")
        created_slo = client.create_slo(test_slo)
        slo_id = created_slo.get('slo', {}).get('id')

        if slo_id:
            print(f"✅ Created SLO with ID: {slo_id}")

            print("\n2. Retrieving SLO...")
            retrieved_slo = client.get_slo(slo_id)
            print(f"✅ Retrieved SLO: {retrieved_slo.get('slo', {}).get('name')}")

            print("\n3. Listing all SLOs...")
            all_slos = client.list_slos()
            print(f"✅ Found {len(all_slos.get('slos', []))} total SLOs")

            print("\n4. Deleting test SLO...")
            client.delete_slo(slo_id)
            print("✅ Test SLO deleted")

        print("\n🎉 All tests passed!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


def show_usage_examples():
    """Show comprehensive usage examples."""
    print("\n📚 Usage Examples")
    print("=" * 50)

    examples = """
# 1. Basic SLO Operations
from grpcurl_client import CoralogixGRPCClient, GRPCConfig

config = GRPCConfig(
    domain="eu2.coralogix.com",
    api_key="your-api-key",
    debug=True
)
client = CoralogixGRPCClient(config)

# Create SLO
slo_data = {
    "name": "API Availability SLO",
    "target_threshold_percentage": 99.95,
    "slo_time_frame": "SLO_TIME_FRAME_28_DAYS",
    # ... rest of SLO data
}
response = client.create_slo(slo_data)

# List SLOs
slos = client.list_slos()

# Delete SLO
client.delete_slo("slo-id-123")

# 2. Import/Export Operations
# Export to file
client.export_slos_to_file("slos_backup.json")

# Import from file
results = client.import_slos_from_file("slos_backup.json")

# 3. Migration Between Instances
from grpcurl_client import migrate_slos_between_instances

# Dry run
migrate_slos_between_instances("CX_TEAMA", "CX_TEAMB", dry_run=True)

# Actual migration
results = migrate_slos_between_instances("CX_TEAMA", "CX_TEAMB")

# 4. Environment Variable Setup
export CX_TEAMA_DOMAIN="eu2.coralogix.com"
export CX_TEAMA_API_KEY="your-team-a-api-key"
export CX_TEAMB_DOMAIN="eu2.coralogix.com"
export CX_TEAMB_API_KEY="your-team-b-api-key"
"""

    print(examples)


def main():
    """Main function for running grpcurl client as a standalone script."""
    print("🚀 Coralogix gRPC Client (grpcurl-based)")
    print("=" * 60)

    # Check if grpcurl is available
    if not shutil.which("grpcurl"):
        print("❌ grpcurl is not installed or not in PATH")
        print("📦 Install grpcurl: https://github.com/fullstorydev/grpcurl#installation")
        exit(1)

    print("✅ grpcurl is available")

    # Show usage examples
    show_usage_examples()

    # Check environment variables
    print("\n🌐 Environment Check:")
    for prefix in ["CX_TEAMA", "CX_TEAMB"]:
        domain = os.getenv(f"{prefix}_DOMAIN", "NOT_SET")
        api_key = os.getenv(f"{prefix}_API_KEY", "NOT_SET")
        print(f"  {prefix}_DOMAIN: {domain}")
        print(f"  {prefix}_API_KEY: {'SET' if api_key != 'NOT_SET' else 'NOT_SET'}")

    # Tests are available but not run automatically
    # To run tests, call test_slo_operations() manually
    print("\n💡 To run tests, call test_slo_operations() manually after setting environment variables")

    print("\n✅ Module ready for use!")


if __name__ == "__main__":
    main()
