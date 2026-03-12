#!/usr/bin/env python3
"""Test script for Zepp MCP with real export data."""

import asyncio
import sys
import tempfile
from pathlib import Path

from zepp_life_mcp.adapters.export_file import ExportFileAdapter
from zepp_life_mcp.config import load_config, save_config, Config
from zepp_life_mcp.server import main as server_main
from zepp_life_mcp.storage import Database
from zepp_life_mcp.services.sync_service import SyncService
from zepp_life_mcp.services.query_service import QueryService


def test_export_path(export_path: str):
    """Test if export path contains valid data."""
    path = Path(export_path)
    
    print(f"🔍 Testing export path: {path}")
    print(f"   Exists: {path.exists()}")
    
    if not path.exists():
        print("   ❌ Path does not exist!")
        return False
    
    # Try to connect
    adapter = ExportFileAdapter(path)
    connected = adapter.connect()
    
    print(f"   Connected: {connected}")
    
    if not connected:
        print("   ❌ Could not connect to export data")
        print("   Make sure this is a directory with exported CSV/JSON files")
        return False
    
    print(f"   Available data types: {adapter.get_available_data_types()}")
    print(f"   User ID: {adapter.get_user_id()}")
    
    # Count records
    for data_type in adapter.get_available_data_types():
        if data_type == "daily_activity":
            count = sum(1 for _ in adapter.iter_daily_activity())
            print(f"   📊 Activity records: {count}")
        elif data_type == "sleep":
            count = sum(1 for _ in adapter.iter_sleep_sessions())
            print(f"   😴 Sleep records: {count}")
        elif data_type == "workouts":
            count = sum(1 for _ in adapter.iter_workouts())
            print(f"   🏃 Workout records: {count}")
        elif data_type == "body_measurements":
            count = sum(1 for _ in adapter.iter_body_measurements())
            print(f"   ⚖️  Body measurement records: {count}")
    
    return True


def setup_config(export_path: str):
    """Configure the server with export path."""
    config = Config(
        mode="export_file",
        export_path=Path(export_path),
    )
    save_config(config)
    print(f"✅ Configuration saved")
    print(f"   Mode: export_file")
    print(f"   Export path: {export_path}")


def test_sync_and_query(export_path: str):
    """Test sync and query functionality."""
    print("\n🔄 Testing sync and query...")
    
    # Setup
    test_db_path = tempfile.mktemp(suffix='.db')
    db = Database(test_db_path)
    adapter = ExportFileAdapter(Path(export_path))
    adapter.connect()
    
    # Sync all data types
    sync = SyncService(adapter, db)
    available_types = adapter.get_available_data_types()
    
    print(f"   Syncing {len(available_types)} data types...")
    
    for data_type in available_types:
        try:
            result = sync.sync_data_type(data_type)
            print(f"   ✓ {data_type}: {result['added']} added, {result['updated']} updated")
        except Exception as e:
            print(f"   ✗ {data_type}: {e}")
    
    # Query examples
    query = QueryService(db, adapter.get_user_id())
    
    print("\n📈 Sample queries:")
    
    # Activity summary
    coverage = db.get_data_coverage(adapter.get_user_id())
    for c in coverage:
        print(f"   {c['data_type']}: {c.get('first_date', 'N/A')} to {c.get('last_date', 'N/A')} ({c.get('days_with_data', 0)} days)")
    
    return True


def main():
    """Main test function."""
    print("=" * 60)
    print("Zepp MCP - Export Data Test")
    print("=" * 60)
    
    # Check command line arguments
    if len(sys.argv) < 2:
        print("\nUsage: python test_export.py <path_to_export_directory>")
        print("\nExample:")
        print("  python test_export.py ~/Downloads/ZeppExport")
        print("\nTo get your export data:")
        print("  1. Open Zepp Life app")
        print("  2. Go to Profile → Settings → Data Export")
        print("  3. Request export and wait for email")
        print("  4. Download and extract the archive")
        sys.exit(1)
    
    export_path = sys.argv[1]
    
    # Test the export path
    if not test_export_path(export_path):
        print("\n❌ Export path test failed")
        sys.exit(1)
    
    # Setup configuration
    print("\n⚙️  Setting up configuration...")
    setup_config(export_path)
    
    # Test sync and query
    test_sync_and_query(export_path)
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    print("\nYou can now add this to Claude Desktop config:")
    print()
    print('{')
    print('  "mcpServers": {')
    print('    "zepp-life": {')
    print(f'      "command": "{sys.executable}",')
    print('      "args": ["-m", "zepp_life_mcp.main", "serve"],')
    print('      "env": {')
    print(f'        "ZEPP_EXPORT_PATH": "{export_path}"')
    print('      }')
    print('    }')
    print('  }')
    print('}')


if __name__ == "__main__":
    main()
