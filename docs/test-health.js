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

console.log("\n[6] Gecerli bar orani (select_valid) — 2026-08-26 vakasi");
{
  // O gun: kapsama %99.7 YESIL iken valid 11/621 = %1.8 -> top10 coktu, panel gormedi.
  const base = {
    last_data_date: "2026-06-29",
    price_count: 621,
    source_pool_count: 623,
    source: "yahoo",
    timestamp: "2026-06-29T14:30:00",
    official_sources: { kap: { status: "ok", latest_event_date: "2026-06-29", total_events: 3 } },
    operation_health: {
      target_time: "14:30", source: "yahoo", last_data_date: "2026-06-29",
      price_count: 621, source_pool_count: 623, delay_minutes: 0,
      data_health: { data_issues: [] }, telegram: { sent: true, status: "sent" },
    },
  };

  // YON-1: cokmus evren -> KIRMIZI (asil vaka)
  const cok = JSON.parse(JSON.stringify(base));
  cok.select_valid_count = 11;
  check("valid 11/621 metrik kirmizi",
    evaluate(cok, MON_PM).metrics.find(m => m.key === "select_valid").status, "r");
  check("valid 11/621 verdict kirmizi", evaluate(cok, MON_PM).verdict, "r");
  check("kapsama YINE yesil (iki oran bagimsiz)",
    evaluate(cok, MON_PM).metrics.find(m => m.key === "coverage").status, "g");

  // YON-2: saglikli evren -> YESIL (pozitif kontrol; tek yonlu test yetmez)
  const iyi = JSON.parse(JSON.stringify(base));
  iyi.select_valid_count = 600;
  check("valid 600/621 metrik yesil",
    evaluate(iyi, MON_PM).metrics.find(m => m.key === "select_valid").status, "g");
  check("valid 600/621 verdict yesil", evaluate(iyi, MON_PM).verdict, "g");

  // YON-3: ALAN YOK -> "n" (olculemedi), KIRMIZI DEGIL. FIX_ANCHOR kurali:
  // eski state'ler bu alani tasimiyor; "yok != kirik" olmali, yoksa sahte alarm.
  const yok = JSON.parse(JSON.stringify(base));
  check("alan yok -> metrik n (olculemedi)",
    evaluate(yok, MON_PM).metrics.find(m => m.key === "select_valid").status, "n");
  check("alan yok -> verdict BOZULMAZ", evaluate(yok, MON_PM).verdict, "g");

  // YON-4: esik siniri (0.5) — content_sanity VALID_RATIO_MIN ile ayni olmali
  const sinirAlt = JSON.parse(JSON.stringify(base));
  sinirAlt.select_valid_count = 310;                    // 310/621 = 0.499 -> kirmizi
  check("oran 0.499 -> kirmizi",
    evaluate(sinirAlt, MON_PM).metrics.find(m => m.key === "select_valid").status, "r");
  const sinirUst = JSON.parse(JSON.stringify(base));
  sinirUst.select_valid_count = 311;                    // 311/621 = 0.501 -> yesil
  check("oran 0.501 -> yesil",
    evaluate(sinirUst, MON_PM).metrics.find(m => m.key === "select_valid").status, "g");

  // operation_health icinden de okunabilmeli (iki yerden de gelebiliyor)
  const oh = JSON.parse(JSON.stringify(base));
  oh.operation_health.select_valid_count = 11;
  check("operation_health icinden de okunur",
    evaluate(oh, MON_PM).metrics.find(m => m.key === "select_valid").status, "r");
}

console.log("\n[8] P0.6/madde-7 bagimsiz stop gozlemi kapisi");
{
  // Bu dosya 2026-09-10'a kadar HICBIR YERDEN kosulmuyordu (yalnizca varligi
  // aranıyordu). Artik selftest node varsa kosturuyor -> senaryo eklemek anlamli.
  // Kapi hukmunu PYTHON uretir (stop_observer.gate_verdict); burada olculen sey
  // panelin o hukmu DOGRU TASIYIP TASIMADIGI, hukmu yeniden hesaplamak DEGIL.
  const base = () => ({
    last_data_date: "2026-06-29",
    price_count: 600,
    source_pool_count: 605,
    source: "yahoo",
    source_pool_fallback: false,
    timestamp: "2026-06-29T09:45:00",
    official_sources: { kap: { status: "ok", latest_event_date: "2026-06-29", total_events: 3 } },
  });
  const iz = (verdict, extra) => Object.assign({
    schema_version: 1,
    generated_at: "2026-06-29T11:30:00Z",
    position_count: 4,
    unpriced_count: 0,
    breach: false,
    price_asof: { oldest: "2026-06-29", newest: "2026-06-29", distinct: 1 },
    price_freshness: { status: "FRESH" },
    gate: { verdict: verdict, reason: "r", detail: "d" },
  }, extra || {});
  const satir = (d) => evaluate(d, MON_PM).metrics.find(m => m.key === "stop_observer");

  // ARTEFAKT YOK -> "n" (olculemedi), "g" DEGIL: yokluk guvence degildir.
  // Ve verdict'i BOZMAMALI (coreWorst "n"leri disarida birakir).
  const yok = base();
  check("artefakt yok -> n", satir(yok).status, "n");
  check("artefakt yok -> verdict bozulmaz", evaluate(yok, MON_PM).verdict, "g");
  check("artefakt yok -> cekirdek metrik", satir(yok).core, true);

  const yesil = base(); yesil.stop_observer = iz("GREEN");
  check("GREEN -> g", satir(yesil).status, "g");
  check("GREEN -> verdict yesil", evaluate(yesil, MON_PM).verdict, "g");

  const sari = base(); sari.stop_observer = iz("YELLOW", { unpriced_count: 1 });
  check("YELLOW -> a", satir(sari).status, "a");
  check("YELLOW -> verdict sari", evaluate(sari, MON_PM).verdict, "a");

  const kirmizi = base(); kirmizi.stop_observer = iz("RED", { unpriced_count: 4 });
  check("RED -> r", satir(kirmizi).status, "r");
  check("RED -> verdict kirmizi", evaluate(kirmizi, MON_PM).verdict, "r");

  // Breach ALT SATIRDA gorunur ama harfi degistirmez: breach bir TICARET olayidir,
  // gozlem saglikli calismistir (kapi "gozlem yapilabildi mi" sorusunu olcer).
  const ihlal = base(); ihlal.stop_observer = iz("GREEN", { breach: true });
  check("breach gorunur", satir(ihlal).sub.indexOf("STOP ALTINDA") >= 0, true);
  check("breach harfi degistirmez", satir(ihlal).status, "g");

  // Bayatlik: hukum Python'da verilir (gate zaten YELLOW gelir), panel TASIR.
  const bayat = base();
  bayat.stop_observer = iz("YELLOW", {
    price_asof: { oldest: "2026-06-22", newest: "2026-06-29", distinct: 3 },
    price_freshness: { status: "STALE", oldest_bar: "2026-06-22" },
  });
  check("bayat aralik gorunur", satir(bayat).sub.indexOf("2026-06-22..2026-06-29") >= 0, true);
  check("bayat isareti gorunur", satir(bayat).sub.indexOf("BAYAT") >= 0, true);

  const bilinmez = base();
  bilinmez.stop_observer = iz("GREEN", { price_freshness: { status: "UNKNOWN" } });
  check("tazelik olculemedi gorunur",
    satir(bilinmez).sub.indexOf("tazelik olculemedi") >= 0, true);
  check("tazelik olculemedi harfi bozmaz", satir(bilinmez).status, "g");

  // Bozuk/eksik iz cokmemeli.
  let coktu = false;
  try {
    const bozuk = base();
    bozuk.stop_observer = { generated_at: "x", gate: null, price_asof: "metin" };
    satir(bozuk);
  } catch (e) { coktu = true; }
  check("bozuk iz cokmez", coktu, false);
}

console.log("\n[9] P0.5 kosum izi (run_trace.json)");
{
  // Hukum PYTHON'da (bist_alpha/run_trace.end); panel TASIR. Olculen: eslem
  //   OK -> g · FAILED -> r · RUNNING -> r · yok/bozuk -> n (olculemedi, g DEGIL).
  // RUNNING neden r: state commit `if: always()` oldugu icin yarim iz origin'e
  // duser; commit'lenmis RUNNING = end() hic cagrilmadi = kosum SONLANAMADI.
  const base = () => ({
    last_data_date: "2026-06-29",
    price_count: 600,
    source_pool_count: 605,
    source: "yahoo",
    source_pool_fallback: false,
    timestamp: "2026-06-29T09:45:00",
    official_sources: { kap: { status: "ok", latest_event_date: "2026-06-29", total_events: 3 } },
  });
  const iz = (status, extra) => Object.assign({
    schema_version: 1,
    slot: "gunici",
    status: status,
    phase: "dashboard",
    phases: ["begin", "feed", "shadow:A", "report", "telegram", "dashboard"],
    started_at: "2026-06-29T11:30:00Z",
    updated_at: "2026-06-29T11:31:00Z",
    ended_at: "2026-06-29T11:31:00Z",
    error: null,
  }, extra || {});
  const satir = (d) => evaluate(d, MON_PM).metrics.find(m => m.key === "run_trace");
  const base_with = (trace) => { const d = base(); d.run_trace = trace; return d; };

  const yok = base();
  check("artefakt yok -> n", satir(yok).status, "n");
  check("artefakt yok -> verdict bozulmaz", evaluate(yok, MON_PM).verdict, "g");
  check("artefakt yok -> cekirdek metrik", satir(yok).core, true);
  check("artefakt yok -> 'OLCULEMEDI' yazar", satir(yok).reason.indexOf("OLCULEMEDI") >= 0, true);

  const ok = base(); ok.run_trace = iz("OK", { sha: "abcdef123456" });
  check("OK -> g", satir(ok).status, "g");
  check("OK -> verdict yesil", evaluate(ok, MON_PM).verdict, "g");
  check("OK -> slot gorunur", satir(ok).sub.indexOf("slot gunici") >= 0, true);
  check("OK -> sha 7 gorunur (hangi kod kostu)", satir(ok).sub.indexOf("sha abcdef1") >= 0, true);
  check("sha yoksa satir bozulmaz", satir(base_with(iz("OK", { sha: null }))).sub.indexOf("sha ") < 0, true);

  const dustu = base();
  dustu.run_trace = iz("FAILED", { phase: "shadow:A", error: "ValueError: fiyat_yok" });
  check("FAILED -> r", satir(dustu).status, "r");
  check("FAILED -> verdict kirmizi", evaluate(dustu, MON_PM).verdict, "r");
  check("FAILED -> asama gorunur", satir(dustu).sub.indexOf("asama shadow:A") >= 0, true);
  check("FAILED -> hata gorunur", satir(dustu).sub.indexOf("fiyat_yok") >= 0, true);
  check("FAILED -> sebep asamayi soyler", satir(dustu).reason.indexOf("shadow:A") >= 0, true);

  const yarim = base();
  yarim.run_trace = iz("RUNNING", { phase: "feed", ended_at: null });
  check("RUNNING -> r (sonlanamadi)", satir(yarim).status, "r");
  check("RUNNING -> verdict kirmizi", evaluate(yarim, MON_PM).verdict, "r");
  check("RUNNING -> 'SONLANAMADI' yazar", satir(yarim).reason.indexOf("SONLANAMADI") >= 0, true);
  check("RUNNING -> yas updated_at'ten (ended_at yok)", satir(yarim).sub.indexOf("yas ") >= 0, true);

  // Kucuk harf status: Python buyuk yazar ama panel toUpperCase ile tasimali.
  const kucuk = base(); kucuk.run_trace = iz("ok");
  check("'ok' kucuk harf -> g", satir(kucuk).status, "g");

  // Bilinmeyen status: ne g ne r -> n; verdict'i bozmaz, yesile de boyamaz.
  const acayip = base(); acayip.run_trace = iz("WHATEVER");
  check("bilinmeyen status -> n", satir(acayip).status, "n");

  // Bozuk/eksik iz cokmemeli; bozuk = n.
  let coktu = false;
  let bozukSt = null;
  try {
    const bozuk = base();
    bozuk.run_trace = "metin";
    bozukSt = satir(bozuk).status;
    const bozuk2 = base();
    bozuk2.run_trace = { status: 7, ended_at: "x", slot: null, phase: undefined };
    satir(bozuk2);
  } catch (e) { coktu = true; }
  check("bozuk iz cokmez", coktu, false);
  check("bozuk iz -> n", bozukSt, "n");
}

console.log("\n" + "=".repeat(42) + "\nSONUC: " + pass + " gecti / " + fail + " kaldi");
process.exit(fail === 0 ? 0 : 1);
