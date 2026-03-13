# Design: All Records Table

Date: 2026-03-13

## Problem
The dashboard visualises aggregated trends but gives no way to inspect individual cases. Users want to see the raw records that underlie the charts.

## Decision
Add a full-width table card below the 9-chart grid. Option A: pure inline JS, consistent with the rest of the dashboard, no extra dependencies.

## Data Layer
- Scraper adds `major` (cells[5]) and `details` (cells[10]) to each record dict.
- `raw_records` array extended from 6 to 9 fields:
  `[date, visa, days, status, check_date, consulate, entry, major, details]`
  Indices 0–5 unchanged — existing chart code unaffected.

## Table
- Full-width `.card` below the grid, title "All Records".
- 9 columns: Visa Type · Entry · Consulate · Major · Status · Check Date · Complete Date · Waiting Days · Details
- Default sort: newest complete date first.
- Click-to-sort on every column header with ▲/▼ indicator.
- Details column blank when empty.

## Cross-filter
- `renderTable(records)` called at the end of `updateAllCharts(records)`.
- Pie slice click → charts and table all filter to that consulate.
- Reset click → all restore to full dataset.

## Styling
- Inherits existing card style (white, rounded, shadow).
- Sticky `<thead>` with light gray background.
- Alternating row shading for readability.
- Details column wider; Status/Waiting Days columns narrow.
