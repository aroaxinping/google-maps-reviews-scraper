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
# HTML template — Google Material Design aesthetic
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Maps Reviews Scraper</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:        #f1f3f4;
    --surface:   #ffffff;
    --surface2:  #f8f9fa;
    --border:    #dadce0;
    --text:      #202124;
    --muted:     #5f6368;
    --blue:      #1a73e8;
    --blue-bg:   #e8f0fe;
    --blue-dark: #1557b0;
    --green:     #34a853;
    --red:       #ea4335;
    --shadow-card: 0 1px 3px rgba(60,64,67,.3), 0 4px 8px rgba(60,64,67,.15);
    --shadow-1:  0 1px 2px rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15);
    --input-bg: #ffffff;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:      #131314;
      --surface: #1e1f20;
      --surface2:#292a2d;
      --border:  #3c4043;
      --text:    #e8eaed;
      --muted:   #9aa0a6;
      --blue:    #8ab4f8;
      --blue-bg: #1a2744;
      --blue-dark:#aecbfa;
      --green:   #81c995;
      --red:     #f28b82;
      --shadow-card:0 1px 3px rgba(0,0,0,.6),0 4px 8px rgba(0,0,0,.4);
      --shadow-1:0 1px 2px rgba(0,0,0,.6),0 1px 3px 1px rgba(0,0,0,.4);
      --input-bg: #1e1f20;
    }
  }
  :root[data-theme="dark"] {
    --bg:      #131314;
    --surface: #1e1f20;
    --surface2:#292a2d;
    --border:  #3c4043;
    --text:    #e8eaed;
    --muted:   #9aa0a6;
    --blue:    #8ab4f8;
    --blue-bg: #1a2744;
    --blue-dark:#aecbfa;
    --green:   #81c995;
    --red:     #f28b82;
    --shadow-card:0 1px 3px rgba(0,0,0,.6),0 4px 8px rgba(0,0,0,.4);
    --shadow-1:0 1px 2px rgba(0,0,0,.6),0 1px 3px 1px rgba(0,0,0,.4);
    --input-bg: #1e1f20;
  }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Roboto', 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }
  /* ── Top app bar ── */
  .g-header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    height: 56px;
    display: flex;
    align-items: center;
    padding: 0 24px;
    gap: 14px;
    box-shadow: 0 1px 4px rgba(60,64,67,.2), 0 2px 6px rgba(60,64,67,.1);
    position: sticky; top: 0; z-index: 10;
  }
  .g-header-logo { display:flex; align-items:center; gap:10px; }
  .g-header-logo svg { flex-shrink:0; }
  .g-header-title { font-size:18px; font-weight:400; color:var(--text); letter-spacing:-.01em; }
  .g-header-title b { color:var(--blue); font-weight:500; }
  .g-chip {
    background:var(--blue-bg); color:var(--blue);
    font-size:11px; font-weight:500; padding:2px 8px; border-radius:12px; letter-spacing:.02em;
  }
  /* ── Layout ── */
  .container {
    max-width: 640px;
    margin: 0 auto;
    padding: 28px 16px 64px;
  }
  /* ── Cards ── */
  .card {
    background: var(--surface);
    border-radius: 8px;
    box-shadow: var(--shadow-card);
    margin-bottom: 16px;
    overflow: hidden;
  }
  .card-hd { padding: 20px 24px 0; }
  .card-title { font-size: 16px; font-weight: 500; margin-bottom: 4px; }
  .card-sub { font-size: 13px; color: var(--muted); margin-bottom: 18px; }
  .card-bd { padding: 0 24px 24px; }
  /* ── Form ── */
  .field { margin-bottom: 14px; }
  .field label {
    display: block; font-size: 11px; font-weight: 500; color: var(--muted);
    margin-bottom: 5px; text-transform: uppercase; letter-spacing: .08em;
  }
  .field small {
    display: block; font-size: 11px; color: var(--muted); margin-top: 4px;
  }
  input[type="text"], input[type="number"], select {
    width: 100%; height: 40px; padding: 0 12px;
    background: var(--input-bg); border: 1px solid var(--border);
    border-radius: 4px; color: var(--text);
    font-family: 'Roboto', sans-serif; font-size: 14px; outline: none;
    transition: border-color .15s, box-shadow .15s; appearance: none;
  }
  input:focus, select:focus {
    border-color: var(--blue);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 20%, transparent);
  }
  /* URL row with Copy button */
  .url-row { display: flex; gap: 8px; align-items: flex-start; }
  .url-row input { flex: 1; }
  .url-row .btn-copy {
    flex-shrink: 0; height: 40px; padding: 0 12px;
    background: transparent; border: 1px solid var(--border);
    border-radius: 4px; color: var(--muted); cursor: pointer;
    font-family: 'Roboto', sans-serif; font-size: 13px; font-weight: 500;
    display: inline-flex; align-items: center; gap: 4px;
    transition: background .15s, color .15s, border-color .15s;
    white-space: nowrap;
  }
  .url-row .btn-copy:hover { background: var(--blue-bg); color: var(--blue); border-color: var(--blue); }
  .url-row .btn-copy.copied { color: var(--green); border-color: var(--green); background: color-mix(in srgb, var(--green) 10%, transparent); }
  .select-wrap { position: relative; }
  .select-wrap::after {
    content: ''; position: absolute; right: 12px; top: 50%;
    transform: translateY(-50%); border: 5px solid transparent;
    border-top-color: var(--muted); border-bottom: none; pointer-events: none;
  }
  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .divider { border: none; border-top: 1px solid var(--border); margin: 18px -24px; }
  .section-lbl {
    font-size: 11px; font-weight: 500; letter-spacing: .08em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 12px;
  }
  /* How it works collapsible */
  .how-details {
    margin-top: 6px; margin-bottom: 14px;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--surface2);
  }
  .how-details summary {
    padding: 8px 12px; font-size: 12px; font-weight: 500;
    color: var(--blue); cursor: pointer; user-select: none;
    list-style: none; display: flex; align-items: center; gap: 6px;
  }
  .how-details summary::-webkit-details-marker { display: none; }
  .how-details summary::before {
    content: '▶'; font-size: 9px; transition: transform .2s; display: inline-block;
  }
  .how-details[open] summary::before { transform: rotate(90deg); }
  .how-details .how-body {
    padding: 0 12px 12px; font-size: 12px; color: var(--muted); line-height: 1.6;
  }
  .how-details .how-body ol { padding-left: 18px; margin-top: 4px; }
  .how-details .how-body li { margin-bottom: 2px; }
  .how-details .how-body code {
    background: var(--border); border-radius: 3px; padding: 0 4px;
    font-size: 11px; color: var(--text);
  }
  /* ── Toggle ── */
  .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; }
  .toggle-info { flex: 1; }
  .toggle-name { font-size: 14px; font-weight: 500; }
  .toggle-desc { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .toggle { position: relative; width: 36px; height: 20px; flex-shrink: 0; margin-left: 16px; }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle-track {
    position: absolute; inset: 0; border-radius: 20px;
    background: var(--border); cursor: pointer; transition: background .2s;
  }
  .toggle-thumb {
    position: absolute; left: 2px; top: 2px; width: 16px; height: 16px;
    border-radius: 50%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,.3);
    transition: transform .2s; pointer-events: none;
  }
  .toggle input:checked ~ .toggle-track { background: var(--blue); }
  .toggle input:checked ~ .toggle-thumb { transform: translateX(16px); }
  /* ── Buttons ── */
  .btn {
    display: inline-flex; align-items: center; gap: 6px; height: 36px;
    padding: 8px 24px; border: none; border-radius: 4px;
    font-family: 'Roboto', sans-serif; font-size: 14px; font-weight: 500;
    cursor: pointer; letter-spacing: .25px; transition: box-shadow .15s, filter .15s;
    text-decoration: none; position: relative; overflow: hidden;
  }
  .btn-blue { background: #1a73e8; color: #fff; }
  .btn-blue::after {
    content: ''; position: absolute; inset: 0;
    background: radial-gradient(circle at center, rgba(255,255,255,.35) 0%, transparent 65%);
    transform: scale(0); opacity: 0; border-radius: inherit;
    transition: transform .45s ease, opacity .45s ease;
  }
  .btn-blue:active::after { transform: scale(3); opacity: 1; transition: none; }
  .btn-blue:hover { filter: brightness(1.08); box-shadow: var(--shadow-1); }
  .btn-blue:disabled { opacity: .55; cursor: not-allowed; }
  .btn-outline { background: transparent; color: var(--blue); border: 1px solid var(--border); }
  .btn-outline:hover { background: var(--blue-bg); }
  .btn-green { background: var(--green); color: #fff; }
  .btn-green:hover { filter: brightness(1.08); }
  /* ── Progress card ── */
  .progress-hd {
    padding: 14px 24px; display: flex; align-items: center; gap: 12px;
    border-bottom: 1px solid var(--border);
  }
  .spinner {
    width: 18px; height: 18px; border: 2px solid var(--border);
    border-top-color: var(--blue); border-radius: 50%;
    animation: spin .8s linear infinite; flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .progress-status { font-size: 13px; color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #progress-log {
    font-family: 'Roboto Mono', 'Fira Code', monospace; font-size: 12px;
    line-height: 1.8; color: var(--muted); padding: 12px 24px;
    height: 190px; overflow-y: auto; overflow-x: hidden; background: var(--surface2);
    word-break: break-all;
  }
  #progress-log .line-ok   { color: var(--green); }
  #progress-log .line-err  { color: var(--red); }
  #progress-log .line-info { color: var(--blue); }
  /* ── Stats pills ── */
  .stat-row { display: flex; gap: 8px; flex-wrap: wrap; padding: 14px 24px 0; }
  .stat-pill {
    display: flex; align-items: center; gap: 5px;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 16px; padding: 3px 10px; font-size: 12px; color: var(--muted);
  }
  .stat-pill .val { color: var(--text); font-weight: 500; font-variant-numeric: tabular-nums; }
  /* ── Skeleton loader ── */
  @keyframes skel-pulse {
    0%,100% { opacity: 1; } 50% { opacity: .45; }
  }
  .skel-card { padding: 20px 24px 24px; }
  .skel-line {
    height: 12px; border-radius: 6px; background: var(--border);
    margin-bottom: 10px; animation: skel-pulse 1.4s ease-in-out infinite;
  }
  /* ── Results ── */
  .result-actions {
    display: flex; gap: 8px; flex-wrap: wrap;
    padding: 14px 24px; border-bottom: 1px solid var(--border);
    align-items: center;
  }
  .dashboard-wrap { position: relative; }
  #dashboard-frame { width: 100%; min-height: 600px; height: 660px; border: none; display: block; }
  .dash-open-link {
    position: absolute; top: 10px; right: 14px;
    font-size: 12px; color: var(--blue); text-decoration: none; font-weight: 500;
    background: var(--surface); padding: 4px 10px; border-radius: 12px;
    border: 1px solid var(--border); box-shadow: var(--shadow-1);
    display: flex; align-items: center; gap: 4px;
    transition: background .15s;
  }
  .dash-open-link:hover { background: var(--blue-bg); }
  /* No reviews notice */
  .no-reviews-notice {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 24px; background: var(--blue-bg);
    border-top: 1px solid color-mix(in srgb, var(--blue) 20%, transparent);
    font-size: 13px; color: var(--blue);
  }
  #results { display: none; }
  #progress-card { display: none; }
  #skeleton-card { display: none; }
  /* ── Responsive ── */
  @media (max-width: 600px) {
    .form-row { grid-template-columns: 1fr; }
    .url-row { flex-wrap: wrap; }
    .url-row input { min-width: 0; }
    .container { padding: 16px 12px 48px; }
    .card-hd, .card-bd { padding-left: 16px; padding-right: 16px; }
    .divider { margin-left: -16px; margin-right: -16px; }
    #progress-log { padding-left: 16px; padding-right: 16px; }
    .stat-row, .progress-hd, .result-actions { padding-left: 16px; padding-right: 16px; }
  }
</style>
</head>
<body>
<!-- Top app bar -->
<div class="g-header">
  <div class="g-header-logo">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" fill="#ea4335"/>
      <circle cx="12" cy="9" r="2.5" fill="white"/>
    </svg>
    <span class="g-header-title">Maps Reviews <b>Scraper</b></span>
  </div>
  <span class="g-chip">v0.2.0</span>
</div>

<div class="container">
  <!-- Form card -->
  <div class="card">
    <div class="card-hd">
      <div class="card-title">Scrape reviews</div>
      <div class="card-sub">Enter a Google Maps place URL to extract all reviews and generate a dashboard.</div>
    </div>
    <div class="card-bd">
      <form id="scrape-form" onsubmit="startScrape(event)">
        <div class="field">
          <label for="url">Google Maps URL</label>
          <div class="url-row">
            <input type="text" id="url" name="url"
              placeholder="https://www.google.com/maps/place/..." required>
            <button type="button" class="btn-copy" id="copy-btn" onclick="copyUrl()" title="Copy URL to clipboard">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
              </svg>
              Copy
            </button>
          </div>
          <details class="how-details">
            <summary>How to get the right URL</summary>
            <div class="how-body">
              <ol>
                <li>Open <a href="https://maps.google.com" target="_blank" rel="noopener" style="color:var(--blue)">Google Maps</a> and search for the place.</li>
                <li>Click the place name to open its detail panel.</li>
                <li>Copy the full URL from your browser's address bar — it should contain <code>/place/</code>.</li>
                <li>Paste it above and press <strong>Start scraping</strong>.</li>
              </ol>
            </div>
          </details>
        </div>
        <hr class="divider">
        <div class="section-lbl">Review options</div>
        <div class="form-row">
          <div class="field">
            <label for="sort">Sort by</label>
            <div class="select-wrap">
              <select id="sort" name="sort">
                <option value="relevant">Most relevant</option>
                <option value="newest">Newest</option>
                <option value="highest">Highest rating</option>
                <option value="lowest">Lowest rating</option>
              </select>
            </div>
          </div>
          <div class="field">
            <label for="language">Language</label>
            <input type="text" id="language" name="language" value="en" placeholder="en / es / fr">
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label for="min_rating">Min rating (1–5)</label>
            <input type="number" id="min_rating" name="min_rating" value="1" min="1" max="5">
          </div>
          <div class="field">
            <label for="max_rating">Max rating (1–5)</label>
            <input type="number" id="max_rating" name="max_rating" value="5" min="1" max="5">
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label for="limit">Limit (0 = all)</label>
            <input type="number" id="limit" name="limit" value="0" min="0">
          </div>
          <div class="field">
            <label for="since">Stop before (YYYY-MM)</label>
            <input type="text" id="since" name="since" placeholder="e.g. 2024-01">
            <small>Stops at reviews older than this month</small>
          </div>
        </div>
        <hr class="divider">
        <div class="section-lbl">Behaviour</div>
        <div class="toggle-row">
          <div class="toggle-info">
            <div class="toggle-name">Headless mode</div>
            <div class="toggle-desc">Run Chrome in the background — no window opens</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="headless" name="headless">
            <span class="toggle-track"></span>
            <span class="toggle-thumb"></span>
          </label>
        </div>
        <div style="margin-top:20px">
          <button type="submit" class="btn btn-blue" id="start-btn">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
            Start scraping
          </button>
        </div>
      </form>
    </div>
  </div>

  <!-- Skeleton loader (shown immediately after submit, before first SSE message) -->
  <div class="card" id="skeleton-card" aria-live="polite" aria-label="Loading">
    <div class="skel-card">
      <div class="skel-line" style="width:45%;height:14px;margin-bottom:16px"></div>
      <div class="skel-line" style="width:80%"></div>
      <div class="skel-line" style="width:65%"></div>
      <div class="skel-line" style="width:72%"></div>
      <div class="skel-line" style="width:55%"></div>
    </div>
  </div>

  <!-- Progress card -->
  <div class="card" id="progress-card">
    <div class="card-hd">
      <div class="card-title" id="progress-place">Scraping…</div>
    </div>
    <div class="stat-row" id="stat-row" style="padding-bottom:14px">
      <span class="stat-pill">Found <span class="val" id="stat-found">0</span></span>
      <span class="stat-pill">New <span class="val" id="stat-new">0</span></span>
      <span class="stat-pill">Pages <span class="val" id="stat-pages">0</span></span>
    </div>
    <div class="progress-hd">
      <div class="spinner" id="spinner"></div>
      <div class="progress-status"><span id="status-text">Starting…</span></div>
    </div>
    <div id="progress-log" aria-live="polite" aria-label="Progress log"></div>
  </div>

  <!-- Results card -->
  <div class="card" id="results">
    <div class="card-hd">
      <div class="card-title" id="result-title">Done</div>
      <div class="card-sub" id="result-sub"></div>
    </div>
    <div id="no-reviews-notice" class="no-reviews-notice" style="display:none">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
      All reviews are already saved — no new reviews found this run.
    </div>
    <div class="result-actions">
      <a id="csv-link" class="btn btn-green" href="#" download>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
        Download CSV
      </a>
      <button class="btn btn-outline" onclick="resetForm()">↩ New scrape</button>
    </div>
    <div class="dashboard-wrap">
      <iframe id="dashboard-frame" src="about:blank" title="Reviews Dashboard"></iframe>
      <a id="dash-open-link" class="dash-open-link" href="#" target="_blank" rel="noopener" style="display:none">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19 19H5V5h7V3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>
        Open in new tab
      </a>
    </div>
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

function copyUrl() {
  const val = document.getElementById('url').value.trim();
  if (!val) return;
  const btn = document.getElementById('copy-btn');
  navigator.clipboard.writeText(val).then(function() {
    btn.classList.add('copied');
    btn.querySelector('span,svg').nextSibling || null;
    const origText = btn.textContent.trim();
    btn.lastChild.textContent = ' Copied!';
    setTimeout(function() {
      btn.classList.remove('copied');
      btn.lastChild.textContent = ' Copy';
    }, 1800);
  }).catch(function() {
    /* fallback: select the field */
    document.getElementById('url').select();
  });
}

function startScrape(e) {
  e.preventDefault();
  if (es) { es.close(); es = null; }

  const btn  = document.getElementById('start-btn');
  const url       = document.getElementById('url').value.trim();
  const sort      = document.getElementById('sort').value;
  const limit     = document.getElementById('limit').value;
  const language  = document.getElementById('language').value.trim() || 'en';
  const headless  = document.getElementById('headless').checked ? '1' : '0';
  const minRating = document.getElementById('min_rating').value;
  const maxRating = document.getElementById('max_rating').value;
  const since     = document.getElementById('since').value.trim();

  if (!url) { alert('Please enter a Google Maps URL'); return; }

  /* Reset UI — show skeleton immediately, hide progress until first event */
  document.getElementById('progress-log').innerHTML = '';
  document.getElementById('results').style.display = 'none';
  document.getElementById('progress-card').style.display = 'none';
  document.getElementById('skeleton-card').style.display = 'block';
  document.getElementById('progress-place').textContent = 'Scraping…';
  document.getElementById('stat-found').textContent = '0';
  document.getElementById('stat-new').textContent = '0';
  document.getElementById('stat-pages').textContent = '0';
  document.getElementById('spinner').style.display = '';
  document.getElementById('no-reviews-notice').style.display = 'none';
  btn.disabled = true;

  const params = new URLSearchParams({
    url, sort, limit, language, headless,
    min_rating: minRating, max_rating: maxRating
  });
  if (since) params.set('since', since);
  es = new EventSource('/scrape?' + params.toString());

  let totalFound = 0, totalNew = 0, pages = 0, firstMessage = true;

  es.onmessage = function(event) {
    try {
      const data = JSON.parse(event.data);

      /* Swap skeleton for real progress card on first message */
      if (firstMessage) {
        firstMessage = false;
        document.getElementById('skeleton-card').style.display = 'none';
        document.getElementById('progress-card').style.display = 'block';
      }

      if (data.type === 'progress') {
        const cls = data.level === 'error' ? 'line-err'
                  : data.level === 'info'  ? 'line-info' : 'line-ok';
        log(data.msg, cls);
        document.getElementById('status-text').textContent = data.msg;
        /* parse "Page N | +X new | Y total" to update pills */
        const m = data.msg.match(/Page\s+(\d+)\s*\|\s*\+(\d+) new\s*\|\s*([\d,]+) total/);
        if (m) {
          pages = parseInt(m[1]);
          totalNew += parseInt(m[2]);
          totalFound = parseInt(m[3].replace(/,/g, ''));
          document.getElementById('stat-found').textContent = totalFound.toLocaleString();
          document.getElementById('stat-new').textContent = totalNew.toLocaleString();
          document.getElementById('stat-pages').textContent = pages;
        }
      } else if (data.type === 'done') {
        es.close(); es = null;
        btn.disabled = false;
        document.getElementById('skeleton-card').style.display = 'none';
        document.getElementById('spinner').style.display = 'none';
        document.getElementById('status-text').textContent =
          'Done — ' + totalFound.toLocaleString() + ' reviews';
        log('✓ Complete', 'line-ok');
        showResults(data, totalFound, totalNew, pages);
      } else if (data.type === 'error') {
        es.close(); es = null;
        btn.disabled = false;
        document.getElementById('skeleton-card').style.display = 'none';
        document.getElementById('spinner').style.display = 'none';
        document.getElementById('status-text').textContent = 'Error: ' + data.msg;
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
    document.getElementById('skeleton-card').style.display = 'none';
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('status-text').textContent = 'Connection lost';
    log('✗ Connection to server lost', 'line-err');
  };
}

function showResults(data, total, newCount, pages) {
  const results = document.getElementById('results');
  results.style.display = 'block';

  if (newCount === 0) {
    document.getElementById('result-title').textContent = 'Up to date';
    document.getElementById('result-sub').textContent =
      total.toLocaleString() + ' reviews already saved · ' + pages + ' pages scanned';
    document.getElementById('no-reviews-notice').style.display = 'flex';
  } else {
    document.getElementById('result-title').textContent = 'Done';
    document.getElementById('result-sub').textContent =
      total.toLocaleString() + ' reviews · '
      + newCount.toLocaleString() + ' new · ' + pages + ' pages';
    document.getElementById('no-reviews-notice').style.display = 'none';
  }

  const csvLink = document.getElementById('csv-link');
  csvLink.href = '/download?path=' + encodeURIComponent(data.csv_path);
  csvLink.download = data.csv_path.split('/').pop() || 'reviews.csv';

  if (data.dashboard_b64) {
    const src = 'data:text/html;base64,' + data.dashboard_b64;
    document.getElementById('dashboard-frame').src = src;
    const openLink = document.getElementById('dash-open-link');
    openLink.href = src;
    openLink.style.display = 'flex';
  }

  results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function resetForm() {
  document.getElementById('results').style.display = 'none';
  document.getElementById('progress-card').style.display = 'none';
  document.getElementById('skeleton-card').style.display = 'none';
  document.getElementById('url').focus();
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
    since: str = Query(""),
) -> StreamingResponse:
    return StreamingResponse(
        _scrape_stream(url, sort, limit, language, headless == "1", min_rating, max_rating, since or None),
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
    since: str | None = None,
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
                since=since,
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
