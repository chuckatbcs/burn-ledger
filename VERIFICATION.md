# Burn Ledger v0.8.0 Verification

Release: 0.8.0  
Date: 2026-09-23

## Result

- **20/20 pytest tests pass.**
- `node --check app/static/app.js` passes.
- API smoke checks verify both ranking bases:
  - `api` ranks by API-equivalent dollars per completed task.
  - `quota` ranks by measured weekly quota percent per completed task.
  - legacy `subscription` query input remains accepted and maps to `quota`.
- Every returned recommendation preserves both economic fields when available:
  - `weekly_burn_pct_per_completed`
  - `tasks_per_weekly_quota`
  - `api_cost_per_completed_task`
- Quota-first ranking never invents weekly burn. Tier 1 and Tier 4 remain unranked in quota-first mode until matched weekly-burn telemetry exists.
- API-first ranking still shows measured weekly burn on cards when it exists.
- Availability overrides still remove disabled models/providers from either ranking without deleting history.
- JavaScript syntax verification passes.

## Current evidence coverage

- **API ranking:** all four workload tiers have recommendation-grade candidates.
- **Weekly-quota ranking:** Tier 2 and Tier 3 currently have comparable measured weekly burn from the matched Antigravity telemetry; Tier 1 and Tier 4 remain telemetry gaps.
- A weekly quota value is treated as measured only when the lane has completed-task telemetry with a positive weekly quota delta.

## Core comparison

For a completed task:

`weekly quota burn/task = weekly quota delta % / completed tasks`

`tasks per weekly allowance = 100 / weekly quota burn/task`

`API $/task = observed success-adjusted token burden × current input/cache/output pricing`

These are intentionally parallel measures. Burn Ledger does not convert quota percentage into API dollars or imply that the units are interchangeable.
