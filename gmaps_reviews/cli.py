"""CLI entry point using Typer."""

from __future__ import annotations
import asyncio
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from .parser import extract_total_count, parse_batch
from .scraper import scrape
from .storage import Store
from .dashboard import generate

app = typer.Typer(name="gmaps-reviews", add_completion=False, rich_markup_mode="rich")
console = Console()

DEFAULT_DB = Path("gmaps_reviews.db")


def _place_id_from_url(url: str) -> str:
    """Derive a stable place_id from the Maps URL."""
    m = re.search(r"0x[0-9a-f]+:0x[0-9a-f]+", url, re.I)
    if m:
        return m.group(0).lower()
    return hashlib.md5(url.encode()).hexdigest()[:16]


def _place_name_from_url(url: str) -> str:
    m = re.search(r"/place/([^/@]+)", url)
    if m:
        return m.group(1).replace("+", " ").replace("%20", " ")
    return "Unknown Place"


@app.command()
def scrape_cmd(
    url: Annotated[str, typer.Argument(help="Google Maps place URL")],
    db: Annotated[Path, typer.Option("--db", help="SQLite database path")] = DEFAULT_DB,
    limit: Annotated[int, typer.Option("--limit", help="Max reviews (0 = all)")] = 0,
    sort: Annotated[str, typer.Option("--sort", help="relevant | newest | highest | lowest")] = "relevant",
    csv: Annotated[Optional[Path], typer.Option("--csv", help="Also export CSV")] = None,
    dashboard: Annotated[Optional[Path], typer.Option("--dashboard", help="Generate HTML dashboard")] = None,
):
    """Scrape all reviews from a Google Maps place URL."""
    place_id   = _place_id_from_url(url)
    place_name = _place_name_from_url(url)
    store = Store(db)

    console.print(f"\n[bold cyan]gmaps-reviews[/bold cyan] — {place_name}")
    console.print(f"  Place ID : [dim]{place_id}[/dim]")
    console.print(f"  Database : [dim]{db}[/dim]")
    console.print(f"  Sort     : [dim]{sort}[/dim]\n")

    existing = store.known_review_ids(place_id)
    console.print(f"  Existing : [dim]{len(existing)} reviews already in DB[/dim]\n")

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

            # Try to detect total on first page
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

        asyncio.run(scrape(url, place_id, on_batch, limit=limit, sort=sort))

    total_in_db = store.total_reviews(place_id)
    console.print(f"\n[green]Done.[/green] {new_total:,} new reviews added. {total_in_db:,} total in DB.")

    store.upsert_place({
        "place_id": place_id, "name": place_name,
        "total_reviews": total_in_db, "scraped_at": captured_at,
    })

    if csv:
        n = store.export_csv(csv, place_id)
        console.print(f"  CSV → {csv} ({n:,} rows)")

    if dashboard:
        reviews = store.all_reviews(place_id)
        generate(reviews, dashboard, place_name=place_name)
        console.print(f"  Dashboard → {dashboard}")

    store.close()


@app.command()
def export(
    db: Annotated[Path, typer.Option("--db")] = DEFAULT_DB,
    place_id: Annotated[Optional[str], typer.Option("--place")] = None,
    csv: Annotated[Optional[Path], typer.Option("--csv")] = None,
    dashboard: Annotated[Optional[Path], typer.Option("--dashboard")] = None,
):
    """Export existing data from the database without scraping."""
    store = Store(db)
    reviews = store.all_reviews(place_id)
    console.print(f"[dim]{len(reviews):,} reviews loaded from {db}[/dim]")

    if csv:
        n = store.export_csv(csv, place_id)
        console.print(f"CSV → {csv} ({n:,} rows)")

    if dashboard:
        name = place_id or "Reviews"
        generate(reviews, dashboard, place_name=name)
        console.print(f"Dashboard → {dashboard}")

    store.close()


if __name__ == "__main__":
    app()
