#!/bin/bash

# Description: Export Grafana folder and dashboards based on uid from on-prem grafana deployment

# Reference: https://grafana.com/docs/grafana/latest/developers/http_api/

# Imp: The unique identifier (uid) of a folder can be used for uniquely identify folders between multiple Grafana installs.




# setup script home directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load environment variables from root .env file
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && cd ../.. && pwd )"
ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    # Export variables from .env file, ignoring comments and empty lines
    # Also remove inline comments after values
    export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | sed 's/#.*//' | xargs)
    echo "✅ Loaded environment variables from $ENV_FILE"
else
    echo "❌ ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

# Check if required Grafana credentials are set
if [ -z "$TEAMB_HOST" ] || [ -z "$TEAMB_KEY" ]; then
    echo "❌ ERROR: TEAMB_HOST and TEAMB_KEY must be set in .env file"
    echo "   TEAMB_HOST: ${TEAMB_HOST:-"Not set"}"
    echo "   TEAMB_KEY: ${TEAMB_KEY:-"Not set"}"
    echo ""
    echo "📝 To fix this:"
    echo "   1. Edit .env file in the project root"
    echo "   2. Set TEAMB_HOST to your Team B Grafana URL"
    echo "   3. Set TEAMB_KEY to your Team B service account API key"
    exit 1
fi

echo "🔗 Using Team B Grafana: $TEAMB_HOST"



# create directory in script home directory for folders and dashboards
if [ ! -d $SCRIPT_DIR/dashboards ] ; then
    mkdir -p $SCRIPT_DIR/dashboards
fi
if [ ! -d $SCRIPT_DIR/folders ] ; then
    mkdir -p $SCRIPT_DIR/folders
fi

# fetch dashboard details
for dash in $(curl -s -k -H "Authorization: Bearer $TEAMB_KEY" $TEAMB_HOST/api/search\?query\=\& | jq -r '.[] | select(.type == "dash-db") | .uid'); do
  curl -s -k -H "Authorization: Bearer $TEAMB_KEY" "$TEAMB_HOST/api/dashboards/uid/$dash" \
    | jq '. |= (.folderUid=.meta.folderUid) |del(.meta) |del(.dashboard.id) + {overwrite: true}' \
    > dashboards/${dash}.json
  echo "Dashboard: ${dash} saved."
done

# fetch folder details
for folder in $(curl -s -k -H "Authorization: Bearer $TEAMB_KEY" $TEAMB_HOST/api/folders |  jq -r '.[] | .uid'); do
  curl -s -k -H "Authorization: Bearer $TEAMB_KEY" $TEAMB_HOST/api/folders/$folder \
    | jq '. |del(.id) + {overwrite: true}' \
    > folders/${folder}.json
  echo "Folder: ${folder} saved."
done