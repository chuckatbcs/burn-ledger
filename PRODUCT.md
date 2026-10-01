# Burn Ledger — Product Contract

Burn Ledger is a local, evidence-aware control surface for measuring how much useful completed work the user's fixed AI subscriptions deliver.

## Primary user
A technically capable operator who uses multiple AI harnesses (ChatGPT Work/Codex, Cursor, Google Antigravity, and free overflow providers) and wants to route work for either quota longevity or time/reliability.

## Core jobs
1. Keep a current catalog of models, public token prices, and capabilities.
2. Watch official subscription/model/usage pages for material changes.
3. Maintain subscription entitlements separately from the general model catalog.
4. Import account telemetry and compute completed-task yield without inventing precision the source instrument does not expose.
5. Preserve history when models or prices change.
6. Surface new models as candidates rather than silently assuming a paid plan includes them.
7. Translate current token economics into comparable task-level reference costs for selectable workload profiles.
8. Export state for other agents and tools.

## Evidence precedence
1. Imported account telemetry for actual burn.
2. Official provider/harness documentation for entitlements, plan rules, and provider-specific prices.
3. Broad catalogs (LiteLLM) for discovery and capability/price hints.
4. User-configured values.
5. Heuristics, always labeled as such.

## Safety / trust rules
- Bind to localhost by default.
- No vendor credentials are required for baseline operation.
- Telemetry descriptions are redacted by default.
- An automatic catalog discovery never becomes an automatic paid-plan entitlement.
- Whole-page hash changes are diagnostic only; only semantic parser results may create user-facing change alerts or update structured fields automatically.
- Quantized quota readings remain labeled quantized; extrapolations remain labeled extrapolations.

## Availability policy
Burn Ledger treats “can I use this right now?” as user-controlled state distinct from entitlement and historical evidence. Users can exclude a vendor or a single model from active routing without deleting anything. The recommendation layer filters to entitled + enabled candidates and recomputes the measured route inside each comparable quota pool/task tier.


## Catalog enrichment
Plan entitlements and catalog economics are separate evidence layers. The plan catalog must resolve aliases/effort suffixes across sources and may merge context from one source with pricing from another. Each displayed field retains provenance. Missing source data is shown as unresolved rather than silently treated as zero.


## Task-cost policy
The catalog may calculate **API-equivalent cost/task** from a fixed reference workload so models can be compared apples-to-apples. This metric is derived from current public Input/Cache-read/Output pricing and the selected task profile. It must never be presented as subscription-effective cost/task. Subscription-effective cost requires observed allowance throughput over a defined time horizon.


## v0.6 recommendation overview
The primary Overview is recommendation-first. It groups entitled models into four workload tiers, applies a conservative capability-fit gate, deduplicates the same underlying model across subscription routes, and sorts the remaining candidates by API-equivalent completed-task cost. Matching success-adjusted telemetry upgrades cost evidence from estimated to measured. Disabled providers/models are removed before ranking; historical evidence remains intact. New model families appear in the catalog immediately but stay out of Top 3 until their tier fit is established or safely inferred at recommendation grade.


## Overview ranking bases

The recommendation board supports two user-selected bases:

1. **API $ / completed task** — reference economics from current model pricing, success-adjusted when matching completion telemetry exists.
2. **Subscription $ + burn / completed task** — only measured subscription telemetry is eligible. Ranking uses effective monthly-plan cost per completed task derived from weekly burn; cards expose weekly and 5-hour burn directly.

No cross-basis fallback is permitted because API token economics and subscription quota economics are different units.
