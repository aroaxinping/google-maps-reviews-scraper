"""SQLite + CSV storage for scraped reviews."""

from __future__ import annotations
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterable

def _extract_words(text: str) -> list:
    latin = [w.lower() for w in re.findall(r"[a-zA-ZÀ-ÿ]{4,}", text)]
    cjk   = re.findall(r"[一-鿿㐀-䶿가-힯぀-ゟ゠-ヿ]{2,}", text)
    arabic = re.findall(r"[؀-ۿ]{4,}", text)
    return latin + cjk + arabic


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
               name=excluded.name,
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

    def export_json(self, path: Path, place_id: str | None = None) -> int:
        rows = self.all_reviews(place_id)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)

    def export_parquet(self, path: Path, place_id: str | None = None) -> int:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Install pandas and pyarrow: pip install pandas pyarrow")
        rows = self.all_reviews(place_id)
        df = pd.DataFrame(rows, columns=CSV_FIELDS)
        df.to_parquet(path, index=False)
        return len(rows)

    def export_excel(self, path: Path, place_id: str | None = None) -> int:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Install pandas and openpyxl: pip install pandas openpyxl")
        rows = self.all_reviews(place_id)
        df = pd.DataFrame(rows, columns=CSV_FIELDS)
        df.to_excel(path, index=False)
        return len(rows)

    def get_stats(self, place_id: str | None = None) -> dict:
        rows = self.all_reviews(place_id)
        total = len(rows)
        with_text = sum(1 for r in rows if r.get("review_text"))
        with_reply = sum(1 for r in rows if r.get("owner_reply"))
        local_guides = sum(1 for r in rows if r.get("local_guide"))

        ratings = [r["rating"] for r in rows if r.get("rating") is not None]
        avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

        rating_dist: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
        for rat in ratings:
            key = str(int(rat))
            if key in rating_dist:
                rating_dist[key] += 1

        dates = [r["date_estimated"] for r in rows if r.get("date_estimated")]
        date_range = (min(dates) if dates else None, max(dates) if dates else None)

        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "is", "it", "was", "are", "be", "we", "i",
            "they", "this", "that", "very", "so", "my", "our", "their", "have",
            "had", "has", "not", "no", "its", "as", "by", "from", "your",
            "el", "la", "los", "las", "de", "en", "y", "que", "un", "una",
            "es", "con", "se", "del", "al", "lo", "le", "su", "por",
        }
        word_counts: Counter = Counter()
        for r in rows:
            if r.get("review_text"):
                for w in _extract_words(r["review_text"]):
                    if w.isascii() and w in stopwords:
                        continue
                    word_counts[w] += 1
        top_words = word_counts.most_common(20)

        lang_counts: dict = {}
        try:
            from langdetect import detect
            for r in rows:
                if r.get("review_text"):
                    try:
                        lang = detect(r["review_text"])
                        lang_counts[lang] = lang_counts.get(lang, 0) + 1
                    except Exception:
                        pass
        except ImportError:
            pass

        return {
            "total": total,
            "with_text": with_text,
            "with_reply": with_reply,
            "avg_rating": avg_rating,
            "local_guides": local_guides,
            "rating_dist": rating_dist,
            "top_words": top_words,
            "date_range": date_range,
            "languages": lang_counts,
        }

    def close(self) -> None:
        self.con.close()
