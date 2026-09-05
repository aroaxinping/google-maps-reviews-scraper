import csv
import json
import pytest
from gmaps_reviews.storage import Store

PLACE_ID = "0x1234:0xabcd"
REVIEWS = [
    {
        "review_id": f"rev_{i}",
        "author": f"User {i}",
        "local_guide": i % 2 == 0,
        "review_count": i * 5,
        "rating": (i % 5) + 1,
        "date_relative": f"{i} months ago",
        "date_estimated": f"2024-{(i % 12) + 1:02d}",
        "has_photos": False,
        "review_text": f"Review number {i}, place is {'great' if i % 2 == 0 else 'terrible'}.",
        "owner_reply": "Thank you!" if i % 4 == 0 else "",
        "source": "Google Maps",
    }
    for i in range(20)
]


def test_insert_and_count(tmp_db):
    n = tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    assert n == 20
    assert tmp_db.total_reviews(PLACE_ID) == 20


def test_deduplication(tmp_db):
    tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    n2 = tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    assert n2 == 0


def test_known_review_ids(tmp_db):
    tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    ids = tmp_db.known_review_ids(PLACE_ID)
    assert len(ids) == 20
    assert "rev_0" in ids


def test_export_csv(tmp_db, tmp_path):
    tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    out = tmp_path / "out.csv"
    n = tmp_db.export_csv(out, PLACE_ID)
    assert n == 20
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert len(rows) == 21


def test_export_json(tmp_db, tmp_path):
    tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    out = tmp_path / "out.jsonl"
    n = tmp_db.export_json(out, PLACE_ID)
    assert n == 20
    lines = [json.loads(l) for l in out.read_text().splitlines() if l]
    assert len(lines) == 20


def test_get_stats(tmp_db):
    tmp_db.insert_reviews(REVIEWS, PLACE_ID)
    s = tmp_db.get_stats(PLACE_ID)
    assert s["total"] == 20
    assert 1.0 <= s["avg_rating"] <= 5.0
    assert sum(s["rating_dist"].values()) == 20
    assert s["with_text"] > 0


def test_upsert_place_updates_name(tmp_db):
    tmp_db.upsert_place({"place_id": PLACE_ID, "name": "Old Name", "total_reviews": 10, "scraped_at": "2026-01-01"})
    tmp_db.upsert_place({"place_id": PLACE_ID, "name": "New Name", "total_reviews": 20, "scraped_at": "2026-01-02"})
    row = tmp_db.con.execute("SELECT name, total_reviews FROM places WHERE place_id=?", (PLACE_ID,)).fetchone()
    assert row[0] == "New Name"
    assert row[1] == 20
