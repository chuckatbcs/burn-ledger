## 0.9.0 — 2026-09-30

- Added official OpenAI GPT-6.1 Sol, GPT-6 Astra, and GPT-6 Luna catalog/pricing evidence; retained GPT-6 Sol as explicitly superseded historical data.
- Added lifecycle/supersession metadata and idempotent migrations for catalog and entitlement rows.
- Added official 272K short/long context pricing bands: long prompts apply 2× input/cache and 1.5× output rates.
- Added OpenAI model/pricing source-watch entries and parser support; recalculated API-equivalent task economics and excluded superseded models from new recommendations.
- Kept quota-first recommendations evidence-gated: weekly burn is ranked/displayed only where measured telemetry exists.

## 0.8.1 — 2026-09-28
- Added additive telemetry provenance fields: `telemetry_fidelity` and `subagent_id`.
- Automatically classifies imported rows as `exact_reported`, `quantized_quota`, or `unknown` when the source does not provide a fidelity label.
- Preserved existing SQLite rows and recommendation behavior; the migration is in-place and non-destructive.

## 0.8.0 — 2026-09-23
- Reframed Overview around the user's actual comparison: weekly quota burn versus API cost for the same generalized completed task.
- Every ranked model now shows weekly quota %/task, estimated tasks per weekly allowance, and API $/task side by side.
- Ranking selector now chooses Lowest weekly quota burn or Lowest API cost; it no longer swaps the visible economics.
- Quota-first mode ranks only measured weekly-burn lanes and never fabricates missing percentages.
- Retained `recommendation_basis=subscription` as a legacy alias for quota-first ranking.

# Changelog

## 0.7.0 — 2026-09-23

### Added
- Overview segmented toggle for **API $ / task** vs **Subscription $ + burn**.
- Subscription-mode Top 3 ranking from measured weekly quota burn and current monthly plan price.
- Raw weekly and 5-hour quota burn per completed task on subscription-ranked cards.
- Coverage/readiness messaging when a tier lacks comparable measured subscription telemetry.

### Changed
- Measured successful completion evidence can promote a model into a tier even when the static family-fit prior was conservative.
- Availability switches refactor both API and subscription rankings.
- Subscription mode never falls back to API economics; missing evidence remains visibly unresolved.

## 0.6.0 — 2026-09-23

### Changed
- Rebuilt Overview around the user's actual decision: Top 3 recommended models for four workload tiers.
- Removed the old subscription-card / measured-lane / dual-routing clutter from the primary Overview surface. Detailed evidence remains available through Catalog and Telemetry.
- Recommendations deduplicate the same model family across multiple subscriptions.
- Capability-fit is now a hard gate before cost ranking, preventing cheap light models from winning heavy-agentic tiers.

### Added
- Tier 1 Light/short, Tier 2 Standard engineering, Tier 3 Deep/multi-file, and Tier 4 Heavy agentic/long-horizon recommendation cards.
- Cost-first Top 3 ordering using API-equivalent completed-task cost. Matching lane telemetry upgrades cost to measured success-adjusted evidence; otherwise the value is explicitly estimated.
- Overview evidence-coverage, source-health, subscription-stack and availability-impact readouts.
- Recommendation-quality notes that identify the next telemetry targets, source failures, availability refactors and new models waiting for fit evidence.

## 0.5.0 — 2026-09-23

- Added a sortable **Cost / task** column to Model Catalog.
- Added Micro (~1k), Standard (~10k), Long-horizon (~50k), and Massive-context (~200k) reference task profiles.
- Cost/task recalculates from current Input/Cache-read/Output economics whenever catalog pricing changes.
- Uses the configured 70/20/10 input/cache/output token mix by default.
- Explicitly labels the metric API-equivalent and keeps it separate from measured subscription burn.
- If cache-read pricing is missing, the estimate uses the normal input rate for that slice and labels the fallback; missing core prices remain unresolved.
- Added full-dataset sorting by cost/task for plan, official, and all-model catalog scopes.


## 0.4.0 — 2026-09-23

- Replaced brittle exact entitlement→catalog lookup with normalized cross-source model enrichment.
- Added field-by-field provenance for context and token economics.
- Added last-known official metadata baselines for core OpenAI, Anthropic, Google, Cursor, and xAI plan models so temporary watcher failures do not blank the catalog.
- Live official/catalog sources continue to supersede baseline data automatically.
- Added complete / partial / unresolved catalog-data status to My plan models.
- Clarified that $/M columns are reference/API economics, not measured subscription burn.
- Preserved all v0.3 availability controls and recommendation behavior.

## 0.3.0 — 2026-09-23

### Added
- Provider-level availability switches for Anthropic, Google, OpenAI, Cursor, xAI, and any future entitled provider discovered in the plan catalog.
- Per-model routing switches in **My plan models**. Disabling a model does not delete catalog, price, telemetry, or history rows.
- Availability-aware recommendation API and live routing cards.
- Recommendation provenance: cards show when the preferred baseline route was **refactored** because a model/provider was excluded.

### Routing logic
- Recommendation candidates must be both **entitled** and **enabled**. Imported telemetry for an unknown/unentitled model cannot become an active recommendation by itself.
- Within each measured quota pool and task tier, **quota-first** chooses the enabled model with the highest measured completed tasks per visible 1% quota point.
- **Time/reliability-first** chooses the enabled model with the lowest success-adjusted seconds per completed task, using first-pass rate and attempts/completed as tie-breakers.
- If a provider switch removes every measured model from a lane, the lane is shown as unavailable rather than silently crossing incomparable quota pools.

### Upgrade
- Adds the `availability_overrides` SQLite table in place; v0.2 data remains unchanged.

## 0.2.0 — 2026-09-23

### Fixed
- Watch Desk alerts are no longer read-only: dismiss one or dismiss all semantic alerts.
- Source failures now preserve the actual error text and consecutive-failure count.
- Source Watch adds Check now and Watching/Paused controls for every source.
- Raw whole-page hash changes no longer create noisy Watch Desk alerts; legacy `source_changed` alerts are auto-acknowledged during upgrade.
- Model Catalog no longer hard-caps the UI at 500 rows or silently hides the remainder.

### Added
- Server-side catalog pagination (25/50/100 rows), full-dataset sorting, scope filters, source/plan filtering, complete provider filters, and accurate result counts.
- Default **My plan models** view so the catalog opens on actionable entitlements instead of the entire discovery universe.
- `Official parsed catalogs` and `All discovered models` views for deeper research.
- Single-source retry API and source enable/disable API.
- In-place SQLite migration for new Source Watch error fields.

### Logic change
- Catalog discovery, entitlement evidence, semantic alerts, and source availability are now separate concepts. A page hash is not treated as a user-actionable change.

## 0.1.0 — 2026-09-23
- Initial local release with subscription stack, telemetry import, catalog discovery, source sync, price history, and v9 Antigravity consensus seed data.
