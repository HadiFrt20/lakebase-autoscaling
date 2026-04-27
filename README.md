# lakebase-autoscaling

A Claude Code plugin for managing **Databricks Lakebase Postgres on the Autoscaling tier** — projects, branches, endpoints, scaling, and connections — without memorizing JSON shapes or CLI flags.

> **Scope**: Autoscaling tier only (`databricks postgres`). The legacy Provisioned tier (`databricks database`) is intentionally out of scope.

## What it does

- **Six slash commands** for the full Lakebase Autoscaling lifecycle: create, connect, scale, branch, status, destroy.
- **One skill** (`lakebase-autoscaling-guide`) that auto-loads when you ask about Lakebase, Postgres on Databricks, branching, scale-to-zero, or compute units.
- **Helper scripts** that fetch host + OAuth token + user email and exec `psql` for you (with brew-PATH fallback the built-in `databricks psql` doesn't have).
- **Progressive-disclosure references** for connecting (psql/psycopg/SQLAlchemy), branching, scaling guidance, the Data API, Unity Catalog integration (REST/SDK — Autoscaling has no `databricks` CLI subcommand for UC yet), and troubleshooting.

## Prerequisites

| Requirement | Why | How |
|---|---|---|
| Databricks CLI **0.285.0+** | Autoscaling commands are gated on this version | `brew install databricks` (then `databricks --version`) |
| Authenticated profile | All commands take `-p PROFILE` | `databricks auth login --host <workspace-url> --profile <name>` |
| `psql` 16+ (optional) | Needed for `/lakebase-connect` and DDL | `brew install postgresql@16` |
| `jq` | Used by helper scripts | `brew install jq` |

A workspace with Lakebase Postgres enabled is required. Ask your Databricks workspace admin if unsure.

## Installation

Install from a local clone or git URL via the Claude Code marketplace:

```bash
# Clone
git clone https://github.com/<owner>/lakebase-autoscaling.git
claude plugin marketplace add ./lakebase-autoscaling
claude plugin install lakebase-autoscaling@lakebase-autoscaling

# Or directly from a git URL
claude plugin marketplace add https://github.com/<owner>/lakebase-autoscaling.git
claude plugin install lakebase-autoscaling@lakebase-autoscaling
```

Verify it loaded: type `/` and look for the `lakebase-*` commands.

## Quick start

```bash
# 1. Create a project (auto-creates `production` branch + `primary` endpoint)
/lakebase-create my-app --profile my-profile

# 2. Open a psql shell — shortest path is the built-in CLI wrapper
databricks psql --project my-app -p my-profile

#    Or use this plugin's command for --export (env vars), Python services, custom DB:
/lakebase-connect projects/my-app/branches/production/endpoints/primary

# 3. Branch off production for dev work
/lakebase-branch my-app dev --from production

# 4. Bump capacity for a load test (max - min ≤ 16 CU)
/lakebase-scale projects/my-app/branches/production/endpoints/primary --min 1 --max 8

# 5. See state at a glance
/lakebase-status my-app

# 6. Tear down (with confirmation)
/lakebase-destroy projects/my-app
```

## Commands

| Command | Purpose |
|---|---|
| `/lakebase-create <project-id>` | Create a project; verify `production` branch + `primary` endpoint reach `ACTIVE`. |
| `/lakebase-connect <endpoint-path>` | Fetch host + OAuth token + user email; print env vars or exec `psql`. |
| `/lakebase-scale <endpoint-path>` | Update `autoscaling_limit_min_cu` / `autoscaling_limit_max_cu` (range 0.5–32). |
| `/lakebase-branch <project> <branch>` | Branch from a source (default `production`) and attach an endpoint. |
| `/lakebase-status <project>` | List branches + endpoints with current state. |
| `/lakebase-destroy <path>` | Delete a project or branch with explicit confirmation. |

## Skill

The bundled skill `lakebase-autoscaling-guide` activates automatically when you mention Lakebase, Postgres on Databricks, scale-to-zero, compute units, branching, or the `databricks postgres` CLI. It teaches Claude:

- The Autoscaling resource hierarchy: `Project > Branch > Endpoint`.
- That `databricks psql` does **not** work on Autoscaling (use direct `psql` with an OAuth token).
- That OAuth tokens expire after 1 hour and must be regenerated.
- That you must `CREATE DATABASE` before tables — the default `postgres` database has a restricted `public` schema.
- Sizing guidance for `min_cu` / `max_cu` based on workload.

Deep references live under `skills/lakebase-autoscaling-guide/references/` and load only when relevant.

## Resources

- Lakebase docs: https://docs.databricks.com/aws/en/oltp/
- Databricks CLI: https://docs.databricks.com/dev-tools/cli/index.html
- Issues / PRs: open in this repo.

## License

MIT — see [LICENSE](./LICENSE).
