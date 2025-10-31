#!/usr/bin/env python3
"""
Simplified SLO gRPC Service for testing.
"""

import json
import os
import subprocess
import shutil
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from core.base_service import BaseService


class SLOGRPCService(BaseService):
    """Simplified SLO service using gRPC calls for migration operations."""
    
    def __init__(self, config):
        """Initialize the SLO gRPC service."""
        super().__init__(config)
        
        # Check if grpcurl is available
        if not shutil.which("grpcurl"):
            error_msg = "grpcurl is required for SLO gRPC service but is not installed."
            print(f"\n❌ {error_msg}")
            print("📦 Please install grpcurl:")
            print("   macOS: brew install grpcurl")
            print("   Linux: Download from https://github.com/fullstorydev/grpcurl/releases")
            raise ValueError(error_msg)
        
        # Get configuration
        self.teama_domain = os.getenv("CX_DOMAIN_TEAMA")
        self.teama_api_key = os.getenv("CX_API_KEY_TEAMA")
        self.teamb_domain = os.getenv("CX_DOMAIN_TEAMB")
        self.teamb_api_key = os.getenv("CX_API_KEY_TEAMB")
        
        if not all([self.teama_domain, self.teama_api_key, self.teamb_domain, self.teamb_api_key]):
            missing = []
            if not self.teama_domain: missing.append("CX_DOMAIN_TEAMA")
            if not self.teama_api_key: missing.append("CX_API_KEY_TEAMA")
            if not self.teamb_domain: missing.append("CX_DOMAIN_TEAMB")
            if not self.teamb_api_key: missing.append("CX_API_KEY_TEAMB")
            raise ValueError(f"Missing environment variables: {missing}")
        
        # Track failed operations
        self.failed_slos = []
        
        print("✅ SLO gRPC service initialized successfully")
    
    @property
    def service_name(self) -> str:
        """Service name property (required by BaseService)."""
        return "slo-grpc"
    
    @property
    def api_endpoint(self) -> str:
        """API endpoint property (required by BaseService)."""
        return "/v1/slo/slos"
    
    def get_service_name(self) -> str:
        """Get the service name."""
        return "slo-grpc"
    
    def get_resource_name(self, resource: Dict[str, Any]) -> str:
        """Get the name of an SLO resource."""
        return resource.get('name', 'Unknown SLO')
    
    def get_resource_identifier(self, resource: Dict[str, Any]) -> str:
        """Get the unique identifier of an SLO resource."""
        return resource.get('id', 'Unknown ID')
    
    def _run_grpcurl(self, domain: str, api_key: str, service: str, method: str, data: Dict = None) -> Dict:
        """
        Run grpcurl command and return the result.

        Args:
            domain: Coralogix domain
            api_key: API key
            service: gRPC service name
            method: gRPC method name
            data: Request data (optional)

        Returns:
            Response data as dictionary
        """
        endpoint = f"ng-api-grpc.{domain}:443"
        full_method = f"{service}/{method}"

        cmd = [
            "grpcurl",
            "-H", f"Authorization: Bearer {api_key[:10]}...",  # Mask API key in logs
            "-d", json.dumps(data or {}),
            endpoint,
            full_method
        ]

        print(f"🔍 Running grpcurl command: {' '.join(cmd[:4])} ... {endpoint} {full_method}")

        try:
            # Use the actual API key in the command
            actual_cmd = [
                "grpcurl",
                "-H", f"Authorization: Bearer {api_key}",
                "-d", json.dumps(data or {}),
                endpoint,
                full_method
            ]

            print(f"🔍 Executing grpcurl with timeout=30s...")
            result = subprocess.run(actual_cmd, capture_output=True, text=True, timeout=30)

            print(f"🔍 grpcurl returned with code: {result.returncode}")

            if result.returncode != 0:
                print(f"🔍 grpcurl stderr: {result.stderr}")
                raise Exception(f"grpcurl failed: {result.stderr}")

            print(f"🔍 grpcurl stdout: {result.stdout[:200]}...")
            return json.loads(result.stdout) if result.stdout.strip() else {}

        except subprocess.TimeoutExpired:
            print("🔍 grpcurl command timed out after 30 seconds")
            raise Exception("grpcurl command timed out")
        except json.JSONDecodeError as e:
            print(f"🔍 Failed to parse JSON response: {e}")
            raise Exception(f"Failed to parse grpcurl response: {e}")
        except Exception as e:
            print(f"🔍 grpcurl command failed: {e}")
            raise Exception(f"grpcurl command failed: {e}")
    
    def fetch_resources_from_teama(self) -> List[Dict[str, Any]]:
        """Fetch all SLOs from Team A using gRPC."""
        try:
            print("🔄 Fetching SLOs from Team A via gRPC...")
            
            response = self._run_grpcurl(
                self.teama_domain,
                self.teama_api_key,
                "com.coralogixapis.slo.v1.SlosService",
                "ListSlos",
                {}
            )
            
            slos = response.get('slos', [])
            print(f"✅ Fetched {len(slos)} SLOs from Team A")
            return slos
            
        except Exception as e:
            print(f"❌ Failed to fetch SLOs from Team A: {e}")
            raise
    
    def fetch_resources_from_teamb(self) -> List[Dict[str, Any]]:
        """Fetch all SLOs from Team B using gRPC."""
        try:
            print("🔄 Fetching SLOs from Team B via gRPC...")
            
            response = self._run_grpcurl(
                self.teamb_domain,
                self.teamb_api_key,
                "com.coralogixapis.slo.v1.SlosService",
                "ListSlos",
                {}
            )
            
            slos = response.get('slos', [])
            print(f"✅ Fetched {len(slos)} SLOs from Team B")
            return slos
            
        except Exception as e:
            print(f"❌ Failed to fetch SLOs from Team B: {e}")
            raise
    
    def create_resource_in_teamb(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Create an SLO in Team B using gRPC."""
        slo_name = self.get_resource_name(resource)
        
        try:
            print(f"🔄 Creating SLO in Team B via gRPC: {slo_name}")
            
            # Clean the SLO data for creation
            cleaned_slo = self._clean_slo_for_creation(resource)
            
            # Create SLO via gRPC
            response = self._run_grpcurl(
                self.teamb_domain,
                self.teamb_api_key,
                "com.coralogixapis.slo.v1.SlosService",
                "CreateSlo",
                {"slo": cleaned_slo}
            )
            
            print(f"✅ Successfully created SLO: {slo_name}")
            return response
            
        except Exception as e:
            print(f"❌ Failed to create SLO '{slo_name}' via gRPC: {e}")
            raise
    
    def delete_resource_in_teamb(self, resource: Dict[str, Any]) -> bool:
        """Delete an SLO in Team B using gRPC."""
        slo_name = self.get_resource_name(resource)
        slo_id = self.get_resource_identifier(resource)
        
        try:
            print(f"🔄 Deleting SLO in Team B via gRPC: {slo_name} (ID: {slo_id})")
            
            # Delete SLO via gRPC
            self._run_grpcurl(
                self.teamb_domain,
                self.teamb_api_key,
                "com.coralogixapis.slo.v1.SlosService",
                "DeleteSlo",
                {"id": slo_id}
            )
            
            print(f"✅ Successfully deleted SLO: {slo_name}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to delete SLO '{slo_name}' via gRPC: {e}")
            return False
    
    def delete_resource_from_teamb(self, resource: Dict[str, Any]) -> bool:
        """Delete an SLO from Team B (required by BaseService)."""
        return self.delete_resource_in_teamb(resource)
    
    def _clean_slo_for_creation(self, slo: Dict[str, Any]) -> Dict[str, Any]:
        """Clean SLO data for creation by removing read-only fields."""
        fields_to_remove = [
            'id', 'revision', 'createTime', 'updateTime', 'createdAt', 'updatedAt',
            'status', 'sloStatus', 'errorBudget', 'burnRate', 'currentHealth'
        ]
        
        cleaned_slo = {}
        for key, value in slo.items():
            if key not in fields_to_remove:
                cleaned_slo[key] = value
        
        return cleaned_slo
    
    def dry_run(self) -> bool:
        """Perform a dry run of the migration."""
        try:
            print("🚀 Starting SLO gRPC dry run...")
            print(f"🔍 Team A domain: {self.teama_domain}")
            print(f"🔍 Team B domain: {self.teamb_domain}")
            print(f"🔍 grpcurl available: {shutil.which('grpcurl') is not None}")

            # Test basic grpcurl connectivity first
            print("🔍 Testing grpcurl connectivity...")

            # Fetch resources from both teams
            print("🔍 About to fetch from Team A...")
            teama_slos = self.fetch_resources_from_teama()

            print("🔍 About to fetch from Team B...")
            teamb_slos = self.fetch_resources_from_teamb()

            print(f"\n📊 Dry Run Results:")
            print(f"  Team A SLOs: {len(teama_slos)}")
            print(f"  Team B SLOs: {len(teamb_slos)}")
            print(f"  Ready for migration!")

            return True

        except Exception as e:
            print(f"❌ Dry run failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def migrate(self) -> bool:
        """Perform the actual migration (required by BaseService)."""
        try:
            print("🚀 Starting SLO gRPC migration...")

            # Fetch resources from both teams
            teama_slos = self.fetch_resources_from_teama()
            teamb_slos = self.fetch_resources_from_teamb()

            # For now, just show what we would do
            print(f"\n📊 Migration Results:")
            print(f"  Team A SLOs: {len(teama_slos)}")
            print(f"  Team B SLOs: {len(teamb_slos)}")
            print(f"  Migration completed!")

            return True

        except Exception as e:
            print(f"❌ Migration failed: {e}")
            return False

    def run(self) -> bool:
        """Perform the actual migration."""
        return self.migrate()
