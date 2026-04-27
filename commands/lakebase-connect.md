---
name: lakebase-connect
description: Connect to a Databricks Lakebase Autoscaling endpoint via psql, or print the connection env vars. Handles host lookup, OAuth token issuance, and user identity.
argument-hint: <endpoint-path> [--profile PROFILE] [--db DBNAME] [--export]
---

# /lakebase-connect

Open a `psql` shell against a Lakebase Autoscaling endpoint, or print the connection details as exportable env vars.

For interactive use, the simplest path is to call `databricks psql` directly with the autoscaling flags — it handles host lookup, OAuth token, and identity. This command exists for the cases the wrapper doesn't cover: `--export` for service configs, custom connection-string formatting, and pinning a specific database via `--db`.

## Usage

```
/lakebase-connect <endpoint-path> [--profile PROFILE] [--db DBNAME] [--export]
```

Arguments:

- `<endpoint-path>` — required. Full path: `projects/<p>/branches/<b>/endpoints/<e>`.
- `--profile` — Databricks CLI profile.
- `--db` — Postgres database to connect to. Defaults to `postgres` (the bootstrap database). For real work, point at a database you created with `CREATE DATABASE`.
- `--export` — instead of opening psql, print `LAKEBASE_HOST`, `LAKEBASE_USER`, `LAKEBASE_PASSWORD`, `LAKEBASE_DBNAME`, and `LAKEBASE_URL` as `export` lines that can be `eval`'d or sourced.

## Alternative: `databricks psql`

For interactive use without `--export` or a custom DB name, just run:

```bash
databricks psql <endpoint-path> -p <PROFILE>
# or pass extra psql args after `--`
databricks psql --project <p> -p <PROFILE> -- -d shop -c "SELECT 1"
```

`/lakebase-connect` falls back to this when no `--export` and `--db` is the default `postgres`.

## Execution

Invoke the `lakebase-autoscaling-guide` skill, then run the bundled helper:

```bash
bash skills/lakebase-autoscaling-guide/scripts/connect.sh <endpoint-path> \
  --profile <PROFILE> \
  [--db <DBNAME>] \
  [--export]
```

The helper:

1. Validates the endpoint path matches `projects/<p>/branches/<b>/endpoints/<e>`.
2. Confirms `databricks` ≥ 0.285.0 and `jq` are present.
3. Looks up `status.hosts.host` for the endpoint.
4. Issues a fresh OAuth token (1-hour TTL).
5. Resolves the user email via `databricks current-user me`.
6. Either `exec`s `psql` (interactive) or prints export lines (with `--export`).

## When to use `--export`

- Configuring a long-running service or notebook where you'll reuse the credentials.
- Sourcing the values into other tooling (`pgcli`, `dbeaver`, custom scripts).
- Emitting credentials into `/tmp/<file>` then `source`ing them.

Do **not** check the printed values into source control or paste them into chat. The token expires in 1 hour; treat it like any short-lived secret.

## Reminders to surface

- For simple interactive use, `databricks psql` (with `--project`/`--branch`/`--endpoint` or a full endpoint path) is shorter than this command. Use `/lakebase-connect` for `--export`, custom database, or service config flows.
- The default `postgres` database has a restricted `public` schema. For tables, connect to a database you created with `CREATE DATABASE myapp;`.
- OAuth tokens last 60 minutes; long sessions need a fresh token.
