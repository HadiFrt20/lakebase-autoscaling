# Troubleshooting Lakebase Autoscaling

A focused error matrix for the Autoscaling tier. For lifecycle/branching issues see [branching.md](branching.md); for connectivity see [connecting.md](connecting.md).

## Contents

- CLI-level errors
- Auth and OAuth errors
- Connection errors
- SQL / permission errors
- Endpoint state errors
- Data API errors
- Cost and capacity surprises

## CLI-level errors

### `unknown command "postgres"`
The Databricks CLI is older than 0.285.0. Autoscaling commands were added in that release.
```bash
brew upgrade databricks      # macOS
databricks --version         # confirm 0.285.0+
```

### `Error: invalid character ... in JSON`
The `--json` flag value isn't valid JSON. Quote it correctly and prefer single quotes around the outer JSON so the inner double quotes survive.

### `Warning: unknown field: <field>` and `Error: Unknown field path in update_mask: '<field>'`
The request body and update-mask paths require a `spec.` wrapper. Symmetric pattern: body is `{"spec": {"foo": ...}}` and mask is `"spec.foo"`. Reads return the same field under `status.foo` (output-only); don't use that on writes.

### `Field endpoint_id must be at least 3 characters`
Endpoint, branch, and project IDs are 3-63 chars. Two-char IDs like `rw` or `ro` are rejected. Use `read-write`, `replica-1`, etc.

### `display_name` ignored on `create-project`
The `create-project` payload silently drops `display_name` (the project's display name initializes to the project ID). Set it after creation:
```bash
databricks postgres update-project projects/<p> "spec.display_name" \
  --json '{"spec": {"display_name": "..."}}' -p $PROFILE
```

### `Error: failed to load profile`
The named profile doesn't exist or the workspace is unreachable.
```bash
databricks auth profiles                                    # list profiles
databricks auth login --host <workspace-url> --profile <p>  # re-auth
```

### `Endpoint ID validation error`
Endpoint, branch, and project IDs must be 3-63 characters, lowercase letters/numbers/hyphens only, and start with a letter.

## Auth and OAuth errors

### `FATAL: password authentication failed for user "..."`
Three causes:
1. **OAuth token expired.** Tokens last 1 hour. Regenerate with `databricks postgres generate-database-credential <endpoint>`.
2. **Wrong user.** The token is bound to the principal who minted it. The `user=` in the connection string must match `databricks current-user me -o json | jq -r '.userName'`.
3. **Wrong endpoint.** Tokens are scoped to the endpoint they were generated for. Don't reuse a primary token against a replica.

### `FATAL: SSL connection is required`
Add `sslmode=require` to the connection string. Lakebase rejects unencrypted connections.

## Connection errors

### `connection refused`
- Endpoint state is not `ACTIVE`. Check: `databricks postgres list-endpoints <branch-path> -o json | jq '.[].status.current_state'`.
- Endpoint is `IDLE` (scaled to zero) and your client times out before wake. Increase client connect timeout to 60s; subsequent queries will be fast.

### `could not translate host name`
Wrong host. Always re-fetch from `status.hosts.host` — host strings are not stable across resource recreations.

### `database "myapp" does not exist`
You connected before running `CREATE DATABASE myapp;`. Connect to `dbname=postgres` first, run the CREATE, then reconnect to `dbname=myapp`.

### Connection works locally but fails from a CI/cloud runner
The Databricks workspace network may have a firewall or private link. Check with the workspace admin; some workspaces require the client to be inside a specific VPC or VNet.

### `psql: \l` errors with `column d.daticulocale does not exist`
psql 16 client connected to Postgres 17 server. Functional queries (`SELECT`, `CREATE`, etc.) still work; only meta-commands like `\l` break. Upgrade the client: `brew install postgresql@17` and `export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"`.

## SQL / permission errors

### `permission denied for schema public`
You connected to the default `postgres` database. Its `public` schema is restricted. Always create your own database first:
```sql
CREATE DATABASE myapp;
\c myapp
-- Now CREATE TABLE, etc., work normally.
```

### `must be owner of table ...`
You're operating as a non-owner principal. Either grant explicit privileges to your role or run the operation as the owner.

### `role "..." does not exist`
The Postgres role hasn't been created. You're connecting as a Databricks user identity — the role with that email is auto-created on first connect, but other roles (like `api_user`) need explicit `CREATE ROLE`.

## Endpoint state errors

### Stuck in `STARTING` for >2 minutes
Check `status.failure_reason` in the endpoint JSON. If empty, wait — large branches can take longer to wake. If a reason is present, file an issue with the workspace admin.

### `current_state: FAILED`
The endpoint is broken. Try `update-endpoint` with the same bounds to nudge it; if that fails, recreate the endpoint (`delete-endpoint` + `create-endpoint`, or delete the branch and re-create from source).

### Cannot delete read-write endpoint
By design — the read-write endpoint is owned by the branch. Delete the **branch** instead; it cascades to all its endpoints.

### `branch is protected`
Unprotect first:
```bash
databricks postgres update-branch projects/<p>/branches/<b> "spec.is_protected" \
  --json '{"spec": {"is_protected": false}}' -p $PROFILE
```

## Data API errors

### `401 Unauthorized` from `/rest/...`
- OAuth token expired or wrong endpoint. Same fix as direct SQL auth.
- The `authenticator` role wasn't created in the target database. Re-run the data API setup SQL from [data-api.md](data-api.md).

### `404 Not Found` for an existing table
- Check the URL path: `<dbname>/<schema>/<table>` — easy to misspell.
- The `api_user` role lacks `USAGE` on the schema. Re-grant.

### `42501 permission denied for table ...`
The `api_user` role lacks SELECT/INSERT/UPDATE/DELETE. Re-run the GRANT statements.

## Cost and capacity surprises

### Bill higher than expected
- Check actual CU usage via the workspace's billing dashboard.
- An endpoint with `min_cu = 1` runs 24/7 even when idle. Lower to 0.5 for scale-to-zero on non-prod.
- A branch you forgot about: `databricks postgres list-branches projects/<p>` and audit.

### Endpoint sat at `max_cu` and queries still slow
- You hit the ceiling. Increase `max_cu`, or add a read replica and route reads to it.
- Check for unindexed query plans — adding capacity won't fix a missing index.

### "Why did the endpoint start running queries on its own?"
Synced tables and federated queries from UC also drive load. Disable or pause them while debugging cost.
