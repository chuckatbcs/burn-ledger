
## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Select/Listbox | Native select controls | UX-CONTRACT.md + index.html | native | keyboard + narrow viewport |
| Form | Native forms with application validation | UX-CONTRACT.md + app.js | settings / telemetry upload | unit + browser |
| Scrollbar | Global application stylesheet | DESIGN.md + styles.css | geometry exceptions only | computed layout + browser |
| Toast | Shared `#toast` live-region surface | UX-CONTRACT.md + app.js | status only | browser + accessibility |

# Burn Ledger UX Contract

## Canonical behaviors
- Navigation: one persistent section tab bar; the selected section is also stored in the URL hash.
- Tables: semantic tables inside panel-owned horizontal overflow; large datasets use server pagination instead of unbounded rendering.
- Model catalog: defaults to **My plan models**. Users can switch to official parsed catalogs or the complete discovery catalog. Search, scope, provider, source/plan, task profile, sort, page, and page size are explicit controls.
- Sorting: catalog column headers are keyboard-accessible buttons. Sorting applies to the full filtered dataset, not only the current page. **Cost / task** is sortable ascending/descending.
- Search: client-triggered remote search, 300 ms debounce, explicit clear button, no stale-result overwrite from older requests.
- Watch Desk: semantic change alerts can be dismissed individually or in bulk. Active source failures are separate operational items with Retry, Pause watcher, and Source Watch actions.
- Source Watch: every watcher can be paused/re-enabled and checked on demand. Failed checks show the actual last error and consecutive-failure count.
- Loading: action button text changes in place and remains the same size class; status text announces progress.
- Errors: inline error surface for failed reads/imports; transient toast for completed actions. Source-fetch errors remain visible until recovery or the watcher is paused.
- Telemetry upload: native file picker, CSV/JSONL only, 20 MB server cap; description storage is redacted by default.
- Settings: saves are reversible; no confirmation dialog.
- Accessibility target: WCAG 2.2 AA baseline.

## Evidence behavior
- Catalog discovery may add a model automatically.
- Entitlement changes require an official deterministic parser or user action.
- Model price changes from trusted structured sources are versioned in price history.
- **Raw whole-page hash changes are diagnostic only and never create Watch Desk alerts.** User-facing alerts require a semantic event such as new/removed model, plan-price change, quota-policy change, or source recovery.
- A failed source check never erases last-known-good pricing, entitlement, or quota evidence.
- Quantized telemetry is never presented as exact hidden quota accounting.

## Availability and routing
- Provider switches and model switches are reversible availability controls, not destructive data operations.
- Provider means the **model vendor** (Anthropic, Google, OpenAI, xAI, Cursor), not the subscription seller. A provider switch therefore applies across every plan that exposes that vendor's models.
- A disabled provider makes all of its models ineligible for recommendations. A disabled model makes only that model ineligible.
- Model-level state is preserved even while its provider is disabled; re-enabling the provider restores only models whose own switch is enabled.
- Historical telemetry, price history, and catalog evidence stay visible when a route is disabled. Disabled measured lanes are visually marked as excluded.
- Recommendations recalculate immediately after an availability change and explicitly show when availability caused the route to refactor.
- Routing never promotes a telemetry-only model that is not present in the current harness entitlement table.


## Model metadata provenance
In My plan models, context and token-economics fields are enriched across catalog sources. A value may come from a different source than the entitlement itself. The UI must expose complete/partial/unresolved status and provenance; an em dash means genuinely unresolved after enrichment, not zero. Reference token prices must never be presented as measured subscription burn.


## Cost/task display
- The Model Catalog always exposes **API-equivalent Cost / task** when enough token-price data exists.
- The selected Task profile defines billable token volume; the configured catalog token mix defines input/cache-read/output shares.
- The UI states the active profile and mix immediately above the table.
- Cost/task is explicitly labeled as API-equivalent reference economics, not measured subscription-effective cost.
- If cache-read pricing is unavailable, cache-read tokens may be conservatively costed at the input rate only when the UI labels that fallback.
- Missing input or output pricing yields an unresolved cost, never a fabricated zero.


## Recommendation Overview
- Overview's primary job is to answer “What should I use?” before exposing operational detail.
- Four stable workload tiers are presented: Light/short, Standard engineering, Deep/multi-file, and Heavy agentic/long-horizon.
- Each tier shows at most three unique model families. Duplicate entitlements for the same underlying model are collapsed to one recommendation route.
- A model must pass the tier capability-fit gate before cost can affect rank; a cheap light model cannot win a heavy tier solely because its token price is low.
- Within the eligible set, recommendations sort by the active Overview cost basis. API mode uses API-equivalent completed-task cost; Subscription mode uses measured subscription-effective cost and burn. Missing subscription evidence is never replaced by API economics.
- Availability switches remove disabled providers/models before ranking and visibly mark a tier when its Top 3 refactors.
- New catalog models with only inferred capability fit are surfaced as evidence gaps rather than silently entering Top 3.
- Overview secondary signals are limited to subscription spend, measured recommendation coverage, source health, availability impact, recommendation-quality notes, and actionable Watch Desk changes.


## Recommendation cost basis

- Overview exposes one segmented control with `API $ / task` and `Subscription $ + burn`.
- Changing the basis immediately reloads the Top 3 and supporting overview signals; availability choices remain unchanged.
- API mode may show estimated costs when task telemetry is unavailable, and must label them estimated.
- Subscription mode may show only models with measured comparable quota telemetry; it must never backfill a missing subscription value from API prices.
- Subscription cards show effective $/completed task plus weekly and 5-hour burn percentage when available.
- A tier with fewer than three measured subscription candidates explains the telemetry gap in place.
