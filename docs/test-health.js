/* Scenario tests for docs/health-logic.js. */
const { evaluate } = require("./health-logic.js");

const MON_PM = Date.UTC(2026, 5, 29, 12, 0, 0); // Istanbul 15:00
const MON_AM = Date.UTC(2026, 5, 29, 6, 0, 0);  // Istanbul 09:00
const SAT = Date.UTC(2026, 5, 27, 12, 0, 0);

let pass = 0;
let fail = 0;

function check(name, got, want) {
  const ok = got === want;
  console.log("  " + (ok ? "OK " : "XX ") + name + ": beklenen=" + want + " alinan=" + got);
  if (ok) pass++; else fail++;
}

console.log("BIST Alpha health logic scenario tests\n");

console.log("[1] Tamamen saglikli -> YESIL");
{
  const d = {
    last_data_date: "2026-06-29",
    price_count: 600,
    source_pool_count: 605,
    source: "yahoo",
    source_pool_fallback: false,
    timestamp: "2026-06-29T09:45:00",
    broker_bulletin: { available: true, fresh: true, age_days: 1, status: "fresh" },
    official_sources: { kap: { status: "ok", latest_event_date: "2026-06-29", total_events: 3 } },
  };
  const r = evaluate(d, MON_PM);
  check("verdict", r.verdict, "g");
  check("broker metriği ayrı gösterilmez", r.metrics.some(m => m.key === "broker"), false);
}

console.log("\n[2] Cekirdek taze + Broker backend stale -> YESIL");
{
  const d = {
    last_data_date: "2026-06-29",
    price_count: 605,
    source_pool_count: 607,
    source: "yahoo",
    source_pool_fallback: false,
    timestamp: "2026-06-29T08:00:00",
    broker_bulletin: { available: true, fresh: false, age_days: 46, status: "stale" },
    missing_symbol_list: ["ALTIN", "DMLKT"],
    official_sources: { kap: { status: "ok", latest_event_date: "2026-06-29", total_events: 3 } },
  };
  const r = evaluate(d, MON_PM);
  check("verdict", r.verdict, "g");
  check("coreWorst", r.coreWorst, "g");
  check("broker metriği ayrı gösterilmez", r.metrics.some(m => m.key === "broker"), false);
  check("missing reason", r.metrics.find(m => m.key === "missing").reason, "eksik: ALTIN, DMLKT");
}

console.log("\n[2b] Backend eski karar bilgi; metrikler esas -> SARI");
{
  const d = {
    operation_health: {
      verdict: "red",
      last_data_date: "2026-06-29",
      source_pool_count: 607,
      price_count: 605,
      source: "yahoo",
      broker_bulletin: { available: true, fresh: false, age_days: 46, status: "stale" },
      data_health: { data_issues: [] },
    },
    timestamp: "2026-06-29T08:00:00",
    official_sources: { kap: { status: "ok", latest_event_date: "2026-06-29", total_events: 3 } },
  };
  const r = evaluate(d, MON_PM);
  check("verdict", r.verdict, "g");
  check("backend", r.backendVerdict, "r");
}

console.log("\n[3] Fiyat kapsama %90 -> KIRMIZI");
{
  const d = {
    last_data_date: "2026-06-29",
    price_count: 540,
    source_pool_count: 600,
    source: "yahoo",
    timestamp: "2026-06-29T09:00:00",
    broker_bulletin: { available: true, fresh: true, age_days: 1 },
  };
  const r = evaluate(d, MON_PM);
  check("verdict", r.verdict, "r");
  check("coverage", r.metrics.find(m => m.key === "coverage").status, "r");
}

console.log("\n[4] Cuma raporu Pzt sabah/ogle cron davranisi");
{
  const d = {
    last_data_date: "2026-06-29",
    price_count: 600,
    source_pool_count: 605,
    source: "yahoo",
    timestamp: "2026-06-26T20:13:00",
    broker_bulletin: { available: true, fresh: true, age_days: 1 },
  };
  check("Pzt sabah sari", evaluate(d, MON_AM).metrics.find(m => m.key === "report_age").status, "a");
  check("Pzt ogle kirmizi", evaluate(d, MON_PM).metrics.find(m => m.key === "report_age").status, "r");
}

console.log("\n[5] Hafta sonu sahte alarm yok");
{
  const d = {
    last_data_date: "2026-06-26",
    price_count: 605,
    source_pool_count: 607,
    source: "yahoo",
    timestamp: "2026-06-26T18:40:00",
    broker_bulletin: { available: true, fresh: true, age_days: 1 },
  };
  const r = evaluate(d, SAT);
  check("cron yesil", r.metrics.find(m => m.key === "report_age").status, "g");
}

console.log("\n[6] Bozuk/eksik girdi -> cokme yok");
{
  let crashed = false;
  let r = null;
  try {
    r = evaluate({ price_count: "abc", source_pool_count: null, last_data_date: "bozuk", timestamp: "x" }, MON_PM);
  } catch (e) {
    crashed = true;
  }
  check("cokmedi", crashed, false);
  if (r) check("verdict", r.verdict, "r");
}

console.log("\n[7] SLA gecikme esikleri");
{
  const base = {
    last_data_date: "2026-06-29",
    price_count: 605,
    source_pool_count: 607,
    source: "yahoo",
    timestamp: "2026-06-29T14:30:00",
    broker_bulletin: { available: true, fresh: true, age_days: 0 },
    operation_health: {
      target_time: "14:30",
      source: "yahoo",
      last_data_date: "2026-06-29",
      price_count: 605,
      source_pool_count: 607,
      data_health: { data_issues: [] },
      telegram: { sent: true, status: "sent" },
      broker_bulletin: { available: true, fresh: true, age_days: 0 },
    },
  };
  const warn = JSON.parse(JSON.stringify(base));
  warn.operation_health.delay_minutes = 40;
  check("40 dk sari", evaluate(warn, MON_PM).metrics.find(m => m.key === "sla").status, "a");
  check("40 dk verdict sari", evaluate(warn, MON_PM).verdict, "a");

  const red = JSON.parse(JSON.stringify(base));
  red.operation_health.delay_minutes = 61;
  check("61 dk kirmizi", evaluate(red, MON_PM).metrics.find(m => m.key === "sla").status, "r");
  check("61 dk verdict kirmizi", evaluate(red, MON_PM).verdict, "r");
}

console.log("\n" + "=".repeat(42) + "\nSONUC: " + pass + " gecti / " + fail + " kaldi");
process.exit(fail === 0 ? 0 : 1);
