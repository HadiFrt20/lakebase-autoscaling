# Data API (PostgREST)

Lakebase exposes a PostgREST-compatible REST API on the same endpoint that serves SQL. This lets web/mobile clients query Postgres directly via HTTPS without a backend.

## Contents

- One-time setup: roles and grants
- Querying via REST
- Writing via REST
- Filtering, ordering, pagination
- Auth model
- When to use the data API vs. SQL

## One-time setup

The data API works through PostgREST's "authenticator → role" model. Set this up once per database:

```sql
-- Connect to the target database first (CREATE DATABASE myapp; \c myapp)

-- 1. The authenticator is the role PostgREST connects as. It LOGINs but
--    doesn't itself have data permissions.
CREATE ROLE authenticator LOGIN NOINHERIT;

-- 2. The api_user role is what queries actually run as. It's the role
--    the authenticator switches into per-request.
CREATE ROLE api_user NOLOGIN;
GRANT api_user TO authenticator;

-- 3. Grant data permissions to api_user.
GRANT USAGE ON SCHEMA public TO api_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO api_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO api_user;

-- 4. Make grants apply to future tables/sequences too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO api_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO api_user;
```

For row-level security, add `RLS` policies bound to `api_user` (standard Postgres `CREATE POLICY` syntax).

## URL shape

The Data API URL is exposed per-project in the **API tab of the project's Catalog Explorer page**. Copy the `REST_ENDPOINT` value from there; the path appended to it is `<schema>/<table>`. Schemas other than `public` work the same way.

```
$REST_ENDPOINT/<schema>/<table>
```

For example, if `REST_ENDPOINT=https://<host>/.../v1/projects/my-app/branches/production/databases/shop/data`, then the users table at `public.users` is queried at `$REST_ENDPOINT/public/users`.

Do **not** hand-construct the path from host + workspace ID — the actual prefix has changed across releases and is not documented as a stable URL template. Always read it from the project's API tab (or the equivalent SDK call) and treat it as opaque.

## Querying

```bash
TOKEN=$(databricks postgres generate-database-credential <endpoint-path> -p $PROFILE -o json | jq -r '.token')
# REST_ENDPOINT comes from the project's API tab — copy/paste it.
REST_ENDPOINT="https://<host>/.../v1/projects/my-app/branches/production/databases/shop/data"

# All rows in public.users
curl -H "Authorization: Bearer $TOKEN" \
  "$REST_ENDPOINT/public/users"

# Filter with PostgREST operators (eq, like, in are documented)
curl -H "Authorization: Bearer $TOKEN" \
  "$REST_ENDPOINT/public/users?status=eq.active&limit=50"

# Order
curl -H "Authorization: Bearer $TOKEN" \
  "$REST_ENDPOINT/public/users?order=created_at.desc"

# Select specific columns
curl -H "Authorization: Bearer $TOKEN" \
  "$REST_ENDPOINT/public/users?select=id,email"

# Pagination — use limit + offset query params (these are the only ones documented)
curl -H "Authorization: Bearer $TOKEN" \
  "$REST_ENDPOINT/public/users?limit=10&offset=0"
```

PostgREST upstream supports a wider operator set (`gt`, `lt`, `gte`, `lte`, `neq`, `ilike`, etc.) and `Range` header pagination, but the **Databricks docs only commit to** `eq`, `like`, `in` filters and `limit`/`offset` pagination. Other PostgREST features may work but are not contractually supported — verify on your target workspace before relying on them.

## Writing

```bash
# Insert
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"name": "Alice", "email": "alice@example.com"}' \
  "$REST_ENDPOINT/public/users"

# Bulk insert
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"name":"A","email":"a@x"},{"name":"B","email":"b@x"}]' \
  "$REST_ENDPOINT/public/users"

# Update (filter is required to prevent updating all rows)
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "archived"}' \
  "$REST_ENDPOINT/public/users?id=eq.42"

# Delete
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "$REST_ENDPOINT/public/users?id=eq.42"
```

## Auth model

The OAuth token in the `Authorization: Bearer` header is the same token used for direct Postgres connections — it expires in 1 hour. Issue a new one via `generate-database-credential`. For browser clients, proxy the token issuance through a backend; never ship the Databricks CLI to end users.

## When to use the data API vs. SQL

Use the data API when:

- A frontend needs typed CRUD without a custom backend.
- You want PostgREST's filter syntax in URLs.
- You're prototyping and want zero glue code.

Use direct SQL when:

- Performance matters (PostgREST adds overhead per request).
- You need transactions across multiple statements.
- You're running migrations, complex joins, or stored-procedure calls.
- The query doesn't fit PostgREST's CRUD/RPC shape.
