#!/usr/bin/env python3
"""Scrapes checkee.info and generates index.html with daily visa case charts."""

import requests
from bs4 import BeautifulSoup
from collections import defaultdict
import json
import re
import statistics
import time
from datetime import datetime, timezone, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.checkee.info/",
}


def fetch_with_retry(url, retries=4, backoff=15):
    """GET with retries on 403/429/5xx."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code in (403, 429, 503) and attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  Got {r.status_code}, retrying in {wait}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  Request error: {e}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def scrape():
    # Step 1: read the "Last 90 Days" dispdate directly from the site's own dropdown
    base = fetch_with_retry("https://www.checkee.info/main.php?sortby=clear_date")
    base_soup = BeautifulSoup(base.text, "html.parser")
    dispdate = None
    for select in base_soup.find_all("select", {"name": "dispdate"}):
        for opt in select.find_all("option"):
            if "90 Days" in opt.get_text():
                dispdate = opt.get("value")
                break
        if dispdate:
            break
    if not dispdate:
        dispdate = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    print(f"Using dispdate: {dispdate}")

    # Step 2: fetch full 90-day dataset
    url = f"https://www.checkee.info/main.php?sortby=clear_date&dispdate={dispdate}"
    r = fetch_with_retry(url)

    soup = BeautifulSoup(r.text, "html.parser")
    records = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 11:
            visa       = cells[2].get_text(strip=True)
            entry      = cells[3].get_text(strip=True)
            consulate  = cells[4].get_text(strip=True)
            major      = cells[5].get_text(strip=True)
            status     = cells[6].get_text(strip=True)
            check_date = cells[7].get_text(strip=True)
            date       = cells[8].get_text(strip=True)
            try:
                days = int(cells[9].get_text(strip=True))
            except ValueError:
                continue
            _dlink     = cells[10].find('a')
            details    = _dlink.get('title', '').strip() if _dlink else ''
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date) and visa and 0 <= days < 2000:
                records.append({
                    "date": date,
                    "visa": visa,
                    "days": days,
                    "status": status,
                    "check_date": check_date,
                    "entry": entry,
                    "consulate": consulate,
                    "major": major,
                    "details": details,
                })
    return records


def scrape_monthly():
    """Scrape homepage monthly case table; return trailing 12 months."""
    r = fetch_with_retry("https://www.checkee.info/")
    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) >= 6:
            month = cells[1].get_text(strip=True)
            if not re.match(r"^\d{4}-\d{2}$", month):
                continue
            try:
                pending = int(cells[2].get_text(strip=True))
                clear   = int(cells[3].get_text(strip=True))
                reject  = int(cells[4].get_text(strip=True))
                total   = int(cells[5].get_text(strip=True))
                avg_wait_raw = cells[6].get_text(strip=True) if len(cells) > 6 else "-"
                avg_wait = float(avg_wait_raw) if avg_wait_raw not in ("-", "", "N/A") else None
            except ValueError:
                continue
            rows.append({"month": month, "pending": pending, "clear": clear, "reject": reject, "total": total, "avg_wait": avg_wait})
    rows.sort(key=lambda x: x["month"])
    rows = rows[-120:]
    return {
        "months":   [r["month"]    for r in rows],
        "pending":  [r["pending"]  for r in rows],
        "clear":    [r["clear"]    for r in rows],
        "reject":   [r["reject"]   for r in rows],
        "total":    [r["total"]    for r in rows],
        "avg_wait": [r["avg_wait"] for r in rows],
    }


def build_data(records, monthly):
    dates = sorted(set(r["date"] for r in records))

    counts = defaultdict(lambda: defaultdict(int))
    raw_days = defaultdict(list)
    day_days = defaultdict(list)
    check_status_counts = defaultdict(lambda: defaultdict(int))  # check_date -> status -> count
    complete_status_counts = defaultdict(lambda: defaultdict(int))  # complete_date -> status -> count
    entry_counts = defaultdict(int)
    consulate_counts = defaultdict(int)

    for r in records:
        counts[r["visa"]][r["date"]] += 1
        raw_days[r["visa"]].append(r["days"])
        day_days[r["date"]].append(r["days"])
        # Include all valid check dates regardless of how old they are
        cd = r["check_date"]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", cd):
            check_status_counts[cd][r["status"]] += 1
        # Complete date distribution
        if re.match(r"^\d{4}-\d{2}-\d{2}$", r["date"]):
            complete_status_counts[r["date"]][r["status"]] += 1
        if r["entry"]:
            entry_counts[r["entry"]] += 1
        if r["consulate"]:
            consulate_counts[r["consulate"]] += 1

    groups_visas = [["B1", "B2"], ["F1", "F2"], ["H1", "H4"], ["J1", "J2"], ["L1", "L2"], ["O1"]]
    stats = {}
    for visas in groups_visas:
        all_days = [d for v in visas for d in raw_days[v]]
        key = ",".join(visas)
        stats[key] = {
            "total": len(all_days),
            "med": round(statistics.median(all_days)) if all_days else 0,
            "min": min(all_days) if all_days else 0,
            "max": max(all_days) if all_days else 0,
        }

    # Per-day stats across all visa types: [median, min, max]
    daily_stats = {}
    for date in dates:
        dl = day_days[date]
        if dl:
            daily_stats[date] = [
                round(statistics.median(dl)),
                min(dl),
                max(dl),
            ]

    # Check date distribution: sorted statuses for consistent coloring
    all_statuses = sorted(set(
        s for day_s in check_status_counts.values() for s in day_s
    ))
    check_dates = sorted(check_status_counts.keys())
    check_dist = {
        "dates": check_dates,
        "statuses": all_statuses,
        "counts": {
            s: {cd: check_status_counts[cd].get(s, 0) for cd in check_dates}
            for s in all_statuses
        }
    }
    complete_dates = sorted(complete_status_counts.keys())
    complete_dist = {
        "dates": complete_dates,
        "statuses": all_statuses,
        "counts": {
            s: {d: complete_status_counts[d].get(s, 0) for d in complete_dates}
            for s in all_statuses
        }
    }

    # Compact raw records: [date, visa, days, status, check_date, consulate, entry, major, details]
    raw_records = [
        [r["date"], r["visa"], r["days"], r["status"], r["check_date"],
         r["consulate"], r["entry"], r["major"], r["details"]]
        for r in records
    ]

    return {
        "dates": dates,
        "counts": {v: dict(d) for v, d in counts.items()},
        "stats": stats,
        "daily_stats": daily_stats,
        "check_dist": check_dist,
        "complete_dist": complete_dist,
        "entry_dist": dict(entry_counts),
        "consulate_dist": dict(consulate_counts),
        "raw_records": raw_records,
        "monthly": monthly,
    }


def generate_html(data, updated):
    data_json = json.dumps(data)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Checkee.info — Daily Visa Case Charts</title>
<link rel="icon" href="https://www.checkee.info/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3/dist/chartjs-plugin-annotation.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #f8f7f4; font-family: 'Inter', Arial, sans-serif; color: #1e293b; }}
  h1 {{ text-align: center; font-size: 24px; font-weight: 700; padding: 24px 0 6px; letter-spacing: -0.3px; color: #1e293b; }}
  .updated {{ text-align: center; font-size: 11px; color: #94a3b8; margin-bottom: 10px; }}
  .updated a {{ color: #94a3b8; }}
  .filter-pill {{
    display: none; margin: 0 auto 14px; width: fit-content;
    background: #fef3c7; color: #92400e; border: 1px solid #fcd34d;
    border-radius: 20px; padding: 4px 14px; font-size: 12px;
    cursor: pointer; user-select: none; font-weight: 500;
  }}
  .filter-pill.active {{ background: #d97706; color: #fff; border-color: #d97706; }}
  .filter-pill:hover {{ background: #fde68a; }}
  .filter-pill.active:hover {{ background: #b45309; }}
  .grid  {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding: 0 20px 24px; max-width: 1500px; margin: 0 auto; align-items: start; }}
  .monthly-wrap {{ padding: 0 20px 24px; max-width: 1500px; margin: 0 auto; }}
  .card {{ background: #fff; border-radius: 8px; padding: 14px; box-shadow: 0 1px 6px rgba(0,0,0,0.08); }}
  .card h3 {{ text-align: center; font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #1e293b; }}
  .stats {{ display: flex; justify-content: center; gap: 14px; margin-top: 8px; font-size: 11px; color: #888; border-top: 1px solid #f0f0f0; padding-top: 7px; }}
  @media (max-width: 900px)  {{ .grid  {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 600px)  {{ .grid {{ grid-template-columns: 1fr; }} }}
/* ── Records table ─────────────────────────────────────────────── */
#recordsTable {{ width:100%; border-collapse:collapse; font-size:12px; table-layout:fixed; }}
#recordsTable thead th {{
  position: sticky; top: 0;
  background: #f0f0f0; border-bottom: 2px solid #ddd;
  padding: 6px 8px; text-align: left; white-space: normal;
  cursor: pointer; user-select: none;
}}
#recordsTable thead th:hover {{ background: #e4e4e4; }}
#recordsTable tbody tr:nth-child(even) {{ background: #f9f9f9; }}
#recordsTable tbody tr:hover {{ background: #eef4ff; }}
#recordsTable tbody td {{
  padding: 5px 8px; border-bottom: 1px solid #eee;
  vertical-align: top; overflow: hidden;
}}
#recordsTable td.col-details {{ white-space: pre-wrap; word-break: break-word; font-size:11px; }}
#recordsTable td.col-major {{ white-space: normal; word-break: break-word; }}
#recordsTable td:not(.col-details):not(.col-major) {{ white-space: nowrap; text-overflow: ellipsis; }}
#recordsTable td.col-days, #recordsTable th.col-days,
#recordsTable td.col-center, #recordsTable th.col-center {{ text-align: center !important; }}
.table-sort-asc::after  {{ content: ' ▲'; font-size:10px; }}
.table-sort-desc::after {{ content: ' ▼'; font-size:10px; }}
#tableCount {{ font-size:12px; color:#888; margin-bottom:6px; }}
</style>
</head>
<body>
<h1>Daily Completed Cases by Visa Category (Last 90 Days)</h1>
<p class="updated">Last updated: {updated} &nbsp;·&nbsp; Source: <a href="https://www.checkee.info" target="_blank">checkee.info</a></p>
<div id="filterPill" class="filter-pill"></div>
<div class="grid" id="grid"></div>
<div class="monthly-wrap" id="monthlyWrap"></div>
<div class="monthly-wrap" id="waitWrap"></div>
<div style="max-width:1500px;margin:0 auto 24px;padding:0 20px">
  <div class="card">
    <h3>All Records (Last 90 Days)</h3>
    <div id="tableCount"></div>
    <table id="recordsTable"><thead></thead><tbody></tbody></table>
  </div>
</div>
<script>
const DATA = {data_json};
const groups = [
  {{ label: 'Business / Visitor', visas: ['B1','B2'], colors: ['#4E79A7','#9CBDDB'] }},
  {{ label: 'Student',            visas: ['F1','F2'], colors: ['#59A14F','#97CB8F'] }},
  {{ label: 'Work',               visas: ['H1','H4'], colors: ['#E15759','#F0AAAB'] }},
  {{ label: 'Exchange Visitor',   visas: ['J1','J2'], colors: ['#F28E2B','#F8BF80'] }},
  {{ label: 'Intracompany',       visas: ['L1','L2'], colors: ['#76B7B2','#AADBD7'] }},
  {{ label: 'Extraordinary Ability', visas: ['O1'],   colors: ['#B07AA1'] }},
];

// Status colors (defined early so updateAllCharts can reference them)
const statusColors = {{}};
const palette = ['#54A06B','#D4635A','#9DB0C8','#A07840','#A86878','#4E6A7A','#7A9AAA','#A09030'];
(DATA.complete_dist.statuses || []).forEach((s, i) => {{
  statusColors[s] = palette[i % palette.length];
}});

const grid = document.getElementById('grid');
const filterPill = document.getElementById('filterPill');
const chartInstances = {{}};
let activeConsulate = null;

// ── Median helper ─────────────────────────────────────────────────────────────
function jsMedian(arr) {{
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}}

// ── Client-side aggregation ───────────────────────────────────────────────────
function buildAgg(records) {{
  const dateSets = new Set();
  const countsMap = {{}};
  const rawDays = {{}};
  const dayDays = {{}};
  const cscMap = {{}};

  const compMap = {{}};
  for (const [date, visa, days, status, checkDate] of records) {{
    dateSets.add(date);
    countsMap[visa] = countsMap[visa] || {{}};
    countsMap[visa][date] = (countsMap[visa][date] || 0) + 1;
    rawDays[visa] = rawDays[visa] || [];
    rawDays[visa].push(days);
    dayDays[date] = dayDays[date] || [];
    dayDays[date].push(days);
    if (/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(checkDate)) {{
      cscMap[checkDate] = cscMap[checkDate] || {{}};
      cscMap[checkDate][status] = (cscMap[checkDate][status] || 0) + 1;
    }}
    if (/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(date)) {{
      compMap[date] = compMap[date] || {{}};
      compMap[date][status] = (compMap[date][status] || 0) + 1;
    }}
  }}

  const dates = [...dateSets].sort();

  const stats = {{}};
  groups.forEach(g => {{
    const allDays = g.visas.flatMap(v => rawDays[v] || []);
    const tot = allDays.length;
    stats[g.visas.join(',')] = {{
      total: tot,
      med:   jsMedian(allDays),
      min:   tot ? Math.min(...allDays) : 0,
      max:   tot ? Math.max(...allDays) : 0,
    }};
  }});

  const daily_stats = {{}};
  for (const date of dates) {{
    const dl = dayDays[date] || [];
    if (dl.length) {{
      daily_stats[date] = [
        jsMedian(dl),
        Math.min(...dl),
        Math.max(...dl),
      ];
    }}
  }}

  // Use the global status list so colors stay consistent even if a consulate
  // has zero records for some statuses.
  const allStatuses = DATA.complete_dist.statuses || [];
  const checkDates  = Object.keys(cscMap).sort();
  const check_dist  = {{
    dates:    checkDates,
    statuses: allStatuses,
    counts:   Object.fromEntries(allStatuses.map(s => [
      s, Object.fromEntries(checkDates.map(cd => [cd, (cscMap[cd] || {{}})[s] || 0]))
    ])),
  }};
  const compDates = Object.keys(compMap).sort();
  const complete_dist = {{
    dates:    compDates,
    statuses: allStatuses,
    counts:   Object.fromEntries(allStatuses.map(s => [
      s, Object.fromEntries(compDates.map(d => [d, (compMap[d] || {{}})[s] || 0]))
    ])),
  }};

  return {{ dates, counts: countsMap, stats, daily_stats, check_dist, complete_dist }};
}}

// ── Refresh all charts from a (possibly filtered) record list ─────────────────
function updateAllCharts(records) {{
  const agg = buildAgg(records);

  // Visa group charts (cards 0-5)
  groups.forEach((g, i) => {{
    const chart = chartInstances['c' + i];
    if (!chart) return;
    const s = agg.stats[g.visas.join(',')] || {{}};
    chart.data.labels = agg.dates;
    chart.data.datasets.forEach((ds, vi) => {{
      const v = g.visas[vi];
      ds.data = agg.dates.map(d => (agg.counts[v] || {{}})[d] || 0);
    }});
    chart.update();
    // Refresh stats footer
    const statsEl = chart.canvas.closest('.card').querySelector('.stats');
    if (statsEl) statsEl.innerHTML =
      '<span>n=<b style="color:#555">' + (s.total || 0) + '</b></span>' +
      '<span>med <b style="color:#888">' + (s.med || 0) + 'd</b></span>' +
      '<span>min <b style="color:#888">' + (s.min || 0) + 'd</b></span>' +
      '<span>max <b style="color:#888">' + (s.max || 0) + 'd</b></span>';
  }});

  // Waiting days chart
  const wc = chartInstances['cWait'];
  if (wc) {{
    const dstat = agg.daily_stats;
    wc.data.labels = agg.dates;
    wc.data.datasets[0].data = agg.dates.map(d => dstat[d] ? dstat[d][1] : null);
    wc.data.datasets[1].data = agg.dates.map(d => dstat[d] ? dstat[d][2] : null);
    wc.data.datasets[2].data = agg.dates.map(d => dstat[d] ? dstat[d][0] : null);
    wc.update();
  }}

  // Issue date distribution chart
  const cdc = chartInstances['cCD'];
  if (cdc) {{
    const cd = agg.complete_dist;
    cdc.data.labels = cd.dates;
    cdc.data.datasets = (cd.statuses || []).map(s => ({{
      label: s,
      data:  cd.dates.map(d => (cd.counts[s] || {{}})[d] || 0),
      backgroundColor: statusColors[s] || '#999',
      stack: 'stack',
      order: 1,
      pointStyle: 'rect',
    }}));
    cdc.update();
  }}
  _currentTableRecords = records;
  renderTable(records);
}}

// ── Cards 0-5: visa group bar charts ─────────────────────────────────────────
groups.forEach((g, i) => {{
  const s = DATA.stats[g.visas.join(',')] || {{}};
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML =
    '<h3>' + g.label + ' (' + g.visas.join(', ') + ')</h3>' +
    '<canvas id="c' + i + '"></canvas>' +
    '<div class="stats">' +
      '<span>n=<b style="color:#555">' + s.total + '</b></span>' +
      '<span>med <b style="color:#888">' + s.med + 'd</b></span>' +
      '<span>min <b style="color:#888">' + s.min + 'd</b></span>' +
      '<span>max <b style="color:#888">' + s.max + 'd</b></span>' +
    '</div>';
  grid.appendChild(card);

  chartInstances['c' + i] = new Chart(document.getElementById('c' + i), {{
    type: 'bar',
    data: {{
      labels: DATA.dates,
      datasets: g.visas.map((v, vi) => ({{
        label: v,
        data: DATA.dates.map(d => (DATA.counts[v] || {{}})[d] || 0),
        backgroundColor: g.colors[vi],
        stack: 'stack'
      }}))
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ position: 'top', labels: {{ font: {{ size: 11 }}, padding: 6 }} }},
        tooltip: {{ mode: 'index', intersect: false }}
      }},
      scales: {{
        x: {{ stacked: true, ticks: {{ maxRotation: 60, font: {{ size: 8 }} }} }},
        y: {{ stacked: true, beginAtZero: true, title: {{ display: true, text: '# Cases', font: {{ size: 10 }} }} }}
      }}
    }}
  }});
}});

// ── Card 6: waiting days area chart ──────────────────────────────────────────
const waitCard = document.createElement('div');
waitCard.className = 'card';
waitCard.innerHTML =
  '<h3>Waiting Days (All Visa Types)</h3>' +
  '<canvas id="cWait"></canvas>' +
  '<div class="stats"><span style="color:#aaa;font-size:10px">shaded band = min–max &nbsp;·&nbsp; line = median</span></div>';
grid.appendChild(waitCard);

const dstat0 = DATA.daily_stats;
chartInstances['cWait'] = new Chart(document.getElementById('cWait'), {{
  type: 'line',
  data: {{
    labels: DATA.dates,
    datasets: [
      {{
        data: DATA.dates.map(d => dstat0[d] ? dstat0[d][1] : null),
        borderColor: 'transparent',
        backgroundColor: 'rgba(100,170,255,0.18)',
        pointRadius: 0,
        fill: '+1',
        tension: 0.4,
      }},
      {{
        data: DATA.dates.map(d => dstat0[d] ? dstat0[d][2] : null),
        borderColor: 'rgba(150,190,255,0.45)',
        backgroundColor: 'transparent',
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
        tension: 0.4,
      }},
      {{
        data: DATA.dates.map(d => dstat0[d] ? dstat0[d][0] : null),
        borderColor: '#9C6EA0',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        tension: 0.4,
      }},
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        mode: 'index',
        intersect: false,
        callbacks: {{
          label: (ctx) => {{
            // Read from chart's live data so filtered values show correctly
            const val = chartInstances['cWait'].data.datasets[ctx.datasetIndex].data[ctx.dataIndex];
            if (val === null || val === undefined) return '';
            return ['Min: ' + val + 'd', 'Max: ' + val + 'd', 'Med: ' + val + 'd'][ctx.datasetIndex];
          }}
        }}
      }}
    }},
    scales: {{
      x: {{ ticks: {{ maxRotation: 60, font: {{ size: 8 }} }} }},
      y: {{ beginAtZero: false, title: {{ display: true, text: 'Wait Days', font: {{ size: 10 }} }} }}
    }}
  }}
}});

// ── Card 7: issue date distribution (appended before waitCard) ────────────────
const cdCard = document.createElement('div');
cdCard.className = 'card';
cdCard.innerHTML = '<h3>Issue Date Distribution (All Visa Types)</h3><canvas id="cCD"></canvas>' +
  '<div class="stats"><span style="color:#aaa;font-size:10px">stacked bars = status by issue date</span></div>';
grid.insertBefore(cdCard, waitCard);

const cd = DATA.complete_dist;
chartInstances['cCD'] = new Chart(document.getElementById('cCD'), {{
  type: 'bar',
  data: {{
    labels: cd.dates,
    datasets: (cd.statuses || []).map(s => ({{
      label: s,
      data: cd.dates.map(d => (cd.counts[s] || {{}})[d] || 0),
      backgroundColor: statusColors[s],
      stack: 'stack',
      order: 1,
      pointStyle: 'rect',
    }})),
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ position: 'top', labels: {{ font: {{ size: 11 }}, padding: 6, usePointStyle: true }} }},
      tooltip: {{ mode: 'index', intersect: false }}
    }},
    scales: {{
      x: {{ stacked: true, ticks: {{ maxRotation: 60, font: {{ size: 8 }} }} }},
      y: {{ stacked: true, beginAtZero: true, title: {{ display: true, text: '# Cases', font: {{ size: 10 }} }} }}
    }}
  }}
}});

// ── Card 8: consulate pie — click to cross-filter ─────────────────────────────
const entryCard = document.createElement('div');
entryCard.className = 'card';
entryCard.innerHTML =
  '<h3>Consulate Distribution (All Visa Types)</h3>' +
  '<canvas id="cEntry"></canvas>' +
  '<div class="stats"><span style="color:#aaa;font-size:10px">click a slice · click again to reset</span></div>';
grid.appendChild(entryCard);

const consDist   = DATA.consulate_dist || {{}};
const consLabels = Object.keys(consDist).sort((a, b) => consDist[b] - consDist[a]);
const consValues = consLabels.map(k => consDist[k]);

// 12-color qualitative palette: evenly-spaced hues, consistent saturation
function consPastel(name) {{
  const qual12 = [
    '#4B6CB7','#3A9E78','#C25B52','#9060B8',
    '#C87C30','#3A96A0','#8A6040','#6A9040',
    '#C05078','#4A70C0','#A06840','#5A9E80'
  ];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return qual12[h % qual12.length];
}}
const consColors = consLabels.map(name => consPastel(name));

chartInstances['cEntry'] = new Chart(document.getElementById('cEntry'), {{
  type: 'pie',
  data: {{
    labels: consLabels,
    datasets: [{{
      data: consValues,
      backgroundColor: [...consColors],
      borderWidth: 1,
      borderColor: '#fff',
    }}]
  }},
  options: {{
    responsive: true,
    aspectRatio: 2,
    onClick: (evt, elements) => {{
      if (!elements.length) return;
      const consulate = consLabels[elements[0].index];

      if (activeConsulate === consulate) {{
        // Reset: show all data
        activeConsulate = null;
        filterPill.style.display = 'none';
        filterPill.classList.remove('active');
        chartInstances['cEntry'].data.datasets[0].backgroundColor = [...consColors];
        chartInstances['cEntry'].update();
        updateAllCharts(DATA.raw_records);
      }} else {{
        // Apply filter
        activeConsulate = consulate;
        filterPill.textContent = '✕  ' + consulate;
        filterPill.style.display = 'block';
        filterPill.classList.add('active');
        // Dim non-selected slices (append '44' alpha to 7-char hex)
        chartInstances['cEntry'].data.datasets[0].backgroundColor =
          consColors.map((c, i) => consLabels[i] === consulate ? c : c + '44');
        chartInstances['cEntry'].update();
        updateAllCharts(DATA.raw_records.filter(r => r[5] === consulate));
      }}
    }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ font: {{ size: 9 }}, padding: 6 }} }},
      tooltip: {{
        callbacks: {{
          label: (ctx) => {{
            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
            const pct = ((ctx.parsed / total) * 100).toFixed(1);
            return ctx.label + ': ' + ctx.parsed + ' (' + pct + '%)';
          }}
        }}
      }}
    }}
  }}
}});

// Clicking the pill also resets the filter
filterPill.addEventListener('click', () => {{
  if (!activeConsulate) return;
  activeConsulate = null;
  filterPill.style.display = 'none';
  filterPill.classList.remove('active');
  chartInstances['cEntry'].data.datasets[0].backgroundColor = [...consColors];
  chartInstances['cEntry'].update();
  updateAllCharts(DATA.raw_records);
}});

// ── Monthly overview chart ────────────────────────────────────────────────────
(function() {{
  const monthly = DATA.monthly;
  if (!monthly || !monthly.months.length) return;
  const monthlyCard = document.createElement('div');
  monthlyCard.className = 'card';
  monthlyCard.innerHTML = '<h3>Monthly Cases (Trailing 10 Years)</h3><canvas id="cMonthly" style="max-height:220px"></canvas>' +
    '<div class="stats"><span style="color:#aaa;font-size:10px">stacked bars = % by status &nbsp;·&nbsp; line = total cases</span></div>';
  document.getElementById('monthlyWrap').appendChild(monthlyCard);
  const mLabels = monthly.months.map(function(m) {{
    const p = m.split('-');
    return new Date(+p[0], +p[1] - 1, 1).toLocaleDateString('en-US', {{ month: 'short', year: 'numeric' }});
  }});
  const pct = function(arr, i) {{ return monthly.total[i] ? +(arr[i] / monthly.total[i] * 100).toFixed(1) : 0; }};
  new Chart(document.getElementById('cMonthly'), {{
    type: 'line',
    data: {{
      labels: mLabels,
      datasets: [
        {{ label: 'Pending', data: monthly.months.map(function(_,i){{ return pct(monthly.pending,i); }}),
          borderColor: '#9DB0C8', backgroundColor: 'rgba(157,176,200,0.25)',
          borderWidth: 1.5, pointRadius: 0, tension: 0.4, fill: 'origin', order: 3 }},
        {{ label: 'Reject',  data: monthly.months.map(function(_,i){{ return pct(monthly.reject,i) + pct(monthly.pending,i); }}),
          borderColor: '#D4635A', backgroundColor: 'rgba(212,99,90,0.25)',
          borderWidth: 1.5, pointRadius: 0, tension: 0.4, fill: '-1', order: 2 }},
        {{ label: 'Clear',   data: monthly.months.map(function(_,i){{ return pct(monthly.clear,i) + pct(monthly.reject,i) + pct(monthly.pending,i); }}),
          borderColor: '#54A06B', backgroundColor: 'rgba(84,160,107,0.25)',
          borderWidth: 1.5, pointRadius: 0, tension: 0.4, fill: '-1', order: 1 }},
        {{ label: 'Total Cases', data: monthly.total,
          borderColor: '#1e293b', backgroundColor: 'transparent',
          borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: false, order: 0, yAxisID: 'yTotal' }},
      ],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'top', labels: {{ font: {{ size: 10 }}, padding: 10, usePointStyle: true, boxWidth: 8 }} }},
        tooltip: {{
          mode: 'index', intersect: false,
          callbacks: {{
            label: function(ctx) {{
              if (ctx.dataset.yAxisID === 'yTotal') return 'Total: ' + ctx.parsed.y;
              const i = ctx.dataIndex;
              const abs = {{ 'Clear': monthly.clear[i], 'Reject': monthly.reject[i], 'Pending': monthly.pending[i] }}[ctx.dataset.label] ?? '';
              const p = {{ 'Clear': pct(monthly.clear,i), 'Reject': pct(monthly.reject,i), 'Pending': pct(monthly.pending,i) }}[ctx.dataset.label] ?? 0;
              return ctx.dataset.label + ': ' + p + '% (' + abs + ')';
            }},
          }},
        }},
        annotation: {{ annotations: {{
          covid: {{
            type: 'line', scaleID: 'x',
            value: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2020'); }}),
            borderColor: 'rgba(180,0,0,0.35)', borderWidth: 1,
            borderDash: [4, 4],
            label: {{ content: '🦠 COVID-19', display: true, position: 'start',
              font: {{ size: 9 }}, color: 'rgba(180,0,0,0.55)',
              backgroundColor: 'transparent', padding: 2 }},
          }},
        }} }},
      }},
      scales: {{
        x: {{
          ticks: {{ font: {{ size: 9 }}, color: '#aaa',
            callback: function(val, i) {{
              const l = mLabels[i] || '';
              return l.startsWith('Jan') ? l : '';
            }}
          }},
          grid: {{ color: 'rgba(0,0,0,0.04)', drawTicks: false }} }},
        y: {{ min: 0, max: 100,
          ticks: {{ font: {{ size: 9 }}, color: '#aaa', callback: function(v) {{ return v + '%'; }} }},
          grid: {{ color: 'rgba(0,0,0,0.05)' }} }},
        yTotal: {{ type: 'linear', position: 'right', beginAtZero: true,
          ticks: {{ font: {{ size: 9 }}, color: '#aaa' }},
          grid: {{ drawOnChartArea: false }} }},
      }},
    }},
  }});

  // ── Avg Waiting Days chart ────────────────────────────────────────────────
  const avgWait = monthly.avg_wait || [];
  if (avgWait.some(function(v) {{ return v !== null; }})) {{
    const waitCard2 = document.createElement('div');
    waitCard2.className = 'card';
    waitCard2.innerHTML = '<h3>Avg Waiting Days for Completed Cases (Trailing 10 Years)</h3><canvas id="cAvgWait" style="max-height:220px"></canvas>' +
      '<div class="stats"><span style="color:#aaa;font-size:10px">line = avg waiting days for cleared/rejected cases that month</span></div>';
    document.getElementById('waitWrap').appendChild(waitCard2);
    new Chart(document.getElementById('cAvgWait'), {{
      type: 'line',
      data: {{
        labels: mLabels,
        datasets: [{{
          label: 'Avg Waiting Days',
          data: avgWait,
          borderColor: '#9C6EA0',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
          spanGaps: true,
        }}],
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{ mode: 'index', intersect: false, callbacks: {{
            label: function(ctx) {{ return 'Avg wait: ' + (ctx.parsed.y !== null ? ctx.parsed.y + 'd' : 'N/A'); }},
          }} }},
          annotation: {{ annotations: {{
            covid: {{
              type: 'line', scaleID: 'x',
              value: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2020'); }}),
              borderColor: 'rgba(180,0,0,0.3)', borderWidth: 1,
              borderDash: [4, 4],
              label: {{ content: '🦠 COVID-19', display: true, position: 'end',
                font: {{ size: 9 }}, color: 'rgba(180,0,0,0.45)',
                backgroundColor: 'transparent', padding: 2 }},
            }},
            obama: {{
              type: 'box', xScaleID: 'x',
              xMin: 0,
              xMax: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2017'); }}),
              backgroundColor: 'rgba(33,150,243,0.06)', borderWidth: 0,
              label: {{ content: 'Obama', display: true, position: {{ x: 'center', y: 'start' }},
                font: {{ size: 10, style: 'italic' }}, color: 'rgba(33,150,243,0.5)' }},
            }},
            trump1: {{
              type: 'box', xScaleID: 'x',
              xMin: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2017'); }}),
              xMax: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2021'); }}),
              backgroundColor: 'rgba(244,67,54,0.06)', borderWidth: 0,
              label: {{ content: 'Trump I', display: true, position: {{ x: 'center', y: 'start' }},
                font: {{ size: 10, style: 'italic' }}, color: 'rgba(244,67,54,0.5)' }},
            }},
            biden: {{
              type: 'box', xScaleID: 'x',
              xMin: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2021'); }}),
              xMax: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2025'); }}),
              backgroundColor: 'rgba(33,150,243,0.06)', borderWidth: 0,
              label: {{ content: 'Biden', display: true, position: {{ x: 'center', y: 'start' }},
                font: {{ size: 10, style: 'italic' }}, color: 'rgba(33,150,243,0.5)' }},
            }},
            trump2: {{
              type: 'box', xScaleID: 'x',
              xMin: mLabels.findIndex(function(l) {{ return l.includes('Jan') && l.includes('2025'); }}),
              xMax: mLabels.length - 1,
              backgroundColor: 'rgba(244,67,54,0.06)', borderWidth: 0,
              label: {{ content: 'Trump II', display: true, position: {{ x: 'center', y: 'start' }},
                font: {{ size: 10, style: 'italic' }}, color: 'rgba(244,67,54,0.5)' }},
            }},
          }} }},
        }},
        scales: {{
          x: {{
            ticks: {{ font: {{ size: 9 }}, color: '#aaa',
              callback: function(val, i) {{
                const l = mLabels[i] || '';
                return (l.startsWith('Jan') || l.startsWith('May') || l.startsWith('Sep')) ? l : '';
              }}
            }},
            grid: {{ color: 'rgba(0,0,0,0.04)', drawTicks: false }},
          }},
          y: {{ beginAtZero: true,
            ticks: {{ font: {{ size: 9 }}, color: '#aaa', callback: function(v) {{ return v + 'd'; }} }},
            grid: {{ color: 'rgba(0,0,0,0.05)' }} }},
        }},
      }},
    }});
  }}
}})();

// ── Records table ─────────────────────────────────────────────────────────
let tableSortCol = 2;   // default: complete date (col index 2 in cols array)
let tableSortDir = -1;  // -1 = desc (newest first)

function renderTable(records) {{
  // cols: [label, record-index, css-class, width]
  const cols = [
    ['Status',        3, '',           '62px'],
    ['Check Date',    4, '',           '92px'],
    ['Complete Date', 0, '',           '110px'],
    ['Waiting Days',  2, 'col-days',   '76px'],
    ['Visa Type',     1, 'col-center',  '72px'],
    ['Entry',         6, '',           '65px'],
    ['Consulate',     5, '',           '90px'],
    ['Major',         7, 'col-major',   '140px'],
    ['Details',       8, 'col-details',''],
  ];

  // Build header once
  const thead = document.querySelector('#recordsTable thead');
  if (!thead.children.length) {{
    const tr = document.createElement('tr');
    const thNum = document.createElement('th');
    thNum.textContent = '#';
    thNum.style.cssText = 'width:36px;text-align:right;color:#aaa';
    tr.appendChild(thNum);
    cols.forEach(([label, , cls, w], ci) => {{
      const th = document.createElement('th');
      th.textContent = label;
      if (cls) th.className = cls;
      if (w) th.style.width = w;
      th.dataset.ci = ci;
      th.addEventListener('click', () => {{
        if (tableSortCol === ci) {{ tableSortDir *= -1; }}
        else {{ tableSortCol = ci; tableSortDir = 1; }}
        renderTable(_currentTableRecords);
      }});
      tr.appendChild(th);
    }});
    thead.appendChild(tr);
  }}

  // Sort indicators (ci-1 because th[0] is the non-sortable # column)
  thead.querySelectorAll('th').forEach((th, ci) => {{
    th.classList.remove('table-sort-asc', 'table-sort-desc');
    if (ci - 1 === tableSortCol)
      th.classList.add(tableSortDir === 1 ? 'table-sort-asc' : 'table-sort-desc');
  }});

  // Sort records
  const [, idx] = cols[tableSortCol];
  const sorted = [...records].sort((a, b) => {{
    const av = a[idx], bv = b[idx];
    return tableSortDir * (av < bv ? -1 : av > bv ? 1 : 0);
  }});

  // Render tbody
  const tbody = document.querySelector('#recordsTable tbody');
  tbody.innerHTML = '';
  sorted.forEach((r, i) => {{
    const tr = document.createElement('tr');
    const tdNum = document.createElement('td');
    tdNum.textContent = i + 1;
    tdNum.style.cssText = 'text-align:right;color:#aaa;user-select:none';
    tr.appendChild(tdNum);
    cols.forEach(([, ri, cls]) => {{
      const td = document.createElement('td');
      if (cls) td.className = cls;
      td.textContent = r[ri] ?? '';
      tr.appendChild(td);
    }});
    tbody.appendChild(tr);
  }});

  // Count line
  const countEl = document.getElementById('tableCount');
  if (countEl) countEl.textContent = sorted.length + ' record' + (sorted.length !== 1 ? 's' : '');
}}

let _currentTableRecords = DATA.raw_records;
updateAllCharts(DATA.raw_records);
</script>
</body>
</html>"""


if __name__ == "__main__":
    import sys
    print("Scraping checkee.info...")
    try:
        records = scrape()
    except Exception as e:
        print(f"ERROR: scrape failed after all retries: {e}")
        print("Keeping existing index.html unchanged.")
        sys.exit(0)
    print(f"Found {len(records)} records")
    if not records:
        print("WARNING: 0 records returned (site may be blocking CI). Keeping existing index.html.")
        sys.exit(0)
    print("Scraping monthly case table...")
    try:
        monthly = scrape_monthly()
        print(f"Monthly rows: {len(monthly['months'])}")
    except Exception as e:
        print(f"WARNING: monthly scrape failed: {e}. Using empty data.")
        monthly = {"months": [], "pending": [], "clear": [], "reject": [], "total": []}
    data = build_data(records, monthly)
    print(f"Dates: {data['dates'][0] if data['dates'] else 'none'} → {data['dates'][-1] if data['dates'] else 'none'}")
    print(f"Statuses found: {data['check_dist']['statuses']}")
    print(f"Check dates: {len(data['check_dist']['dates'])} days")
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(data, updated)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Generated index.html ✓")
