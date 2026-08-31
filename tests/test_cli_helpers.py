from gmaps_reviews.cli import _place_id_from_url, _place_name_from_url, _slugify, _normalise_since


def test_place_id_hex_format():
    url = "https://www.google.com/maps/place/X/@14.0,120.9/data=!3m1!0x3397c3e43bc1e5c5:0x19a5d35e25f8b3f6"
    pid = _place_id_from_url(url)
    assert pid.startswith("0x")
    assert ":" in pid


def test_place_id_fallback_is_hex():
    pid = _place_id_from_url("https://maps.app.goo.gl/abc123")
    assert len(pid) == 16
    assert all(c in "0123456789abcdef" for c in pid)


def test_place_name_with_plus():
    url = "https://www.google.com/maps/place/Taal+Vista+Hotel/@14.0,120.9"
    assert _place_name_from_url(url) == "Taal Vista Hotel"


def test_place_name_unknown():
    assert _place_name_from_url("https://maps.app.goo.gl/x") == "Unknown Place"


def test_slugify_basic():
    assert _slugify("Taal Vista Hotel") == "taal-vista-hotel"


def test_slugify_strips_edge_hyphens():
    assert _slugify("--hello--") == "hello"


def test_normalise_since_full_date():
    assert _normalise_since("2024-03-15") == "2024-03"


def test_normalise_since_month_only():
    assert _normalise_since("2024-03") == "2024-03"


def test_normalise_since_none():
    assert _normalise_since(None) is None
