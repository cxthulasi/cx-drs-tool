"""
Logging configuration for the Coralogix DR Tool.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog
from rich.console import Console
from rich.logging import RichHandler


def setup_logger(service_name: str, feature: str, log_level: str = "INFO", json_console: bool = False) -> structlog.stdlib.BoundLogger:
    """
    Set up structured logging for the DR tool.

    Args:
        service_name: Name of the service (e.g., 'parsing-rules')
        feature: Feature name for log file organization
        log_level: Logging level
        json_console: If True, output single-line JSON to console (for Coralogix ingestion)

    Returns:
        Configured logger instance
    """
    # Create logs directory structure
    logs_dir = Path("logs") / feature
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Generate log filename with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d-%H")
    log_filename = f"cx-dr-log-{service_name}-{timestamp}.log"
    log_filepath = logs_dir / log_filename

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Create logger
    logger = structlog.get_logger(service_name)

    # Add file handler for persistent logging (always JSON)
    file_handler = logging.FileHandler(log_filepath)
    file_handler.setLevel(getattr(logging, log_level.upper()))

    # Get the root logger and add handlers
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    # Add console handler - either JSON or Rich formatting
    if json_console:
        # Single-line JSON output for Coralogix ingestion
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(logging.Formatter('%(message)s'))
    else:
        # Rich formatting for human-readable output
        console_handler = RichHandler(
            console=Console(stderr=True),
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True
        )
        console_handler.setLevel(getattr(logging, log_level.upper()))

    root_logger.addHandler(console_handler)

    # Log initial setup information
    logger.info(
        "Logger initialized",
        service=service_name,
        feature=feature,
        log_file=str(log_filepath),
        log_level=log_level,
        json_console=json_console
    )

    return logger


class LoggerMixin:
    """Mixin class to add logging capabilities to services."""
    
    def __init__(self, service_name: str, feature: str, log_level: str = "INFO"):
        self.logger = setup_logger(service_name, feature, log_level)
    
    def log_api_call(self, method: str, url: str, status_code: Optional[int] = None,
                     response_time: Optional[float] = None, error: Optional[str] = None):
        """Log API call details."""
        log_data = {
            "method": method,
            "url": url,
        }

        if status_code is not None:
            log_data["status_code"] = status_code

        if response_time is not None:
            log_data["response_time_ms"] = round(response_time * 1000, 2)

        if error:
            log_data["error"] = error
            self.logger.error("API call failed", **log_data)
        else:
            self.logger.info("API call completed", **log_data)
    
    def log_migration_start(self, resource_type: str, dry_run: bool = False):
        """Log migration start."""
        self.logger.info(
            "Migration started",
            resource_type=resource_type,
            dry_run=dry_run
        )
    
    def log_migration_complete(self, resource_type: str, success: bool,
                              resources_processed: int, errors: int = 0):
        """Log migration completion."""
        self.logger.info(
            "Migration completed",
            resource_type=resource_type,
            success=success,
            resources_processed=resources_processed,
            errors=errors
        )
    
    def log_resource_action(self, action: str, resource_type: str,
                           resource_name: str, success: bool, error: Optional[str] = None):
        """Log individual resource actions."""
        log_data = {
            "action": action,
            "resource_type": resource_type,
            "resource_name": resource_name,
            "success": success
        }

        if error:
            log_data["error"] = error
            self.logger.error("Resource action failed", **log_data)
        else:
            self.logger.info("Resource action completed", **log_data)
