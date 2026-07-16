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
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", action="append", default=[], help="Protected Cloudflare base URL; derives key paths")
    parser.add_argument("--protected", action="append", default=[], help="Protected URL to test directly")
    parser.add_argument("--retired", action="append", default=[], help="Old URL expected to be blocked/retired")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    protected_urls: list[str] = []
    for base in args.base:
        protected_urls.extend(_derive(base))
    protected_urls.extend(args.protected)

    if not protected_urls and not args.retired:
        parser.error("provide --base, --protected, or --retired")

    results: list[Result] = []
    for url in protected_urls:
        results.append(check_protected(url, args.timeout))
    for url in args.retired:
        results.append(check_retired(url, args.timeout))

    failures = _print_results(results)
    if failures:
        print(f"\nRESULT: FAIL ({failures} issue(s))")
        return 1
    print("\nRESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
