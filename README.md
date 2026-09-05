# google-maps-reviews-scraper

[![PyPI](https://img.shields.io/pypi/v/google-maps-reviews-scraper)](https://pypi.org/project/google-maps-reviews-scraper/)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://aroaxinping.github.io/google-maps-reviews-scraper/)

**Get all Google Maps reviews for any place — free, no API key, no limits.**

[**→ Live dashboard demo (4,370 Taal Vista Hotel reviews)**](https://aroaxinping.github.io/google-maps-reviews-scraper/)

The Google Places API charges ~$17 per 1,000 reviews and caps at 5 per place. This gets them all for $0.

> Scraped 4,370 reviews from a single hotel in under 10 minutes.

![Dashboard preview](assets/preview.png)

---

## Why this exists

If you want Google Maps reviews at scale, your options are:

- **Google Places API** — capped at 5 reviews per place, costs money beyond the free tier
- **Third-party APIs** (SerpApi, Outscraper, etc.) — pay per request, no control over your data
- **Existing scrapers** — most scroll the DOM and silently break after ~900 reviews because the scroll container hits a physical maximum height

This tool takes a different approach: it intercepts the same internal API that Google Maps itself uses, then paginates through all pages with cursor-based requests. No scroll limit. No DOM parsing. No vendor lock-in. Works as long as you have a Google account.

## How it's different

Most scrapers break after ~900 reviews because they rely on scrolling, which hits a physical DOM limit. This one intercepts the real `batchexecute` API that Google Maps uses internally and paginates via cursor — the same way the app does it. No scroll limit. No review cap.

| | This tool | Other scrapers | Google Places API |
|---|---|---|---|
| Review limit | ✅ None | ❌ ~900 | ❌ 5 per place |
| Cost | ✅ Free | ✅ Free | ❌ ~$17/1k reviews |
| API key required | ✅ No | ✅ No | ❌ Yes |
| Breaks on UI changes | ✅ No (API) | ❌ Yes (DOM) | ✅ No |
| Local Guide info | ✅ Yes | ❌ No | ❌ No |
| Estimated dates | ✅ Yes | ❌ No | ❌ No |
| Sort order control | ✅ Yes | ❌ No | ❌ No |
| Multi-place from file | ✅ Yes | ❌ No | ❌ No |
| HTML dashboard | ✅ Yes | ❌ No | ❌ No |

---

## Requirements

- Python ≥ 3.11
- Google Chrome installed (Linux, macOS, or Windows)
- A Google account logged in on Chrome (for session auth)

## Install

```bash
pip install uv
uv pip install -e .
playwright install chromium
```

## Usage

### Scrape a single place

```bash
# Scrape all reviews — saves to SQLite
gmaps-reviews scrape "https://www.google.com/maps/place/..."

# Scrape newest reviews first
gmaps-reviews scrape "https://..." --sort newest

# Scrape + export CSV + dashboard in one shot
gmaps-reviews scrape "https://..." --csv reviews.csv --dashboard dashboard.html

# Auto-organize output into a directory
gmaps-reviews scrape "https://..." --output-dir ./data
# → ./data/taal-vista-hotel/reviews.csv
# → ./data/taal-vista-hotel/dashboard.html

# Limit to first 500 reviews
gmaps-reviews scrape "https://..." --limit 500

# Use a different database
gmaps-reviews scrape "https://..." --db hotels.db
```

### Scrape multiple places from a file

```bash
# places.txt — one URL per line, # to comment
gmaps-reviews scrape-file places.txt

# With output directory (one subfolder per place)
gmaps-reviews scrape-file places.txt --output-dir ./data --db all_places.db
```

`places.txt` format:
```
# Philippines hotels
https://www.google.com/maps/place/Taal+Vista+Hotel/...
https://www.google.com/maps/place/Shangri-La+Boracay/...

# Madrid restaurants
https://www.google.com/maps/place/DiverXO/...
```

### Export from existing database

```bash
# Export CSV + dashboard without scraping again
gmaps-reviews export --db hotels.db --csv all.csv --dashboard all.html

# Filter to one place
gmaps-reviews export --db hotels.db --place 0x....:0x.... --csv taal.csv
```

### Sort options

| `--sort` value | Description |
|---|---|
| `relevant` (default) | Google's default ranking |
| `newest` | Most recent reviews first |
| `highest` | Highest rated first |
| `lowest` | Lowest rated (most critical) first |

### Chrome path

If Chrome is not auto-detected, set the path via environment variable:

```bash
CHROME_PATH="/usr/bin/google-chrome-stable" gmaps-reviews scrape "https://..."
```

Auto-detected locations by platform:
- **Linux**: `/usr/bin/google-chrome-stable`, `/usr/bin/google-chrome`, `/usr/bin/chromium-browser`
- **macOS**: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- **Windows**: `C:\Program Files\Google\Chrome\Application\chrome.exe`

---

## Output fields

| Field | Description |
|---|---|
| `review_id` | Stable Google review ID |
| `author` | Reviewer name |
| `local_guide` | True / False |
| `review_count` | Reviewer's total reviews on Google |
| `rating` | 1–5 stars |
| `date_relative` | "a year ago", "3 months ago"… |
| `date_estimated` | YYYY-MM estimated from relative date |
| `has_photos` | True / False |
| `review_text` | Full review text (original language) |
| `owner_reply` | Owner response, if any |

## How it works

1. Opens your real Chrome profile — inherits your Google session
2. Navigates to the Maps URL and clicks the Reviews tab
3. Optionally clicks the sort button to set the desired order
4. Scrolls once to trigger the first `batchexecute` request — captures the URL, headers, and session token (`x-maps-bgkey`)
5. Loops via in-page XHR with cursor substitution — no scrolling, no DOM parsing, no limits
6. Stores raw batches + parsed reviews in SQLite; resumes automatically if interrupted
7. Exports CSV and HTML dashboard on demand

## License

MIT
