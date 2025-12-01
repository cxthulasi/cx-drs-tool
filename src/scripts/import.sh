#!/bin/bash

# Description: Export Grafana folder and dashboards based on uid from on-prem grafana deployment

# Reference: https://grafana.com/docs/grafana/latest/developers/http_api/

# Imp: The unique identifier (uid) of a folder can be used for uniquely identify folders between multiple Grafana installs.

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

# Check if required Grafana credentials are set
if [ -z "$TEAMA_HOST" ] || [ -z "$CX_API_KEY_TEAMA" ]; then
    echo "❌ ERROR: TEAMA_HOST and CX_API_KEY_TEAMA must be set"
    echo "   TEAMA_HOST: ${TEAMA_HOST:-"Not set"}"
    echo "   CX_API_KEY_TEAMA: ${CX_API_KEY_TEAMA:-"Not set"}"
    echo ""
    echo "📝 To fix this:"
    echo "   - For local: Edit .env file in the project root"
    echo "   - For K8s: Check ConfigMap and Secrets are properly mounted"
    echo "   1. Set TEAMA_HOST to your Team A Grafana URL"
    echo "   2. Set CX_API_KEY_TEAMA to your Team A service account API key"
    exit 1
fi

echo "🔗 Using Team A Grafana: $TEAMA_HOST"

# setup script home directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# create directory in script home directory for folders and dashboards
if [ ! -d $SCRIPT_DIR/dashboards ] ; then
    mkdir -p $SCRIPT_DIR/dashboards
fi
if [ ! -d $SCRIPT_DIR/folders ] ; then
    mkdir -p $SCRIPT_DIR/folders
fi

# fetch dashboard details
for dash in $(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMA" $TEAMA_HOST/api/search\?query\=\& | jq -r '.[] | select(.type == "dash-db") | .uid'); do
  curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMA" "$TEAMA_HOST/api/dashboards/uid/$dash" \
    | jq '. |= (.folderUid=.meta.folderUid) |del(.meta) |del(.dashboard.id) + {overwrite: true}' \
    > dashboards/${dash}.json
  echo "Dashboard: ${dash} saved."
done

# fetch folder details
for folder in $(curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMA" $TEAMA_HOST/api/folders |  jq -r '.[] | .uid'); do
  curl -s -k -H "Authorization: Bearer $CX_API_KEY_TEAMA" $TEAMA_HOST/api/folders/$folder \
    | jq '. |del(.id) + {overwrite: true}' \
    > folders/${folder}.json
  echo "Folder: ${folder} saved."
done