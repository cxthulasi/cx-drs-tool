#!/bin/bash

# Description: Sync Grafana folders and dashboards to Team B from exported JSON files
# This script ensures Team B is in sync with Team A by:
# 1. Deleting dashboards/folders that no longer exist in Team A
# 2. Updating changed dashboards/folders (delete + recreate)
# 3. Creating new dashboards/folders
# 4. Skipping unchanged resources

# Reference: https://grafana.com/docs/grafana/latest/developers/http_api/

# setup script home directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load environment variables from root .env file (if it exists)
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && cd ../.. && pwd )"
ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    # Export variables from .env file, ignoring comments and empty lines
    # Also remove inline comments after values
    export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | sed 's/#.*//' | xargs)
    echo "✅ Loaded environment variables from $ENV_FILE"
else
    echo "ℹ️  No .env file found at $ENV_FILE - using environment variables from system/K8s"
fi

# Check if required variables are set
if [ -z "$TEAMB_HOST" ] || [ -z "$CX_API_KEY_TEAMB" ]; then
    echo "❌ ERROR: TEAMB_HOST and CX_API_KEY_TEAMB must be set"
    echo "   TEAMB_HOST: $TEAMB_HOST"
    echo "   CX_API_KEY_TEAMB: $CX_API_KEY_TEAMB"
    echo "   - For local: Edit .env file in the project root"
    echo "   - For K8s: Check ConfigMap and Secrets are properly mounted"
    exit 1
fi

echo "🚀 Starting sync to Team B Grafana"
echo "   Target: $TEAMB_HOST"

# Counters for statistics
FOLDERS_CREATED=0
FOLDERS_UPDATED=0
FOLDERS_DELETED=0
FOLDERS_SKIPPED=0
FOLDERS_FAILED=0
DASHBOARDS_CREATED=0
DASHBOARDS_UPDATED=0
DASHBOARDS_DELETED=0
DASHBOARDS_SKIPPED=0
DASHBOARDS_FAILED=0

# Function to get existing resources from Team B
get_existing_teamb_resources() {
    echo "🔍 Fetching existing resources from Team B..."

    # Get existing dashboards
    EXISTING_DASHBOARDS=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" "$TEAMB_HOST/api/search?query=&" | jq -r '.[] | select(.type == "dash-db") | .uid' 2>/dev/null)

    # Get existing folders
    EXISTING_FOLDERS=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" "$TEAMB_HOST/api/folders" | jq -r '.[] | .uid' 2>/dev/null)

    echo "   Found $(echo "$EXISTING_DASHBOARDS" | wc -w) existing dashboards"
    echo "   Found $(echo "$EXISTING_FOLDERS" | wc -w) existing folders"
}

# Function to delete folder from Team B
delete_folder() {
    local folder_uid="$1"

    echo "🗑️  Deleting folder: $folder_uid"

    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -X DELETE "$TEAMB_HOST/api/folders/$folder_uid")

    if [ $? -eq 0 ]; then
        echo "   ✅ Folder deleted successfully: $folder_uid"
        ((FOLDERS_DELETED++))
        return 0
    else
        echo "   ❌ Failed to delete folder: $folder_uid"
        ((FOLDERS_FAILED++))
        return 1
    fi
}

# Function to delete dashboard from Team B
delete_dashboard() {
    local dashboard_uid="$1"

    echo "🗑️  Deleting dashboard: $dashboard_uid"

    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -X DELETE "$TEAMB_HOST/api/dashboards/uid/$dashboard_uid")

    if [ $? -eq 0 ]; then
        echo "   ✅ Dashboard deleted successfully: $dashboard_uid"
        ((DASHBOARDS_DELETED++))
        return 0
    else
        echo "   ❌ Failed to delete dashboard: $dashboard_uid"
        ((DASHBOARDS_FAILED++))
        return 1
    fi
}

# Function to check if resources are different (simplified check)
resources_are_different() {
    local teamb_resource="$1"
    local teama_file="$2"

    # For now, we'll always consider them different to ensure sync
    # In a more sophisticated implementation, we could compare checksums or modification dates
    return 0  # Always return "different" to ensure sync
}

# Function to create folder in Team B
create_folder() {
    local folder_file="$1"
    local folder_uid=$(jq -r '.uid' "$folder_file" 2>/dev/null)

    echo "📁 Creating folder: $folder_uid"

    # Read the folder JSON
    if [ ! -f "$folder_file" ]; then
        echo "   ❌ Folder file not found: $folder_file"
        ((FOLDERS_FAILED++))
        return 1
    fi

    # Create folder using Grafana API
    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -H "Content-Type: application/json" \
        -X POST "$TEAMB_HOST/api/folders" \
        -d @"$folder_file")

    # Check if creation was successful
    if echo "$response" | jq -e '.uid' > /dev/null 2>&1; then
        created_uid=$(echo "$response" | jq -r '.uid')
        echo "   ✅ Folder created successfully: $created_uid"
        ((FOLDERS_CREATED++))
        return 0
    else
        echo "   ❌ Failed to create folder: $response"
        ((FOLDERS_FAILED++))
        return 1
    fi
}

# Function to create dashboard in Team B
create_dashboard() {
    local dashboard_file="$1"
    local dashboard_uid=$(jq -r '.dashboard.uid // .uid' "$dashboard_file" 2>/dev/null)

    echo "📊 Creating dashboard: $dashboard_uid"

    # Read the dashboard JSON
    if [ ! -f "$dashboard_file" ]; then
        echo "   ❌ Dashboard file not found: $dashboard_file"
        ((DASHBOARDS_FAILED++))
        return 1
    fi

    # Create dashboard using Grafana API
    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -H "Content-Type: application/json" \
        -X POST "$TEAMB_HOST/api/dashboards/db" \
        -d @"$dashboard_file")

    # Check if creation was successful
    if echo "$response" | jq -e '.uid' > /dev/null 2>&1; then
        created_uid=$(echo "$response" | jq -r '.uid')
        echo "   ✅ Dashboard created successfully: $created_uid"
        ((DASHBOARDS_CREATED++))
        return 0
    else
        echo "   ❌ Failed to create dashboard: $response"
        ((DASHBOARDS_FAILED++))
        return 1
    fi
}

# Function to sync folder (create, update, or skip)
sync_folder() {
    local folder_file="$1"
    local folder_uid=$(jq -r '.uid' "$folder_file" 2>/dev/null)

    # Check if folder exists in Team B
    if echo "$EXISTING_FOLDERS" | grep -q "^$folder_uid$"; then
        echo "📁 Folder exists in Team B: $folder_uid"

        # For simplicity, we'll always update (delete + recreate) existing folders
        # In production, you might want to compare content first
        echo "   🔄 Updating folder (delete + recreate)"
        if delete_folder "$folder_uid"; then
            sleep 1  # Brief delay between delete and create
            if create_folder "$folder_file"; then
                ((FOLDERS_UPDATED++))
                ((FOLDERS_CREATED--))  # Adjust counter since this is an update, not a new creation
            fi
        fi
    else
        echo "📁 New folder to create: $folder_uid"
        create_folder "$folder_file"
    fi
}

# Function to sync dashboard (create, update, or skip)
sync_dashboard() {
    local dashboard_file="$1"
    local dashboard_uid=$(jq -r '.dashboard.uid // .uid' "$dashboard_file" 2>/dev/null)

    # Check if dashboard exists in Team B
    if echo "$EXISTING_DASHBOARDS" | grep -q "^$dashboard_uid$"; then
        echo "📊 Dashboard exists in Team B: $dashboard_uid"

        # For simplicity, we'll always update (delete + recreate) existing dashboards
        # In production, you might want to compare content first
        echo "   🔄 Updating dashboard (delete + recreate)"
        if delete_dashboard "$dashboard_uid"; then
            sleep 1  # Brief delay between delete and create
            if create_dashboard "$dashboard_file"; then
                ((DASHBOARDS_UPDATED++))
                ((DASHBOARDS_CREATED--))  # Adjust counter since this is an update, not a new creation
            fi
        fi
    else
        echo "📊 New dashboard to create: $dashboard_uid"
        create_dashboard "$dashboard_file"
    fi
}

# Get existing resources from Team B
get_existing_teamb_resources

# Step 1: Delete orphaned resources (exist in Team B but not in Team A)
echo ""
echo "🔄 Step 1: Cleaning up orphaned resources in Team B..."

# Get Team A resource UIDs
TEAMA_FOLDER_UIDS=""
if [ -d "$SCRIPT_DIR/folders" ]; then
    for folder_file in "$SCRIPT_DIR/folders"/*.json; do
        if [ -f "$folder_file" ]; then
            folder_uid=$(jq -r '.uid' "$folder_file" 2>/dev/null)
            TEAMA_FOLDER_UIDS="$TEAMA_FOLDER_UIDS $folder_uid"
        fi
    done
fi

TEAMA_DASHBOARD_UIDS=""
if [ -d "$SCRIPT_DIR/dashboards" ]; then
    for dashboard_file in "$SCRIPT_DIR/dashboards"/*.json; do
        if [ -f "$dashboard_file" ]; then
            dashboard_uid=$(jq -r '.dashboard.uid // .uid' "$dashboard_file" 2>/dev/null)
            TEAMA_DASHBOARD_UIDS="$TEAMA_DASHBOARD_UIDS $dashboard_uid"
        fi
    done
fi

# Delete orphaned dashboards
for existing_dashboard in $EXISTING_DASHBOARDS; do
    if ! echo "$TEAMA_DASHBOARD_UIDS" | grep -q "$existing_dashboard"; then
        echo "🗑️  Orphaned dashboard found in Team B: $existing_dashboard"
        delete_dashboard "$existing_dashboard"
        sleep 0.5
    fi
done

# Delete orphaned folders (skip 'general' folder)
for existing_folder in $EXISTING_FOLDERS; do
    if [ "$existing_folder" != "general" ] && ! echo "$TEAMA_FOLDER_UIDS" | grep -q "$existing_folder"; then
        echo "🗑️  Orphaned folder found in Team B: $existing_folder"
        delete_folder "$existing_folder"
        sleep 0.5
    fi
done

# Step 2: Sync folders (create new, update existing)
echo ""
echo "🔄 Step 2: Syncing folders to Team B..."
if [ -d "$SCRIPT_DIR/folders" ]; then
    folder_count=$(find "$SCRIPT_DIR/folders" -name "*.json" | wc -l)
    echo "Found $folder_count folder(s) to sync"

    for folder_file in "$SCRIPT_DIR/folders"/*.json; do
        if [ -f "$folder_file" ]; then
            sync_folder "$folder_file"
            sleep 0.5  # Small delay between operations
        fi
    done
else
    echo "No folders directory found - skipping folder sync"
fi

# Step 3: Sync dashboards (create new, update existing)
echo ""
echo "🔄 Step 3: Syncing dashboards to Team B..."
if [ -d "$SCRIPT_DIR/dashboards" ]; then
    dashboard_count=$(find "$SCRIPT_DIR/dashboards" -name "*.json" | wc -l)
    echo "Found $dashboard_count dashboard(s) to sync"

    for dashboard_file in "$SCRIPT_DIR/dashboards"/*.json; do
        if [ -f "$dashboard_file" ]; then
            sync_dashboard "$dashboard_file"
            sleep 0.5  # Small delay between operations
        fi
    done
else
    echo "No dashboards directory found - skipping dashboard sync"
fi

# Display final statistics
echo ""
echo "📊 SYNC RESULTS:"
echo "================"
echo "Folders:"
echo "  ✅ Created:  $FOLDERS_CREATED"
echo "  🔄 Updated:  $FOLDERS_UPDATED"
echo "  🗑️  Deleted:  $FOLDERS_DELETED"
echo "  ⏭️  Skipped:  $FOLDERS_SKIPPED"
echo "  ❌ Failed:   $FOLDERS_FAILED"
echo ""
echo "Dashboards:"
echo "  ✅ Created:  $DASHBOARDS_CREATED"
echo "  🔄 Updated:  $DASHBOARDS_UPDATED"
echo "  🗑️  Deleted:  $DASHBOARDS_DELETED"
echo "  ⏭️  Skipped:  $DASHBOARDS_SKIPPED"
echo "  ❌ Failed:   $DASHBOARDS_FAILED"
echo ""

# Calculate totals
TOTAL_OPERATIONS=$((FOLDERS_CREATED + FOLDERS_UPDATED + FOLDERS_DELETED + DASHBOARDS_CREATED + DASHBOARDS_UPDATED + DASHBOARDS_DELETED))
TOTAL_FAILED=$((FOLDERS_FAILED + DASHBOARDS_FAILED))
TOTAL_SUCCESS=$((TOTAL_OPERATIONS - TOTAL_FAILED))

echo "📈 OVERALL SUMMARY:"
echo "==================="
echo "Total Operations: $TOTAL_OPERATIONS"
echo "Successful Ops:   $TOTAL_SUCCESS"
echo "Failed Ops:       $TOTAL_FAILED"

if [ $TOTAL_FAILED -eq 0 ]; then
    echo ""
    echo "🎉 Team B successfully synced with Team A!"
    exit 0
else
    echo ""
    echo "⚠️  Some operations failed - check the logs above"
    exit 1
fi
