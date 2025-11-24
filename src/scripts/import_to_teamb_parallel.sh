#!/bin/bash

# Description: Sync Grafana folders and dashboards to Team B with PARALLEL BATCH PROCESSING
# This script processes dashboards in parallel batches to avoid timeouts with large datasets
# Key improvements:
# - Parallel processing of dashboards in configurable batch sizes
# - Reduced timeout risk for large migrations
# - Progress tracking and better error handling
# - macOS compatible (no flock, no grep -P)

# setup script home directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load environment variables from root .env file (macOS compatible)
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && cd ../.. && pwd )"
ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    # macOS compatible env loading - process line by line
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Remove inline comments and export
        line=$(echo "$line" | sed 's/#.*$//' | sed 's/[[:space:]]*$//')
        [ -n "$line" ] && export "$line"
    done < "$ENV_FILE"
    echo "✅ Loaded environment variables from $ENV_FILE"
else
    echo "❌ ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

# Check if required variables are set
if [ -z "$TEAMB_HOST" ] || [ -z "$CX_API_KEY_TEAMB" ]; then
    echo "❌ ERROR: TEAMB_HOST and CX_API_KEY_TEAMB must be set in .env file"
    exit 1
fi

echo "🚀 Starting PARALLEL sync to Team B Grafana"
echo "   Target: $TEAMB_HOST"

# Configuration for parallel processing
BATCH_SIZE=${GRAFANA_BATCH_SIZE:-10}  # Process 10 dashboards in parallel by default
MAX_PARALLEL_JOBS=${GRAFANA_MAX_PARALLEL:-5}  # Max 5 parallel jobs at once

echo "   Batch size: $BATCH_SIZE dashboards per batch"
echo "   Max parallel jobs: $MAX_PARALLEL_JOBS"

# Counters for statistics (using files for thread-safe counting)
STATS_DIR="$SCRIPT_DIR/.sync_stats_$$"
mkdir -p "$STATS_DIR"

# Initialize counter files
echo "0" > "$STATS_DIR/folders_created"
echo "0" > "$STATS_DIR/folders_updated"
echo "0" > "$STATS_DIR/folders_deleted"
echo "0" > "$STATS_DIR/folders_failed"
echo "0" > "$STATS_DIR/dashboards_created"
echo "0" > "$STATS_DIR/dashboards_updated"
echo "0" > "$STATS_DIR/dashboards_deleted"
echo "0" > "$STATS_DIR/dashboards_failed"

# Thread-safe counter increment (macOS compatible - no flock needed)
increment_counter() {
    local counter_file="$STATS_DIR/$1"

    # Simple increment - race conditions are acceptable for statistics
    # The slight inaccuracy is better than complex locking on macOS
    local count=$(cat "$counter_file" 2>/dev/null || echo "0")
    echo $((count + 1)) > "$counter_file"
}

# Function to get existing resources from Team B
get_existing_teamb_resources() {
    echo "🔍 Fetching existing resources from Team B..."
    
    EXISTING_DASHBOARDS=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" "$TEAMB_HOST/api/search?query=&" | jq -r '.[] | select(.type == "dash-db") | .uid' 2>/dev/null)
    EXISTING_FOLDERS=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" "$TEAMB_HOST/api/folders" | jq -r '.[] | .uid' 2>/dev/null)
    
    echo "   Found $(echo "$EXISTING_DASHBOARDS" | wc -w | tr -d ' ') existing dashboards"
    echo "   Found $(echo "$EXISTING_FOLDERS" | wc -w | tr -d ' ') existing folders"
}

# Function to delete folder from Team B
delete_folder() {
    local folder_uid="$1"
    
    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -X DELETE "$TEAMB_HOST/api/folders/$folder_uid")
    
    if [ $? -eq 0 ]; then
        increment_counter "folders_deleted"
        return 0
    else
        increment_counter "folders_failed"
        return 1
    fi
}

# Function to delete dashboard from Team B
delete_dashboard() {
    local dashboard_uid="$1"
    
    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -X DELETE "$TEAMB_HOST/api/dashboards/uid/$dashboard_uid")
    
    if [ $? -eq 0 ]; then
        increment_counter "dashboards_deleted"
        return 0
    else
        increment_counter "dashboards_failed"
        return 1
    fi
}

# Function to create folder in Team B
create_folder() {
    local folder_file="$1"
    local folder_uid=$(jq -r '.uid' "$folder_file" 2>/dev/null)
    
    if [ ! -f "$folder_file" ]; then
        increment_counter "folders_failed"
        return 1
    fi
    
    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -H "Content-Type: application/json" \
        -X POST "$TEAMB_HOST/api/folders" \
        -d @"$folder_file")
    
    if echo "$response" | jq -e '.uid' > /dev/null 2>&1; then
        increment_counter "folders_created"
        return 0
    else
        increment_counter "folders_failed"
        return 1
    fi
}

# Function to create dashboard in Team B
create_dashboard() {
    local dashboard_file="$1"
    local dashboard_uid=$(jq -r '.dashboard.uid // .uid' "$dashboard_file" 2>/dev/null)

    if [ ! -f "$dashboard_file" ]; then
        increment_counter "dashboards_failed"
        return 1
    fi

    response=$(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMB" \
        -H "Content-Type: application/json" \
        -X POST "$TEAMB_HOST/api/dashboards/db" \
        -d @"$dashboard_file")

    if echo "$response" | jq -e '.uid' > /dev/null 2>&1; then
        increment_counter "dashboards_created"
        return 0
    else
        increment_counter "dashboards_failed"
        return 1
    fi
}

# Function to sync folder (create, update, or skip)
sync_folder() {
    local folder_file="$1"
    local folder_uid=$(jq -r '.uid' "$folder_file" 2>/dev/null)

    if echo "$EXISTING_FOLDERS" | grep -q "^$folder_uid$"; then
        if delete_folder "$folder_uid"; then
            sleep 0.5
            if create_folder "$folder_file"; then
                increment_counter "folders_updated"
                # Decrement created counter since this is an update
                local created=$(cat "$STATS_DIR/folders_created")
                echo $((created - 1)) > "$STATS_DIR/folders_created"
            fi
        fi
    else
        create_folder "$folder_file"
    fi
}

# Function to sync dashboard (create, update, or skip) - PARALLEL SAFE
sync_dashboard() {
    local dashboard_file="$1"
    local dashboard_uid=$(jq -r '.dashboard.uid // .uid' "$dashboard_file" 2>/dev/null)

    if echo "$EXISTING_DASHBOARDS" | grep -q "^$dashboard_uid$"; then
        if delete_dashboard "$dashboard_uid"; then
            sleep 0.3
            if create_dashboard "$dashboard_file"; then
                increment_counter "dashboards_updated"
                # Decrement created counter since this is an update
                local created=$(cat "$STATS_DIR/dashboards_created")
                echo $((created - 1)) > "$STATS_DIR/dashboards_created"
            fi
        fi
    else
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

# Delete orphaned dashboards (sequential for safety)
for existing_dashboard in $EXISTING_DASHBOARDS; do
    if ! echo "$TEAMA_DASHBOARD_UIDS" | grep -q "$existing_dashboard"; then
        echo "🗑️  Orphaned dashboard: $existing_dashboard"
        delete_dashboard "$existing_dashboard"
        sleep 0.3
    fi
done

# Delete orphaned folders (skip 'general' folder)
for existing_folder in $EXISTING_FOLDERS; do
    if [ "$existing_folder" != "general" ] && ! echo "$TEAMA_FOLDER_UIDS" | grep -q "$existing_folder"; then
        echo "🗑️  Orphaned folder: $existing_folder"
        delete_folder "$existing_folder"
        sleep 0.3
    fi
done

# Step 2: Sync folders (sequential - folders are usually few)
echo ""
echo "🔄 Step 2: Syncing folders to Team B..."
if [ -d "$SCRIPT_DIR/folders" ]; then
    folder_count=$(find "$SCRIPT_DIR/folders" -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
    echo "Found $folder_count folder(s) to sync"

    for folder_file in "$SCRIPT_DIR/folders"/*.json; do
        if [ -f "$folder_file" ]; then
            sync_folder "$folder_file"
            sleep 0.3
        fi
    done
else
    echo "No folders directory found - skipping folder sync"
fi

# Step 3: Sync dashboards in PARALLEL BATCHES
echo ""
echo "🔄 Step 3: Syncing dashboards to Team B (PARALLEL BATCHES)..."
if [ -d "$SCRIPT_DIR/dashboards" ]; then
    dashboard_files=("$SCRIPT_DIR/dashboards"/*.json)
    total_dashboards=${#dashboard_files[@]}

    # Check if any dashboards exist
    if [ ! -f "${dashboard_files[0]}" ]; then
        echo "No dashboard files found - skipping dashboard sync"
    else
        echo "Found $total_dashboards dashboard(s) to sync"
        echo "Processing in batches of $BATCH_SIZE with max $MAX_PARALLEL_JOBS parallel jobs"

        processed=0
        batch_num=1

        # Process dashboards in batches
        for ((i=0; i<total_dashboards; i+=BATCH_SIZE)); do
            echo ""
            echo "📦 Processing batch $batch_num (dashboards $((i+1))-$((i+BATCH_SIZE > total_dashboards ? total_dashboards : i+BATCH_SIZE)) of $total_dashboards)"

            # Process batch in parallel
            for ((j=i; j<i+BATCH_SIZE && j<total_dashboards; j++)); do
                dashboard_file="${dashboard_files[$j]}"

                # Run sync_dashboard in background (parallel)
                (
                    sync_dashboard "$dashboard_file"
                ) &

                # Limit number of parallel jobs
                if (( (j - i + 1) % MAX_PARALLEL_JOBS == 0 )); then
                    wait  # Wait for current batch of parallel jobs to complete
                fi
            done

            # Wait for all jobs in this batch to complete
            wait

            processed=$((i + BATCH_SIZE))
            if [ $processed -gt $total_dashboards ]; then
                processed=$total_dashboards
            fi

            echo "✅ Batch $batch_num complete ($processed/$total_dashboards dashboards processed)"
            batch_num=$((batch_num + 1))
        done

        echo ""
        echo "✅ All dashboard batches completed!"
    fi
else
    echo "No dashboards directory found - skipping dashboard sync"
fi

# Read final statistics from counter files
FOLDERS_CREATED=$(cat "$STATS_DIR/folders_created")
FOLDERS_UPDATED=$(cat "$STATS_DIR/folders_updated")
FOLDERS_DELETED=$(cat "$STATS_DIR/folders_deleted")
FOLDERS_FAILED=$(cat "$STATS_DIR/folders_failed")
DASHBOARDS_CREATED=$(cat "$STATS_DIR/dashboards_created")
DASHBOARDS_UPDATED=$(cat "$STATS_DIR/dashboards_updated")
DASHBOARDS_DELETED=$(cat "$STATS_DIR/dashboards_deleted")
DASHBOARDS_FAILED=$(cat "$STATS_DIR/dashboards_failed")

# Clean up stats directory
rm -rf "$STATS_DIR"

# Display final statistics
echo ""
echo "📊 SYNC RESULTS:"
echo "================"
echo "Folders:"
echo "  ✅ Created:  $FOLDERS_CREATED"
echo "  🔄 Updated:  $FOLDERS_UPDATED"
echo "  🗑️  Deleted:  $FOLDERS_DELETED"
echo "  ❌ Failed:   $FOLDERS_FAILED"
echo ""
echo "Dashboards:"
echo "  ✅ Created:  $DASHBOARDS_CREATED"
echo "  🔄 Updated:  $DASHBOARDS_UPDATED"
echo "  🗑️  Deleted:  $DASHBOARDS_DELETED"
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

