#!/usr/bin/env python3
"""Sanitize public dashboard/state artifacts before private+Access migration.

This does not change strategy, portfolio state, or the F engine. It only removes
local paths and named third-party source identities from public JSON artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs" / "state"
THIRD_PARTY_MARKERS = ("stockeys", "x.com", "twitter")


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _has_third_party_marker(payload) -> bool:
    text = " ".join(str(payload.get(key) or "") for key in ("id", "source", "source_url", "label", "name", "handle", "note"))
    text = text.lower()
    return any(marker in text for marker in THIRD_PARTY_MARKERS)


def _public_source_id(source: dict) -> str:
    if _has_third_party_marker(source):
        return "third_party_secondary_source"
    return str(source.get("id") or "third_party_source")


def _public_label(source: dict) -> str:
    typ = str(source.get("type") or "catalyst")
    if _has_third_party_marker(source):
        return f"third_party_{typ}_screen"
    return str(source.get("label") or typ)


def _event_key(event: dict) -> str:
    return "|".join(str(event.get(key) or "") for key in ("source_id", "type", "event_date", "ticker"))


def _sanitize_catalyst_event(event: dict) -> dict:
    event = dict(event)
    if _has_third_party_marker(event):
        event["source_id"] = "third_party_secondary_source"
        event["source"] = "third_party_public_source"
        event["source_url"] = None
        event["label"] = f"third_party_{event.get('type') or 'catalyst'}_screen"
        event["keywords"] = []
        event["note"] = None
        event["key"] = _event_key(event)
    return event


def _sanitize_catalyst_payload(payload: dict) -> dict:
    if isinstance(payload.get("events"), list):
        dedup = {}
        for event in payload["events"]:
            if isinstance(event, dict):
                event = _sanitize_catalyst_event(event)
                dedup[event.get("key") or _event_key(event)] = event
        payload["events"] = list(dedup.values())
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
    if isinstance(summary, dict):
        if summary.get("latest_source_id"):
            summary["latest_source_id"] = "third_party_secondary_source"
        if summary.get("latest_source_label"):
            summary["latest_source_label"] = "third_party_event_screen"
    return payload


def _sanitize_broker_summary(summary: dict) -> dict:
    summary["input_error_count"] = len(summary.get("input_errors") or []) if "input_errors" in summary else summary.get("input_error_count", 0)
    summary.pop("input_errors", None)
    summary.pop("source_registry", None)
    summary.setdefault("source_registry_count", 4)
    summary["source_registry_policy"] = "Source identities and URLs are private until dashboard is behind Access."
    summary["public_detail_policy"] = "Raw broker calls, target prices, notes and per-ticker bulletin details stay private-only."
    summary["detail_storage"] = "private_local_ledger"
    readiness = summary.get("readiness") if isinstance(summary.get("readiness"), dict) else {}
    readiness["message"] = "Broker bulten sicili hazir; olcum icin public olmayan ozel event extract bekleniyor."
    readiness["next_step"] = "Ilk broker bulten extract dosyasini private input alanina koy; public panel sadece agregayi gosterir."
    summary["readiness"] = readiness
    return summary


def _sanitize_flow_summary(summary: dict) -> dict:
    summary.pop("local_input_dir", None)
    summary["local_input_source"] = "private_local"
    readiness = summary.get("readiness") if isinstance(summary.get("readiness"), dict) else {}
    readiness["next_step"] = "KAP geri alim olayi geldikce otomatik olculur; yabanci/takas icin private input alani kullan."
    summary["readiness"] = readiness
    summary["public_detail_policy"] = "raw takas holder details and licensed flow extracts stay private-only"
    return summary


def sanitize_dashboard() -> bool:
    path = STATE / "dashboard.json"
    payload = _load(path, None)
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("catalyst_ledger"), dict):
        payload["catalyst_ledger"] = _sanitize_catalyst_payload(payload["catalyst_ledger"])
    if isinstance(payload.get("broker_bulletin_ledger"), dict):
        payload["broker_bulletin_ledger"] = _sanitize_broker_summary(payload["broker_bulletin_ledger"])
    if isinstance(payload.get("flow_ledger"), dict):
        payload["flow_ledger"] = _sanitize_flow_summary(payload["flow_ledger"])
    _save(path, payload)
    return True


def sanitize_broker_files() -> int:
    changed = 0
    path = STATE / "broker_bulletin_ledger.json"
    payload = _load(path, None)
    if isinstance(payload, dict):
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
        _sanitize_broker_summary(summary)
        _save(path, payload)
        changed += 1

    path = STATE / "broker_bulletin_sources.json"
    payload = _load(path, None)
    if isinstance(payload, dict):
        sources = payload.get("sources", [])
        tier_counts = {}
        for source in sources if isinstance(sources, list) else []:
            tier = str(source.get("tier") or "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        _save(path, {
            "source_registry_count": len(sources) if isinstance(sources, list) else 0,
            "source_registry_tiers": tier_counts,
            "policy": "Source identities and URLs are private until dashboard is behind Access.",
        })
        changed += 1
    return changed


def sanitize_flow_file() -> bool:
    path = STATE / "flow_ledger.json"
    payload = _load(path, None)
    if not isinstance(payload, dict):
        return False
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
    _sanitize_flow_summary(summary)
    for event in payload.get("events", []) if isinstance(payload.get("events"), list) else []:
        if isinstance(event, dict) and event.get("source_file"):
            event.pop("source_file", None)
            event["source_ref"] = "private_local"
    _save(path, payload)
    return True


def sanitize_catalyst_files() -> int:
    changed = 0
    path = STATE / "catalyst_ledger.json"
    payload = _load(path, None)
    if isinstance(payload, dict):
        _save(path, _sanitize_catalyst_payload(payload))
        changed += 1

    path = STATE / "catalyst_sources.json"
    payload = _load(path, None)
    if isinstance(payload, dict):
        sources = payload.get("sources", [])
        sanitized = []
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            sanitized.append({
                "id": _public_source_id(source),
                "date": source.get("date"),
                "source": "third_party_public_source",
                "source_url": None,
                "type": source.get("type"),
                "label": _public_label(source),
                "confidence": source.get("confidence"),
                "tickers": source.get("tickers", []),
                "public_detail_policy": "source identity withheld until dashboard is behind Access",
            })
        _save(path, {"sources": sanitized})
        changed += 1

    path = STATE / "catalyst_policy.json"
    payload = _load(path, None)
    if isinstance(payload, dict):
        for tier in (payload.get("source_tiers") or {}).values():
            if isinstance(tier, dict) and isinstance(tier.get("examples"), list):
                tier["examples"] = ["third_party_public_source"]
        payload["x_search_templates"] = ["third_party catalyst keywords; source identity private until Access"]
        payload["source_registry"] = [
            {"tier": "data_vendor", "status": "watch_only", "public_detail_policy": "identity withheld until Access"},
            {"tier": "social", "status": "watch_only", "public_detail_policy": "identity withheld until Access"},
        ]
        _save(path, payload)
        changed += 1
    return changed


def main() -> int:
    changed = 0
    changed += 1 if sanitize_dashboard() else 0
    changed += sanitize_broker_files()
    changed += 1 if sanitize_flow_file() else 0
    changed += sanitize_catalyst_files()
    print(f"sanitized_public_state_files={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
