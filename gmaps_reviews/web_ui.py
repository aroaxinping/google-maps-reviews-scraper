"""
FastAPI web UI for Google Maps reviews scraper.
Run with: python -m gmaps_reviews.web_ui
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import unquote

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import StreamingResponse

from .scraper import scrape
from .storage import Store
from .dashboard import generate
from .parser import extract_total_count

app = FastAPI(title="Google Maps Reviews Scraper")

# ---------------------------------------------------------------------------
# Helpers (mirrors cli.py without the Rich / Typer dependency)
# ---------------------------------------------------------------------------

def _place_id_from_url(url: str) -> str:
    m = re.search(r"0x[0-9a-f]+:0x[0-9a-f]+", url, re.I)
    if m:
        return m.group(0).lower()
    return hashlib.md5(url.encode()).hexdigest()[:16]


def _place_name_from_url(url: str) -> str:
    m = re.search(r"/place/([^/@]+)", url)
    if m:
        return unquote(m.group(1).replace("+", " ")).strip()
    return "Unknown Place"


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# HTML template (single page, dark theme)
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google Maps Reviews Scraper</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2d3348;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #3b82f6;
    --accent-hover: #2563eb;
    --success: #22c55e;
    --error: #ef4444;
    --input-bg: #111827;
  }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    min-height: 100vh;
    padding: 2rem 1rem;
  }
  .container {
    max-width: 860px;
    margin: 0 auto;
  }
  h1 {
    font-size: 1.6rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
    color: var(--text);
  }
  .subtitle {
    color: var(--muted);
    margin-bottom: 2rem;
    font-size: 0.9rem;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
  }
  .card h2 {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 1rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  .form-grid .full {
    grid-column: 1 / -1;
  }
  .field label {
    display: block;
    font-size: 0.82rem;
    font-weight: 500;
    color: var(--muted);
    margin-bottom: 0.35rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .field input[type="text"],
  .field input[type="number"],
  .field select {
    width: 100%;
    background: var(--input-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 0.55rem 0.75rem;
    font-size: 0.95rem;
    outline: none;
    transition: border-color 0.15s;
  }
  .field input:focus,
  .field select:focus {
    border-color: var(--accent);
  }
  .field select option {
    background: var(--surface);
  }
  .checkbox-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-top: 1.6rem;
  }
  .checkbox-row input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
  }
  .checkbox-row label {
    color: var(--text);
    font-size: 0.9rem;
    cursor: pointer;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.65rem 1.4rem;
    border-radius: 7px;
    border: none;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    text-decoration: none;
  }
  .btn-primary {
    background: var(--accent);
    color: #fff;
  }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-success {
    background: var(--success);
    color: #fff;
  }
  .btn-success:hover { filter: brightness(0.9); }
  #progress-log {
    background: #080a10;
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 1rem;
    height: 220px;
    overflow-y: auto;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-size: 0.8rem;
    line-height: 1.7;
    color: var(--muted);
  }
  #progress-log .line-ok  { color: #86efac; }
  #progress-log .line-err { color: #fca5a5; }
  #progress-log .line-info{ color: #93c5fd; }
  #results { display: none; }
  #results .actions {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 1.25rem;
  }
  #dashboard-frame {
    width: 100%;
    height: 700px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg);
  }
  .status-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--muted);
    margin-right: 6px;
    vertical-align: middle;
  }
  .status-dot.running { background: var(--accent); animation: pulse 1s infinite; }
  .status-dot.done    { background: var(--success); }
  .status-dot.error   { background: var(--error); }
  @keyframes pulse {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.4; }
  }
  #status-line {
    font-size: 0.85rem;
    color: var(--muted);
    margin-bottom: 0.75rem;
    display: flex;
    align-items: center;
  }
</style>
</head>
<body>
<div class="container">
  <h1>Google Maps Reviews Scraper</h1>
  <p class="subtitle">Scrape reviews from any Google Maps place URL and explore the results</p>

  <!-- Form -->
  <div class="card">
    <h2>Configuration</h2>
    <form id="scrape-form" onsubmit="startScrape(event)">
      <div class="form-grid">
        <div class="field full">
          <label for="url">Google Maps URL</label>
          <input type="text" id="url" name="url" placeholder="https://www.google.com/maps/place/..." required>
        </div>
        <div class="field">
          <label for="sort">Sort reviews by</label>
          <select id="sort" name="sort">
            <option value="relevant">Most Relevant</option>
            <option value="newest">Newest</option>
            <option value="highest">Highest Rating</option>
            <option value="lowest">Lowest Rating</option>
          </select>
        </div>
        <div class="field">
          <label for="limit">Limit (0 = all)</label>
          <input type="number" id="limit" name="limit" value="0" min="0">
        </div>
        <div class="field">
          <label for="language">Language code</label>
          <input type="text" id="language" name="language" value="en" placeholder="en">
        </div>
        <div class="field">
          <label for="min_rating">Min rating (1–5)</label>
          <input type="number" id="min_rating" name="min_rating" value="1" min="1" max="5">
        </div>
        <div class="field">
          <label for="max_rating">Max rating (1–5)</label>
          <input type="number" id="max_rating" name="max_rating" value="5" min="1" max="5">
        </div>
        <div class="field">
          <div class="checkbox-row">
            <input type="checkbox" id="headless" name="headless">
            <label for="headless">Headless mode (no browser window)</label>
          </div>
        </div>
      </div>
      <div style="margin-top:1.25rem">
        <button type="submit" class="btn btn-primary" id="start-btn">▶ Start Scraping</button>
      </div>
    </form>
  </div>

  <!-- Progress -->
  <div class="card" id="progress-card" style="display:none">
    <h2>Progress</h2>
    <div id="status-line">
      <span class="status-dot" id="status-dot"></span>
      <span id="status-text">Initialising…</span>
    </div>
    <div id="progress-log"></div>
  </div>

  <!-- Results -->
  <div class="card" id="results">
    <h2>Results</h2>
    <div class="actions">
      <a id="csv-link" class="btn btn-success" href="#" download>⬇ Download CSV</a>
    </div>
    <iframe id="dashboard-frame" src="about:blank" title="Dashboard"></iframe>
  </div>
</div>

<script>
let es = null;

function log(msg, cls) {
  const box = document.getElementById('progress-log');
  const line = document.createElement('div');
  line.className = cls || '';
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function setStatus(state, text) {
  const dot = document.getElementById('status-dot');
  dot.className = 'status-dot ' + state;
  document.getElementById('status-text').textContent = text;
}

function startScrape(e) {
  e.preventDefault();
  if (es) { es.close(); es = null; }

  const form = document.getElementById('scrape-form');
  const btn  = document.getElementById('start-btn');
  const url       = document.getElementById('url').value.trim();
  const sort      = document.getElementById('sort').value;
  const limit     = document.getElementById('limit').value;
  const language  = document.getElementById('language').value.trim() || 'en';
  const headless  = document.getElementById('headless').checked ? '1' : '0';
  const minRating = document.getElementById('min_rating').value;
  const maxRating = document.getElementById('max_rating').value;

  if (!url) { alert('Please enter a Google Maps URL'); return; }

  // Reset UI
  document.getElementById('progress-log').innerHTML = '';
  document.getElementById('results').style.display = 'none';
  document.getElementById('progress-card').style.display = 'block';
  btn.disabled = true;
  btn.textContent = '⏳ Scraping…';
  setStatus('running', 'Starting scraper…');

  const params = new URLSearchParams({ url, sort, limit, language, headless,
                                       min_rating: minRating, max_rating: maxRating });
  es = new EventSource('/scrape?' + params.toString());

  es.onmessage = function(event) {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'progress') {
        log(data.msg, data.level === 'error' ? 'line-err' : data.level === 'info' ? 'line-info' : 'line-ok');
        setStatus('running', data.msg);
      } else if (data.type === 'done') {
        es.close(); es = null;
        btn.disabled = false;
        btn.textContent = '▶ Start Scraping';
        setStatus('done', 'Scraping complete!');
        log('✓ Done!', 'line-ok');
        showResults(data);
      } else if (data.type === 'error') {
        es.close(); es = null;
        btn.disabled = false;
        btn.textContent = '▶ Start Scraping';
        setStatus('error', 'Error: ' + data.msg);
        log('✗ ' + data.msg, 'line-err');
      }
    } catch(err) {
      log('[parse error] ' + event.data, 'line-err');
    }
  };

  es.onerror = function() {
    if (es && es.readyState === EventSource.CLOSED) return;
    if (es) { es.close(); es = null; }
    btn.disabled = false;
    btn.textContent = '▶ Start Scraping';
    setStatus('error', 'Connection lost');
    log('✗ Connection to server lost', 'line-err');
  };
}

function showResults(data) {
  const results = document.getElementById('results');
  results.style.display = 'block';

  const csvLink = document.getElementById('csv-link');
  csvLink.href = '/download?path=' + encodeURIComponent(data.csv_path);
  csvLink.download = data.csv_path.split('/').pop() || 'reviews.csv';

  if (data.dashboard_b64) {
    const src = 'data:text/html;base64,' + data.dashboard_b64;
    document.getElementById('dashboard-frame').src = src;
  }
  results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=HTML_TEMPLATE)


@app.get("/download")
async def download(path: str = Query(...)) -> FileResponse:
    p = Path(path)
    if not p.exists() or not p.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p, filename=p.name, media_type="text/csv")


@app.get("/scrape")
async def scrape_sse(
    url: str = Query(...),
    sort: str = Query("relevant"),
    limit: int = Query(0),
    language: str = Query("en"),
    headless: str = Query("0"),
    min_rating: int = Query(1),
    max_rating: int = Query(5),
) -> StreamingResponse:
    return StreamingResponse(
        _scrape_stream(url, sort, limit, language, headless == "1", min_rating, max_rating),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _scrape_stream(
    url: str,
    sort: str,
    limit: int,
    language: str,
    headless: bool,
    min_rating: int,
    max_rating: int,
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    place_id   = _place_id_from_url(url)
    place_name = _place_name_from_url(url)
    captured_at = datetime.now(tz=timezone.utc).isoformat()

    tmpdir = Path(tempfile.mkdtemp(prefix="gmaps_ui_"))
    db_path  = tmpdir / "reviews.db"
    csv_path = tmpdir / f"{_slugify(place_name) or 'reviews'}.csv"
    dash_path = tmpdir / "dashboard.html"

    store = Store(db_path)
    existing: set[str] = set()
    page_num = [0]
    detected_total = [0]
    new_total = [0]

    async def on_batch(reviews, next_cursor, raw):
        page_num[0] += 1

        if page_num[0] == 1 and not detected_total[0]:
            n = extract_total_count(raw)
            if n:
                detected_total[0] = n

        new_reviews = [r for r in reviews if r["review_id"] not in existing]
        inserted = store.insert_reviews(new_reviews, place_id)
        new_total[0] += inserted
        for r in new_reviews:
            existing.add(r["review_id"])

        total_in_db = store.total_reviews(place_id)
        msg = f"Page {page_num[0]:>3} | +{inserted} new | {total_in_db:,} total"
        if detected_total[0]:
            pct = int(total_in_db / detected_total[0] * 100)
            msg += f" ({pct}%)"
        await queue.put({"type": "progress", "msg": msg})

    async def run_scraper():
        try:
            await queue.put({"type": "progress", "msg": f"Opening Chrome for: {place_name}", "level": "info"})
            await scrape(
                url, place_id, on_batch,
                limit=limit,
                sort=sort,
                headless=headless,
                language=language,
                min_rating=min_rating,
                max_rating=max_rating,
            )
            await queue.put(None)  # sentinel
        except Exception as exc:
            await queue.put({"type": "error", "msg": str(exc)})

    task = asyncio.create_task(run_scraper())

    # yield a keep-alive comment so the browser connects immediately
    yield ": connected\n\n"

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if item is None:
                break

            if item.get("type") == "error":
                yield _sse(item)
                return

            yield _sse(item)

    finally:
        if not task.done():
            task.cancel()

    # Scraping done — build outputs
    try:
        total_in_db = store.total_reviews(place_id)
        store.upsert_place({
            "place_id": place_id,
            "name": place_name,
            "total_reviews": total_in_db,
            "scraped_at": captured_at,
        })

        n_csv = store.export_csv(csv_path, place_id)
        yield _sse({"type": "progress", "msg": f"CSV exported: {n_csv:,} rows → {csv_path.name}", "level": "info"})

        reviews = store.all_reviews(place_id)
        generate(reviews, dash_path, place_name=place_name)
        yield _sse({"type": "progress", "msg": "Dashboard generated", "level": "info"})

        dash_b64 = base64.b64encode(dash_path.read_bytes()).decode("ascii")

        yield _sse({
            "type": "done",
            "csv_path": str(csv_path),
            "dashboard_path": str(dash_path),
            "dashboard_b64": dash_b64,
            "total": total_in_db,
        })
    except Exception as exc:
        yield _sse({"type": "error", "msg": f"Post-processing error: {exc}"})
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
