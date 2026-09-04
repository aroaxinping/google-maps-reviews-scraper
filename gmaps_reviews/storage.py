"""SQLite + CSV storage for scraped reviews."""

from __future__ import annotations
import csv
import json
import sqlite3
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    place_id    TEXT PRIMARY KEY,
    name        TEXT,
    address     TEXT,
    phone       TEXT,
    website     TEXT,
    category    TEXT,
    rating      REAL,
    total_reviews INTEGER,
    scraped_at  TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id     TEXT PRIMARY KEY,
    place_id      TEXT REFERENCES places(place_id),
    author        TEXT,
    local_guide   INTEGER,
    review_count  INTEGER,
    rating        INTEGER,
    date_relative TEXT,
    date_estimated TEXT,
    has_photos    INTEGER,
    review_text   TEXT,
    owner_reply   TEXT,
    source        TEXT
);

CREATE TABLE IF NOT EXISTS raw_batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id    TEXT,
    captured_at TEXT,
    data        TEXT
);
"""

CSV_FIELDS = [
    "review_id", "place_id", "author", "local_guide", "review_count",
    "rating", "date_relative", "date_estimated", "has_photos",
    "review_text", "owner_reply", "source",
]


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def upsert_place(self, place: dict) -> None:
        self.con.execute(
            """INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(place_id) DO UPDATE SET
               total_reviews=excluded.total_reviews,
               scraped_at=excluded.scraped_at""",
            (
                place.get("place_id"), place.get("name"), place.get("address"),
                place.get("phone"), place.get("website"), place.get("category"),
                place.get("rating"), place.get("total_reviews"),
                place.get("scraped_at"),
            ),
        )
        self.con.commit()

    def insert_reviews(self, reviews: Iterable[dict], place_id: str) -> int:
        inserted = 0
        for r in reviews:
            try:
                self.con.execute(
                    """INSERT OR IGNORE INTO reviews VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r["review_id"], place_id, r["author"],
                        int(r["local_guide"]), r["review_count"],
                        r["rating"], r["date_relative"], r["date_estimated"],
                        int(r["has_photos"]),
                        r["review_text"], r["owner_reply"], r["source"],
                    ),
                )
                if self.con.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
            except Exception:
                continue
        self.con.commit()
        return inserted

    def save_raw_batch(self, place_id: str, captured_at: str, raw: str) -> None:
        self.con.execute(
            "INSERT INTO raw_batches (place_id, captured_at, data) VALUES (?,?,?)",
            (place_id, captured_at, json.dumps(raw)),
        )
        self.con.commit()

    def known_review_ids(self, place_id: str) -> set[str]:
        rows = self.con.execute(
            "SELECT review_id FROM reviews WHERE place_id=?", (place_id,)
        ).fetchall()
        return {r[0] for r in rows}

    def total_reviews(self, place_id: str) -> int:
        return self.con.execute(
            "SELECT COUNT(*) FROM reviews WHERE place_id=?", (place_id,)
        ).fetchone()[0]

    def export_csv(self, path: Path, place_id: str | None = None) -> int:
        where = "WHERE place_id=?" if place_id else ""
        params = (place_id,) if place_id else ()
        rows = self.con.execute(
            f"SELECT {','.join(CSV_FIELDS)} FROM reviews {where}", params
        ).fetchall()
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            w.writerows(rows)
        return len(rows)

    def all_reviews(self, place_id: str | None = None) -> list[dict]:
        where = "WHERE place_id=?" if place_id else ""
        params = (place_id,) if place_id else ()
        rows = self.con.execute(
            f"SELECT {','.join(CSV_FIELDS)} FROM reviews {where}", params
        ).fetchall()
        return [dict(zip(CSV_FIELDS, r)) for r in rows]

    def close(self) -> None:
        self.con.close()
