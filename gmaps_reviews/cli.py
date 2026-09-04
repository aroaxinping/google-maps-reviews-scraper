"""CLI entry point using Typer."""

from __future__ import annotations
import asyncio
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import unquote

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table

from .parser import extract_total_count
from .scraper import scrape
from .storage import Store
from .dashboard import generate

app = typer.Typer(name="gmaps-reviews", add_completion=False, rich_markup_mode="rich")
console = Console()

DEFAULT_DB = Path("gmaps_reviews.db")


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


def _scrape_one(
    url: str,
    db: Path,
    limit: int,
    sort: str,
    headless: bool,
    language: str,
    since: Optional[str],
    min_rating: int,
    max_rating: int,
    csv: Optional[Path],
    json_out: Optional[Path],
    dashboard: Optional[Path],
    output_dir: Optional[Path],
) -> None:
    place_id   = _place_id_from_url(url)
    place_name = _place_name_from_url(url)
    store = Store(db)

    effective_csv = csv
    effective_dashboard = dashboard
    if output_dir:
        slug = _slugify(place_name)
        dest = output_dir / slug
        if effective_csv is None:
            effective_csv = dest / "reviews.csv"
        if effective_dashboard is None:
            effective_dashboard = dest / "dashboard.html"

    console.print(f"\n[bold cyan]gmaps-reviews[/bold cyan] — {place_name}")
    console.print(f"  Place ID : [dim]{place_id}[/dim]")
    console.print(f"  Database : [dim]{db}[/dim]")
    flags = []
    if sort != "relevant":
        flags.append(f"sort={sort}")
    if headless:
        flags.append("headless")
    if language != "en":
        flags.append(f"lang={language}")
    if since:
        flags.append(f"since={since}")
    if min_rating > 0 or max_rating < 5:
        flags.append(f"rating={min_rating}-{max_rating}★")
    if flags:
        console.print(f"  Options  : [dim]{' · '.join(flags)}[/dim]")

    existing = store.known_review_ids(place_id)
    if existing:
        console.print(
            f"\n  [dim]Resuming: {len(existing):,} existing reviews found, "
            "continuing from where we left off[/dim]"
        )
    else:
        console.print()

    captured_at = datetime.now(tz=timezone.utc).isoformat()
    new_total = 0
    page_num = [0]
    detected_total = [0]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=False,
    ) as progress:
        task_id = progress.add_task("Scraping…", total=None)

        async def on_batch(reviews, next_cursor, raw):
            nonlocal new_total
            page_num[0] += 1

            if page_num[0] == 1 and not detected_total[0]:
                n = extract_total_count(raw)
                if n:
                    detected_total[0] = n
                    progress.update(task_id, total=n)

            new_reviews = [r for r in reviews if r["review_id"] not in existing]
            inserted = store.insert_reviews(new_reviews, place_id)
            new_total += inserted
            for r in new_reviews:
                existing.add(r["review_id"])

            total_in_db = store.total_reviews(place_id)
            progress.update(
                task_id,
                completed=total_in_db,
                description=f"pg {page_num[0]:>4} | +{inserted} new | {total_in_db:,} total",
            )

        asyncio.run(scrape(
            url, place_id, on_batch,
            limit=limit, sort=sort, headless=headless,
            language=language, since=since,
            min_rating=min_rating, max_rating=max_rating,
        ))

    total_in_db = store.total_reviews(place_id)
    console.print(
        f"\n[green]Done.[/green] {new_total:,} new reviews added · {total_in_db:,} total in DB."
    )

    store.upsert_place({
        "place_id": place_id, "name": place_name,
        "total_reviews": total_in_db, "scraped_at": captured_at,
    })

    if effective_csv:
        effective_csv.parent.mkdir(parents=True, exist_ok=True)
        n = store.export_csv(effective_csv, place_id)
        console.print(f"  CSV       → {effective_csv} ({n:,} rows)")

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        n = store.export_json(json_out, place_id)
        console.print(f"  JSONL     → {json_out} ({n:,} rows)")

    if effective_dashboard:
        effective_dashboard.parent.mkdir(parents=True, exist_ok=True)
        reviews = store.all_reviews(place_id)
        generate(reviews, effective_dashboard, place_name=place_name)
        console.print(f"  Dashboard → {effective_dashboard}")

    store.close()


@app.command("scrape")
def scrape_cmd(
    url: Annotated[str, typer.Argument(help="Google Maps place URL")],
    db: Annotated[Path, typer.Option("--db", help="SQLite database path")] = DEFAULT_DB,
    limit: Annotated[int, typer.Option("--limit", help="Max reviews (0 = all)")] = 0,
    sort: Annotated[str, typer.Option("--sort", help="relevant | newest | highest | lowest")] = "relevant",
    headless: Annotated[bool, typer.Option("--headless/--no-headless", help="Run Chrome without a window")] = False,
    language: Annotated[str, typer.Option("--language", help="Maps UI language code (e.g. es, fr, de)")] = "en",
    since: Annotated[Optional[str], typer.Option("--since", help="Stop at reviews older than YYYY-MM")] = None,
    min_rating: Annotated[int, typer.Option("--min-rating", help="Only keep reviews with rating >= N")] = 0,
    max_rating: Annotated[int, typer.Option("--max-rating", help="Only keep reviews with rating <= N")] = 5,
    csv: Annotated[Optional[Path], typer.Option("--csv", help="Export CSV")] = None,
    json_out: Annotated[Optional[Path], typer.Option("--json", help="Export JSONL")] = None,
    dashboard: Annotated[Optional[Path], typer.Option("--dashboard", help="Generate HTML dashboard")] = None,
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir", help="Auto-create <dir>/<place>/reviews.csv and dashboard.html")] = None,
):
    """Scrape all reviews from a Google Maps place URL."""
    _scrape_one(url, db, limit, sort, headless, language, since, min_rating, max_rating,
                csv, json_out, dashboard, output_dir)


@app.command("scrape-file")
def scrape_file_cmd(
    urls_file: Annotated[Path, typer.Argument(help="Text file with one Google Maps URL per line")],
    db: Annotated[Path, typer.Option("--db")] = DEFAULT_DB,
    limit: Annotated[int, typer.Option("--limit", help="Max reviews per place (0 = all)")] = 0,
    sort: Annotated[str, typer.Option("--sort")] = "relevant",
    headless: Annotated[bool, typer.Option("--headless/--no-headless")] = False,
    language: Annotated[str, typer.Option("--language")] = "en",
    since: Annotated[Optional[str], typer.Option("--since")] = None,
    min_rating: Annotated[int, typer.Option("--min-rating")] = 0,
    max_rating: Annotated[int, typer.Option("--max-rating")] = 5,
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir")] = None,
):
    """Scrape multiple places from a file — one Google Maps URL per line."""
    if not urls_file.exists():
        console.print(f"[red]File not found:[/red] {urls_file}")
        raise typer.Exit(1)

    urls = [
        line.strip()
        for line in urls_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        console.print("[yellow]No URLs found in file.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold cyan]scrape-file[/bold cyan] — {len(urls)} places · DB: {db}\n")

    for i, url in enumerate(urls, 1):
        place_name = _place_name_from_url(url)
        console.rule(f"[bold]{i}/{len(urls)}[/bold] · {place_name}")
        _scrape_one(url, db, limit, sort, headless, language, since, min_rating, max_rating,
                    None, None, None, output_dir)

    console.print(f"\n[green bold]All done.[/green bold] Scraped {len(urls)} places → {db}")


@app.command()
def export(
    db: Annotated[Path, typer.Option("--db")] = DEFAULT_DB,
    place_id: Annotated[Optional[str], typer.Option("--place")] = None,
    csv: Annotated[Optional[Path], typer.Option("--csv")] = None,
    json_out: Annotated[Optional[Path], typer.Option("--json", help="Export JSONL")] = None,
    parquet: Annotated[Optional[Path], typer.Option("--parquet", help="Export Parquet (requires pandas+pyarrow)")] = None,
    excel: Annotated[Optional[Path], typer.Option("--excel", help="Export Excel (requires pandas+openpyxl)")] = None,
    dashboard: Annotated[Optional[Path], typer.Option("--dashboard")] = None,
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir")] = None,
):
    """Export existing data from the database without scraping."""
    store = Store(db)
    reviews = store.all_reviews(place_id)
    console.print(f"[dim]{len(reviews):,} reviews loaded from {db}[/dim]")

    effective_csv = csv
    effective_dashboard = dashboard
    if output_dir and place_id:
        slug = _slugify(place_id)
        dest = output_dir / slug
        if effective_csv is None:
            effective_csv = dest / "reviews.csv"
        if effective_dashboard is None:
            effective_dashboard = dest / "dashboard.html"

    if effective_csv:
        effective_csv.parent.mkdir(parents=True, exist_ok=True)
        n = store.export_csv(effective_csv, place_id)
        console.print(f"CSV     → {effective_csv} ({n:,} rows)")

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        n = store.export_json(json_out, place_id)
        console.print(f"JSONL   → {json_out} ({n:,} rows)")

    if parquet:
        parquet.parent.mkdir(parents=True, exist_ok=True)
        try:
            n = store.export_parquet(parquet, place_id)
            console.print(f"Parquet → {parquet} ({n:,} rows)")
        except ImportError as e:
            console.print(f"[yellow]{e}[/yellow]")

    if excel:
        excel.parent.mkdir(parents=True, exist_ok=True)
        try:
            n = store.export_excel(excel, place_id)
            console.print(f"Excel   → {excel} ({n:,} rows)")
        except ImportError as e:
            console.print(f"[yellow]{e}[/yellow]")

    if effective_dashboard:
        effective_dashboard.parent.mkdir(parents=True, exist_ok=True)
        name = place_id or "Reviews"
        generate(reviews, effective_dashboard, place_name=name)
        console.print(f"Dashboard → {effective_dashboard}")

    store.close()


@app.command()
def stats(
    db: Annotated[Path, typer.Option("--db")] = DEFAULT_DB,
    place_id: Annotated[Optional[str], typer.Option("--place")] = None,
):
    """Show a summary of scraped reviews in the database."""
    store = Store(db)
    s = store.get_stats(place_id)
    store.close()

    console.print(f"\n[bold cyan]Stats[/bold cyan] — {db}" + (f" · {place_id}" if place_id else ""))
    console.print()

    # Summary cards
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold cyan")
    table.add_row("Total reviews",  f"{s['total']:,}")
    table.add_row("Average rating", f"{s['avg_rating']:.2f} ★")
    table.add_row("With text",      f"{s['with_text']:,}")
    table.add_row("Owner replies",  f"{s['with_reply']:,}")
    table.add_row("Local Guides",   f"{s['local_guides']:,}")
    if s["date_range"][0]:
        table.add_row("Date range", f"{s['date_range'][0]} → {s['date_range'][1]}")
    console.print(table)

    # Rating distribution
    console.print("\n[dim]Rating distribution[/dim]")
    for star in ["5", "4", "3", "2", "1"]:
        count = s["rating_dist"].get(star, 0)
        pct = count / s["total"] * 100 if s["total"] else 0
        bar = "█" * int(pct / 2)
        console.print(f"  {star}★  {bar:<50} {count:,} ({pct:.1f}%)")

    # Top words
    if s["top_words"]:
        console.print("\n[dim]Top words[/dim]")
        words = "  ".join(f"[cyan]{w}[/cyan] {c}" for w, c in s["top_words"][:15])
        console.print(f"  {words}")

    console.print()


@app.command()
def web(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
):
    """Launch the web UI in your browser."""
    try:
        import uvicorn
        from .web_ui import app as web_app
    except ImportError:
        console.print("[red]Web UI requires FastAPI and uvicorn:[/red]")
        console.print("  pip install 'google-maps-reviews-scraper[web]'")
        raise typer.Exit(1)
    console.print(f"[bold cyan]Web UI[/bold cyan] → http://{host}:{port}")
    uvicorn.run(web_app, host=host, port=port)


if __name__ == "__main__":
    app()
