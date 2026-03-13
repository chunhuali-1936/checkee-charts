# Checkee Charts

Auto-updated US visa administrative processing dashboard, sourced from [checkee.info](https://www.checkee.info).

**Live dashboard → https://chunhuali-1936.github.io/checkee-charts**

![Dashboard Screenshot](screenshot.png)

## What it shows

9 cards across 3 columns:

**Visa group bar charts (cards 1–6)** — daily case counts (stacked bar) by status (Clear / Reject), with summary stats: total cases, median / min / max waiting days.

| Card | Visas |
|---|---|
| Business / Visitor | B1, B2 |
| Student | F1, F2 |
| Work | H1, H4 |
| Exchange Visitor | J1, J2 |
| Intracompany | L1, L2 |
| Extraordinary Ability | O1 |

**Card 7 — Waiting Days** — area chart of median waiting days over time, all visa types combined.

**Card 8 — Check Date Distribution (All Visa Types)** — stacked bar of case counts by check date (Clear / Reject), with a normal distribution fit overlay.

**Card 9 — Consulate Distribution (All Visa Types)** — pie chart of cases by consulate, colored by city vibe. Click a slice to cross-filter all other cards.

## How it works

1. `generate.py` scrapes checkee.info and produces a self-contained `index.html`
2. GitHub Actions runs it every 2 hours, commits the updated HTML, and GitHub Pages serves it

## Run locally

```bash
pip install -r requirements.txt
python generate.py
open index.html
```
