---
name: lakebase-scale
description: Update the autoscaling min/max compute units (CU) on a Lakebase Autoscaling endpoint. Range 0.5-32; both bounds applied together.
argument-hint: <endpoint-path> --min <min-cu> --max <max-cu> [--profile PROFILE]
---

# /lakebase-scale

Update `autoscaling_limit_min_cu` and `autoscaling_limit_max_cu` on an endpoint. The update is online — existing connections keep working; new capacity comes online within a few seconds.

## Usage

```
/lakebase-scale <endpoint-path> --min <min-cu> --max <max-cu> [--profile PROFILE]
```

Arguments:

- `<endpoint-path>` — required. `projects/<p>/branches/<b>/endpoints/<e>`.
- `--min`, `--max` — both required. Each must be in `[0.5, 32]`. `min ≤ max`. **`max - min ≤ 16`** (server-enforced).
- `--profile` — Databricks CLI profile.

## Execution

Invoke the `lakebase-autoscaling-guide` skill, then:

1. **Validate inputs**
   - `0.5 ≤ min ≤ max ≤ 32`.
   - `max - min ≤ 16` (the API rejects updates that violate this).
   - Endpoint exists: `databricks postgres get-endpoint <endpoint-path> --profile <PROFILE>` returns 200.

2. **Apply the update**
   ```bash
   databricks postgres update-endpoint <endpoint-path> \
     "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
     --json '{"spec": {"autoscaling_limit_min_cu": <min>, "autoscaling_limit_max_cu": <max>}}' \
     --profile <PROFILE>
   ```

3. **Print the diff** — show old vs. new bounds and the endpoint state.

## Sizing guidance

When the user asks "what bounds should I use?", refer to the table in
`skills/lakebase-autoscaling-guide/references/scaling.md`. Every example below respects `max - min ≤ 16`:

- Dev / preview: `min=0.5`, `max=1` (scale-to-zero saves cost).
- Low-traffic prod: `min=1`, `max=4`.
- Mid-traffic prod (100-1k RPS): `min=2`, `max=8`.
- High-traffic prod: `min=4`, `max=16` + read replicas.
- Bursting analytics: `min=8`, `max=24` or `min=16`, `max=32` (server-side cap is `max - min ≤ 16`).

Setting `min_cu = 0.5` enables scale-to-zero — the endpoint suspends when idle and pays only storage. Cold start can take a few moments on next connect (no firm SLA). Don't use scale-to-zero for latency-sensitive prod paths.

## Failure modes

- `min > max` → reject locally before calling the API.
- Endpoint not found → surface the error and stop.
- The API returns the same bounds → no-op; tell the user nothing changed.
