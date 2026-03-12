#!/usr/bin/env python3
"""Scrapes checkee.info and generates index.html with daily visa case charts."""

import requests
from bs4 import BeautifulSoup
from collections import defaultdict
import json
import re
from datetime import datetime, timezone, timedelta


def scrape():
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    # Step 1: read the "Last 90 Days" dispdate directly from the site's own dropdown
    base = requests.get("https://www.checkee.info/main.php?sortby=clear_date", headers=headers, timeout=30)
    base.raise_for_status()
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
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    records = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 11:
            visa = cells[2].get_text(strip=True)
            date = cells[8].get_text(strip=True)
            try:
                days = int(cells[9].get_text(strip=True))
            except ValueError:
                continue
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date) and visa and 0 <= days < 2000:
                records.append({"date": date, "visa": visa, "days": days})
    return records


def build_data(records):
    dates = sorted(set(r["date"] for r in records))

    counts = defaultdict(lambda: defaultdict(int))
    raw_days = defaultdict(list)
    for r in records:
        counts[r["visa"]][r["date"]] += 1
        raw_days[r["visa"]].append(r["days"])

    groups_visas = [["B1", "B2"], ["F1", "F2"], ["H1", "H4"], ["J1", "J2"], ["L1", "L2"], ["O1"]]
    stats = {}
    for visas in groups_visas:
        all_days = [d for v in visas for d in raw_days[v]]
        key = ",".join(visas)
        stats[key] = {
            "total": len(all_days),
            "avg": round(sum(all_days) / len(all_days)) if all_days else 0,
            "min": min(all_days) if all_days else 0,
            "max": max(all_days) if all_days else 0,
        }

    return {
        "dates": dates,
        "counts": {v: dict(d) for v, d in counts.items()},
        "stats": stats,
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
  .updated {{ text-align: center; font-size: 11px; color: #999; margin-bottom: 16px; }}
  .updated a {{ color: #999; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding: 0 20px 20px; max-width: 1500px; margin: 0 auto; }}
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
<div class="grid" id="grid"></div>
<script>
const DATA = {data_json};
const groups = [
  {{ label: 'Business / Visitor', visas: ['B1','B2'], colors: ['#9C27B0','#E91E63'] }},
  {{ label: 'Student',            visas: ['F1','F2'], colors: ['#4CAF50','#8BC34A'] }},
  {{ label: 'Work (H)',           visas: ['H1','H4'], colors: ['#2196F3','#00BCD4'] }},
  {{ label: 'Exchange Visitor',   visas: ['J1','J2'], colors: ['#FF9800','#FF5722'] }},
  {{ label: 'Intracompany',       visas: ['L1','L2'], colors: ['#607D8B','#795548'] }},
  {{ label: 'Extraordinary Ability', visas: ['O1'],   colors: ['#FFC107'] }},
];

const grid = document.getElementById('grid');
groups.forEach((g, i) => {{
  const s = DATA.stats[g.visas.join(',')] || {{}};
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML =
    '<h3>' + g.label + ' (' + g.visas.join(', ') + ')</h3>' +
    '<canvas id="c' + i + '"></canvas>' +
    '<div class="stats">' +
      '<span>n=<b style="color:#555">' + s.total + '</b></span>' +
      '<span>avg <b style="color:#e67e22">' + s.avg + 'd</b></span>' +
      '<span>min <b style="color:#27ae60">' + s.min + 'd</b></span>' +
      '<span>max <b style="color:#e74c3c">' + s.max + 'd</b></span>' +
    '</div>';
  grid.appendChild(card);

  new Chart(document.getElementById('c' + i), {{
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
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Scraping checkee.info...")
    records = scrape()
    print(f"Found {len(records)} records")
    data = build_data(records)
    print(f"Dates: {data['dates'][0] if data['dates'] else 'none'} → {data['dates'][-1] if data['dates'] else 'none'}")
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(data, updated)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Generated index.html ✓")
