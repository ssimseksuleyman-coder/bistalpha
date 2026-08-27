/* BIST Alpha health logic.
   Pure evaluator for both browser and Node tests. It reads dashboard.json only;
   it never changes trading state and never touches the F engine. */
(function (root) {
  const CONFIG = {
    dataAge: { freshTd: 1, warnTd: 2 },
    coverage: { green: 0.98, amber: 0.95 },
    missing: { greenPct: 1, amberPct: 5 },
    source: { firstRunGraceIstHour: 12 },
    minPool: 100,
  };

  const RANK = { g: 0, a: 1, r: 2, n: -1 };

  function worse(a, b) {
    return RANK[b] > RANK[a] ? b : a;
  }

  function num(value) {
    const n = typeof value === "number"
      ? value
      : (typeof value === "string" && value.trim() !== "" ? Number(value) : NaN);
    return Number.isFinite(n) ? n : null;
  }

  function str(value) {
    return typeof value === "string" && value.trim() !== "" ? value : null;
  }

  function dateOnly(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ""));
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null;
  }

  function timestampMs(value) {
    if (!value) return null;
    const s = String(value);
    const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(s);
    const t = Date.parse(hasZone ? s : s + "+03:00");
    return Number.isFinite(t) ? t : null;
  }

  function tradingDaysBetween(fromMs, toMs) {
    if (fromMs == null || toMs == null) return null;
    const day = 86400000;
    const fromD = Math.floor(fromMs / day) * day;
    const toD = Math.floor(toMs / day) * day;
    if (toD <= fromD) return 0;
    let count = 0;
    for (let t = fromD + day; t <= toD; t += day) {
      const wd = new Date(t).getUTCDay();
      if (wd !== 0 && wd !== 6) count++;
    }
    return count;
  }

  function istanbulHour(nowMs) {
    return (new Date(nowMs).getUTCHours() + 3) % 24;
  }

  function metric(key, core, label, hint, value, sub, status, reason) {
    return { key, core, label, hint, value, sub, status, reason };
  }

  function normalizeVerdict(value) {
    const s = String(value || "").toLowerCase();
    if (s === "green" || s === "g" || s === "yesil") return "g";
    if (s === "amber" || s === "a" || s === "sari" || s === "yellow") return "a";
    if (s === "red" || s === "r" || s === "kirmizi") return "r";
    return null;
  }

  function evaluate(data, nowMs) {
    const d = data && typeof data === "object" ? data : {};
    const h = d.operation_health && typeof d.operation_health === "object"
      ? d.operation_health
      : {};
    const out = [];

    const lastData = str(h.last_data_date) || str(d.last_data_date) || str(d.date);
    const dataAge = tradingDaysBetween(dateOnly(lastData), nowMs);
    out.push(metric(
      "last_data", true, "Son veri tarihi", "<=1 islem gunu taze",
      lastData || "-", dataAge == null ? "gecersiz" : dataAge + " islem gunu",
      dataAge == null ? "r" : dataAge <= CONFIG.dataAge.freshTd ? "g" : dataAge <= CONFIG.dataAge.warnTd ? "a" : "r",
      dataAge == null ? "tarih okunamadi" : "veri yasi " + dataAge + " islem gunu"
    ));

    const pool = num(h.source_pool_count ?? d.source_pool_count);
    const priceCount = num(h.price_count ?? d.price_count);
    const coverage = pool != null && pool > 0 && priceCount != null && priceCount >= 0
      ? priceCount / pool
      : null;
    let coverageStatus = "r";
    let coverageReason = "price_count/source_pool_count eksik";
    if (coverage != null) {
      if (pool < CONFIG.minPool) {
        coverageStatus = "r";
        coverageReason = "havuz " + pool + " < " + CONFIG.minPool + " (anormal)";
      } else if (coverage >= CONFIG.coverage.green) {
        coverageStatus = "g";
        coverageReason = "kapsama %" + (coverage * 100).toFixed(1);
      } else if (coverage >= CONFIG.coverage.amber) {
        coverageStatus = "a";
        coverageReason = "kapsama %" + (coverage * 100).toFixed(1);
      } else {
        coverageStatus = "r";
        coverageReason = "kapsama %" + (coverage * 100).toFixed(1);
      }
    }
    out.push(metric(
      "coverage", true, "Fiyat kapsama", "fiyat_count / kaynak_havuzu",
      coverage == null ? "-" : priceCount + "/" + pool,
      coverage == null ? "" : "%" + (coverage * 100).toFixed(1),
      coverageStatus, coverageReason
    ));

    let missing = num(h.missing_symbols);
    let missingPct = num(h.missing_symbol_pct);
    if ((missing == null || missingPct == null) && pool != null && priceCount != null && pool > 0) {
      missing = Math.max(0, pool - priceCount);
      missingPct = missing / pool * 100;
    }
    const missingList = Array.isArray(h.missing_symbol_list)
      ? h.missing_symbol_list
      : (Array.isArray(d.missing_symbol_list) ? d.missing_symbol_list : []);
    out.push(metric(
      "missing", true, "Eksik semboller", "<%1 iyi, %1-5 uyari, >%5 sorun",
      missing == null ? "-" : missing,
      missingPct == null ? "" : "%" + missingPct.toFixed(2),
      missingPct == null ? "n" : missingPct < CONFIG.missing.greenPct ? "g" : missingPct <= CONFIG.missing.amberPct ? "a" : "r",
      missingList.length ? "eksik: " + missingList.join(", ") : (missingPct == null ? "hesaplanamadi" : "eksik oran %" + missingPct.toFixed(2))
    ));

    const fallback = Boolean(h.fallback || d.source_pool_fallback || String(h.source || d.source || "").startsWith("file_fallback_from_"));
    const source = str(h.source) || str(d.source);
    out.push(metric(
      "source", true, "Veri kaynagi / fallback", "birincil kaynak mi, yedek mi",
      source || "-", fallback ? "FALLBACK" : "birincil",
      source ? (fallback ? "a" : "g") : "n",
      source ? (fallback ? "yedek kaynaga dusmus" : "birincil kaynak: " + source) : "kaynak yok"
    ));

    const ts = timestampMs(d.timestamp);
    const reportAge = tradingDaysBetween(ts, nowMs);
    const ih = istanbulHour(nowMs);
    let reportStatus = "n";
    let reportSub = "";
    let reportReason = "timestamp okunamadi";
    if (reportAge != null) {
      reportSub = reportAge === 0 ? "bugun" : reportAge + " islem gunu";
      if (reportAge === 0) {
        reportStatus = "g";
        reportReason = "rapor bugun guncellendi";
      } else if (reportAge === 1 && ih < CONFIG.source.firstRunGraceIstHour) {
        reportStatus = "a";
        reportReason = "Istanbul " + ih + ":00 - bugunku kosu beklemede";
      } else if (reportAge === 1) {
        reportStatus = "r";
        reportReason = "Istanbul " + ih + ":00 - bugunku kosular gelmedi";
      } else {
        reportStatus = "r";
        reportReason = "rapor " + reportAge + " islem gunu once";
      }
    }
    out.push(metric(
      "report_age", true, "Rapor tazeligi", "cron ve dashboard canli mi",
      d.timestamp ? String(d.timestamp).replace("T", " ") : "-",
      reportSub, reportStatus, reportReason
    ));

    const delay = num(h.delay_minutes);
    const slaInfo = h.sla || {};
    const slaReason = slaInfo.root_cause || (delay == null ? "manuel/push calismasi" : "hedefe gore " + delay + " dakika");
    out.push(metric(
      "sla", true, "Rapor SLA", "hedef saat ve gecikme dakikasi",
      h.target_time || "-", delay == null ? "plansiz" : delay + " dk gecikme | " + slaReason,
      delay == null ? "n" : delay <= 15 ? "g" : delay <= 60 ? "a" : "r",
      slaReason
    ));

    const tg = h.telegram || {};
    out.push(metric(
      "telegram", true, "Telegram durumu", "rapor mesaji kullaniciya ulasti mi",
      tg.status || "-", tg.sent === true ? "gonderildi" : tg.sent === false ? "hata" : "bilinmiyor",
      tg.sent === true ? "g" : tg.sent === false ? "r" : "n",
      tg.sent === true ? "Telegram API basarili" : tg.sent === false ? "Telegram API hata dondurdu" : "sonuc kaydi yok"
    ));

    const consistency = d.consistency && d.consistency.account_values;
    const cStatus = consistency && consistency.status;
    out.push(metric(
      "account_consistency", true, "Hesap tutarliligi", "dashboard / Telegram / portfolio ayni mi",
      cStatus || "-",
      consistency ? "max getiri farki %" + (consistency.max_return_diff_pct ?? "-") : "metrik yok",
      cStatus === "ok" ? "g" : cStatus === "warn" ? "a" : "n",
      consistency ? (consistency.note || "hesaplar karsilastirildi") : "dashboard.json henuz bu metrigi uretmiyor"
    ));

    const kap = (d.official_sources && d.official_sources.kap) || {};
    const kapStatus = kap.status || "missing";
    out.push(metric(
      "kap", false, "KAP resmi kaynak", "katalizor olay toplama durumu",
      kap.latest_event_date || "-",
      "olay " + (kap.total_events ?? 0) + " | " + kapStatus,
      kapStatus === "ok" ? "g" : kapStatus === "error" ? "r" : "a",
      kap.error || kap.note || "KAP status bekleniyor"
    ));

    const issues = (h.data_health && h.data_health.data_issues) || [];
    out.push(metric(
      "health", true, "Bakim saglik kontrolu", "NaN, donmus fiyat, eski veri uyarilari",
      issues.length, issues.length ? issues.slice(0, 2).join(" | ") : "sorun yok",
      issues.length ? "r" : "g",
      issues.length ? "bakim " + issues.length + " sorun buldu" : "bakim temiz"
    ));

    const cleaning = h.data_cleaning || (h.data_health && h.data_health.data_cleaning) || {};
    const dropped = cleaning.dropped_dates || [];
    out.push(metric(
      "data_cleaning", false, "Veri temizleme", "yarim/seyrek son bar atildi mi",
      cleaning.dropped_sparse_tail ? "uygulandi" : "yok",
      cleaning.dropped_sparse_tail ? "son saglikli " + (cleaning.last_healthy_date || "-") : "ham veri kullanildi",
      cleaning.dropped_sparse_tail ? "a" : "g",
      cleaning.dropped_sparse_tail
        ? "atilan gun: " + dropped.map(x => x.date + " %" + x.nan_pct).join(", ")
        : "son satir yeterli dolulukta"
    ));

    out.push(metric(
      "gap", false, "Fiyat/hacim bosluk orani", "seri ici eksik bar orani",
      "N/A", "backend metrigi eklenecek", "n",
      "dashboard.json henuz bu metrigi uretmiyor"
    ));

    const coreWorst = out.filter(x => x.core && x.status !== "n").reduce((w, x) => worse(w, x.status), "g");
    const auxWorst = out.filter(x => !x.core && x.status !== "n").reduce((w, x) => worse(w, x.status), "g");
    const backendVerdict = normalizeVerdict(h.verdict);
    let verdict = coreWorst;
    let note = "Cekirdek operasyon saglikli; sinyal raporu okunabilir.";
    if (coreWorst === "r") note = "Cekirdek veri/operasyon sorunlu; sinyale temkinli yaklas.";
    else if (coreWorst === "a") note = "Cekirdek katmanda uyari var; raporu kontrol ederek kullan.";
    else if (auxWorst === "r" || auxWorst === "a") {
      verdict = "a";
      note = "Fiyat verisi saglikli; yardimci kaynaklarda uyari var.";
    }
    if (backendVerdict && backendVerdict !== verdict) {
      note += " Backend eski karar: " + backendVerdict + "; panel guncel metriklere gore okur.";
    }

    return { metrics: out, verdict, note, coreWorst, auxWorst, backendVerdict };
  }

  const api = { evaluate, CONFIG, tradingDaysBetween, istanbulHour, timestampMs, dateOnly };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.BistHealth = api;
})(typeof window !== "undefined" ? window : globalThis);
