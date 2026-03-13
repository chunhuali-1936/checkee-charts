# Records Table Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full-width sortable records table below the 9-chart grid that cross-filters with the consulate pie chart.

**Architecture:** Extend the Python scraper to capture `major` and `details`, widen the `raw_records` JS array to 9 fields, add a `renderTable(records)` function hooked into the existing `updateAllCharts`, and append the table card HTML after the chart grid.

**Tech Stack:** Python (BeautifulSoup scraper), vanilla JS + Chart.js (already in use), single self-contained `index.html`.

---

### Task 1: Extend scraper — capture `major` and `details`

**Files:**
- Modify: `generate.py:70-89` (the `scrape()` row-parsing block)

**Step 1: Edit the row parser to extract cells[5] and cells[10]**

In `generate.py`, find the block inside `if len(cells) == 11:` and add two lines after `consulate`:

```python
visa       = cells[2].get_text(strip=True)
entry      = cells[3].get_text(strip=True)
consulate  = cells[4].get_text(strip=True)
major      = cells[5].get_text(strip=True)   # ADD
status     = cells[6].get_text(strip=True)
check_date = cells[7].get_text(strip=True)
date       = cells[8].get_text(strip=True)
try:
    days = int(cells[9].get_text(strip=True))
except ValueError:
    continue
details    = cells[10].get_text(strip=True)  # ADD
```

Then add `"major": major` and `"details": details` to the `records.append({...})` dict:

```python
records.append({
    "date": date,
    "visa": visa,
    "days": days,
    "status": status,
    "check_date": check_date,
    "entry": entry,
    "consulate": consulate,
    "major": major,      # ADD
    "details": details,  # ADD
})
```

**Step 2: Verify the scraper still runs cleanly**

```bash
cd /tmp/checkee-charts && python generate.py
```

Expected: `Found NNN records` and `Generated index.html ✓` with no errors.

**Step 3: Commit**

```bash
git add generate.py
git commit -m "feat: scrape major and details fields"
```

---

### Task 2: Extend `raw_records` to 9 fields

**Files:**
- Modify: `generate.py:153-157` (the `raw_records` list comprehension in `build_data()`)

**Step 1: Widen the array**

Replace:
```python
# Compact raw records for client-side filtering: [date, visa, days, status, check_date, consulate]
raw_records = [
    [r["date"], r["visa"], r["days"], r["status"], r["check_date"], r["consulate"]]
    for r in records
]
```

With:
```python
# Compact raw records: [date, visa, days, status, check_date, consulate, entry, major, details]
raw_records = [
    [r["date"], r["visa"], r["days"], r["status"], r["check_date"],
     r["consulate"], r["entry"], r["major"], r["details"]]
    for r in records
]
```

Indices 0–5 are unchanged so existing chart code (`r[5]` filter, `buildAgg`) is unaffected.

**Step 2: Verify**

```bash
python generate.py
```

Expected: same output as before — the change only widens the JSON blob.

**Step 3: Commit**

```bash
git add generate.py
git commit -m "feat: extend raw_records to include entry, major, details (indices 6-8)"
```

---

### Task 3: Add table CSS

**Files:**
- Modify: `generate.py` — inside the `<style>` block in `generate_html()`

**Step 1: Find the end of the `<style>` block**

Search for `</style>` in `generate_html()`. Add the following CSS just before it:

```css
/* ── Records table ─────────────────────────────────────────────── */
#recordsTable { width:100%; border-collapse:collapse; font-size:12px; }
#recordsTable thead th {
  position: sticky; top: 0;
  background: #f0f0f0; border-bottom: 2px solid #ddd;
  padding: 6px 8px; text-align: left; white-space: nowrap;
  cursor: pointer; user-select: none;
}
#recordsTable thead th:hover { background: #e4e4e4; }
#recordsTable tbody tr:nth-child(even) { background: #f9f9f9; }
#recordsTable tbody tr:hover { background: #eef4ff; }
#recordsTable tbody td {
  padding: 5px 8px; border-bottom: 1px solid #eee;
  vertical-align: top;
}
#recordsTable td.col-details { max-width: 260px; word-break: break-word; }
#recordsTable td.col-days { text-align: right; }
.table-sort-asc::after  { content: ' ▲'; font-size:10px; }
.table-sort-desc::after { content: ' ▼'; font-size:10px; }
#tableCount { font-size:12px; color:#888; margin-bottom:6px; }
```

**Step 2: Verify**

```bash
python generate.py
```

Expected: runs without errors.

**Step 3: Commit**

```bash
git add generate.py
git commit -m "feat: add CSS for records table"
```

---

### Task 4: Add `renderTable` JS function

**Files:**
- Modify: `generate.py` — add JS function just before the closing `</script>` tag (near line 646)

**Step 1: Add sort state and `renderTable` function**

Find the line `updateAllCharts(DATA.raw_records);` that appears after the pie-chart reset handler (near the bottom of the script block, just before `</script>`). Insert the following **before** that final `updateAllCharts` call:

```javascript
// ── Records table ─────────────────────────────────────────────────────────
let tableSortCol = 0;   // default: complete date (index 0)
let tableSortDir = -1;  // -1 = desc (newest first)

function renderTable(records) {{
  const cols = [
    // [header label, record index, css-class]
    ['Visa Type',     1, ''],
    ['Entry',         6, ''],
    ['Consulate',     5, ''],
    ['Major',         7, ''],
    ['Status',        3, ''],
    ['Check Date',    4, ''],
    ['Complete Date', 0, ''],
    ['Waiting Days',  2, 'col-days'],
    ['Details',       8, 'col-details'],
  ];

  // Build / refresh header
  const thead = document.querySelector('#recordsTable thead');
  if (!thead.children.length) {{
    const tr = document.createElement('tr');
    cols.forEach(([label, , cls], ci) => {{
      const th = document.createElement('th');
      th.textContent = label;
      if (cls) th.className = cls;
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

  // Update sort indicators
  thead.querySelectorAll('th').forEach((th, ci) => {{
    th.classList.remove('table-sort-asc', 'table-sort-desc');
    if (ci === tableSortCol)
      th.classList.add(tableSortDir === 1 ? 'table-sort-asc' : 'table-sort-desc');
  }});

  // Sort
  const [, idx] = cols[tableSortCol];
  const sorted = [...records].sort((a, b) => {{
    const av = a[idx], bv = b[idx];
    return tableSortDir * (av < bv ? -1 : av > bv ? 1 : 0);
  }});

  // Render tbody
  const tbody = document.querySelector('#recordsTable tbody');
  tbody.innerHTML = '';
  sorted.forEach(r => {{
    const tr = document.createElement('tr');
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
```

**Step 2: Hook `renderTable` into `updateAllCharts`**

Find the closing `}}` of the `updateAllCharts(records)` function (after the check-date distribution chart update, around line 353). Add one line just before the closing brace:

```javascript
  // Refresh records table
  _currentTableRecords = records;
  renderTable(records);
}}
```

**Step 3: Verify**

```bash
python generate.py && open index.html
```

Expected: page loads, table appears below charts with all rows and sortable headers.

**Step 4: Commit**

```bash
git add generate.py
git commit -m "feat: add renderTable JS + hook into updateAllCharts"
```

---

### Task 5: Add table card HTML

**Files:**
- Modify: `generate.py` — `generate_html()`, after the `</div>` that closes the chart grid

**Step 1: Find the grid closing tag and append table card**

Search for the closing `</div>` of the chart grid (the line that ends the `grid` div). After it, add:

```html
<div class="card" style="grid-column:1/-1">
  <h3>All Records</h3>
  <div id="tableCount"></div>
  <table id="recordsTable">
    <thead></thead>
    <tbody></tbody>
  </table>
</div>
```

Because this card lives outside the `grid` div, wrap it in a container div with `max-width` and `margin: auto` matching the grid, or simply add `style="max-width:1400px;margin:0 auto 24px;padding:0 16px"` to the outer div.

**Step 2: Verify**

```bash
python generate.py && open index.html
```

Expected:
- Table card appears below the 3-column chart grid
- Rows are populated (should show ~570 records)
- Clicking a column header sorts asc/desc with ▲/▼ indicator
- Clicking a consulate pie slice filters the table rows
- Clicking the slice again resets to all rows

**Step 3: Commit**

```bash
git add generate.py index.html
git commit -m "feat: add All Records table card below charts"
```

---

### Task 6: Final push

```bash
cd /tmp/checkee-charts && git push
```

Expected: remote accepts the push. Check https://chunhuali-1936.github.io/checkee-charts after ~1 min for live result.
