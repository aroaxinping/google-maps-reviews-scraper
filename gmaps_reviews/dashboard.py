"""Generate a self-contained HTML dashboard from scraped reviews."""

from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

from .storage import _extract_words


def _rating_distribution(reviews: list[dict]) -> dict:
    counts = Counter(int(r["rating"]) for r in reviews if r["rating"])
    return {str(i): counts.get(i, 0) for i in range(1, 6)}


def _monthly_counts(reviews: list[dict]) -> dict:
    counts: Counter = Counter()
    for r in reviews:
        if r.get("date_estimated"):
            counts[r["date_estimated"]] += 1
    return dict(sorted(counts.items()))


def _top_words(reviews: list[dict], n: int = 40) -> list[tuple[str, int]]:
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "is", "it", "was", "are", "be", "we", "i",
        "they", "this", "that", "very", "so", "my", "our", "their", "have",
        "had", "has", "not", "no", "its", "as", "by", "from", "your",
        "el", "la", "los", "las", "de", "en", "y", "que", "un", "una",
        "es", "con", "se", "del", "al", "lo", "le", "su", "por",
    }
    words: Counter = Counter()
    for r in reviews:
        if r.get("review_text"):
            for w in _extract_words(r["review_text"]):
                if w.isascii() and w in stopwords:
                    continue
                words[w] += 1
    return words.most_common(n)


def _reply_rate_by_month(reviews: list) -> dict:
    total: dict = defaultdict(int)
    replied: dict = defaultdict(int)
    for r in reviews:
        month = r.get("date_estimated")
        if not month:
            continue
        total[month] += 1
        if r.get("owner_reply"):
            replied[month] += 1
    return {m: round(replied[m] / total[m], 3) for m in sorted(total) if total[m] >= 3}


def generate(reviews: list[dict], output_path: Path, place_name: str = "Place") -> None:
    ratings = _rating_distribution(reviews)
    monthly = _monthly_counts(reviews)
    top_words = _top_words(reviews)

    total = len(reviews)
    with_text = sum(1 for r in reviews if r.get("review_text"))
    with_reply = sum(1 for r in reviews if r.get("owner_reply"))
    avg_rating = (
        sum(int(r["rating"]) for r in reviews if r.get("rating")) / total
        if total else 0
    )
    local_guides = sum(1 for r in reviews if r.get("local_guide"))

    data = {
        "place_name": place_name,
        "total": total,
        "with_text": with_text,
        "with_reply": with_reply,
        "avg_rating": round(avg_rating, 2),
        "local_guides": local_guides,
        "ratings": ratings,
        "monthly": monthly,
        "top_words": top_words,
    }
    data["reply_rate"] = _reply_rate_by_month(reviews)

    html = _render(data)
    output_path.write_text(html, encoding="utf-8")


def _render(d: dict) -> str:
    data_json = json.dumps(d, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{d['place_name']} — Reviews Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, sans-serif; background: #0f1117; color: #e2e8f0; }}
  header {{ padding: 2rem; border-bottom: 1px solid #1e2130; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; }}
  .sub {{ color: #94a3b8; margin-top: .3rem; font-size: .9rem; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 1rem; padding: 1.5rem 2rem; }}
  .card {{ background: #1e2130; border-radius: 10px; padding: 1.2rem 1.6rem; flex: 1; min-width: 140px; }}
  .card .val {{ font-size: 2rem; font-weight: 800; color: #60a5fa; }}
  .card .lbl {{ font-size: .8rem; color: #94a3b8; margin-top: .2rem; }}
  .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 1.5rem; padding: 0 2rem 2rem; }}
  .chart-box {{ background: #1e2130; border-radius: 10px; padding: 1rem; }}
  .chart-box h2 {{ font-size: .95rem; color: #94a3b8; margin-bottom: .5rem; padding: .2rem .5rem; }}
</style>
</head>
<body>
<header>
  <h1>{d['place_name']}</h1>
  <div class="sub">Google Maps Reviews Dashboard · {d['total']:,} reviews</div>
</header>
<div class="stats">
  <div class="card"><div class="val">{d['total']:,}</div><div class="lbl">Total reviews</div></div>
  <div class="card"><div class="val">{d['avg_rating']:.2f}★</div><div class="lbl">Average rating</div></div>
  <div class="card"><div class="val">{d['with_text']:,}</div><div class="lbl">With text</div></div>
  <div class="card"><div class="val">{d['with_reply']:,}</div><div class="lbl">Owner replies</div></div>
  <div class="card"><div class="val">{d['local_guides']:,}</div><div class="lbl">Local Guides</div></div>
</div>
<div class="charts">
  <div class="chart-box"><h2>Rating distribution</h2><div id="ch-ratings"></div></div>
  <div class="chart-box"><h2>Reviews over time (estimated)</h2><div id="ch-timeline"></div></div>
  <div class="chart-box"><h2>Top words in reviews</h2><div id="ch-words"></div></div>
  <div class="chart-box"><h2>Owner Reply Rate Over Time</h2><div id="ch-reply"></div></div>
</div>
<script>
const DATA = {data_json};
const COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#3b82f6'];
const dark = {{ paper_bgcolor:'#1e2130', plot_bgcolor:'#1e2130',
  font:{{color:'#e2e8f0'}}, margin:{{t:10,b:40,l:50,r:10}} }};

// Rating distribution
const rLabels = ['1★','2★','3★','4★','5★'];
const rVals   = [1,2,3,4,5].map(i => DATA.ratings[i] || 0);
Plotly.newPlot('ch-ratings', [{{
  type:'bar', x:rLabels, y:rVals,
  marker:{{color:COLORS}},
  text:rVals, textposition:'outside'
}}], {{...dark, xaxis:{{fixedrange:true}}, yaxis:{{fixedrange:true}}}}, {{displayModeBar:false}});

// Timeline
if (Object.keys(DATA.monthly).length) {{
  const months = Object.keys(DATA.monthly).sort();
  Plotly.newPlot('ch-timeline', [{{
    type:'scatter', mode:'lines+markers',
    x:months, y:months.map(m=>DATA.monthly[m]),
    line:{{color:'#60a5fa', width:2}},
    marker:{{color:'#60a5fa', size:4}}
  }}], {{...dark, xaxis:{{fixedrange:true}}, yaxis:{{fixedrange:true}}}}, {{displayModeBar:false}});
}} else {{
  document.getElementById('ch-timeline').innerHTML =
    '<p style="color:#94a3b8;padding:2rem;text-align:center">No date data (reviews lack relative dates)</p>';
}}

// Top words
const words = DATA.top_words.slice(0,30);
Plotly.newPlot('ch-words', [{{
  type:'bar', orientation:'h',
  x: words.map(w=>w[1]).reverse(),
  y: words.map(w=>w[0]).reverse(),
  marker:{{color:'#818cf8'}}
}}], {{...dark, xaxis:{{fixedrange:true}}, yaxis:{{fixedrange:true, automargin:true}},
  height: 480}}, {{displayModeBar:false}});
if (Object.keys(DATA.reply_rate || {{}}).length >= 2) {{
  const months = Object.keys(DATA.reply_rate).sort();
  Plotly.newPlot('ch-reply', [{{
    type: 'scatter', mode: 'lines+markers',
    x: months, y: months.map(m => Math.round(DATA.reply_rate[m]*100)),
    line: {{color: '#22c55e', width: 2}},
    marker: {{color: '#22c55e', size: 5}},
    hovertemplate: '%{{x}}: %{{y}}%<extra></extra>',
  }}], {{
    ...dark,
    yaxis: {{fixedrange: true, ticksuffix: '%', range: [0, 100]}},
    xaxis: {{fixedrange: true}},
  }}, {{displayModeBar: false}});
}}
</script>
</body>
</html>"""
