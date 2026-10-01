# Burn Ledger v0.9.0

Local, evidence-aware tracking for AI subscription burn, model discovery, pricing changes, and completed-task yield.

Version 0.9.0 adds official OpenAI GPT-6.1 Sol, GPT-6 Astra, and GPT-6 Luna lifecycle/pricing evidence. GPT-6 Sol remains available as historical superseded data. API-equivalent task costs use OpenAI's short/long context bands: prompts above 272K input tokens apply 2× input/cache and 1.5× output pricing.

## What it does

- Tracks ChatGPT Plus/Work+Codex, Cursor Pro, Google AI Pro/Antigravity, and free overflow plans as separate subscription/harness records.
- Seeds the accepted Antigravity matched-telemetry routing matrix from the September 23, 2026 reconciliation.
- Automatically syncs a broad model catalog from the LiteLLM Model Catalog API and retains model price history.
- Watches current official OpenAI, Cursor, Google Antigravity, NVIDIA, and Nous sources for availability and semantic changes.
- Parses Cursor's official model pricing into structured price records and Antigravity's official model table into entitlements.
- Imports CSV/JSONL task telemetry, preserving retries and calculating completed tasks per visible quota point plus success-adjusted tokens/steps/time.
- Keeps general model discovery separate from paid-plan entitlement so a newly discovered model is never silently assumed to be included in a subscription.
- Exports JSON and CSV for other agents or analysis tools.
- Lets you disable a model vendor or individual plan model without deleting history; measured routing recommendations recalculate immediately from the remaining enabled lanes.
- Calculates a sortable **API-equivalent cost per task** from current Input/Cache/Output economics using selectable Micro, Standard, Long-horizon, or Massive-context reference workloads.
- Opens on a recommendation-first Overview with **Top 3 models for four task tiers**, ranked cheapest completed-task cost first after workload-fit and availability gates. Measured completion telemetry upgrades the ranking cost where available; unmeasured picks remain explicitly estimated.
- Adds an Overview **cost-basis toggle**: API $/completed task or measured Subscription $ + quota burn/completed task. Subscription mode never substitutes API prices for missing quota telemetry.

## Overview cost basis

The Top 3 board has two ranking modes:

- **API $ / task** — reference token economics, upgraded with observed success-adjusted token/retry burden when matching telemetry exists.
- **Subscription $ + burn** — measured subscription economics only. Effective $/completed task is derived from the current monthly plan price and measured weekly quota burn. Cards also show weekly and 5-hour percentage burn per completed task.

Subscription mode is intentionally evidence-gated. A tier with no comparable measured weekly burn shows a telemetry gap rather than silently falling back to API pricing.

## Run locally

```bash
./start.sh
```

Open: `http://127.0.0.1:8795`

Windows PowerShell:

```powershell
.\start.ps1
```

## Run with Docker

```bash
docker compose up -d --build
```

The compose file binds only to `127.0.0.1:8795` and persists SQLite data in `./data`.

## Automatic updates

Burn Ledger runs a source sync on startup and then every 6 hours by default. Change the interval from Settings or with the API. A sync:

1. Pulls the LiteLLM catalog for new models, capabilities, context sizes, and public model prices.
2. Parses Cursor's official model-pricing table and versions price changes.
3. Parses Google's Antigravity model table to refresh selectable entitlements.
4. Tracks source availability and hashes for diagnostics, but only raises Watch Desk alerts for semantic changes that can be identified safely.
5. Applies automatic plan-price changes for seeded plans only when an exact trusted extraction rule matches the official source (currently ChatGPT Plus, Cursor Pro, and Google AI Pro). Every change is added to price history. Otherwise it raises a review event.

This design is intentional: public API/catalog pricing can safely update automatically, while subscription inclusion and quota policy remain evidence-sensitive.

## Telemetry import

Upload `.csv` or `.jsonl` from the Telemetry screen. Current normalized fields include:

- `task_id`, `matched_pair_id`, `task_class`
- `model_id`, `reasoning` / `reasoning_level`, `quota_pool`
- `five_hour_before_pct`, `five_hour_after_pct`
- `weekly_before_pct`, `weekly_after_pct`
- `completed`, `first_pass_success`, `attempt_number`
- `tool_calls`, `agent_steps`
- `input_tokens`, `cache_tokens`, `output_tokens`
- `wall_clock_seconds`
- `telemetry_fidelity` (`exact_reported`, `quantized_quota`, or `unknown`; inferred when absent)
- `subagent_id` (optional agent identity for concurrent/subagent runs)
- `description` / `sanitized_description`

Task descriptions are redacted before storage by default.

## API

FastAPI docs: `http://127.0.0.1:8795/docs`

Useful endpoints:

- `GET /api/dashboard`
- `POST /api/sync`
- `GET /api/models` (paginated/sortable; defaults to enabled-plan entitlements)
- `GET /api/sources`
- `PATCH /api/sources/{id}`
- `POST /api/sources/{id}/sync`
- `POST /api/changes/{id}/ack`
- `POST /api/changes/ack-all`
- `GET /api/subscriptions`
- `GET /api/availability`
- `PATCH /api/availability/provider/{provider}`
- `PATCH /api/availability/model/{model_key}`
- `POST /api/telemetry/import`
- `GET /api/metrics`
- `GET /api/export.json`
- `GET /api/export.csv`

## Evidence model

Burn Ledger uses this precedence:

1. Account telemetry for actual subscription burn.
2. Official provider/harness sources for entitlement and plan rules.
3. Broad catalogs for discovery and price/capability hints.
4. User-configured values.
5. Explicitly labeled heuristics.

The application does not convert a catalog appearance into an entitlement automatically.

## Notes

- The app requires network access for automatic source sync. It still runs fully offline with its last SQLite state.
- Source fetch failures are recorded and do not erase last-known-good values.
- Antigravity whole-percent quota observations remain labeled quantized; `×100` yields are extrapolations, not guaranteed reset-window capacity.


## Upgrade from v0.5.0

Unzip v0.6.0 **over the same `burn-ledger` folder**. The release ZIP does not contain a database file, so `data/burn-ledger.db` is preserved. No destructive database migration is required.

```bash
cd ~/Apps
unzip -o ~/Downloads/Burn_Ledger_v0.6.0_2026-09-23.zip
cd burn-ledger
./start.sh
```

## Recommendation Overview (v0.6)

The Overview is now a decision page rather than a telemetry dump. It shows exactly three unique model families for each workload tier:

- Tier 1 — Light / short
- Tier 2 — Standard engineering
- Tier 3 — Deep / multi-file
- Tier 4 — Heavy agentic / long-horizon

Models must first pass a workload-suitability gate. Eligible models are then sorted by **API-equivalent completed-task cost**. When matching lane telemetry exists, Burn Ledger scales cost by observed success-adjusted token/retry burden and marks the value measured. Otherwise it uses the tier reference workload and marks the value estimated. The same underlying model is deduplicated when it appears through multiple subscriptions. Provider/model availability switches immediately refactor the Top 3 without deleting history.

## Upgrade from v0.4.0

Unzip v0.5.0 **over the same `burn-ledger` folder**. The release ZIP does not contain a database file, so `data/burn-ledger.db` is preserved. Existing telemetry, availability overrides, price history, source state, and model history remain intact. v0.5 adds derived task-cost comparison logic only; no destructive database migration is required.

```bash
cd ~/Apps
unzip -o ~/Downloads/Burn_Ledger_v0.5.0_2026-09-23.zip
cd burn-ledger
./start.sh
```

Provider switches apply to the actual model vendor across plans (for example Anthropic disables Claude models in both Cursor and Antigravity). Individual model switches apply by model key. Turning something back on restores it to routing without recreating any telemetry.


## Catalog enrichment (v0.4)

`My plan models` is an enriched view. Plan entitlements are matched to model-catalog records using normalized model identities rather than exact slugs only. Context and token economics are selected field-by-field from the strongest available source. Live official source rows take precedence; a last-known official baseline keeps core plan models populated when a watcher is temporarily unavailable. The table marks data as complete, partial, or unresolved and shows source provenance. Token $/M values are reference/API economics and are not used as a substitute for measured subscription burn.


## Cost per task (v0.5)

Model Catalog now includes a sortable **Cost / task** column. This is an API-equivalent reference estimate, not subscription-effective cost. Choose the comparison workload from the **Task profile** control:

- Micro: ~1,000 billable tokens
- Standard engineering: ~10,000
- Long-horizon: ~50,000
- Massive context: ~200,000

By default the profile uses the tracker token mix of 70% normal input, 20% cache-read input, and 10% output. The estimate updates automatically when the model's token pricing changes. If a provider publishes no cache-read price, Burn Ledger conservatively prices that portion at the normal input rate and labels the estimate accordingly.


## v0.8 overview comparison
The Overview now shows weekly subscription quota burn/task, estimated tasks per weekly allowance, and API $/completed task side by side. The ranking selector changes ordering only: lowest weekly quota burn or lowest API cost. Weekly quota values are shown only when measured.
