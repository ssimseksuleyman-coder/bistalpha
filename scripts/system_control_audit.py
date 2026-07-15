"""BIST Alpha system control audit.

This script is intentionally read-mostly: it checks architecture, state files,
public-output hygiene, operational gates, and measurement ledgers without
changing the trading engine. Use it as a maintenance control, not as a signal.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "docs" / "state"
PUBLIC_DIR = ROOT / "docs"

FORBIDDEN_PUBLIC_TERMS = [
    "statDeniz",
    "deniz_bulletin",
    "deniz_regime",
    "market_score_deniz",
    "Deniz bulten",
    "Deniz bülten",
    "Deniz market",
]

TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b")


@dataclass
class Check:
    category: str
    control: str
    status: str
    summary: str
    evidence: list[str]
    action: str = ""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(read_text(path)), None
    except Exception as exc:  # pragma: no cover - diagnostic path
        return None, str(exc)


def add(
    checks: list[Check],
    category: str,
    control: str,
    status: str,
    summary: str,
    evidence: list[str] | None = None,
    action: str = "",
) -> None:
    checks.append(
        Check(
            category=category,
            control=control,
            status=status,
            summary=summary,
            evidence=evidence or [],
            action=action,
        )
    )


def py_files() -> list[Path]:
    ignored_parts = {".git", ".venv", "__pycache__"}
    return [
        p
        for p in ROOT.rglob("*.py")
        if not any(part in ignored_parts for part in p.relative_to(ROOT).parts)
    ]


def public_files() -> list[Path]:
    if not PUBLIC_DIR.exists():
        return []
    return [
        p
        for p in PUBLIC_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".html", ".js", ".json", ".md"}
    ]


def gitignore_lines() -> list[str]:
    path = ROOT / ".gitignore"
    return read_text(path).splitlines() if path.exists() else []


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def check_duplicates(checks: list[Check]) -> None:
    ignored_parts = {".git", ".venv", "__pycache__"}
    files = [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(part in ignored_parts for part in p.relative_to(ROOT).parts)
    ]
    names = defaultdict(list)
    for p in files:
        names[p.name.lower()].append(rel(p))
    duplicates = {name: paths for name, paths in names.items() if len(paths) > 1}
    notable = [
        f"{name}: {', '.join(paths[:4])}{' ...' if len(paths) > 4 else ''}"
        for name, paths in sorted(duplicates.items())
        if not name.endswith((".pyc", ".tmp"))
    ][:10]
    add(
        checks,
        "Duplicate / redundant files",
        "Duplicate basename scan",
        "warn" if notable else "pass",
        "Same-name files exist and should stay intentional." if notable else "No notable duplicate basenames found.",
        notable,
        "Keep only if each copy has a different role; otherwise merge or archive under local/.",
    )

    root_scripts = sorted(p.name for p in ROOT.glob("*.py"))
    add(
        checks,
        "Duplicate / redundant files",
        "Root script sprawl",
        "warn" if len(root_scripts) > 12 else "pass",
        f"{len(root_scripts)} root-level Python scripts found.",
        root_scripts[:30],
        "Promote active scripts into scripts/ or bist_alpha/; move experiments to local/ after audit.",
    )


def check_public_hygiene(checks: list[Check]) -> None:
    hits = []
    for path in public_files():
        text = read_text(path)
        for term in FORBIDDEN_PUBLIC_TERMS:
            if term in text:
                hits.append(f"{rel(path)} contains {term}")
    add(
        checks,
        "Misleading / noisy outputs",
        "Public broker-label hygiene",
        "fail" if hits else "pass",
        "Public docs/state contain legacy broker bulletin labels." if hits else "Public docs/state are clean from legacy broker labels.",
        hits[:30],
        "Sanitize docs/state and rerun cloud workflow if any hit appears.",
    )

    dash_path = STATE_DIR / "dashboard.json"
    dash, err = load_json(dash_path)
    if err:
        add(checks, "Misleading / noisy outputs", "Dashboard JSON parse", "fail", err, [rel(dash_path)])
        return
    legacy_keys = [
        k
        for k in ["deniz_bulletin", "deniz_regime", "market_score_deniz", "statDeniz"]
        if isinstance(dash, dict) and k in dash
    ]
    add(
        checks,
        "Misleading / noisy outputs",
        "Dashboard legacy-field check",
        "fail" if legacy_keys else "pass",
        "Dashboard has legacy public fields." if legacy_keys else "Dashboard has no legacy public broker fields.",
        legacy_keys,
    )


def check_json_state(checks: list[Check]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    failures = []
    for path in sorted(STATE_DIR.glob("*.json")):
        obj, err = load_json(path)
        if err:
            failures.append(f"{rel(path)}: {err}")
        else:
            parsed[path.name] = obj
    add(
        checks,
        "Data integrity / validation",
        "State JSON parse",
        "fail" if failures else "pass",
        f"{len(parsed)} state JSON files parsed.",
        failures[:20],
        "Fix malformed generated state before trusting the panel.",
    )

    dash = parsed.get("dashboard.json")
    required = ["timestamp", "date", "top10", "accounts", "operation_health"]
    missing = [k for k in required if not isinstance(dash, dict) or k not in dash]
    add(
        checks,
        "Data integrity / validation",
        "Dashboard required fields",
        "fail" if missing else "pass",
        "Dashboard schema has required fields." if not missing else "Dashboard schema is incomplete.",
        missing,
    )

    if isinstance(dash, dict):
        pool = dash.get("source_pool_count")
        price = dash.get("price_count")
        missing_symbols = dash.get("missing_symbol_list") or []
        coverage = None
        if isinstance(pool, (int, float)) and pool:
            coverage = float(price or 0) / float(pool) * 100.0
        add(
            checks,
            "Data integrity / validation",
            "Live price coverage",
            "pass" if coverage is not None and coverage >= 99.0 else "warn",
            f"Coverage {coverage:.2f}% ({price}/{pool}); missing {len(missing_symbols)}." if coverage is not None else "Coverage metric not available.",
            [", ".join(map(str, missing_symbols[:10]))] if missing_symbols else [],
            "Investigate if coverage falls below 99% or missing list grows.",
        )
    return parsed


def check_security(checks: list[Check]) -> None:
    ignored_parts = {".git", ".venv", "__pycache__"}
    tracked_like = [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(part in ignored_parts for part in p.relative_to(ROOT).parts)
    ]
    token_hits = []
    for path in tracked_like:
        if path.suffix.lower() in {".png", ".db", ".xlsx", ".zip"}:
            continue
        text = read_text(path)
        if TOKEN_RE.search(text):
            token_hits.append(rel(path))
    add(
        checks,
        "Security / legal compliance",
        "Secret token scan",
        "fail" if token_hits else "pass",
        "Potential Telegram/API token found in repo files." if token_hits else "No token-looking literals found in scanned files.",
        token_hits[:20],
        "Move secrets to GitHub Actions secrets and rotate exposed tokens.",
    )

    ignores = "\n".join(gitignore_lines())
    required_ignores = ["local/", "deniz_inbox/", "data/omega/*.json", "deniz_snapshots/*", ".env"]
    missing = [x for x in required_ignores if x not in ignores]
    add(
        checks,
        "Security / legal compliance",
        "Private/licensed-data ignore policy",
        "fail" if missing else "pass",
        "Private and licensed-data paths are ignored." if not missing else "Ignore policy missing private/licensed paths.",
        missing,
        "Keep licensed broker-derived data local; public repo may contain code and sanitized aggregates only.",
    )


def check_code_quality(checks: list[Check]) -> None:
    compile_errors = []
    for path in py_files():
        try:
            source = read_text(path).lstrip("\ufeff")
            compile(source, str(path), "exec")
        except Exception as exc:
            compile_errors.append(f"{rel(path)}: {exc}")
    add(
        checks,
        "Operational / code quality",
        "Python syntax compile",
        "fail" if compile_errors else "pass",
        f"{len(py_files())} Python files compile." if not compile_errors else "Python syntax errors found.",
        compile_errors[:20],
        "Fix syntax errors before deploy.",
    )

    daemon = ROOT / "daemon.py"
    text = read_text(daemon) if daemon.exists() else ""
    ledgers = [
        "opportunity_ledger",
        "performance_ledger",
        "catalyst_ledger",
        "quality_ledger",
        "macro_surprise_ledger",
        "broker_bulletin_ledger",
        "flow_ledger",
    ]
    missing = [name for name in ledgers if name not in text]
    isolated = all(f'state["{name}"] = {name}.update' in text and "except Exception" in text for name in ledgers if name in text)
    add(
        checks,
        "Operational / code quality",
        "Ledger daemon isolation",
        "fail" if missing else ("pass" if isolated else "warn"),
        "Dashboard ledgers are attached with daemon isolation." if not missing and isolated else "Some ledger hooks need isolation review.",
        missing,
        "Every measurement ledger must fail closed into its own error field; F report must continue.",
    )


def check_workflow(checks: list[Check]) -> None:
    path = ROOT / ".github" / "workflows" / "bist-alpha.yml"
    text = read_text(path) if path.exists() else ""
    required = ["workflow_dispatch", "schedule:", "contents: write", "python3 daemon.py", "git add -f portfolios/"]
    missing = [x for x in required if x not in text]
    add(
        checks,
        "Application steps / live operations",
        "GitHub Actions 7/24 workflow",
        "fail" if missing else "pass",
        "Cloud workflow has schedule, manual trigger, daemon run, and state persistence." if not missing else "Workflow missing live-operation pieces.",
        missing,
        "Restore workflow pieces before relying on 7/24 operation.",
    )

    has_fallback = "DATA_FALLBACK_CHAIN" in text and 'ALLOW_FILE_FALLBACK: "1"' in text
    add(
        checks,
        "Application steps / live operations",
        "Data-source fallback chain",
        "pass" if has_fallback else "warn",
        "Workflow has Yahoo plus fallback chain." if has_fallback else "Fallback chain not visible in workflow.",
        [],
        "Keep fallback enabled so Yahoo outages do not kill the report.",
    )


def check_strategy_risk(checks: list[Check], parsed: dict[str, Any]) -> None:
    dash = parsed.get("dashboard.json")
    if isinstance(dash, dict):
        governance = dash.get("account_governance") or {}
        f_role = ((governance.get("F") or {}).get("role") or "").lower()
        add(
            checks,
            "Strategic / algorithmic decisions",
            "F production role",
            "pass" if f_role == "production" else "warn",
            f"F role is {f_role or 'not reported'}.",
            [],
            "F must remain production; experimental accounts stay shadow/ledger until promoted.",
        )

        accounts = dash.get("accounts") or {}
        g1 = accounts.get("G1") or {}
        g1_role = str(g1.get("role") or "").lower()
        add(
            checks,
            "Strategic / algorithmic decisions",
            "G1 shadow discipline",
            "pass" if "shadow" in g1_role or "G1" in accounts else "warn",
            f"G1 account present with role '{g1_role or 'not reported'}'.",
            [],
            "G1 measures re-entry regret; it must not replace F without promotion gates.",
        )

        health = dash.get("operation_health") or {}
        sla = health.get("sla") or {}
        level = str(
            health.get("level")
            or health.get("status")
            or sla.get("status")
            or health.get("decision")
            or ""
        ).lower()
        add(
            checks,
            "Risk / execution controls",
            "Operation gate",
            "warn" if level in {"red", "kirmizi", "kırmızı"} else "pass",
            f"Operation gate reports '{level or 'not reported'}'.",
            [str(health)[:500]],
            "Signals are low-trust while operation gate is red; fix ops before promotion.",
        )

    portfolio = ROOT / "bist_alpha" / "portfolio.py"
    text = read_text(portfolio) if portfolio.exists() else ""
    needed = ["check_stops", "stop", "current_value"]
    missing = [x for x in needed if x not in text]
    add(
        checks,
        "Risk / execution controls",
        "Portfolio stop/value primitives",
        "fail" if missing else "pass",
        "Portfolio has stop and valuation primitives." if not missing else "Portfolio risk primitives missing.",
        missing,
    )


def check_monitoring_docs(checks: list[Check]) -> None:
    needed_docs = [
        "README.md",
        "MASAUSTU_KURULUM.md",
        "OTOMASYON_KILAVUZU.md",
        "docs/KAP_FINANSAL_TABLO_OTOMASYON.md",
        "docs/AKIS_GERI_ALIM_DEFTERI.md",
        "docs/BROKER_BULTEN_DEFTERI.md",
    ]
    missing = [p for p in needed_docs if not (ROOT / p).exists()]
    add(
        checks,
        "Documentation / knowledge management",
        "Core runbook coverage",
        "warn" if missing else "pass",
        "Core operational docs are present." if not missing else "Some operational docs are missing.",
        missing,
        "Keep setup, workflow, official-source, and ledger docs close to code.",
    )

    ui_needed = ["docs/index.html", "docs/health.html", "docs/health-logic.js", "docs/test-health.js"]
    ui_missing = [p for p in ui_needed if not (ROOT / p).exists()]
    add(
        checks,
        "User / interface management",
        "Dashboard and health UI files",
        "fail" if ui_missing else "pass",
        "Dashboard and health UI files are present." if not ui_missing else "UI files missing.",
        ui_missing,
    )

    monitor_files = ["bist_alpha/maintenance.py", "bist_alpha/selfheal.py", "selftest.py"]
    mon_missing = [p for p in monitor_files if not (ROOT / p).exists()]
    add(
        checks,
        "Monitoring / feedback controls",
        "Selftest and maintenance modules",
        "fail" if mon_missing else "pass",
        "Selftest, maintenance, and self-heal modules are present." if not mon_missing else "Maintenance/selftest modules missing.",
        mon_missing,
    )


def check_orphans(checks: list[Check]) -> None:
    modules = {p.stem: p for p in (ROOT / "bist_alpha").glob("*.py") if p.stem != "__init__"}
    references: Counter[str] = Counter()
    generated_self_reports = {STATE_DIR / "system_control_audit.json"}
    reference_files = (
        py_files()
        + [p for p in ROOT.glob("*.md") if p.is_file()]
        + [p for p in public_files() if p not in generated_self_reports]
    )
    for path in reference_files:
        text = read_text(path)
        for name in modules:
            if name in text:
                references[name] += 1

    allowed_entrylike = {
        "deniz",
        "deniz_fetcher",
        "event_study",
        "optimizer",
        "validate",
        "telegram_ingest",
        "omega",
    }
    orphan_candidates = [
        f"{name} ({rel(path)})"
        for name, path in sorted(modules.items())
        if references[name] <= 1 and name not in allowed_entrylike
    ]
    add(
        checks,
        "Unconnected / orphan processes",
        "Low-reference module scan",
        "warn" if orphan_candidates else "pass",
        f"{len(orphan_candidates)} low-reference module candidates.",
        orphan_candidates[:30],
        "Review manually; low reference is not always wrong, but it should be intentional.",
    )


def check_performance_dr_stress(checks: list[Check]) -> None:
    evidence = []
    for path in ["run_backtest.py", "taban_readiness.py", "floor_lock_accounting.py", "ibs_reversal_ledger.py"]:
        if (ROOT / path).exists():
            evidence.append(path)
    add(
        checks,
        "Edge cases / stress tests",
        "Stress and counterfactual tools",
        "warn" if len(evidence) < 3 else "pass",
        f"{len(evidence)} stress/counterfactual tools found.",
        evidence,
        "Keep stress tools separate from production execution.",
    )

    tracked_portfolios = list((ROOT / "portfolios").glob("portfolio_*.json"))
    add(
        checks,
        "Backup / disaster recovery / live transition",
        "Persistent paper portfolio state",
        "pass" if tracked_portfolios else "warn",
        f"{len(tracked_portfolios)} portfolio state files present.",
        [rel(p) for p in tracked_portfolios],
        "State persistence is required for 7/24 shadow continuity.",
    )

    self_maintenance = all((ROOT / p).exists() for p in ["selftest.py", "bist_alpha/maintenance.py", "scripts/system_control_audit.py"])
    add(
        checks,
        "Self-maintenance controls",
        "System can audit itself",
        "pass" if self_maintenance else "warn",
        "Selftest, maintenance, and this control audit exist." if self_maintenance else "Self-maintenance chain incomplete.",
        [],
        "Schedule this audit after major changes or before promotion decisions.",
    )


def build_report() -> dict[str, Any]:
    checks: list[Check] = []
    check_duplicates(checks)
    check_public_hygiene(checks)
    parsed = check_json_state(checks)
    check_security(checks)
    check_code_quality(checks)
    check_workflow(checks)
    check_strategy_risk(checks, parsed)
    check_monitoring_docs(checks)
    check_orphans(checks)
    check_performance_dr_stress(checks)

    counts = Counter(c.status for c in checks)
    overall = "red" if counts["fail"] else ("yellow" if counts["warn"] else "green")
    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "overall": overall,
        "summary": dict(counts),
        "checks": [asdict(c) for c in checks],
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"overall={report['overall']} summary={report['summary']}")
    for item in report["checks"]:
        status = item["status"].upper()
        print(f"[{status}] {item['category']} :: {item['control']} - {item['summary']}")
        if item.get("action") and item["status"] != "pass":
            print(f"  action: {item['action']}")
        for ev in item.get("evidence", [])[:5]:
            print(f"  - {ev}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run BIST Alpha system control audit.")
    parser.add_argument("--write", type=Path, help="Write JSON report to this path.")
    parser.add_argument("--fail-on-red", action="store_true", help="Return non-zero only when a red/fail check exists.")
    args = parser.parse_args(argv)

    report = build_report()
    print_report(report)

    if args.write:
        out = args.write
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {rel(out)}")

    if args.fail_on_red and report["overall"] == "red":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
