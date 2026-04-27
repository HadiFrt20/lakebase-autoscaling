# Scaling Lakebase Autoscaling Endpoints

Each endpoint scales automatically between `autoscaling_limit_min_cu` and `autoscaling_limit_max_cu`. Tuning these bounds is the main lever you have.

## Contents

- What a Compute Unit (CU) is
- Default bounds and the legal range
- Sizing heuristic
- Scale-to-zero
- Read replicas
- Updating bounds
- Cost notes

## What a Compute Unit is

One CU is a fixed bundle of CPU + memory provisioned for the endpoint. Lakebase exposes it as a fractional unit so endpoints can scale smoothly under load.

- 0.5 CU — minimum; suitable for dev/preview/scale-to-zero.
- 1 CU — typical "always on" baseline for low-traffic prod.
- 2-4 CU — moderate web app or service.
- 8-16 CU — high-throughput workloads, complex queries, large indexes.
- 32 CU — maximum per endpoint.

For workloads that exceed 32 CU, scale **horizontally** with read replicas, or split data across multiple databases. Note also that the `max_cu - min_cu` span on a single endpoint cannot exceed **16 CU** — see "Default bounds and the legal range" below.

## Default bounds and the legal range

A freshly created `primary` endpoint defaults to `min=1`, `max=1` (no autoscaling — fixed at 1 CU). Update bounds explicitly to enable autoscaling:

```bash
databricks postgres update-endpoint <endpoint-path> \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 4.0}}' \
  -p <PROFILE>
```

The legal range:

- `0.5 ≤ min_cu ≤ max_cu ≤ 32`
- **`max_cu - min_cu ≤ 16`** — server-enforced. The official docs say: *"The difference between your maximum and minimum cannot exceed 16 CU."* So `min=0.5, max=32` is rejected; `min=16, max=32` is allowed.

Both bounds must be supplied together in the same update.

## Sizing heuristic

A starting point — measure and adjust. Every row below respects the `max - min ≤ 16` cap:

| Workload | min_cu | max_cu | Notes |
|---|---|---|---|
| Local dev / preview branches | 0.5 | 1 | Scale-to-zero saves cost when idle |
| Low-traffic prod (<100 RPS) | 1 | 4 | Avoids cold starts; absorbs bursts |
| Mid-traffic prod (100-1k RPS) | 2 | 8 | Headroom for index rebuilds and analytics |
| High-traffic prod (>1k RPS) | 4 | 16 | Add read replicas before pushing further |
| Heavy analytics, predictable peak | 8 | 24 | 16 CU span is the max — must keep min ≥ 8 if you want max=24 |
| Batch ETL bursting to ceiling | 16 | 32 | Highest legal cap; expensive when always-on |

To go beyond 32 CU effective capacity, scale **horizontally** with read replicas (each replica has its own 0.5-32 / 16-span autoscaling envelope).

If p99 latency creeps up under load, increase `max_cu` (and `min_cu` if you'd cross the 16 CU span). If the endpoint sits at `max_cu` constantly, raise the floor — you are oversaturating, not bursting. If the endpoint never crosses 30% of `max_cu`, lower `max_cu` to cap cost.

## Scale-to-zero

Scale-to-zero is controlled by **two** settings, not one:

1. `autoscaling_limit_min_cu = 0.5` — allows the endpoint to scale below 1 CU.
2. `suspend_timeout_duration` — the idle timer (Go-style duration string, e.g. `"300s"`). When the endpoint sees no activity for this long, it suspends. `"0s"` **disables** suspension entirely (the endpoint stays warm at `min_cu`).

**Asymmetry to remember**: `suspend_timeout_duration` is settable at `create-endpoint` time, but `update-endpoint` rejects it as an unknown field. To change the suspend behavior of an existing endpoint:

- For an auto-created `primary`: change the project's `default_endpoint_settings` and recreate the branch (read-write endpoints can't be deleted independently).
- For a read-only replica: delete and recreate the endpoint with the new value.

What you CAN change on an existing endpoint via `update-endpoint`: `autoscaling_limit_min_cu`, `autoscaling_limit_max_cu`, `disabled`.

```bash
# Set min/max bounds on an existing endpoint
databricks postgres update-endpoint <endpoint-path> \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2}}' \
  -p <PROFILE>

# Set suspend_timeout_duration at endpoint creation only
databricks postgres create-endpoint <branch-path> replica-1 \
  --json '{"spec": {
    "endpoint_type": "ENDPOINT_TYPE_READ_ONLY",
    "autoscaling_limit_min_cu": 0.5,
    "autoscaling_limit_max_cu": 2,
    "suspend_timeout_duration": "300s"
  }}' \
  -p <PROFILE>
```

Suspended endpoints:

- Cost only **storage**, not compute.
- Take a few moments to wake on the next connection — Databricks docs say only "It may take a few moments for your compute to activate" without a firm SLA. Plan for several seconds at minimum.
- Show `current_state: IDLE` while suspended.

Use scale-to-zero for:
- Dev / preview / per-PR branches.
- Internal tools used by humans during business hours.
- Anything where occasional 30s wake latency is acceptable.

Do **not** use scale-to-zero for:
- User-facing prod paths with strict latency SLOs.
- Cron jobs that fire every few minutes (they keep paying wake costs).

To set defaults for **all future branches** in a project, configure the project's `default_endpoint_settings`. The mask must target the **parent** field (`spec.default_endpoint_settings`), and the body must include every field you want kept — the API replaces the whole object:

```bash
databricks postgres update-project projects/<p> "spec.default_endpoint_settings" \
  --json '{"spec": {"default_endpoint_settings": {
    "autoscaling_limit_min_cu": 0.5,
    "autoscaling_limit_max_cu": 2,
    "suspend_timeout_duration": "300s"
  }}}' \
  -p <PROFILE>
```

Leaf-path masks like `spec.default_endpoint_settings.suspend_timeout_duration` are rejected as unknown — use the parent mask. Note: this only affects branches created **after** the update. Existing endpoints keep their old settings.

## Read replicas (horizontal scaling)

If `max_cu = 32` is not enough on the primary, add read replicas:

```bash
databricks postgres create-endpoint projects/<p>/branches/<b> replica-1 \
  --json '{"spec": {
    "endpoint_type": "ENDPOINT_TYPE_READ_ONLY",
    "autoscaling_limit_min_cu": 1,
    "autoscaling_limit_max_cu": 8
  }}' \
  -p <PROFILE>
```

Each replica has its own host. Application traffic is **not** automatically split — your app or pgbouncer decides which host serves a given query.

## Updating bounds

```bash
databricks postgres update-endpoint <endpoint-path> \
  "spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu" \
  --json '{"spec": {"autoscaling_limit_min_cu": 1.0, "autoscaling_limit_max_cu": 8.0}}' \
  -p <PROFILE>
```

The two-argument form (`spec.foo,spec.bar` followed by `--json`) is a field mask: it tells the API to update only those fields. Always pass both `min` and `max` to avoid leaving them inconsistent.

The update is online — existing connections keep working. New capacity comes online within a few seconds.

## Cost notes

Pricing is region-dependent. Charges accrue for:

- **Compute**: per CU-hour, prorated to the actual CU consumed (autoscaling means you pay only for what you use within the bounds).
- **Storage**: per GB-month for the branch's data.
- **PITR storage**: per GB-month for the WAL retained for point-in-time branching.

For current rates see https://www.databricks.com/product/pricing — Lakebase / OLTP section.

A useful mental model: if `min_cu = 1` and the endpoint is idle 24/7, you pay for 1 CU × 720 hours/month plus storage. Setting `min_cu = 0.5` with an idle workload often cuts compute cost by 50-90% via scale-to-zero, at the cost of cold-start latency.
