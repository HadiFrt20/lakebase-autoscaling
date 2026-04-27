#!/usr/bin/env bash
# connect.sh — fetch host + OAuth token + user email for a Lakebase Autoscaling
# endpoint and either print export commands or exec psql.
#
# Usage:
#   bash connect.sh <endpoint-path> [--profile PROFILE] [--db DBNAME] [--export]
#
# Examples:
#   # Open an interactive psql shell against the primary endpoint:
#   bash connect.sh projects/my-app/branches/production/endpoints/primary --profile dev
#
#   # Connect to a specific database:
#   bash connect.sh projects/my-app/branches/production/endpoints/primary --db shop
#
#   # Print export lines (LAKEBASE_HOST, LAKEBASE_USER, LAKEBASE_PASSWORD, LAKEBASE_URL):
#   bash connect.sh projects/my-app/branches/production/endpoints/primary --export
#
# Requirements: databricks CLI 0.285.0+, jq, psql (unless --export).

set -euo pipefail

ENDPOINT_PATH=""
PROFILE="DEFAULT"
DBNAME="postgres"
EXPORT_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile|-p) PROFILE="$2"; shift 2 ;;
    --db|-d)      DBNAME="$2";  shift 2 ;;
    --export)     EXPORT_ONLY=true; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0 ;;
    -*)
      echo "Unknown flag: $1" >&2
      exit 2 ;;
    *)
      if [[ -z "$ENDPOINT_PATH" ]]; then ENDPOINT_PATH="$1"; shift
      else echo "Unexpected positional arg: $1" >&2; exit 2; fi ;;
  esac
done

if [[ -z "$ENDPOINT_PATH" ]]; then
  echo "Usage: bash connect.sh <endpoint-path> [--profile PROFILE] [--db DBNAME] [--export]" >&2
  exit 2
fi

# Resource IDs: 3-63 chars, start with a lowercase letter, only [a-z0-9-]. The API rejects shorter/non-conforming IDs.
ID='[a-z][a-z0-9-]{2,62}'
if ! [[ "$ENDPOINT_PATH" =~ ^projects/${ID}/branches/${ID}/endpoints/${ID}$ ]]; then
  echo "Endpoint path must be projects/<p>/branches/<b>/endpoints/<e>" >&2
  echo "  where each <id> is 3-63 chars, lowercase letters/digits/hyphens, starting with a letter." >&2
  echo "  got: $ENDPOINT_PATH" >&2
  exit 2
fi

command -v jq >/dev/null || { echo "jq not found; brew install jq" >&2; exit 1; }
command -v databricks >/dev/null || { echo "databricks CLI not found" >&2; exit 1; }

CLI_VERSION=$(databricks --version 2>/dev/null | awk '{print $NF}' | sed 's/^v//')
if ! awk -v v="$CLI_VERSION" 'BEGIN{split(v,a,".");exit !(a[1]>0 || a[2]>=285)}'; then
  echo "databricks CLI must be >= 0.285.0 (found $CLI_VERSION)" >&2
  exit 1
fi

HOST=$(databricks postgres get-endpoint "$ENDPOINT_PATH" --profile "$PROFILE" --output json \
  | jq -er '.status.hosts.host')

TOKEN=$(databricks postgres generate-database-credential "$ENDPOINT_PATH" \
  --profile "$PROFILE" --output json | jq -er '.token')

EMAIL=$(databricks current-user me --profile "$PROFILE" --output json | jq -er '.userName')

if $EXPORT_ONLY; then
  cat <<EOF
export LAKEBASE_HOST="$HOST"
export LAKEBASE_USER="$EMAIL"
export LAKEBASE_PASSWORD="$TOKEN"
export LAKEBASE_DBNAME="$DBNAME"
export LAKEBASE_URL="postgresql://$EMAIL:\${LAKEBASE_PASSWORD}@$HOST:5432/$DBNAME?sslmode=require"
EOF
  exit 0
fi

if ! command -v psql >/dev/null; then
  for d in /opt/homebrew/opt/postgresql@17/bin /opt/homebrew/opt/postgresql@16/bin /usr/local/opt/postgresql@17/bin /usr/local/opt/postgresql@16/bin; do
    if [ -x "$d/psql" ]; then PATH="$d:$PATH"; break; fi
  done
fi
command -v psql >/dev/null || { echo "psql not found on PATH; brew install postgresql@17" >&2; exit 1; }

PGPASSWORD="$TOKEN" exec psql "host=$HOST port=5432 dbname=$DBNAME user=$EMAIL sslmode=require"
