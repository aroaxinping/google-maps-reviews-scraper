from datetime import datetime
import pytest
from gmaps_reviews.parser import parse_batch, extract_total_count


def test_parse_batch_returns_reviews(raw_batch_0):
    reviews, cursor = parse_batch(raw_batch_0)
    assert len(reviews) > 0
    assert cursor is not None


def test_review_required_fields(raw_batch_0):
    reviews, _ = parse_batch(raw_batch_0)
    r = reviews[0]
    for field in ("review_id", "author", "rating", "local_guide", "review_text", "source"):
        assert field in r, f"missing field: {field}"
    assert r["source"] == "Google Maps"
    assert isinstance(r["local_guide"], bool)


def test_no_duplicate_review_ids(raw_batch_0):
    reviews, _ = parse_batch(raw_batch_0)
    ids = [r["review_id"] for r in reviews]
    assert len(ids) == len(set(ids))


def test_extract_total_count_returns_none(raw_batch_0):
    assert extract_total_count(raw_batch_0) is None


def test_different_batches_have_different_ids(raw_batch_0, raw_batch_5):
    r0, _ = parse_batch(raw_batch_0)
    r5, _ = parse_batch(raw_batch_5)
    ids0 = {r["review_id"] for r in r0}
    ids5 = {r["review_id"] for r in r5}
    assert not (ids0 & ids5), "Different pages must not share review IDs"
