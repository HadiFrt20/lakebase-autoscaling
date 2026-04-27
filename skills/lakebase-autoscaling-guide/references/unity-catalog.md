# Unity Catalog Integration

Lakebase Autoscaling projects can be registered in Unity Catalog (UC) so they're queryable from Databricks SQL warehouses, notebooks, and Lakeflow pipelines. UC also powers **synced tables** — managed copies of UC tables inside a Lakebase project for low-latency serving — and **Lakehouse Sync**, which goes the other direction (Lakebase → Delta via CDC).

> **Important — namespace difference vs. Provisioned tier**: the `databricks database` CLI subcommands (`create-database-catalog`, `create-synced-database-table`, etc.) are the **Provisioned-tier** path. They take a `DATABASE_INSTANCE_NAME` (Provisioned's "DatabaseInstance" resource) and **do not work with Autoscaling projects**. As of CLI 0.289.1 there is **no `databricks postgres` CLI subcommand** for UC registration on Autoscaling. Use the REST API, SDK, or Catalog Explorer UI.

## Contents

- Register an Autoscaling project as a UC catalog
- Querying from Databricks SQL
- Synced tables (UC → Lakebase, low-latency serving)
- Lakehouse Sync (Lakebase → UC Delta, CDC)
- Permissions
- Troubleshooting

## Register an Autoscaling project

### Option A — Catalog Explorer UI (easiest)

1. Open Catalog Explorer in the workspace.
2. Click **+ Create catalog**.
3. Choose **Lakebase Postgres** as the catalog type.
4. Choose **Autoscaling**.
5. Pick the project, branch, and Postgres database to expose.
6. Name the catalog and save.

### Option B — REST API

```bash
TOKEN=$(databricks auth token -p <PROFILE> | jq -r '.access_token')
WORKSPACE_HOST=https://<workspace-host>

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$WORKSPACE_HOST/api/2.0/postgres/catalogs?catalog_id=lakebase_shop" \
  -d '{
    "spec": {
      "postgres_database": "shop",
      "branch": "projects/my-app/branches/production"
    }
  }'
```

- `catalog_id` — name the catalog will have in UC.
- `postgres_database` — the Postgres logical database (e.g. `shop`, **not** `postgres`).
- `branch` — full branch path; the catalog is bound to a specific branch, not just a project.

### Option C — Python SDK

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import DatabaseCatalog, DatabaseCatalogSpec

w = WorkspaceClient(profile="<PROFILE>")
w.postgres.create_catalog(
    catalog_id="lakebase_shop",
    catalog=DatabaseCatalog(
        spec=DatabaseCatalogSpec(
            postgres_database="shop",
            branch="projects/my-app/branches/production",
        )
    ),
)
```

(Java SDK has the analogous `w.postgres().createCatalog(...)`.)

## Querying from Databricks SQL

Once registered, query Lakebase tables like any UC table:

```sql
SELECT * FROM lakebase_shop.public.users LIMIT 10;

-- Joins against Delta tables work
SELECT u.email, count(o.id) AS orders
FROM lakebase_shop.public.users u
LEFT JOIN main.analytics.orders_fact o ON o.user_id = u.id
GROUP BY u.email;
```

Reads go through a federated query path — they hit Lakebase live, not a snapshot. Heavy analytical queries are usually better served by Lakehouse Sync (see below) so they read from Delta instead.

## Synced tables (UC → Lakebase, low-latency serving)

Synced tables let Databricks **maintain a copy of a UC-managed (Delta) table inside a Lakebase Autoscaling project** for low-latency serving. Sync runs continuously or on a schedule.

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$WORKSPACE_HOST/api/2.0/postgres/synced_tables" \
  -d '{
    "spec": {
      "name": "main.default.user_profiles",
      "branch": "projects/my-app/branches/production",
      "logical_database_name": "shop",
      "scheduling_policy": "CONTINUOUS"
    }
  }'
```

Python SDK:

```python
from databricks.sdk.service.postgres import SyncedTable, SyncedTableSpec, SchedulingPolicy

w.postgres.create_synced_table(
    SyncedTable(
        spec=SyncedTableSpec(
            name="main.default.user_profiles",
            branch="projects/my-app/branches/production",
            logical_database_name="shop",
            scheduling_policy=SchedulingPolicy.CONTINUOUS,
        )
    )
)
```

Sync modes:

- **CONTINUOUS** — change-data-captured updates within seconds of the Delta write.
- **TRIGGERED** — synced on a schedule or job trigger.
- **SNAPSHOT** — full overwrite; suitable for slowly-changing tables.

Use synced tables when:

- A web app needs millisecond reads from a Delta-managed dataset.
- A model serving endpoint needs feature-store reads.
- An ML pipeline produces inference outputs that customer-facing services consume.

## Lakehouse Sync (Lakebase → UC Delta, CDC)

The reverse direction: replicate Autoscaling tables **out** to UC as Delta tables via Change Data Capture. Set up under the project's **Sync** tab in Catalog Explorer (no CLI subcommand). Use this when transactional data written to Lakebase needs to feed analytics, ML training, or external warehouses.

## Permissions

Once registered, Lakebase catalogs use **standard UC grants**:

```sql
GRANT USE CATALOG ON CATALOG lakebase_shop TO `app-readers`;
GRANT USE SCHEMA ON SCHEMA lakebase_shop.public TO `app-readers`;
GRANT SELECT ON TABLE lakebase_shop.public.users TO `app-readers`;
```

UC permissions stack on top of Postgres-side `GRANT`s. A Postgres role still needs the appropriate object privileges for the UC user's identity to read/write.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `databricks database create-database-catalog` fails for an Autoscaling project | Wrong namespace — that command is for the Provisioned tier. Use REST `POST /api/2.0/postgres/catalogs`, the SDK, or the UI |
| `catalog not found` after creating | Race with metastore propagation; retry after 30s |
| `permission denied` from a SQL warehouse | UC grant missing OR Postgres grant missing for the principal |
| Synced table shows stale data | Continuous sync paused or failed; check the sync job status |
| `connection refused` in federated query | Endpoint scaled to zero; first query wakes it (allow time for cold start) |
| Looking for Terraform support | Tracking issue — autoscaling support for `databricks_database_database_catalog` is not yet GA. Use REST or SDK in the meantime |

## References

- Register Autoscaling in UC: https://docs.databricks.com/aws/en/oltp/projects/register-uc
- Synced tables: https://docs.databricks.com/aws/en/oltp/projects/sync-tables
- Get started: https://docs.databricks.com/aws/en/oltp/projects/get-started
- API usage: https://docs.databricks.com/aws/en/oltp/projects/api-usage
