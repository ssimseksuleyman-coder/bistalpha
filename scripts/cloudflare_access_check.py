#!/usr/bin/env python
"""
Unauthenticated Cloudflare Access smoke check.

This script does not log in. It verifies that protected dashboard URLs do not
serve the dashboard or JSON state to an anonymous client.

OK for protected URLs means:
- 401/403, or
- 3xx redirect to a Cloudflare Access login path/host, or
- Access login page markers in the response body.

FAIL means:
- 200 serving dashboard or JSON markers,
- 5xx infrastructure error,
- any response that is not clearly an Access gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests


DASHBOARD_MARKERS = (
    "BIST Alpha",
    "Top 10 Sinyal",
    "dashboard.json",
    "Operasyon Kapisi",
    "Performans Defteri",
)

JSON_MARKERS = (
    '"top"',
    '"accounts"',
    '"operation"',
    '"generated_at"',
    '"last_data_date"',
)

SANITIZE_FORBIDDEN_KEYS = {
    "deniz_bulletin",
    "deniz_regime",
    "market_score",
    "market_score_deniz",
    "source_file",
    "yan_kaynak",
}

SANITIZE_FORBIDDEN_TEXT = (
    "deniz",
    "deniz yatirim",
    "deniz yatırım",
    "deniz_inbox",
    "teknik_takip",
    "local/",
    "stockeys",
    "bizim menkul",
    "icbc turkey",
    "tera yatirim",
    "bizimmenkul.com.tr",
    "icbcyatirim.com.tr",
    "terayatirim.com",
)

ACCESS_MARKERS = (
    "cloudflare access",
    "cloudflareaccess.com",
    "/cdn-cgi/access",
    "teams.cloudflare.com",
    "cf-access",
    "access login",
)


@dataclass
class Result:
    label: str
    url: str
    ok: bool
    status: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "url": self.url,
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail,
        }


def _get(url: str, timeout: float) -> requests.Response | None:
    try:
        return requests.get(
            url,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "bist-alpha-access-check/1.0"},
        )
    except requests.RequestException:
        return None


def _text(response: requests.Response) -> str:
    try:
        return response.text or ""
    except Exception:
        return ""


def _is_access_response(response: requests.Response) -> bool:
    location = response.headers.get("Location", "")
    haystack = f"{location}\n{_text(response)[:4096]}".lower()
    if response.status_code in {401, 403}:
        return True
    if 300 <= response.status_code < 400 and any(marker in haystack for marker in ACCESS_MARKERS):
        return True
    if response.status_code == 200 and any(marker in haystack for marker in ACCESS_MARKERS):
        return True
    return False


def _looks_like_public_dashboard(response: requests.Response) -> bool:
    body = _text(response)[:20000]
    body_l = body.lower()
    content_type = response.headers.get("Content-Type", "").lower()
    if response.status_code != 200:
        return False
    if "application/json" in content_type:
        return True
    stripped = body.lstrip()
    if stripped.startswith("{") and any(marker in body for marker in JSON_MARKERS):
        return True
    if any(marker.lower() in body_l for marker in DASHBOARD_MARKERS):
        return True
    return False


def check_protected(url: str, timeout: float) -> Result:
    response = _get(url, timeout)
    if response is None:
        return Result("protected", url, False, "ERR", "request failed; manual check required")
    if response.status_code >= 500:
        return Result("protected", url, False, str(response.status_code), "server error; Access not proven")
    if _is_access_response(response):
        return Result("protected", url, True, str(response.status_code), "Access gate detected")
    if _looks_like_public_dashboard(response):
        return Result("protected", url, False, str(response.status_code), "PUBLIC dashboard/state content")
    return Result(
        "protected",
        url,
        False,
        str(response.status_code),
        "no Access gate detected; inspect response manually",
    )


def check_retired(url: str, timeout: float) -> Result:
    response = _get(url, timeout)
    if response is None:
        return Result("retired", url, False, "ERR", "request failed; manual check required")
    if response.status_code >= 500:
        return Result("retired", url, False, str(response.status_code), "server error; retired state not proven")
    if response.status_code in {401, 403, 404, 410, 451}:
        return Result("retired", url, True, str(response.status_code), "retired/blocked")
    if _is_access_response(response):
        return Result("retired", url, True, str(response.status_code), "Access gate detected")
    if _looks_like_public_dashboard(response):
        return Result("retired", url, False, str(response.status_code), "old public dashboard still visible")
    return Result("retired", url, True, str(response.status_code), "not serving dashboard markers")


def check_github_pages_api(url: str, timeout: float) -> Result:
    response = _get(url, timeout)
    if response is None:
        return Result("github_pages_api", url, False, "ERR", "request failed; manual check required")
    if response.status_code == 404:
        return Result("github_pages_api", url, True, "404", "GitHub Pages API not found/disabled")
    if response.status_code == 200:
        return Result("github_pages_api", url, False, "200", "GitHub Pages API still returns config")
    if response.status_code >= 500:
        return Result("github_pages_api", url, False, str(response.status_code), "GitHub API server error")
    return Result("github_pages_api", url, False, str(response.status_code), "unexpected API response; manual check required")


def _with_page(url: str, page: int) -> str:
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("per_page", "100")
    query["page"] = str(page)
    return urlunparse(parts._replace(query=urlencode(query)))


def check_forks_api(url: str, timeout: float, max_pages: int = 20) -> Result:
    total = 0
    for page in range(1, max_pages + 1):
        page_url = _with_page(url, page)
        response = _get(page_url, timeout)
        if response is None:
            return Result("forks_api", url, False, "ERR", "request failed; manual check required")
        if response.status_code != 200:
            return Result("forks_api", url, False, str(response.status_code), "GitHub forks API unavailable")
        try:
            payload = response.json()
        except ValueError:
            return Result("forks_api", url, False, "200", "GitHub forks API returned non-JSON")
        if not isinstance(payload, list):
            return Result("forks_api", url, False, "200", "GitHub forks API returned unexpected payload")
        total += len(payload)
        link = response.headers.get("Link", "")
        if 'rel="next"' not in link:
            break
    if total:
        return Result("forks_api", url, False, "200", f"{total} fork(s) found")
    return Result("forks_api", url, True, "200", "fork inventory empty")


def _walk_json(value, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", key
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        yield path, value


def check_sanitize_state(path: str) -> Result:
    target = Path(path)
    if not target.exists():
        return Result("sanitize_state", path, False, "MISS", "state file missing")
    if target.is_dir():
        hits: list[str] = []
        checked = 0
        for child in sorted(target.glob("*.json")):
            checked += 1
            result = check_sanitize_state(str(child))
            if not result.ok:
                hits.append(f"{child.as_posix()}: {result.detail}")
            if len(hits) >= 10:
                break
        if hits:
            return Result("sanitize_state", path, False, "DIRTY", "; ".join(hits))
        return Result("sanitize_state", path, True, "OK", f"checked {checked} JSON files")
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return Result("sanitize_state", path, False, "ERR", f"JSON parse failed: {exc}")

    hits: list[str] = []
    for json_path, token in _walk_json(payload):
        token_s = str(token)
        token_l = token_s.lower()
        if token_l in SANITIZE_FORBIDDEN_KEYS:
            hits.append(f"{json_path} key={token_s}")
        elif any(marker in token_l for marker in SANITIZE_FORBIDDEN_TEXT):
            hits.append(f"{json_path} text={token_s[:80]}")
        if len(hits) >= 10:
            break

    if hits:
        return Result("sanitize_state", path, False, "DIRTY", "; ".join(hits))
    return Result("sanitize_state", path, True, "OK", "no licensed/private markers found")


def _derive(base: str) -> list[str]:
    if not base.endswith("/"):
        base += "/"
    return [
        base,
        urljoin(base, "state/dashboard.json"),
        urljoin(base, "state/system_control_audit.json"),
        urljoin(base, "health.html"),
    ]


def _print_results(results: Iterable[Result]) -> int:
    failures = 0
    for result in results:
        mark = "OK" if result.ok else "FAIL"
        print(f"{mark:4} {result.label:9} {result.status:>4} {result.url}")
        print(f"     {result.detail}")
        if not result.ok:
            failures += 1
    return failures


def _none_if_empty(values: list[bool]) -> bool | None:
    if not values:
        return None
    return all(values)


def _security_gate(results: list[Result], args: argparse.Namespace) -> dict:
    protected = [r for r in results if r.label == "protected"]
    retired = [r for r in results if r.label == "retired"]
    github_pages_api = [r for r in results if r.label == "github_pages_api"]
    forks_api = [r for r in results if r.label == "forks_api"]
    sanitize_state = [r for r in results if r.label == "sanitize_state"]
    protected_html = [
        r for r in protected
        if "/state/" not in r.url and not r.url.lower().endswith(".json")
    ]
    protected_json = [
        r for r in protected
        if "/state/" in r.url or r.url.lower().endswith(".json")
    ]
    pages_dev = [r for r in protected if ".pages.dev" in r.url.lower()]

    privacy_checks = {
        "access_html_ok": _none_if_empty([r.ok for r in protected_html]),
        "access_json_ok": _none_if_empty([r.ok for r in protected_json]),
        "pages_dev_ok": _none_if_empty([r.ok for r in pages_dev]),
        "github_pages_retired": _none_if_empty([r.ok for r in retired + github_pages_api]),
        "fork_inventory_ok": True if args.fork_inventory_ok else _none_if_empty([r.ok for r in forks_api]),
        "cloudflare_deploy_ok": True if args.cloudflare_deploy_ok else None,
        "sanitize_ok": True if args.sanitize_ok else _none_if_empty([r.ok for r in sanitize_state]),
    }
    live_fresh_ok = True if args.live_fresh_ok else None
    checks = {**privacy_checks, "live_fresh_ok": live_fresh_ok}

    failures = [r for r in results if not r.ok]
    missing = [name for name, value in privacy_checks.items() if value is None]
    missing_freshness = [] if live_fresh_ok is True else ["live_fresh_ok"]
    if failures:
        level = "red"
    elif missing:
        level = "yellow"
    else:
        level = "green"
    privacy_ok = level == "green"
    promotion_ok = privacy_ok and live_fresh_ok is True

    return {
        "privacy_ok": privacy_ok,
        "live_fresh_ok": live_fresh_ok,
        "promotion_ok": promotion_ok,
        "level": level,
        "privacy_level": level,
        "mode": args.mode,
        "last_check": datetime.now().astimezone().isoformat(timespec="seconds"),
        "check_source": "scripts/cloudflare_access_check.py",
        "checks": checks,
        "missing_checks": missing,
        "missing_freshness_checks": missing_freshness,
        "results": [r.as_dict() for r in results],
        "decision": "new_layer_promotion_allowed" if promotion_ok else "no_new_layer_promotion",
        "note": "Gizlilik kirmizi/sari iken yeni katman terfi ettirilmez.",
        "freshness_note": "live_fresh_ok null ise tazelik bilinmiyor kabul edilir; yesil sayilmaz.",
    }


def _write_gate(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", action="append", default=[], help="Protected Cloudflare base URL; derives key paths")
    parser.add_argument("--protected", action="append", default=[], help="Protected URL to test directly")
    parser.add_argument("--retired", action="append", default=[], help="Old URL expected to be blocked/retired")
    parser.add_argument("--github-pages-api", help="GitHub Pages REST API URL expected to return 404")
    parser.add_argument("--forks-api", help="GitHub forks REST API URL expected to return an empty paginated list")
    parser.add_argument("--sanitize-state", help="Local dashboard/state JSON to scan for licensed/private markers")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--mode", choices=("normal", "urgent", "manual"), default="manual")
    parser.add_argument("--fork-inventory-ok", action="store_true", help="Mark fork inventory check as completed")
    parser.add_argument("--cloudflare-deploy-ok", action="store_true", help="Mark post-private Cloudflare deploy check as completed")
    parser.add_argument("--live-fresh-ok", action="store_true", help="Mark manual authenticated freshness check as completed")
    parser.add_argument("--sanitize-ok", action="store_true", help="Manual override; prefer --sanitize-state")
    parser.add_argument("--write-gate", help="Write local/security_gate.json style output")
    args = parser.parse_args(argv)

    protected_urls: list[str] = []
    for base in args.base:
        protected_urls.extend(_derive(base))
    protected_urls.extend(args.protected)

    if not any([protected_urls, args.retired, args.github_pages_api, args.forks_api, args.sanitize_state]):
        parser.error("provide --base, --protected, --retired, --github-pages-api, --forks-api, or --sanitize-state")

    results: list[Result] = []
    for url in protected_urls:
        results.append(check_protected(url, args.timeout))
    for url in args.retired:
        results.append(check_retired(url, args.timeout))
    if args.github_pages_api:
        results.append(check_github_pages_api(args.github_pages_api, args.timeout))
    if args.forks_api:
        results.append(check_forks_api(args.forks_api, args.timeout))
    if args.sanitize_state:
        results.append(check_sanitize_state(args.sanitize_state))

    failures = _print_results(results)
    gate = _security_gate(results, args)
    if args.write_gate:
        _write_gate(args.write_gate, gate)
        print(f"\nSECURITY_GATE: {args.write_gate} ({gate['level']})")
    if failures:
        print(f"\nRESULT: FAIL ({failures} issue(s))")
        return 1
    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
