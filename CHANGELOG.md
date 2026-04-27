# Changelog

All notable changes to this plugin are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-27

### Added
- Initial release.
- Six lifecycle commands: `/lakebase-create`, `/lakebase-connect`, `/lakebase-scale`, `/lakebase-branch`, `/lakebase-status`, `/lakebase-destroy`.
- `lakebase-autoscaling-guide` skill with progressive-disclosure references.
- Helper scripts: `connect.sh` (bash, fetches host/token/email and exec psql) and `connection.py` (Python, psycopg/SQLAlchemy helpers).
- Reference docs: connecting, branching, scaling, data-api, unity-catalog, troubleshooting.

### Validated against live workspace (CLI 0.289.1)
The following were confirmed end-to-end by creating, connecting to, scaling, branching, and destroying a real project:
- `spec.*` wrapper is required for both update-mask paths and `--json` request bodies; reads return the same fields under `status.*`.
- Resource lookup uses `.name` (full path) — `.id` does not exist on read responses. `connect.sh` and `connection.py` switched to `get-endpoint`-by-name.
- `create-project` silently ignores `display_name` in its payload — must be set via `update-project` with mask `spec.display_name`.
- `create-branch` auto-creates a `primary` read-write endpoint sized from the project's `default_endpoint_settings` (contradicts older docs that said branches start endpoint-less).
- Endpoint/branch/project IDs must be **3-63 chars** (2-char IDs like `rw` are rejected). Examples updated to `replica-1` etc.
- Scale-to-zero is controlled by **two** settings together: `autoscaling_limit_min_cu` and `suspend_timeout_duration` (Go duration string, `"0s"` disables suspension). Documented in `references/scaling.md`.
- psql 16 client against PG17 server: `\l` and similar meta-commands fail (`daticulocale does not exist`). Recommend `postgresql@17` client.
- `suspend_timeout_duration` is **asymmetric**: settable at `create-endpoint` time but `update-endpoint` rejects it as an unknown field. To change suspend behavior on an existing endpoint, recreate it (or for a branch's `primary`, change the project's `default_endpoint_settings` and recreate the branch).
- Update-mask **leaf paths** inside nested objects are rejected (`spec.default_endpoint_settings.suspend_timeout_duration` fails). Use the **parent-field mask** (`spec.default_endpoint_settings`) and provide the entire object — the API replaces it wholesale.
- `connect.sh` now auto-finds `psql` at standard Homebrew locations (`postgresql@17`/`postgresql@16`) when not on `PATH`.
- Validated end-to-end: `psycopg` v3, `psycopg2`, and `TokenRefresher` all connect to a live endpoint and run real queries.
- Discovered: **root branches (`production`) cannot be deleted independently** — server returns `Cannot delete root branch ... Root branches cannot be deleted independently.` regardless of protection state. The only way to remove the root branch is to delete the whole project. `is_protected` is an *additional* manual lock for non-root branches.

### Adversary-review fixes
After running `dr-adversary` on the docs, the following claims were corrected:
- **CU span constraint added**: `max - min ≤ 16 CU` is server-enforced (per Databricks public docs). Sizing tables in `references/scaling.md` were missing this; rows like `min=4, max=32` were illegal. All examples now respect the cap.
- **`databricks psql` works on Autoscaling**: the previous claim that it "doesn't work on Autoscaling" was wrong — CLI 0.289.1's `databricks psql` exposes `--autoscaling`, `--project`, `--branch`, `--endpoint` flags. Documented as the recommended interactive path.
- **Data API URL shape rewritten**: the previous `https://<host>/api/2.0/workspace/<id>/rest/...` template was not in any public doc and is unsupported. The correct approach: copy `REST_ENDPOINT` from the project's API tab (Catalog Explorer) and treat it as opaque. Pagination corrected from `Range`/`Range-Unit` headers (upstream PostgREST, not documented for Databricks) to `?limit=N&offset=M`.
- **Unity Catalog reference rewritten end-to-end**: the previous content used `databricks database create-database-catalog` and `databricks database create-synced-database-table`, which are **Provisioned-tier** commands and don't accept Autoscaling project paths. Autoscaling registration uses **REST `POST /api/2.0/postgres/catalogs`** + **Python/Java SDK** + Catalog Explorer UI. There is **no `databricks postgres` CLI subcommand** for UC registration as of CLI 0.289.1 (Apr 2026). Terraform support is also pending (databricks/terraform-provider-databricks#5389).
- **Cold-start timing softened**: removed the "30-60 seconds" folk number; Databricks docs only commit to "a few moments to activate."
- **`/lakebase-destroy` UC cascade caveat**: removed the assumption that delete-project cleans up registered UC catalogs — undocumented behavior, treat UC integration as separately managed.
