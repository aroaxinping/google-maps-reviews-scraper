"""Optional sentiment analysis via TextBlob. Install: pip install textblob"""
from __future__ import annotations


def analyze(text: str) -> dict:
    """Return {"polarity": float, "subjectivity": float, "label": str}."""
    try:
        from textblob import TextBlob
    except ImportError:
        raise ImportError("Install textblob: pip install textblob")
    blob = TextBlob(text)
    p = blob.sentiment.polarity
    label = "positive" if p > 0.1 else "negative" if p < -0.1 else "neutral"
    return {"polarity": round(p, 3), "subjectivity": round(blob.sentiment.subjectivity, 3), "label": label}


def add_sentiment(reviews: list[dict]) -> list[dict]:
    """Add 'sentiment' dict to each review that has review_text. Skips if TextBlob unavailable."""
    try:
        from textblob import TextBlob  # noqa: F401
    except ImportError:
        return reviews
    result = []
    for r in reviews:
        r = dict(r)
        if r.get("review_text"):
            try:
                r["sentiment"] = analyze(r["review_text"])
            except Exception:
                r["sentiment"] = None
        result.append(r)
    return result
