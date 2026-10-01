# Burn Ledger source registry

Burn Ledger separates **discovery**, **official entitlement/policy**, **source availability**, and **measured account telemetry**.

## Automatic catalog / economics

- LiteLLM Model Catalog API: `https://api.litellm.ai/model_catalog`
  - Purpose: broad model discovery, context windows, capability flags, public per-token pricing.
  - Fallback: LiteLLM's maintained `model_prices_and_context_window.json` on GitHub.
  - Trust role: discovery and price/capability hint; never sufficient by itself to mark a paid harness entitlement.

## Official subscription / harness sources

- OpenAI ChatGPT Plus price: `https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus`
- OpenAI Work/Codex entitlements: `https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex`
- OpenAI API model catalog: `https://developers.openai.com/api/docs/models`
- OpenAI API pricing: `https://developers.openai.com/api/docs/pricing` (short/long context bands; official parser)
- Cursor Models & Pricing: `https://cursor.com/docs/models-and-pricing`
- Cursor plan pricing: `https://cursor.com/help/account-and-billing/pricing`
- Google One plan pricing: `https://one.google.com/about/plans`
- Google Antigravity models: `https://antigravity.google/docs/models`
- Google Antigravity plans: `https://antigravity.google/docs/plans`
- Google Antigravity pricing: `https://antigravity.google/pricing`
- NVIDIA model catalog: `https://build.nvidia.com/models`
- Nous Research portal: `https://portal.nousresearch.com/`

## Update behavior

- Exact trusted parsers may update structured fields automatically.
- Raw source hashes are stored only for diagnostics and `last_change_at`; **a whole-page hash change does not create a Watch Desk alert**.
- User-facing alerts require semantic evidence: new/removed model, model/plan price change, quota-policy change, or source recovery.
- Source fetch failures preserve the last-known-good structured state. The UI shows the actual error, tracks repeated failures, and lets the user retry or pause each watcher.
- New catalog models are added automatically after the initial baseline sync.
- Models missing from a complete catalog snapshot are marked inactive and logged as changes.
- Cursor and Antigravity official model tables can refresh harness entitlements automatically.
- ChatGPT Plus, Cursor Pro, and Google AI Pro plan prices can update automatically only when their exact seeded extraction rule matches the official page.
- All model price changes are versioned in `model_price_history`; plan price changes are versioned in `subscription_price_history`.


## Official metadata baseline
Burn Ledger v0.4 ships a last-known official baseline for core plan models so context/pricing fields remain usable during temporary source failures. Baseline entries are stored as `official_baseline` catalog rows and are superseded field-by-field by live official/catalog rows when those sources sync successfully.
