# Connecting to Lakebase Autoscaling

`databricks psql` is the simplest interactive path — it supports Autoscaling via the `--autoscaling`, `--project`, `--branch`, and `--endpoint` flags (CLI 0.285.0+). For programmatic access, fetch host + OAuth token + identity yourself and use any standard Postgres client.

## Contents

- `databricks psql` (recommended for interactive use)
- The three pieces every programmatic connection needs
- Direct `psql` (without the wrapper)
- psycopg (v3, recommended)
- psycopg2 (v2, widely deployed)
- SQLAlchemy
- Java/JDBC
- Token rotation patterns
- `.pgpass` and connection strings

## `databricks psql` (interactive)

```bash
# Auto-select branch/endpoint when only one exists
databricks psql --project my-app -p $PROFILE

# Full path
databricks psql projects/my-app/branches/production/endpoints/primary -p $PROFILE

# Pass extra args to underlying psql after `--`
databricks psql --project my-app -p $PROFILE -- -d shop -c "SELECT count(*) FROM users;"

# Restrict to autoscaling projects in interactive selector
databricks psql --autoscaling -p $PROFILE
```

Requires `psql` on `$PATH` (the wrapper does **not** auto-discover Homebrew install locations — if you see `Error: exec: "psql": executable file not found in $PATH`, prepend `/opt/homebrew/opt/postgresql@17/bin` or `/opt/homebrew/opt/postgresql@16/bin` to `PATH`). The bundled `scripts/connect.sh` includes that fallback if you need it.

The CLI handles host lookup, OAuth token issuance, and identity. Use this for ad-hoc queries; use the explicit-credential flow below for services and scripts that need long-running or pooled connections.

## The three pieces every connection needs

Every connection needs:

1. **Host** — from `databricks postgres list-endpoints <branch> -o json | jq -r '.[].status.hosts.host'`. One host per endpoint.
2. **OAuth token** — from `databricks postgres generate-database-credential <endpoint> -o json | jq -r '.token'`. **Expires in 1 hour.** Fetch at runtime; never hardcode.
3. **User identity** — your Databricks user email, from `databricks current-user me -o json | jq -r '.userName'`. The token is bound to this principal.

Port is always `5432`. SSL is required (`sslmode=require`).

## Direct psql

```bash
PROFILE=my-profile
ENDPOINT=projects/my-app/branches/production/endpoints/primary

HOST=$(databricks postgres get-endpoint "$ENDPOINT" -p "$PROFILE" -o json \
  | jq -r '.status.hosts.host')
TOKEN=$(databricks postgres generate-database-credential "$ENDPOINT" -p "$PROFILE" -o json \
  | jq -r '.token')
EMAIL=$(databricks current-user me -p "$PROFILE" -o json | jq -r '.userName')

PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=postgres user=$EMAIL sslmode=require"
```

`get-endpoint` returns a single object directly — no need to list and filter. Endpoint resources are identified by `name` (the full path) and `uid` (a UUID string); there is **no `.id` field** on the API responses.

Run a single statement:

```bash
PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=mydb user=$EMAIL sslmode=require" \
  -c "SELECT count(*) FROM users;"
```

The bundled `scripts/connect.sh` wraps these three lookups. Prefer it over inlining.

## psycopg (v3, recommended for new code)

```python
import json, subprocess
import psycopg

def connect(project: str, branch: str, endpoint: str, profile: str, dbname: str = "postgres"):
    branch_path = f"projects/{project}/branches/{branch}"
    endpoint_path = f"{branch_path}/endpoints/{endpoint}"

    host = json.loads(subprocess.check_output(
        ["databricks", "postgres", "list-endpoints", branch_path,
         "--profile", profile, "--output", "json"]
    ))[0]["status"]["hosts"]["host"]

    token = json.loads(subprocess.check_output(
        ["databricks", "postgres", "generate-database-credential", endpoint_path,
         "--profile", profile, "--output", "json"]
    ))["token"]

    email = json.loads(subprocess.check_output(
        ["databricks", "current-user", "me", "--profile", profile, "--output", "json"]
    ))["userName"]

    return psycopg.connect(
        host=host, port=5432, dbname=dbname,
        user=email, password=token, sslmode="require",
    )

with connect("my-app", "production", "primary", "my-profile", "shop") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM products;")
        print(cur.fetchone())
```

## psycopg2 (v2)

Same shape, swap the import and `psycopg2.connect(...)`:

```python
import psycopg2
conn = psycopg2.connect(
    host=host, port=5432, database=dbname,
    user=email, password=token, sslmode="require",
)
```

(Note: psycopg2 uses `database=` while psycopg v3 uses `dbname=`.)

## SQLAlchemy

```python
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

# host, email, token from the same lookups as above
url = f"postgresql+psycopg://{email}:{quote_plus(token)}@{host}:5432/{dbname}?sslmode=require"
engine = create_engine(url, pool_pre_ping=True)

with engine.connect() as conn:
    for row in conn.execute(text("SELECT now();")):
        print(row)
```

`pool_pre_ping=True` recycles dead connections that may exist after a scale-to-zero idle period.

## Java / JDBC

```
jdbc:postgresql://<host>:5432/<dbname>?ssl=true&sslmode=require
```

Use the OAuth token as the password and the user email as the username. Set the JDBC driver to `org.postgresql.Driver` (42.6+).

## Token rotation patterns

OAuth tokens expire after **1 hour**. Choose a rotation strategy:

- **Short-lived scripts**: fetch at start, ignore expiry. Fine for migrations and one-off DDL.
- **Long-running services**: fetch at startup, then refresh every 50 minutes via a background task. Reconnect with the new token (Postgres has no in-protocol token refresh).
- **Connection pools**: hook into the pool's connection-creation callback to call `generate-database-credential` per new physical connection. Set pool `max_lifetime < 60min` so connections recycle before expiry.

For a Databricks App or service principal, prefer a service-principal token over a user token — the user-bound flow above is for human/dev access.

## `.pgpass` and persistent connection strings

`.pgpass` works but the password line goes stale every hour, so it is rarely worth it. If you do use it:

```
# ~/.pgpass (chmod 600)
<host>:5432:*:<email>:<token>
```

Then:

```bash
psql "host=<host> port=5432 dbname=mydb user=<email> sslmode=require"
```

Better: source a generated env file:

```bash
bash scripts/connect.sh "$ENDPOINT" --profile "$PROFILE" --export > /tmp/lakebase.env
source /tmp/lakebase.env
psql "$LAKEBASE_URL"
```

`scripts/connect.sh --export` prints `LAKEBASE_HOST`, `LAKEBASE_USER`, `LAKEBASE_PASSWORD`, and a ready-to-use `LAKEBASE_URL`.
