from __future__ import annotations

import re
import json
from typing import Any

from app.db import query

_EFFORT_WORDS = {"low","medium","high","xhigh","max","thinking","fast","standard","default","mode"}
_SOURCE_PRIORITY = {
    "cursor_official": 100,
    "official_baseline": 95,
    "provider_official": 95,
    "litellm": 60,
}


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _compact(value: str | None) -> str:
    return "".join(_tokens(value))


def _base(value: str | None) -> str:
    toks = [t for t in _tokens(value) if t not in _EFFORT_WORDS]
    return "".join(toks)


def _provider(value: str | None) -> str:
    v = (value or "").strip().lower()
    aliases = {
        "anthropic": "anthropic",
        "google": "google",
        "openai": "openai",
        "xai": "xai",
        "spacexai": "xai",
        "cursor": "cursor",
    }
    return aliases.get(v, v)


def match_score(plan_row: dict[str, Any], catalog_row: dict[str, Any]) -> int:
    pp = _provider(plan_row.get("provider"))
    cp = _provider(catalog_row.get("provider"))
    if pp and cp and pp != cp:
        return -1

    candidates_plan = [plan_row.get("external_id"), plan_row.get("display_name")]
    candidates_cat = [catalog_row.get("external_id"), catalog_row.get("display_name")]

    for p in candidates_plan:
        for c in candidates_cat:
            if p and c and _compact(p) == _compact(c):
                return 100

    for p in candidates_plan:
        for c in candidates_cat:
            bp, bc = _base(p), _base(c)
            if bp and bc and bp == bc:
                return 92
            if bp and bc and (bp.startswith(bc) or bc.startswith(bp)) and min(len(bp), len(bc)) >= 7:
                return 82

    pt = set(_tokens(plan_row.get("external_id")) + _tokens(plan_row.get("display_name"))) - _EFFORT_WORDS
    ct = set(_tokens(catalog_row.get("external_id")) + _tokens(catalog_row.get("display_name"))) - _EFFORT_WORDS
    if pt and ct:
        overlap = len(pt & ct) / max(len(pt), len(ct))
        if overlap >= 0.8:
            return 72
    return -1


def _best_value(candidates: list[tuple[int, dict[str, Any]]], field: str) -> tuple[Any, str | None, str | None]:
    best: tuple[int, Any, str | None, str | None] | None = None
    for score, row in candidates:
        value = row.get(field)
        if value is None:
            continue
        source = row.get("source") or "unknown"
        rank = score * 10 + _SOURCE_PRIORITY.get(source, 50)
        item = (rank, value, source, row.get("source_url"))
        if best is None or item[0] > best[0]:
            best = item
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def enrich_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = query("SELECT * FROM model_catalog WHERE active=1")
    out: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        scored = [(match_score(row, c), c) for c in catalog]
        candidates = [(s, c) for s, c in scored if s >= 70]
        candidates.sort(key=lambda x: x[0], reverse=True)

        sources_used: set[str] = set()
        context, context_source, context_url = _best_value(candidates, "context_window")
        if context is not None:
            row["context_window"] = context
            sources_used.add(context_source or "unknown")
        pricing_fields = ["input_per_million", "cache_write_per_million", "cache_read_per_million", "output_per_million"]
        pricing_source = pricing_url = None
        for field in pricing_fields:
            value, source_name, source_url = _best_value(candidates, field)
            if value is not None:
                row[field] = value
                if pricing_source is None or _SOURCE_PRIORITY.get(source_name or "", 50) > _SOURCE_PRIORITY.get(pricing_source, 50):
                    pricing_source, pricing_url = source_name, source_url
                sources_used.add(source_name or "unknown")

        if candidates:
            # Keep latest catalog verification independently of entitlement verification.
            seen = [c.get("last_seen_at") for _, c in candidates if c.get("last_seen_at")]
            row["catalog_last_seen_at"] = max(seen) if seen else None
            row["catalog_match_score"] = candidates[0][0]
            # Carry provider-published long-context bands through to the cost
            # calculator. Do not infer a surcharge merely from token volume.
            for _, candidate in candidates:
                raw_capabilities = candidate.get("capabilities_json")
                try:
                    capabilities = json.loads(raw_capabilities) if isinstance(raw_capabilities, str) else (raw_capabilities or {})
                except (TypeError, ValueError):
                    capabilities = {}
                if isinstance(capabilities, dict):
                    if isinstance(capabilities.get("long_context"), dict):
                        row["long_context_pricing"] = capabilities["long_context"]
                    if isinstance(capabilities.get("long_context_multipliers"), dict):
                        row["long_context_multipliers"] = capabilities["long_context_multipliers"]
                    if capabilities.get("long_context_threshold") is not None:
                        row["long_context_threshold"] = capabilities["long_context_threshold"]
                if row.get("long_context_pricing") or row.get("long_context_multipliers"):
                    break
        else:
            row["catalog_last_seen_at"] = None
            row["catalog_match_score"] = None

        row["context_source"] = context_source
        row["context_source_url"] = context_url
        row["pricing_source"] = pricing_source
        row["pricing_source_url"] = pricing_url
        row["catalog_sources"] = sorted(sources_used)

        core = [row.get("context_window"), row.get("input_per_million"), row.get("output_per_million")]
        if all(v is not None for v in core):
            row["data_status"] = "complete"
        elif any(v is not None for v in core) or row.get("cache_read_per_million") is not None:
            row["data_status"] = "partial"
        else:
            row["data_status"] = "unresolved"
        out.append(row)
    return out
