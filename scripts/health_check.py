#!/usr/bin/env python3
"""
Health check script for the Coralogix DR Tool.

This script verifies that the tool is properly configured and can connect to both teams.
"""

import sys
import os
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.config import Config
from core.api_client import APIClient, CoralogixAPIError


def check_environment():
    """Check if environment is properly set up."""
    print("🔍 Checking environment setup...")
    
    # Check if .env file exists
    if not Path('.env').exists():
        print("❌ .env file not found")
        print("   Please copy .env.example to .env and configure your API keys")
        return False
    
    print("✅ .env file found")
    
    # Check if required directories exist
    required_dirs = ['logs', 'state', 'snapshots']
    for dir_name in required_dirs:
        if not Path(dir_name).exists():
            print(f"⚠️  Directory '{dir_name}' not found (will be created automatically)")
        else:
            print(f"✅ Directory '{dir_name}' exists")
    
    return True


def check_configuration():
    """Check if configuration is valid."""
    print("\n🔍 Checking configuration...")
    
    try:
        config = Config()
        config.validate_config()
        print("✅ Configuration is valid")
        return config
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected configuration error: {e}")
        return None


def check_api_connectivity(config):
    """Check API connectivity for both teams."""
    print("\n🔍 Checking API connectivity...")
    
    # Test Team A connectivity
    print("  Testing Team A connection...")
    try:
        with APIClient(config, 'teama') as client:
            # Try a simple API call (this might need to be adjusted based on actual API)
            response = client.get('/health')  # Placeholder endpoint
            print("✅ Team A API connection successful")
    except CoralogixAPIError as e:
        if e.status_code == 404:
            print("⚠️  Team A API connected but /health endpoint not found (this is expected)")
        else:
            print(f"❌ Team A API connection failed: {e}")
            return False
    except Exception as e:
        print(f"❌ Team A API connection error: {e}")
        return False
    
    # Test Team B connectivity
    print("  Testing Team B connection...")
    try:
        with APIClient(config, 'teamb') as client:
            # Try a simple API call (this might need to be adjusted based on actual API)
            response = client.get('/health')  # Placeholder endpoint
            print("✅ Team B API connection successful")
    except CoralogixAPIError as e:
        if e.status_code == 404:
            print("⚠️  Team B API connected but /health endpoint not found (this is expected)")
        else:
            print(f"❌ Team B API connection failed: {e}")
            return False
    except Exception as e:
        print(f"❌ Team B API connection error: {e}")
        return False
    
    return True


def check_dependencies():
    """Check if all required dependencies are installed."""
    print("\n🔍 Checking dependencies...")
    
    required_packages = [
        'requests', 'python-dotenv', 'pydantic', 'httpx', 
        'tenacity', 'structlog', 'rich'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} (missing)")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n❌ Missing packages: {', '.join(missing_packages)}")
        print("   Run: pip install -r requirements.txt")
        return False
    
    return True


def main():
    """Main health check function."""
    print("🏥 Coralogix DR Tool - Health Check")
    print("=" * 50)
    
    all_checks_passed = True
    
    # Check environment
    if not check_environment():
        all_checks_passed = False
    
    # Check dependencies
    if not check_dependencies():
        all_checks_passed = False
    
    # Check configuration
    config = check_configuration()
    if not config:
        all_checks_passed = False
    
    # Check API connectivity (only if config is valid)
    if config:
        if not check_api_connectivity(config):
            all_checks_passed = False
    
    # Summary
    print("\n" + "=" * 50)
    if all_checks_passed:
        print("✅ All health checks passed! The DR tool is ready to use.")
        print("\nNext steps:")
        print("  1. Run a dry run: python dr-tool.py parsing-rules --dry-run")
        print("  2. Run actual migration: python dr-tool.py parsing-rules")
        return 0
    else:
        print("❌ Some health checks failed. Please fix the issues above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
