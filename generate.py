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
    "Accept-Encoding": "gzip, deflate, br",
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
            details    = cells[10].get_text(strip=True)
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


def build_data(records):
    dates = sorted(set(r["date"] for r in records))

    counts = defaultdict(lambda: defaultdict(int))
    raw_days = defaultdict(list)
    day_days = defaultdict(list)
    check_status_counts = defaultdict(lambda: defaultdict(int))  # check_date -> status -> count
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
        "entry_dist": dict(entry_counts),
        "consulate_dist": dict(consulate_counts),
        "raw_records": raw_records,
    }


def generate_html(data, updated):
    data_json = json.dumps(data)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Checkee.info — Daily Visa Case Charts</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #f5f5f5; font-family: Arial, sans-serif; }}
  h1 {{ text-align: center; font-size: 17px; padding: 20px 0 6px; }}
  .updated {{ text-align: center; font-size: 11px; color: #999; margin-bottom: 10px; }}
  .updated a {{ color: #999; }}
  .filter-pill {{
    display: none; margin: 0 auto 14px; width: fit-content;
    background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9;
    border-radius: 20px; padding: 4px 14px; font-size: 12px;
    cursor: pointer; user-select: none;
  }}
  .filter-pill:hover {{ background: #bbdefb; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding: 0 20px 24px; max-width: 1500px; margin: 0 auto; align-items: start; }}
  .card {{ background: #fff; border-radius: 8px; padding: 14px; box-shadow: 0 1px 4px rgba(0,0,0,.12); }}
  .card h3 {{ text-align: center; font-size: 12px; font-weight: bold; margin-bottom: 8px; }}
  .stats {{ display: flex; justify-content: center; gap: 14px; margin-top: 8px; font-size: 11px; color: #888; border-top: 1px solid #f0f0f0; padding-top: 7px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 600px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>Daily Completed Cases by Visa Category (Last 90 Days)</h1>
<p class="updated">Last updated: {updated} &nbsp;·&nbsp; Source: <a href="https://www.checkee.info" target="_blank">checkee.info</a></p>
<div id="filterPill" class="filter-pill"></div>
<div class="grid" id="grid"></div>
<script>
const DATA = {data_json};
const groups = [
  {{ label: 'Business / Visitor', visas: ['B1','B2'], colors: ['#9C27B0','#E91E63'] }},
  {{ label: 'Student',            visas: ['F1','F2'], colors: ['#4CAF50','#8BC34A'] }},
  {{ label: 'Work',               visas: ['H1','H4'], colors: ['#2196F3','#00BCD4'] }},
  {{ label: 'Exchange Visitor',   visas: ['J1','J2'], colors: ['#FF9800','#FF5722'] }},
  {{ label: 'Intracompany',       visas: ['L1','L2'], colors: ['#607D8B','#795548'] }},
  {{ label: 'Extraordinary Ability', visas: ['O1'],   colors: ['#FFC107'] }},
];

// Status colors (defined early so updateAllCharts can reference them)
const statusColors = {{}};
const palette = ['#F8BBD0','#333333','#2196F3','#FF9800','#9C27B0','#607D8B','#795548','#00BCD4'];
(DATA.check_dist.statuses || []).forEach((s, i) => {{
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
  const allStatuses = DATA.check_dist.statuses || [];
  const checkDates  = Object.keys(cscMap).sort();
  const check_dist  = {{
    dates:    checkDates,
    statuses: allStatuses,
    counts:   Object.fromEntries(allStatuses.map(s => [
      s, Object.fromEntries(checkDates.map(cd => [cd, (cscMap[cd] || {{}})[s] || 0]))
    ])),
  }};

  return {{ dates, counts: countsMap, stats, daily_stats, check_dist }};
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
      '<span>med <b style="color:#e67e22">' + (s.med || 0) + 'd</b></span>' +
      '<span>min <b style="color:#27ae60">' + (s.min || 0) + 'd</b></span>' +
      '<span>max <b style="color:#e74c3c">' + (s.max || 0) + 'd</b></span>';
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

  // Check date distribution chart
  const cdc = chartInstances['cCD'];
  if (cdc) {{
    const cd = agg.check_dist;
    cdc.data.labels = cd.dates;
    cdc.data.datasets = [
      ...(cd.statuses || []).map(s => ({{
        label: s,
        data:  cd.dates.map(d => (cd.counts[s] || {{}})[d] || 0),
        backgroundColor: statusColors[s] || '#999',
        stack: 'stack',
        order: 1,
        pointStyle: 'rect',
      }})),
      cdNormalLine(cd.dates, cd.counts, cd.statuses),
    ];
    cdc.update();
  }}
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
      '<span>med <b style="color:#e67e22">' + s.med + 'd</b></span>' +
      '<span>min <b style="color:#27ae60">' + s.min + 'd</b></span>' +
      '<span>max <b style="color:#e74c3c">' + s.max + 'd</b></span>' +
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
        borderColor: '#e67e22',
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

// ── Card 7: check date distribution ──────────────────────────────────────────
const cdCard = document.createElement('div');
cdCard.className = 'card';
cdCard.innerHTML = '<h3>Check Date Distribution (All Visa Types)</h3><canvas id="cCD"></canvas>' +
  '<div class="stats"><span style="color:#aaa;font-size:10px">stacked bars = status &nbsp;·&nbsp; curve = normal dist. fit</span></div>';
grid.appendChild(cdCard);

const cd = DATA.check_dist;
function cdNormalLine(dates, counts, statuses) {{
  const totals = dates.map(d =>
    (statuses || []).reduce((sum, s) => sum + ((counts[s] || {{}})[d] || 0), 0)
  );
  const N = totals.reduce((a, b) => a + b, 0);
  if (!N || dates.length < 2) {{
    return {{ type: 'line', label: 'Normal dist.', data: dates.map(() => 0),
              borderColor: '#888', backgroundColor: 'transparent',
              borderWidth: 1.5, pointRadius: 0, fill: false, order: 0 }};
  }}
  // Weighted mean and std dev (using date index as x)
  const mean = totals.reduce((s, v, i) => s + v * i, 0) / N;
  const variance = totals.reduce((s, v, i) => s + v * (i - mean) ** 2, 0) / N;
  const std = Math.sqrt(variance) || 1;
  // Gaussian PDF scaled so total area ≈ N (bin width = 1 day)
  const sq2pi = Math.sqrt(2 * Math.PI);
  const data = dates.map((_, i) =>
    N * Math.exp(-0.5 * ((i - mean) / std) ** 2) / (std * sq2pi)
  );
  return {{
    type: 'line',
    label: 'Normal dist.',
    data,
    borderColor: '#555',
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    pointRadius: 0,
    pointStyle: 'line',
    tension: 0,
    fill: false,
    order: 0,
  }};
}}
chartInstances['cCD'] = new Chart(document.getElementById('cCD'), {{
  type: 'bar',
  data: {{
    labels: cd.dates,
    datasets: [
      ...(cd.statuses || []).map(s => ({{
        label: s,
        data: cd.dates.map(d => (cd.counts[s] || {{}})[d] || 0),
        backgroundColor: statusColors[s],
        stack: 'stack',
        order: 1,
        pointStyle: 'rect',
      }})),
      cdNormalLine(cd.dates, cd.counts, cd.statuses),
    ]
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

// City-vibe pastel mapping — medium-saturation tones inspired by each city's character
function consPastel(name) {{
  const n = name.toLowerCase();
  if (n.includes('beijing'))            return '#EF9A9A'; // imperial rose
  if (n.includes('shanghai'))           return '#CE93D8'; // cosmopolitan mauve
  if (n.includes('guangzhou'))          return '#FFCC80'; // cantonese amber
  if (n.includes('chengdu'))            return '#A5D6A7'; // panda sage
  if (n.includes('shenyang'))           return '#90CAF9'; // manchurian sky
  if (n.includes('wuhan'))              return '#FFF176'; // yellow crane gold
  if (n.includes('chongqing'))          return '#FFAB91'; // hot-pot terracotta
  if (n.includes('nanjing'))            return '#B39DDB'; // ancient-capital lavender
  if (n.includes('hong kong') || n.includes('hongkong')) return '#F48FB1'; // neon-nights pink
  if (n.includes('fuzhou'))             return '#80DEEA'; // coastal cyan
  if (n.includes('qingdao'))            return '#80CBC4'; // ocean teal
  if (n.includes('harbin'))             return '#81D4FA'; // ice-festival blue
  if (n.includes('kunming'))            return '#C5E1A5'; // spring-city green
  if (n.includes('taipei'))             return '#FF80AB'; // night-market sakura
  if (n.includes('seoul'))              return '#BA68C8'; // k-beauty violet
  if (n.includes('tokyo'))              return '#F8BBD0'; // cherry blossom
  if (n.includes('osaka'))              return '#FFA726'; // takoyaki amber
  if (n.includes('mumbai') || n.includes('bombay')) return '#FFB74D'; // saffron
  if (n.includes('delhi') || n.includes('new delhi')) return '#AED581'; // garden green
  if (n.includes('hyderabad'))          return '#4DD0E1'; // biryani teal
  if (n.includes('chennai'))            return '#FF8A65'; // warm spice coral
  if (n.includes('kolkata') || n.includes('calcutta')) return '#FFE082'; // marigold
  if (n.includes('singapore'))          return '#FFD54F'; // tropical gold
  if (n.includes('bangkok') || n.includes('thailand')) return '#FFD740'; // golden temple
  if (n.includes('manila') || n.includes('philippine')) return '#F06292'; // island pink
  if (n.includes('london'))             return '#90A4AE'; // foggy steel
  if (n.includes('paris'))              return '#FFD180'; // city-of-lights gold
  if (n.includes('frankfurt'))          return '#B0BEC5'; // bauhaus grey
  if (n.includes('toronto'))            return '#64B5F6'; // clear lake blue
  if (n.includes('sydney'))             return '#4DB6AC'; // harbour teal
  if (n.includes('mexico'))             return '#FFCA28'; // dia-de-los-muertos gold
  if (n.includes('lima') || n.includes('peru')) return '#C8E6C9'; // andean green
  return '#B0BEC5'; // neutral fallback
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
        chartInstances['cEntry'].data.datasets[0].backgroundColor = [...consColors];
        chartInstances['cEntry'].update();
        updateAllCharts(DATA.raw_records);
      }} else {{
        // Apply filter
        activeConsulate = consulate;
        filterPill.textContent = '✕  ' + consulate;
        filterPill.style.display = 'block';
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
  chartInstances['cEntry'].data.datasets[0].backgroundColor = [...consColors];
  chartInstances['cEntry'].update();
  updateAllCharts(DATA.raw_records);
}});
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
    data = build_data(records)
    print(f"Dates: {data['dates'][0] if data['dates'] else 'none'} → {data['dates'][-1] if data['dates'] else 'none'}")
    print(f"Statuses found: {data['check_dist']['statuses']}")
    print(f"Check dates: {len(data['check_dist']['dates'])} days")
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(data, updated)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Generated index.html ✓")
