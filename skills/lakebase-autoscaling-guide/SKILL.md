---
name: lakebase-autoscaling-guide
description: Create, connect to, scale, branch, and tear down Databricks Lakebase Postgres on the Autoscaling tier using the `databricks postgres` CLI (v0.285.0+). Use when the user mentions Lakebase, Postgres on Databricks, scale-to-zero, compute units (CU), branching a database, the `databricks postgres` CLI, or asks how to connect a service to Lakebase. Covers the resource hierarchy (Project > Branch > Endpoint), OAuth-based connections, autoscaling bounds, branch lifecycle, the PostgREST data API, and Unity Catalog integration. Out of scope: the legacy Provisioned tier (`databricks database`).
---

# Lakebase Autoscaling Guide

Operate Databricks Lakebase Postgres on the **Autoscaling tier**. Autoscaling is the modern, default Lakebase tier: scale-to-zero, first-class branches, and a hierarchical resource model.

## When to apply this skill

- The user asks to create, connect to, branch, scale, or delete a Lakebase database.
- The user mentions `databricks postgres`, scale-to-zero, compute units / CU, branching a Postgres database on Databricks, or PostgREST.
- The user is troubleshooting Lakebase connectivity, OAuth tokens, or `permission denied for schema public`.
- A bundled slash command was invoked (`/lakebase-create`, `/lakebase-connect`, `/lakebase-scale`, `/lakebase-branch`, `/lakebase-status`, `/lakebase-destroy`).

If the user explicitly asks about the **Provisioned tier** (`databricks database create-database-instance`, `CU_1`/`CU_2`/`CU_4`/`CU_8` capacity tiers, the `DatabaseInstance` resource model), this skill does not apply — say so and stop. Note: `databricks psql` itself is NOT a Provisioned-only signal — the same command supports both tiers via `--provisioned` / `--autoscaling` flags.

## Prerequisites checklist

Before running any command, verify:

```bash
databricks --version            # must be 0.285.0 or higher
databricks auth profiles        # must show the target profile
psql --version                  # 14+ recommended; needed for shell access
jq --version                    # required by helper scripts
```

If the CLI is older, instruct the user to upgrade (e.g. `brew upgrade databricks`). Do not attempt workarounds — Autoscaling commands are gated on the CLI version.

## Resource model

Autoscaling Lakebase is hierarchical:

```
Project          projects/<project-id>
  └── Branch     projects/<project-id>/branches/<branch-id>
       └── Endpoint   projects/<project-id>/branches/<branch-id>/endpoints/<endpoint-id>
```

- **Project**: top-level container. Creating a project auto-provisions a `production` branch and a `primary` read-write endpoint. The project's `default_endpoint_settings` (autoscaling bounds + `suspend_timeout_duration`) become the template for any new branch's auto-created `primary` endpoint.
- **Branch**: copy-on-write database snapshot (think git branches). **A new branch automatically gets a `primary` read-write endpoint** that inherits the project's `default_endpoint_settings`. Override afterwards with `update-endpoint`.
- **Endpoint**: the compute that serves connections. `ENDPOINT_TYPE_READ_WRITE` (one per branch) or `ENDPOINT_TYPE_READ_ONLY` (replicas, multiple allowed). Each endpoint has its own `min_cu` / `max_cu` autoscaling bounds (range 0.5-32, with `max - min ≤ 16 CU`) and a `suspend_timeout_duration` (idle timer for scale-to-zero — `"0s"` disables suspension).

Resource IDs: 3-63 chars, lowercase letters/numbers/hyphens, must start with a letter. **2-char IDs are rejected by the API.**

API write/read asymmetry: requests use a `spec.*` wrapper (e.g. `--json '{"spec": {"autoscaling_limit_min_cu": 1}}'` with mask `"spec.autoscaling_limit_min_cu"`), but reads return the same fields under `status.*`. Treat `spec` as desired state and `status` as observed state.

## 60-second quickstart

```bash
PROFILE=my-profile
PROJECT=my-app

# 1. Create the project (auto-creates production branch + primary endpoint).
#    create-project ignores display_name in its payload — set it after with update-project.
databricks postgres create-project "$PROJECT" -p "$PROFILE"

# Optional: set a human-readable display name
databricks postgres update-project "projects/$PROJECT" "spec.display_name" \
  --json '{"spec": {"display_name": "My App"}}' \
  -p "$PROFILE"

# 2. Wait for endpoint to reach ACTIVE (usually 60-90s)
until [ "$(databricks postgres list-endpoints "projects/$PROJECT/branches/production" \
  -p "$PROFILE" -o json | jq -r '.[0].status.current_state')" = "ACTIVE" ]; do
  sleep 5
done

# 3. Connect (uses the helper script bundled with this skill)
bash scripts/connect.sh "projects/$PROJECT/branches/production/endpoints/primary" \
  --profile "$PROFILE"
```

## Core operations

Each operation has a dedicated reference under `references/` for depth. Load the matching reference when the user asks for more.

### Create a project

```bash
databricks postgres create-project <project-id> -p <PROFILE>
```

Auto-creates `branches/production` and `endpoints/primary` (defaults: `min_cu=1`, `max_cu=1`, `suspend_timeout_duration="0s"`).

`create-project` does **not** accept `display_name` in its payload — the field is silently ignored. To set a human-readable name, follow up with:

```bash
databricks postgres update-project projects/<project-id> "spec.display_name" \
  --json '{"spec": {"display_name": "<Display Name>"}}' \
  -p <PROFILE>
```

### Connect

The simplest path is `databricks psql` with the autoscaling flags — it handles host lookup, token issuance, and identity for you:

```bash
databricks psql --project <p> --branch <b> --endpoint <e> -p <PROFILE>
# or pass the full path:
databricks psql projects/<p>/branches/<b>/endpoints/<e> -p <PROFILE>
# pass extra args to the underlying psql after `--`:
databricks psql --project <p> -p <PROFILE> -- -d mydb -c "SELECT 1"
```

For programmatic access (Python, JDBC, services) you fetch the three pieces yourself:

```bash
HOST=$(databricks postgres get-endpoint projects/<p>/branches/<b>/endpoints/<e> \
  -p <PROFILE> -o json | jq -r '.status.hosts.host')
TOKEN=$(databricks postgres generate-database-credential \
  projects/<p>/branches/<b>/endpoints/<e> \
  -p <PROFILE> -o json | jq -r '.token')
EMAIL=$(databricks current-user me -p <PROFILE> -o json | jq -r '.userName')
PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=postgres user=$EMAIL sslmode=require"
```

OAuth tokens expire after **1 hour** — regenerate as needed. The bundled `scripts/connect.sh` automates the three lookups for shell use; `scripts/connection.py` does the same for Python (psycopg/psycopg2/SQLAlchemy). See [references/connecting.md](references/connecting.md).

### Scale an endpoint

```bash
databricks postgres update-endpoint \
  projects/<p>/branches/<b>/endpoints/<endpoint> \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 1.0, "autoscaling_limit_max_cu": 8.0}}' \
  -p <PROFILE>
```

Bounds: 0.5 ≤ min ≤ max ≤ 32 CU, with **`max - min ≤ 16 CU`** (a hard server-side cap). Setting `min_cu` to 0.5 enables scale-to-zero behavior; setting `min_cu >= 1` keeps the endpoint warm. See [references/scaling.md](references/scaling.md) for sizing guidance.

### Branch

```bash
databricks postgres create-branch projects/<p> <new-branch> \
  --json '{"spec": {"source_branch": "projects/<p>/branches/production", "no_expiry": true}}' \
  -p <PROFILE>
```

The new branch comes with a `primary` read-write endpoint already attached, sized from the project's `default_endpoint_settings`. To resize after creation:

```bash
databricks postgres update-endpoint projects/<p>/branches/<new-branch>/endpoints/primary \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2.0}}' \
  -p <PROFILE>
```

`suspend_timeout_duration` cannot be changed on an existing endpoint via `update-endpoint` — it's only settable at `create-endpoint` time, or for new branches' primary endpoints via the project's `default_endpoint_settings`.

To add a read-only replica, use `create-endpoint` with `endpoint_type: ENDPOINT_TYPE_READ_ONLY` and a 3+ char ID. See [references/branching.md](references/branching.md) for protection, deletion, and read-replica patterns.

### Inspect status

```bash
databricks postgres get-project projects/<p> -p <PROFILE> -o json
databricks postgres list-branches projects/<p> -p <PROFILE> -o json
databricks postgres list-endpoints projects/<p>/branches/<b> -p <PROFILE> -o json
```

Endpoint states to watch: `ACTIVE` (ready), `STARTING`, `IDLE` (scaled to zero), `STOPPED`, `FAILED`.

### Destroy

```bash
# Non-root branch (cascades to its endpoints; unprotect first if protected)
databricks postgres delete-branch projects/<p>/branches/<b> -p <PROFILE>

# Project (cascades to ALL branches, endpoints, and data — only way to remove the root branch)
databricks postgres delete-project projects/<p> -p <PROFILE>
```

**Always** confirm with the user before deleting. Deletion is permanent. Note:
- The default `production` branch is a **root** branch and cannot be deleted independently — only via deleting the whole project.
- Read-write endpoints can't be deleted on their own; delete the branch instead. Read-only replicas can.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `unknown command postgres` | CLI < 0.285.0 | Upgrade CLI |
| `Warning: unknown field` + `Unknown field path in update_mask` | JSON body or update-mask missing the `spec.` prefix | Wrap fields under `spec`; use `spec.<field>` in the mask |
| `Field endpoint_id must be at least 3 characters` | Endpoint/branch/project ID is 1-2 chars | Use 3+ char IDs |
| `display_name` doesn't appear after create | `create-project` ignores `display_name` payload | Set with `update-project` and mask `spec.display_name` |
| `permission denied for schema public` | Working in default `postgres` database | `CREATE DATABASE myapp;` then connect to `myapp` |
| Auth fails after working earlier | OAuth token expired (1h TTL) | Regenerate via `generate-database-credential` |
| Cannot delete read-write endpoint | Read-write endpoints are tied to the branch | Delete the branch instead (cascades) |
| Endpoint stuck in `STARTING` | Cold start from scale-to-zero | Wait a few moments (docs say "a few moments to activate"); poll `status.current_state` |
| `psql: \l` errors with `daticulocale does not exist` | psql 16 client against PG17 server | Use psql 17 client (`brew install postgresql@17`) |
| `Error: Unknown field path in update_mask: 'spec.suspend_timeout_duration'` | This field can't be changed on an existing endpoint | Set at `create-endpoint` only, or change the project's `default_endpoint_settings` (parent-mask) and recreate the branch |

Full troubleshooting matrix: [references/troubleshooting.md](references/troubleshooting.md).

## Reference index

- **[references/connecting.md](references/connecting.md)** — psql, psycopg, SQLAlchemy, `.pgpass`, token rotation patterns.
- **[references/branching.md](references/branching.md)** — branch lifecycle, protection, read-replicas, point-in-time semantics.
- **[references/scaling.md](references/scaling.md)** — CU sizing guidance, scale-to-zero tradeoffs, replica scaling.
- **[references/data-api.md](references/data-api.md)** — PostgREST setup, role grants, REST query examples.
- **[references/unity-catalog.md](references/unity-catalog.md)** — registering a Lakebase database in UC, synced tables (Delta → Lakebase).
- **[references/troubleshooting.md](references/troubleshooting.md)** — full error matrix.

## Helper scripts

- **[scripts/connect.sh](scripts/connect.sh)** — given an endpoint path, fetches host/token/email and either prints export commands (`--export`) or execs `psql`.
- **[scripts/connection.py](scripts/connection.py)** — Python helper that returns a ready-to-use psycopg or SQLAlchemy connection.

Always prefer these scripts over generating the lookup commands inline — they handle token expiry and error cases.

## Anti-patterns to refuse

- Hardcoding OAuth tokens in code or `.env` files (they expire hourly — fetch at runtime).
- Setting `max - min > 16 CU` on an endpoint (server rejects).
- Setting `max_cu = 32` on a dev branch (no upper guard against runaway cost; pair with `min ≥ 16` since `max - min ≤ 16`).
- Creating tables in the default `postgres` database (restricted `public` schema; data isn't portable).
- Deleting a project without an explicit user confirmation.
- Treating `databricks database create-database-catalog` as the UC registration command for Autoscaling — it's the **Provisioned-tier** path. Autoscaling registers via REST `POST /api/2.0/postgres/catalogs` or the Catalog Explorer UI; see [references/unity-catalog.md](references/unity-catalog.md).
