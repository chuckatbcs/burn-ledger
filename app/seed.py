from __future__ import annotations

import json
import os
from .db import connect, get_setting, set_setting, utcnow



def _seed_official_catalog_baseline() -> None:
    # Last-known official/public model economics used so plan rows remain useful even
    # when a live source is temporarily unavailable. Live source rows are separate
    # records and take precedence during enrichment.
    from app.services.catalog import CatalogModel, upsert_models

    rows = [
        CatalogModel(source="official_baseline", external_id="gpt-6-astra", provider="OpenAI", display_name="GPT-6 Astra", context_window=1_050_000, input_per_million=10.0, cache_write_per_million=12.5, cache_read_per_million=1.0, output_per_million=50.0, reasoning_supported=True, source_url="https://developers.openai.com/api/docs/models/gpt-6-astra"),
        CatalogModel(source="official_baseline", external_id="gpt-6.1-sol", provider="OpenAI", display_name="GPT-6.1 Sol", context_window=1_050_000, input_per_million=2.0, cache_write_per_million=2.5, cache_read_per_million=0.1, output_per_million=10.0, reasoning_supported=True, source_url="https://developers.openai.com/api/docs/models/gpt-6.1-sol", announced_at="2026-09-29", capabilities={"long_context_threshold": 272_000, "long_context_multipliers": {"input": 2.0, "cache_read": 2.0, "output": 1.5}}),
        CatalogModel(source="official_baseline", external_id="gpt-6-sol", provider="OpenAI", display_name="GPT-6 Sol", context_window=1_050_000, input_per_million=2.0, cache_write_per_million=2.5, cache_read_per_million=0.2, output_per_million=10.0, reasoning_supported=True, source_url="https://developers.openai.com/api/docs/models/gpt-6-sol", lifecycle_status="superseded", superseded_by="gpt-6.1-sol", announced_at="2026-09-22"),
        CatalogModel(source="official_baseline", external_id="gpt-5.6-sol", provider="OpenAI", display_name="GPT-5.6 Sol", context_window=1_050_000, input_per_million=4.0, cache_write_per_million=5.0, cache_read_per_million=0.4, output_per_million=20.0, reasoning_supported=True, source_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol"),
        CatalogModel(source="official_baseline", external_id="gpt-5.6-terra", provider="OpenAI", display_name="GPT-5.6 Terra", context_window=1_050_000, input_per_million=2.0, cache_write_per_million=2.5, cache_read_per_million=0.2, output_per_million=12.0, reasoning_supported=True, source_url="https://developers.openai.com/api/docs/models/gpt-5.6-terra"),
        CatalogModel(source="official_baseline", external_id="gpt-5.6-luna", provider="OpenAI", display_name="GPT-5.6 Luna", context_window=1_050_000, input_per_million=0.2, cache_write_per_million=0.25, cache_read_per_million=0.02, output_per_million=1.2, reasoning_supported=True, source_url="https://developers.openai.com/api/docs/models/gpt-5.6-luna"),
        CatalogModel(source="official_baseline", external_id="claude-sonnet-4-6", provider="Anthropic", display_name="Claude Sonnet 4.6", context_window=1_000_000, input_per_million=3.0, cache_read_per_million=0.3, output_per_million=15.0, reasoning_supported=True, source_url="https://www.anthropic.com/claude/sonnet"),
        CatalogModel(source="official_baseline", external_id="claude-opus-4-6-thinking", provider="Anthropic", display_name="Claude Opus 4.6", context_window=1_000_000, input_per_million=5.0, cache_read_per_million=0.5, output_per_million=25.0, reasoning_supported=True, source_url="https://www.anthropic.com/news/claude-opus-4-6"),
        CatalogModel(source="official_baseline", external_id="composer-2-5", provider="Cursor", display_name="Composer 2.5", context_window=200_000, input_per_million=0.5, cache_read_per_million=0.2, output_per_million=2.5, source_url="https://prod.cursor.com/docs/models/cursor-composer-2-5"),
        CatalogModel(source="official_baseline", external_id="claude-fable-5-1-high", provider="Anthropic", display_name="Claude Fable 5.1 High", context_window=300_000, input_per_million=10.0, cache_write_per_million=12.5, cache_read_per_million=0.25, output_per_million=50.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/claude-fable-5-1"),
        CatalogModel(source="official_baseline", external_id="claude-opus-5-5-medium", provider="Anthropic", display_name="Claude Opus 5.5 Medium", context_window=300_000, input_per_million=4.0, cache_write_per_million=5.0, cache_read_per_million=0.2, output_per_million=20.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/claude-opus-5-5"),
        CatalogModel(source="official_baseline", external_id="claude-haiku-5-5", provider="Anthropic", display_name="Claude Haiku 5.5", context_window=200_000, input_per_million=1.0, cache_read_per_million=0.1, output_per_million=5.0, source_url="https://prod.cursor.com/docs/models/claude-haiku-5-5"),
        CatalogModel(source="official_baseline", external_id="claude-haiku-4-5", provider="Anthropic", display_name="Claude Haiku 4.5", context_window=200_000, input_per_million=0.8, cache_read_per_million=0.08, output_per_million=4.0, source_url="https://prod.cursor.com/docs/models/claude-haiku-4-5"),
        CatalogModel(source="official_baseline", external_id="claude-3-5-haiku", provider="Anthropic", display_name="Claude 3.5 Haiku", context_window=200_000, input_per_million=0.8, cache_read_per_million=0.08, output_per_million=4.0, source_url="https://prod.cursor.com/docs/models/claude-3-5-haiku"),
        CatalogModel(source="official_baseline", external_id="cursor-small", provider="Cursor", display_name="Cursor Small", context_window=128_000, input_per_million=0.2, cache_read_per_million=0.05, output_per_million=0.8, source_url="https://prod.cursor.com/docs/models/cursor-small"),
        CatalogModel(source="official_baseline", external_id="deepseek-v3", provider="DeepSeek", display_name="DeepSeek V3", context_window=128_000, input_per_million=0.14, cache_read_per_million=0.014, output_per_million=0.28, source_url="https://prod.cursor.com/docs/models/deepseek-v3"),
        CatalogModel(source="official_baseline", external_id="deepseek-r1", provider="DeepSeek", display_name="DeepSeek R1", context_window=128_000, input_per_million=0.55, cache_read_per_million=0.055, output_per_million=2.19, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/deepseek-r1"),
        CatalogModel(source="official_baseline", external_id="claude-sonnet-5-5-medium", provider="Anthropic", display_name="Claude Sonnet 5.5 Medium", context_window=300_000, input_per_million=2.0, cache_write_per_million=2.5, cache_read_per_million=0.2, output_per_million=10.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/claude-sonnet-5-5"),
        CatalogModel(source="official_baseline", external_id="claude-sonnet-5-high", provider="Anthropic", display_name="Claude Sonnet 5 High", context_window=200_000, input_per_million=2.0, cache_write_per_million=2.5, cache_read_per_million=0.2, output_per_million=10.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/claude-sonnet-5"),
        CatalogModel(source="official_baseline", external_id="grok-4-7-high", provider="xAI", display_name="Grok 4.7 High", context_window=256_000, input_per_million=2.0, cache_read_per_million=0.5, output_per_million=6.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/grok-4-7"),
        CatalogModel(source="official_baseline", external_id="gemini-3-8-flash-high", provider="Google", display_name="Gemini 3.8 Flash High", context_window=200_000, input_per_million=0.75, cache_read_per_million=0.075, output_per_million=3.5, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/gemini-3-8-flash"),
        CatalogModel(source="official_baseline", external_id="gemini-3.8-flash-medium", provider="Google", display_name="Gemini 3.8 Flash Medium", context_window=200_000, input_per_million=0.75, cache_read_per_million=0.075, output_per_million=3.5, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/gemini-3-8-flash"),
        CatalogModel(source="official_baseline", external_id="gemini-3.1-pro-high", provider="Google", display_name="Gemini 3.1 Pro High", context_window=200_000, input_per_million=2.0, cache_read_per_million=0.2, output_per_million=12.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models/gemini-3-1-pro"),
        CatalogModel(source="official_baseline", external_id="gpt-5-6-sol-medium", provider="OpenAI", display_name="GPT-5.6 Sol Medium", context_window=1_050_000, input_per_million=4.0, cache_write_per_million=5.0, cache_read_per_million=0.4, output_per_million=20.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models-and-pricing"),
        CatalogModel(source="official_baseline", external_id="gpt-5-6-terra-medium", provider="OpenAI", display_name="GPT-5.6 Terra Medium", context_window=1_050_000, input_per_million=2.0, cache_write_per_million=2.5, cache_read_per_million=0.2, output_per_million=12.0, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models-and-pricing"),
        CatalogModel(source="official_baseline", external_id="gpt-5-6-luna-low", provider="OpenAI", display_name="GPT-5.6 Luna Low", context_window=1_050_000, input_per_million=0.2, cache_write_per_million=0.25, cache_read_per_million=0.02, output_per_million=1.2, reasoning_supported=True, source_url="https://prod.cursor.com/docs/models-and-pricing"),
    ]
    upsert_models(rows, emit_new_events=False, complete_snapshot=False)

def seed_all() -> None:
    now = utcnow()
    with connect() as conn:
        subscriptions = [
            ("OpenAI", "ChatGPT Plus / Work + Codex", 20.00, "USD", "https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus", r"\$([0-9]+(?:\.[0-9]+)?)/month", 1, "official"),
            ("Cursor", "Cursor Pro", 20.00, "USD", "https://prod.cursor.com/help/account-and-billing/pricing", r"Pro\s*\$?([0-9]+(?:\.[0-9]+)?)\s*/?\s*mo", 1, "official"),
            ("Google", "Google AI Pro / Antigravity", 19.99, "USD", "https://one.google.com/about/plans", r"Google AI Pro\s*\(5 TB\)\s*\$([0-9]+(?:\.[0-9]+)?)/mo", 1, "official"),
            ("NVIDIA", "NIM Developer / Free", 0.00, "USD", "https://build.nvidia.com/models", None, 0, "official_dynamic"),
            ("Nous Research", "Portal Free", 0.00, "USD", "https://portal.nousresearch.com/", None, 0, "official_dynamic"),
        ]
        for provider, plan, price, cur, url, regex, auto, evidence in subscriptions:
            conn.execute(
                """INSERT INTO subscriptions(provider,plan_name,monthly_price,currency,source_url,price_regex,auto_update_price,evidence_status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(provider,plan_name) DO UPDATE SET source_url=excluded.source_url, price_regex=excluded.price_regex""",
                (provider, plan, price, cur, url, regex, auto, evidence, now, now),
            )

        sub_ids = {r["plan_name"]: r["id"] for r in conn.execute("SELECT id,plan_name FROM subscriptions")}
        for r in conn.execute("SELECT id,monthly_price,currency FROM subscriptions").fetchall():
            exists = conn.execute("SELECT 1 FROM subscription_price_history WHERE subscription_id=? LIMIT 1", (r["id"],)).fetchone()
            if not exists:
                conn.execute("INSERT INTO subscription_price_history(subscription_id,captured_at,monthly_price,currency,reason) VALUES(?,?,?,?,?)", (r["id"],now,r["monthly_price"],r["currency"],"initial_seed"))
        pools = [
            (sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance", "5h + possible weekly", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["Cursor Pro"], "Cursor Models", "monthly", "official", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], "Other Models", "monthly", "official", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Google AI Pro / Antigravity"], "Gemini Models", "5h + weekly", "official", "https://antigravity.google/docs/plans"),
            (sub_ids["Google AI Pro / Antigravity"], "Claude & GPT Models", "5h + weekly", "official", "https://antigravity.google/docs/plans"),
        ]
        for sub_id, name, reset, evidence, url in pools:
            conn.execute(
                """INSERT INTO quota_pools(subscription_id,name,reset_window,evidence_status,source_url)
                   VALUES(?,?,?,?,?) ON CONFLICT(subscription_id,name) DO UPDATE SET reset_window=excluded.reset_window, source_url=excluded.source_url""",
                (sub_id, name, reset, evidence, url),
            )

        pool_ids = {(r["subscription_id"], r["name"]): r["id"] for r in conn.execute("SELECT id,subscription_id,name FROM quota_pools")}
        # Official/known harness availability. These are entitlement records, not price records.
        harness = [
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-6-astra", "GPT-6 Astra", "low/medium/high", "standard", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-6.1-sol", "GPT-6.1 Sol", "low/medium/high/xhigh/max", "standard", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-6-sol", "GPT-6 Sol", "none/low/medium/high/xhigh/max", "standard", "superseded", "https://developers.openai.com/api/docs/models/gpt-6-sol"),
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-6-luna", "GPT-6 Luna", "none/low/medium/high/xhigh/max", "standard", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-5.6-sol", "GPT-5.6 Sol", "low/medium/high", "standard", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-5.6-terra", "GPT-5.6 Terra", "medium", "standard", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["ChatGPT Plus / Work + Codex"], pool_ids[(sub_ids["ChatGPT Plus / Work + Codex"], "Plus Work/Codex allowance")], "gpt-5.6-luna", "GPT-5.6 Luna", "low", "standard", "official", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"),
            (sub_ids["Google AI Pro / Antigravity"], pool_ids[(sub_ids["Google AI Pro / Antigravity"], "Gemini Models")], "gemini-3.8-flash-medium", "Gemini 3.8 Flash", "medium", "standard", "official", "https://antigravity.google/docs/models"),
            (sub_ids["Google AI Pro / Antigravity"], pool_ids[(sub_ids["Google AI Pro / Antigravity"], "Gemini Models")], "gemini-3.1-pro-high", "Gemini 3.1 Pro", "high", "standard", "official", "https://antigravity.google/docs/models"),
            (sub_ids["Google AI Pro / Antigravity"], pool_ids[(sub_ids["Google AI Pro / Antigravity"], "Claude & GPT Models")], "claude-sonnet-4-6", "Claude Sonnet 4.6", "thinking", "standard", "official", "https://antigravity.google/docs/models"),
            (sub_ids["Google AI Pro / Antigravity"], pool_ids[(sub_ids["Google AI Pro / Antigravity"], "Claude & GPT Models")], "claude-opus-4-6-thinking", "Claude Opus 4.6", "thinking", "standard", "official", "https://antigravity.google/docs/models"),
            # Last-known Cursor baseline. Live official Cursor parsing supersedes these rows when available.
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Cursor Models")], "composer-2-5", "Composer 2.5", "default", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Cursor Models")], "cursor-small", "Cursor Small", "none", "fast", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "claude-haiku-5-5", "Claude Haiku 5.5", "none", "fast", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "claude-haiku-4-5", "Claude Haiku 4.5", "none", "fast", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "claude-3-5-haiku", "Claude 3.5 Haiku", "none", "fast", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "claude-opus-5-5-medium", "Claude Opus 5.5 Medium", "medium", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "claude-fable-5-1-high", "Claude Fable 5.1 High", "high", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "claude-sonnet-5-high", "Claude Sonnet 5 High", "high", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "grok-4-7-high", "Grok 4.7 High", "high", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "gemini-3-8-flash-high", "Gemini 3.8 Flash High", "high", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "deepseek-v3", "DeepSeek V3", "none", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "deepseek-r1", "DeepSeek R1", "high", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "gpt-5-6-sol-medium", "GPT-5.6 Sol Medium", "medium", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "gpt-5-6-terra-medium", "GPT-5.6 Terra Medium", "medium", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
            (sub_ids["Cursor Pro"], pool_ids[(sub_ids["Cursor Pro"], "Other Models")], "gpt-5-6-luna-low", "GPT-5.6 Luna Low", "low", "standard", "baseline", "https://prod.cursor.com/docs/models-and-pricing"),
        ]
        for vals in harness:
            conn.execute(
                """INSERT OR IGNORE INTO harness_models(subscription_id,quota_pool_id,model_key,model_display_name,reasoning,speed,entitlement_status,source_url,source_evidence,last_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (*vals, "seeded from current official/current-account reconciliation", now),
            )
        conn.execute(
            "UPDATE harness_models SET lifecycle_status='superseded',superseded_by='gpt-6.1-sol',entitlement_status='superseded' WHERE model_key='gpt-6-sol'"
        )

        watches = [
            ("openai-plus-price", "OpenAI ChatGPT Plus price", "https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus", "html", "hash"),
            ("openai-work-codex", "OpenAI Work/Codex usage", "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex", "html", "openai_usage"),
            ("openai-models", "OpenAI model catalog", "https://developers.openai.com/api/docs/models", "html", "hash"),
            ("openai-api-pricing", "OpenAI API pricing", "https://developers.openai.com/api/docs/pricing", "html", "openai_pricing"),
            ("google-one-plans", "Google One AI plan pricing", "https://one.google.com/about/plans", "html", "hash"),
            ("cursor-models-pricing", "Cursor Models & Pricing", "https://prod.cursor.com/docs/models-and-pricing", "html", "cursor_pricing"),
            ("cursor-plan-pricing", "Cursor plan pricing", "https://prod.cursor.com/help/account-and-billing/pricing", "html", "hash"),
            ("antigravity-models", "Google Antigravity models", "https://antigravity.google/docs/models", "html", "antigravity_models"),
            ("antigravity-plans", "Google Antigravity plans", "https://antigravity.google/docs/plans", "html", "hash"),
            ("antigravity-pricing", "Google Antigravity pricing", "https://antigravity.google/pricing", "html", "hash"),
            ("nvidia-models", "NVIDIA model catalog", "https://build.nvidia.com/models", "html", "hash"),
            ("nous-portal", "Nous Research portal", "https://portal.nousresearch.com/", "html", "hash"),
            ("litellm-catalog", "LiteLLM model catalog", "https://api.litellm.ai/model_catalog?page_size=500&page=1", "json", "litellm_catalog"),
        ]
        for key, label, url, kind, parser in watches:
            conn.execute(
                """INSERT INTO source_watch(source_key,label,url,kind,parser)
                   VALUES(?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET label=excluded.label,url=excluded.url,kind=excluded.kind,parser=excluded.parser""",
                (key, label, url, kind, parser),
            )

        # v9 consensus Antigravity matched metrics.
        google_sub = sub_ids["Google AI Pro / Antigravity"]
        gem_pool = pool_ids[(google_sub, "Gemini Models")]
        claude_pool = pool_ids[(google_sub, "Claude & GPT Models")]
        metrics = [
            (gem_pool,"gemini-3.8-flash-medium","Tier 2: Standard Engineering",20,22,20,.90,1,1,20,2000,7682.5,7.3,70.9,"consensus_matched"),
            (gem_pool,"gemini-3.1-pro-high","Tier 2: Standard Engineering",20,21,20,.95,5,2,4,400,10981.8,8.55,113.15,"consensus_matched"),
            (gem_pool,"gemini-3.8-flash-medium","Tier 3: Long-Horizon Agent Coding",20,29,20,.60,4,4,5,500,104205.55,44.35,448.4,"consensus_matched"),
            (gem_pool,"gemini-3.1-pro-high","Tier 3: Long-Horizon Agent Coding",20,25,20,.75,10,5,2,200,44284.25,21.05,285.0,"consensus_matched"),
            (claude_pool,"claude-sonnet-4-6","Tier 2: Standard Engineering",20,22,20,.90,6,2,3.3333333333,333.3333333333,18105.85,8.5,103.45,"consensus_matched"),
            (claude_pool,"claude-opus-4-6-thinking","Tier 2: Standard Engineering",20,21,20,.95,13,6,1.5384615385,153.8461538462,19268.95,8.1,126.95,"consensus_matched"),
            (claude_pool,"claude-sonnet-4-6","Tier 3: Long-Horizon Agent Coding",20,29,20,.55,10,5,2,200,45593.45,20.55,315.15,"consensus_matched"),
            (claude_pool,"claude-opus-4-6-thinking","Tier 3: Long-Horizon Agent Coding",20,25,20,.75,20,10,1,100,44112.65,19.9,300.2,"consensus_matched"),
        ]
        observed = "2026-09-23T00:00:00+00:00"
        for pool_id, model, task_class, n, attempts, completed, fp, q5, qw, per1, ext, toks, steps, secs, status in metrics:
            conn.execute(
                """INSERT OR IGNORE INTO lane_metrics(subscription_id,quota_pool_id,model_key,task_class,sample_size,attempts,completed,first_pass_rate,visible_quota_delta_pct,weekly_quota_delta_pct,completed_per_visible_1pct,visible_100point_extrapolation,tokens_per_completed,steps_per_completed,seconds_per_completed,evidence_status,observed_at,source_label,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (google_sub,pool_id,model,task_class,n,attempts,completed,fp,q5,qw,per1,ext,toks,steps,secs,status,observed,"Antigravity + ChatGPT Pass-6 consensus","100-point figures are quantized-UI extrapolations, not guaranteed reset capacity."),
            )

    if get_setting("sync_interval_minutes") is None:
        set_setting("sync_interval_minutes", int(os.getenv("BURN_LEDGER_SYNC_INTERVAL_MINUTES", "360")))
    if get_setting("catalog_token_mix") is None:
        set_setting("catalog_token_mix", {"input": 0.70, "cache_read": 0.20, "output": 0.10})
    if get_setting("telemetry_redact_descriptions") is None:
        set_setting("telemetry_redact_descriptions", True)
    _seed_official_catalog_baseline()
    discover_local_environment()


def discover_local_environment() -> None:
    """Discovers local tool ecosystems (Ollama, Antigravity CLI) and records them in the database."""
    now = utcnow()
    # 1. Local Ollama discovery
    ollama_models: list[tuple[str, str, int]] = []
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "BurnLedger/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
            for m in data.get("models", []):
                name = m.get("name", "")
                if not name:
                    continue
                details = m.get("details", {})
                param_size = details.get("parameter_size", "")
                ctx = details.get("context_length", 131072) or 131072
                display_name = f"{name} (Local {param_size})" if param_size else f"{name} (Local)"
                ollama_models.append((f"ollama/{name}", display_name, int(ctx)))
    except Exception:
        pass

    with connect() as conn:
        if ollama_models:
            conn.execute(
                """INSERT INTO subscriptions(provider,plan_name,monthly_price,currency,evidence_status,created_at,updated_at)
                   VALUES('Ollama','Localhost Open Weights',0.0,'USD','local_environment',?,?)
                   ON CONFLICT(provider,plan_name) DO NOTHING""",
                (now, now),
            )
            ollama_sub = conn.execute("SELECT id FROM subscriptions WHERE provider='Ollama' AND plan_name='Localhost Open Weights'").fetchone()
            if ollama_sub:
                sub_id = ollama_sub["id"]
                conn.execute(
                    """INSERT INTO quota_pools(subscription_id,name,reset_window,evidence_status)
                       VALUES(?,'Local GPU/CPU Inference','unmetered','local_environment')
                       ON CONFLICT(subscription_id,name) DO NOTHING""",
                    (sub_id,),
                )
                pool = conn.execute("SELECT id FROM quota_pools WHERE subscription_id=? AND name='Local GPU/CPU Inference'", (sub_id,)).fetchone()
                if pool:
                    pool_id = pool["id"]
                    for model_key, display_name, ctx in ollama_models:
                        conn.execute(
                            """INSERT OR IGNORE INTO harness_models(subscription_id,quota_pool_id,model_key,model_display_name,reasoning,speed,entitlement_status,source_evidence,last_verified)
                                VALUES(?,?,?,?,'default','fast','local_detected','discovered via local Ollama endpoint',?)""",
                            (sub_id, pool_id, model_key, display_name, now),
                        )

            # Check if any previously discovered Ollama model was removed
            ollama_active_keys = {m[0] for m in ollama_models}
            for r in conn.execute("SELECT id, model_key, lifecycle_status FROM harness_models WHERE subscription_id=?", (sub_id,)).fetchall():
                if r["model_key"] not in ollama_active_keys and r["lifecycle_status"] == "active":
                    conn.execute(
                        "UPDATE harness_models SET lifecycle_status='deprecated', entitlement_status='deprecated' WHERE id=?",
                        (r["id"],)
                    )

        # 2. Local Antigravity CLI discovery
        try:
            import subprocess
            import re
            out = subprocess.check_output(["agy", "models"], stderr=subprocess.PIPE, timeout=12).decode("utf-8")
            antigravity_sub = conn.execute("SELECT id FROM subscriptions WHERE provider='Google' AND plan_name LIKE '%Antigravity%'").fetchone()
            if antigravity_sub:
                sub_id = antigravity_sub["id"]
                gem_pool = conn.execute("SELECT id FROM quota_pools WHERE subscription_id=? AND name LIKE '%Gemini%'", (sub_id,)).fetchone()
                claude_pool = conn.execute("SELECT id FROM quota_pools WHERE subscription_id=? AND name LIKE '%Claude%'", (sub_id,)).fetchone()
                active_keys = set()
                for line in out.splitlines():
                    line = re.sub(r'^[⠋⠙⠹⠸⠼⠴⠦⠧⠇\s]*Fetching available models\.\.\.', '', line).strip()
                    if not line:
                        continue
                    parts = re.split(r'\t+|\s{2,}', line)
                    if len(parts) >= 2:
                        model_key = parts[0].strip()
                        display_name = parts[1].strip()
                        active_keys.add(model_key)
                        target_pool = gem_pool["id"] if ("gemini" in model_key and gem_pool) else (claude_pool["id"] if claude_pool else None)
                        if target_pool:
                            conn.execute(
                                """INSERT INTO harness_models(subscription_id,quota_pool_id,model_key,model_display_name,reasoning,speed,entitlement_status,source_evidence,last_verified,lifecycle_status)
                                   VALUES(?,?,?,?,'default','standard','local_detected','discovered via agy models CLI',?,'active')
                                   ON CONFLICT(subscription_id,model_key,reasoning,speed) DO UPDATE SET
                                     model_display_name=excluded.model_display_name,quota_pool_id=excluded.quota_pool_id,
                                     last_verified=excluded.last_verified,lifecycle_status='active',entitlement_status='local_detected'""",
                                (sub_id, target_pool, model_key, display_name, now),
                            )

                # Prune and supersede unmeasured models no longer reported by agy models
                for r in conn.execute("SELECT id, model_key, lifecycle_status FROM harness_models WHERE subscription_id=?", (sub_id,)).fetchall():
                    m_key = r["model_key"]
                    has_metrics = conn.execute("SELECT 1 FROM lane_metrics WHERE model_key=?", (m_key,)).fetchone()
                    if m_key not in active_keys and r["lifecycle_status"] == "active" and not has_metrics:
                        superseded_target = "claude-sonnet-5-5-medium" if "sonnet" in m_key else ("claude-opus-5-5-medium" if "opus" in m_key else None)
                        conn.execute(
                            """UPDATE harness_models
                               SET lifecycle_status='superseded', entitlement_status='superseded', superseded_by=?
                               WHERE id=?""",
                            (superseded_target, r["id"])
                        )
        except Exception:
            pass

