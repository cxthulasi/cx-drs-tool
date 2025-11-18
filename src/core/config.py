"""
Configuration management for the Coralogix DR Tool.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Config(BaseModel):
    """Configuration class for the DR tool."""
    
    # Team A (Source) Configuration
    cx_api_key_teama: str = Field(..., description="API key for Team A")
    cx_api_url_teama: str = Field(
        default="https://api.coralogix.com/mgmt", 
        description="API URL for Team A"
    )
    
    # Team B (Target) Configuration
    cx_api_key_teamb: str = Field(..., description="API key for Team B")
    cx_api_url_teamb: str = Field(
        default="https://api.coralogix.com/mgmt", 
        description="API URL for Team B"
    )
    
    # Logging Configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json or text)")

    # Service Exclusions Configuration
    exclude_services: Optional[str] = Field(
        default=None,
        description="Comma-separated list of services to exclude from 'all' command"
    )
    
    # Rate Limiting Configuration
    api_rate_limit_per_second: int = Field(
        default=10, 
        description="API rate limit per second"
    )
    api_retry_max_attempts: int = Field(
        default=3, 
        description="Maximum retry attempts for API calls"
    )
    api_retry_backoff_factor: float = Field(
        default=2.0, 
        description="Backoff factor for retries"
    )
    
    # Storage Configuration
    state_storage_path: str = Field(
        default="./state", 
        description="Path to store state files"
    )
    snapshots_storage_path: str = Field(
        default="./snapshots",
        description="Path to store snapshot files"
    )
    outputs_storage_path: str = Field(
        default="./outputs",
        description="Path to store exported artifacts for comparison"
    )
    logs_storage_path: str = Field(
        default="./logs",
        description="Path to store log files"
    )

    # Safety Configuration
    safety_storage_path: str = Field(
        default="./safety",
        description="Path to store safety checkpoints and data"
    )
    min_resources_threshold: int = Field(
        default=1,
        description="Minimum number of resources expected from TeamA"
    )
    max_zero_results_window_hours: int = Field(
        default=24,
        description="Maximum hours to track zero results history"
    )
    require_confirmation_for_mass_delete: bool = Field(
        default=True,
        description="Require confirmation for mass deletion operations"
    )

    # Versioning Configuration
    versions_storage_path: str = Field(
        default="./versions",
        description="Path to store version snapshots"
    )
    max_versions_to_keep: int = Field(
        default=10,
        description="Maximum number of versions to keep per service"
    )
    
    def __init__(self, **kwargs):
        # Load environment variables
        load_dotenv()
        
        # Override with environment variables
        env_config = {
            'cx_api_key_teama': os.getenv('CX_API_KEY_TEAMA'),
            'cx_api_url_teama': os.getenv('CX_API_URL_TEAMA', 'https://api.coralogix.com/mgmt'),
            'cx_api_key_teamb': os.getenv('CX_API_KEY_TEAMB'),
            'cx_api_url_teamb': os.getenv('CX_API_URL_TEAMB', 'https://api.coralogix.com/mgmt'),
            'log_level': os.getenv('LOG_LEVEL', 'INFO'),
            'log_format': os.getenv('LOG_FORMAT', 'json'),
            'api_rate_limit_per_second': int(os.getenv('API_RATE_LIMIT_PER_SECOND', '10')),
            'api_retry_max_attempts': int(os.getenv('API_RETRY_MAX_ATTEMPTS', '3')),
            'api_retry_backoff_factor': float(os.getenv('API_RETRY_BACKOFF_FACTOR', '2.0')),
            'state_storage_path': os.getenv('STATE_STORAGE_PATH', './state'),
            'snapshots_storage_path': os.getenv('SNAPSHOTS_STORAGE_PATH', './snapshots'),
            'outputs_storage_path': os.getenv('OUTPUTS_STORAGE_PATH', './outputs'),
            'logs_storage_path': os.getenv('LOGS_STORAGE_PATH', './logs'),
            'safety_storage_path': os.getenv('SAFETY_STORAGE_PATH', './safety'),
            'versions_storage_path': os.getenv('VERSIONS_STORAGE_PATH', './versions'),
            'min_resources_threshold': int(os.getenv('MIN_RESOURCES_THRESHOLD', '1')),
            'max_zero_results_window_hours': int(os.getenv('MAX_ZERO_RESULTS_WINDOW_HOURS', '24')),
            'require_confirmation_for_mass_delete': os.getenv('REQUIRE_CONFIRMATION_FOR_MASS_DELETE', 'true').lower() == 'true',
            'max_versions_to_keep': int(os.getenv('MAX_VERSIONS_TO_KEEP', '10')),
        }
        
        # Remove None values
        env_config = {k: v for k, v in env_config.items() if v is not None}
        
        # Merge with provided kwargs
        env_config.update(kwargs)
        
        super().__init__(**env_config)
    
    def validate_config(self) -> bool:
        """Validate that required configuration is present."""
        if not self.cx_api_key_teama:
            raise ValueError("CX_API_KEY_TEAMA is required")
        if not self.cx_api_key_teamb:
            raise ValueError("CX_API_KEY_TEAMB is required")
        return True
    
    @property
    def teama_headers(self) -> dict:
        """Get headers for Team A API calls."""
        return {
            'Authorization': f'Bearer {self.cx_api_key_teama}',
            'Content-Type': 'application/json',
        }
    
    @property
    def teamb_headers(self) -> dict:
        """Get headers for Team B API calls."""
        return {
            'Authorization': f'Bearer {self.cx_api_key_teamb}',
            'Content-Type': 'application/json',
        }
