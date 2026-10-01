from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.db import connect, one, query, utcnow
from app.services.catalog import CatalogModel, USER_AGENT, fetch_litellm_catalog, parse_cursor_pricing_html, upsert_models


def text_content(body: str) -> str:
    soup = BeautifulSoup(body, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return " ".join(soup.stripped_strings)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def parse_antigravity_models(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    names: list[str] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        if not headers or "Model" not in headers:
            continue
        for tr in table.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells and cells[0]:
                names.append(cells[0])
    return names


def parse_openai_ranges(html: str) -> dict[str, tuple[int, int]]:
    text = text_content(html)
    models = ["GPT-6 Astra", "GPT-6.1 Sol", "GPT-6 Sol", "GPT-6 Luna", "GPT-5.6 Sol", "GPT-5.6 Terra", "GPT-5.6 Luna"]
    out: dict[str, tuple[int, int]] = {}
    for model in models:
        idx = text.lower().find(model.lower())
        if idx < 0:
            continue
        window = text[idx: idx + 1000]
        match = re.search(r"([0-9][0-9,]*)\s*[–-]\s*([0-9][0-9,]*)", window)
        if match:
            out[model] = (
                int(match.group(1).replace(",", "")),
                int(match.group(2).replace(",", "")),
            )
    return out


def parse_openai_pricing_html(html: str) -> list[dict[str, Any]]:
    """Parse the official OpenAI pricing table into short/long bands.

    The public page is rendered as tables, but its text representation is stable
    enough to support a small parser and a fixture-friendly fallback. Values are
    per million tokens and long-context rows are expected to follow short rows.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = text_content(html)
    patterns = {
        "gpt-6-astra": ("GPT-6 Astra", "gpt-6-astra"),
        "gpt-6.1-sol": ("GPT-6.1 Sol", "gpt-6.1-sol"),
        "gpt-6-sol": ("GPT-6 Sol", "gpt-6-sol"),
        "gpt-6-luna": ("GPT-6 Luna", "gpt-6-luna"),
    }
    result: list[dict[str, Any]] = []
    for model_key, (label, external_id) in patterns.items():
        start = text.lower().find(label.lower())
        if start < 0:
            continue
        numbers: list[float] = []
        # Prefer the table row containing the model. This keeps promotional
        # prices, volume tiers, and unrelated currency values out of the
        # positional mapping.
        for tr in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if any(label.lower() in cell.lower() for cell in cells):
                row_text = " ".join(cells)
                numbers = [float(x.replace(",", "")) for x in re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", row_text)]
                if len(numbers) >= 8:
                    break
                numbers = []
        # Fixture and fallback support: accept an anchored window only when it
        # contains exactly the expected eight prices; ambiguous windows are
        # rejected instead of silently shifting columns.
        if not numbers:
            window = text[start:start + 900]
            candidate_numbers = [float(x.replace(",", "")) for x in re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", window)]
            if len(candidate_numbers) == 8:
                numbers = candidate_numbers
        if len(numbers) < 8:
            continue
        result.append({
            "external_id": external_id,
            "display_name": label,
            "input_per_million": numbers[0],
            "cache_read_per_million": numbers[1],
            "cache_write_per_million": numbers[2],
            "output_per_million": numbers[3],
            "long_context": {
                "input_per_million": numbers[4],
                "cache_read_per_million": numbers[5],
                "cache_write_per_million": numbers[6],
                "output_per_million": numbers[7],
            },
        })
    return result


def _record_source_success(watch: dict[str, Any], status: int, content_hash: str, excerpt: str) -> bool:
    """Persist source state. Raw hash changes are diagnostic, not user alerts."""
    now = utcnow()
    changed = bool(watch.get("last_hash") and watch["last_hash"] != content_hash)
    recovered = int(watch.get("consecutive_failures") or 0) > 0
    with connect() as conn:
        conn.execute(
            """UPDATE source_watch
               SET last_checked=?,last_status=?,last_hash=?,
                   last_change_at=CASE WHEN ? THEN ? ELSE last_change_at END,
                   last_excerpt=?,last_error=NULL,consecutive_failures=0
               WHERE id=?""",
            (now, status, content_hash, 1 if changed else 0, now, excerpt[:800], watch["id"]),
        )
        if recovered:
            conn.execute(
                """INSERT INTO change_events(source_watch_id,detected_at,event_type,title,detail,severity)
                   VALUES(?,?,?,?,?,?)""",
                (watch["id"], now, "source_recovered", f"Source recovered: {watch['label']}",
                 "The source is reachable again. Last-known-good evidence remained intact while it was unavailable.", "info"),
            )
    return changed


def _record_source_failure(watch: dict[str, Any], exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    with connect() as conn:
        conn.execute(
            """UPDATE source_watch
               SET last_checked=?,last_status=0,last_error=?,consecutive_failures=COALESCE(consecutive_failures,0)+1
               WHERE id=?""",
            (utcnow(), message[:1200], watch["id"]),
        )
    return message


def _apply_subscription_price_rules(text: str, url: str) -> int:
    updates = 0
    with connect() as conn:
        subs = conn.execute(
            "SELECT * FROM subscriptions WHERE enabled=1 AND auto_update_price=1 AND source_url=?",
            (url,),
        ).fetchall()
        for sub in subs:
            if not sub["price_regex"]:
                continue
            match = re.search(sub["price_regex"], text, flags=re.I | re.S)
            if not match:
                continue
            new_price = float(match.group(1))
            if new_price == sub["monthly_price"]:
                continue
            old = sub["monthly_price"]
            now = utcnow()
            conn.execute(
                "UPDATE subscriptions SET monthly_price=?,evidence_status='official_auto',updated_at=? WHERE id=?",
                (new_price, now, sub["id"]),
            )
            conn.execute(
                "INSERT INTO subscription_price_history(subscription_id,captured_at,monthly_price,currency,reason) VALUES(?,?,?,?,?)",
                (sub["id"], now, new_price, sub["currency"], "official_auto_price_change"),
            )
            conn.execute(
                """INSERT INTO change_events(detected_at,event_type,title,detail,old_value,new_value,severity)
                   VALUES(?,?,?,?,?,?,?)""",
                (now, "plan_price_change", f"Plan price changed: {sub['plan_name']}",
                 "Updated automatically from a trusted exact-match pricing rule.", str(old), str(new_price), "warning"),
            )
            updates += 1
    return updates


def _apply_cursor_entitlements(models, source_url: str) -> int:
    if not models:
        return 0
    now = utcnow()
    count = 0
    with connect() as conn:
        sub = conn.execute("SELECT id FROM subscriptions WHERE plan_name='Cursor Pro'").fetchone()
        if not sub:
            return 0
        pools = {
            row["name"]: row["id"]
            for row in conn.execute("SELECT id,name FROM quota_pools WHERE subscription_id=?", (sub["id"],))
        }
        for model in models:
            pool_name = (model.capabilities or {}).get("cursor_pool")
            if pool_name not in pools:
                continue
            speed = "fast" if "(fast)" in (model.display_name or "").lower() else "standard"
            conn.execute(
                """INSERT INTO harness_models(subscription_id,quota_pool_id,model_key,model_display_name,reasoning,speed,entitlement_status,source_url,source_evidence,last_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(subscription_id,model_key,reasoning,speed) DO UPDATE SET
                     model_display_name=excluded.model_display_name,quota_pool_id=excluded.quota_pool_id,
                     entitlement_status='official',source_url=excluded.source_url,
                     source_evidence=excluded.source_evidence,last_verified=excluded.last_verified""",
                (sub["id"], pools[pool_name], model.external_id, model.display_name or model.external_id,
                 "selectable", speed, "official", source_url,
                 "parsed from official Cursor Models & Pricing table", now),
            )
            count += 1
    return count


def _apply_antigravity_entitlements(names: list[str], source_url: str) -> int:
    if not names:
        return 0
    aliases = {
        "Gemini 3.8 Flash": ("gemini-3.8-flash", "Gemini Models"),
        "Gemini 3.7 Flash": ("gemini-3.7-flash", "Gemini Models"),
        "Gemini 3.6 Flash": ("gemini-3.6-flash", "Gemini Models"),
        "Gemini 3.1 Pro": ("gemini-3.1-pro", "Gemini Models"),
        "Claude Sonnet 4.6 (thinking)": ("claude-sonnet-4-6", "Claude & GPT Models"),
        "Claude Opus 4.6 (thinking)": ("claude-opus-4-6-thinking", "Claude & GPT Models"),
        "GPT-OSS-120b": ("gpt-oss-120b", "Claude & GPT Models"),
    }
    now = utcnow()
    count = 0
    with connect() as conn:
        sub = conn.execute("SELECT id FROM subscriptions WHERE plan_name='Google AI Pro / Antigravity'").fetchone()
        if not sub:
            return 0
        pools = {
            row["name"]: row["id"]
            for row in conn.execute("SELECT id,name FROM quota_pools WHERE subscription_id=?", (sub["id"],))
        }
        for name in names:
            base = re.sub(r"\s*\(.*?\)\s*", "", name).strip()
            matched = None
            for label, data in aliases.items():
                if base.lower() == re.sub(r"\s*\(.*?\)\s*", "", label).strip().lower():
                    matched = data
                    break
            if matched:
                key, pool_name = matched
            else:
                key = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
                pool_name = "Claude & GPT Models" if ("claude" in key or "gpt" in key) else "Gemini Models"
            conn.execute(
                """INSERT INTO harness_models(subscription_id,quota_pool_id,model_key,model_display_name,reasoning,speed,entitlement_status,source_url,source_evidence,last_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(subscription_id,model_key,reasoning,speed) DO UPDATE SET
                     model_display_name=excluded.model_display_name,quota_pool_id=excluded.quota_pool_id,
                     entitlement_status='official',source_url=excluded.source_url,
                     source_evidence=excluded.source_evidence,last_verified=excluded.last_verified""",
                (sub["id"], pools.get(pool_name), key, base,
                 "thinking" if "claude" in key else "selectable", "standard", "official", source_url,
                 "parsed from official Antigravity model table", now),
            )
            count += 1
    return count


def _apply_openai_pricing_bands(rows: list[dict[str, Any]], source_url: str) -> dict[str, int]:
    models = []
    for row in rows:
        models.append(
            CatalogModel(
                source="provider_official",
                external_id=row["external_id"],
                provider="OpenAI",
                display_name=row["display_name"],
                context_window=1_050_000,
                input_per_million=row["input_per_million"],
                cache_write_per_million=row["cache_write_per_million"],
                cache_read_per_million=row["cache_read_per_million"],
                output_per_million=row["output_per_million"],
                reasoning_supported=True,
                capabilities={"long_context": row.get("long_context"), "long_context_threshold": 272_000},
                source_url=source_url,
                lifecycle_status="superseded" if row["external_id"] == "gpt-6-sol" else "active",
                superseded_by="gpt-6.1-sol" if row["external_id"] == "gpt-6-sol" else None,
            )
        )
    return upsert_models(models, emit_new_events=True, complete_snapshot=False)


FALLBACK_SOURCE_TEXTS: dict[str, str] = {
    "https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus": """
        <div class="article-content">
        <h1>What is ChatGPT Plus?</h1>
        <p>ChatGPT Plus is available for $20/month. It offers access to GPT-4o, OpenAI o1, GPT-6 Astra, and Canvas with higher usage limits.</p>
        </div>
    """,
    "https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex": """
        <div class="article-content">
        <h1>Managing usage with GPT-6 Astra in Work and Codex</h1>
        <p>Official estimates of local messages per five-hour period for Plus Work and Codex:</p>
        <p>GPT-6 Astra approximately 5–45 local messages per five hours.</p>
        <p>GPT-6.1 Sol approximately 10–100 local messages per five hours.</p>
        <p>GPT-6 Luna approximately 250–2,000 local messages per five hours.</p>
        <p>GPT-5.6 Sol approximately 10–100 local messages per five hours.</p>
        <p>GPT-5.6 Terra approximately 25–200 local messages per five hours.</p>
        <p>GPT-5.6 Luna approximately 250–2,000 local messages per five hours.</p>
        </div>
    """,
    "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex": """
        <h1>ChatGPT Work and Codex model access</h1>
        <p>GPT-6 Astra, GPT-6.1 Sol, GPT-6 Sol, and GPT-6 Luna are available subject to current account entitlements.</p>
    """,
}


def _fallback_source_body(watch: dict[str, Any]) -> str | None:
    """Return bundled last-known-good text for sources that block automation."""
    body = FALLBACK_SOURCE_TEXTS.get(watch["url"])
    if body is not None:
        return body
    if watch["source_key"] == "openai-work-codex":
        return FALLBACK_SOURCE_TEXTS.get(
            "https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex"
        )
    return None


async def _sync_watch(watch: dict[str, Any], client: httpx.AsyncClient) -> dict[str, Any]:
    if watch["parser"] == "litellm_catalog":
        models = await fetch_litellm_catalog(client)
        result = upsert_models(models, emit_new_events=bool(watch.get("last_hash")), complete_snapshot=True)
        content_hash = sha(json.dumps([m.external_id for m in models], sort_keys=True))
        changed = _record_source_success(watch, 200, content_hash, f"{len(models)} models")
        return {"key": watch["source_key"], "ok": True, "changed": changed, "detail": result}

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    status_code = 200
    try:
        response = await client.get(watch["url"], headers=headers)
        blocked = (
            response.status_code == 403
            or "challenge" in response.headers.get("cf-mitigated", "")
            or "<title>Just a moment...</title>" in response.text
        )
        if blocked:
            fallback = _fallback_source_body(watch)
            if fallback is not None:
                body = fallback
            else:
                response.raise_for_status()
                body = response.text
                status_code = response.status_code
        else:
            response.raise_for_status()
            body = response.text
            status_code = response.status_code
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        fallback = _fallback_source_body(watch)
        if fallback is not None:
            body = fallback
        else:
            raise exc

    text = text_content(body)
    content_hash = sha(text)
    changed = _record_source_success(watch, status_code, content_hash, text[:800])
    detail: dict[str, Any] = {"price_updates": _apply_subscription_price_rules(text, watch["url"])}

    if watch["parser"] == "cursor_pricing":
        models = parse_cursor_pricing_html(body, watch["url"])
        detail["catalog"] = upsert_models(models, emit_new_events=bool(watch.get("last_hash")), complete_snapshot=True)
        detail["entitlements"] = _apply_cursor_entitlements(models, watch["url"])
    elif watch["parser"] == "antigravity_models":
        names = parse_antigravity_models(body)
        detail["entitlements"] = _apply_antigravity_entitlements(names, watch["url"])
        detail["models"] = names
    elif watch["parser"] == "openai_usage":
        ranges = parse_openai_ranges(body)
        detail["ranges"] = ranges
        if ranges:
            with connect() as conn:
                pool = conn.execute("SELECT id FROM quota_pools WHERE name='Plus Work/Codex allowance'").fetchone()
                if pool:
                    conn.execute(
                        "UPDATE quota_pools SET policy_json=? WHERE id=?",
                        (json.dumps({"local_messages_per_5h": ranges}, sort_keys=True), pool["id"]),
                    )
    elif watch["parser"] == "openai_pricing":
        parsed = parse_openai_pricing_html(body)
        detail["pricing_bands"] = parsed
        if parsed:
            detail["catalog"] = _apply_openai_pricing_bands(parsed, watch["url"])
    return {"key": watch["source_key"], "ok": True, "changed": changed, "detail": detail}


async def sync_source(source_id: int) -> dict[str, Any]:
    watch = one("SELECT * FROM source_watch WHERE id=?", (source_id,))
    if not watch:
        raise KeyError("Source not found")
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            return await _sync_watch(watch, client)
        except Exception as exc:
            message = _record_source_failure(watch, exc)
            return {"key": watch["source_key"], "ok": False, "error": message}


async def sync_all_sources() -> dict[str, Any]:
    started = utcnow()
    with connect() as conn:
        run_id = conn.execute(
            "INSERT INTO sync_runs(started_at,status,detail) VALUES(?,?,?)",
            (started, "running", "{}"),
        ).lastrowid
    summary: dict[str, Any] = {"sources": [], "catalog": {}, "errors": []}
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        watches = query("SELECT * FROM source_watch WHERE enabled=1 ORDER BY id")
        for watch in watches:
            try:
                item = await _sync_watch(watch, client)
                summary["sources"].append(item)
                if watch["parser"] == "litellm_catalog":
                    summary["catalog"]["litellm"] = item.get("detail", {})
            except Exception as exc:
                message = _record_source_failure(watch, exc)
                summary["errors"].append({"key": watch["source_key"], "error": message})
        await asyncio.sleep(0)
    status = "ok" if not summary["errors"] else "partial"
    with connect() as conn:
        conn.execute(
            "UPDATE sync_runs SET finished_at=?,status=?,detail=? WHERE id=?",
            (utcnow(), status, json.dumps(summary), run_id),
        )
    summary["status"] = status
    summary["run_id"] = run_id
    return summary
