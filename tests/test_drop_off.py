"""
Unit tests for the optional drop-off point feature (src/services/drop_off.py).
No network and no real API key needed: the API is replaced by a fake fetcher.

The sample response below follows the field names in the Kierrätys.info API
v3.1 documentation. Check it against one real response once you have a key.
"""
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from src.services import drop_off as d

HELSINKI = (60.1699, 24.9384)


def _spot(name, lon, lat, **extra):
    spot = {
        "spot_id": 1,
        "name": name,
        "operator": "Test Oy",
        "contact_info": "",
        "address": "Esimerkkikatu 1",
        "postal_code": "00100",
        "municipality": "Helsinki",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "materials": [{"code": 108, "name": "Vaarallinen jäte"}],
        "opening_hours_en": "<p>Mon-Fri 8-16<br>Sat closed</p>",
        "occupied": True,
    }
    spot.update(extra)
    return spot


def _page(*spots):
    return {"count": len(spots), "next": None, "previous": None, "results": list(spots)}


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_request_url_uses_lon_lat_order_and_material_code():
    url = d.build_request_url(108, "KEY", lat=60.404, lon=25.107, radius_m=5000)
    q = _query(url)
    assert q["point"] == "25.10700,60.40400"  # lon first, then lat
    assert q["dist"] == "5000"
    assert q["material"] == "108"
    assert q["api_key"] == "KEY"


def test_location_search_sorts_by_distance_and_limits_results():
    far = _spot("Far", 24.9384, 60.30)
    near = _spot("Near", 24.9384, 60.18)
    mid = _spot("Mid", 24.9384, 60.22)
    points = d.find_drop_off_points(
        "hazardous_waste", lat=HELSINKI[0], lon=HELSINKI[1],
        api_key="KEY", fetcher=lambda url: _page(far, near, mid), max_results=2,
    )
    assert [p.name for p in points] == ["Near", "Mid"]
    assert points[0].distance_km < points[1].distance_km


def test_radius_widens_until_something_is_found():
    seen = []

    def fetcher(url):
        seen.append(_query(url)["dist"])
        return _page() if len(seen) < 3 else _page(_spot("Remote", 24.9, 60.9))

    points = d.find_drop_off_points(
        "glass", lat=60.17, lon=24.94, api_key="KEY", fetcher=fetcher
    )
    assert seen == ["10000", "30000", "100000"]
    assert [p.name for p in points] == ["Remote"]


def test_nothing_found_returns_empty_list():
    points = d.find_drop_off_points(
        "construction_waste", lat=60.17, lon=24.94, api_key="KEY", fetcher=lambda url: _page()
    )
    assert points == []


def test_text_search_capitalises_municipality_and_sends_postal_code():
    captured = {}

    def fetcher(url):
        captured.update(_query(url))
        return _page(_spot("A", 24.9, 60.2))

    d.find_drop_off_points(
        "electrical_equipment", municipality=" tampere ", postal_code="33 100",
        api_key="KEY", fetcher=fetcher,
    )
    assert captured["municipality"] == "Tampere"
    assert captured["postal_code"] == "33100"
    assert captured["material"] == "109"
    assert "point" not in captured


def test_invalid_postal_code_is_rejected():
    with pytest.raises(d.DropOffError, match="5 digits"):
        d.find_drop_off_points("paper", postal_code="123", api_key="KEY", fetcher=lambda u: _page())


def test_text_search_needs_some_place():
    with pytest.raises(d.DropOffError, match="municipality"):
        d.find_drop_off_points("paper", api_key="KEY", fetcher=lambda u: _page())


def test_unknown_material_is_rejected():
    with pytest.raises(d.DropOffError):
        d.find_drop_off_points("pizza", municipality="Espoo", api_key="KEY", fetcher=lambda u: _page())


def test_every_category_with_a_drop_off_has_a_code_and_a_positive_intro():
    for key in d.MATERIAL_CHOICES:
        assert d.supports_drop_off(key)
        assert d.drop_off_intro(key).strip()
    assert d.MATERIAL_CHOICES["construction_waste"][1] == 119
    assert d.MATERIAL_CHOICES["garden_waste"][1] == 101
    assert d.MATERIAL_CHOICES["glass"][1] == 107


def test_bin_categories_and_unknown_values_have_no_drop_off_section():
    for key in ("biowaste", "mixed_waste", None, "", "pizza"):
        assert not d.supports_drop_off(key)
        assert d.drop_off_intro(key) == ""


def test_garden_waste_text_warns_that_local_rules_differ():
    assert "differ" in d.drop_off_intro("garden_waste")
    assert "waste company" in d.drop_off_intro("garden_waste")


def test_packaging_text_is_conditional_on_home_collection():
    for key in ("paper", "cardboard", "glass", "metal", "plastic"):
        assert "no collection" in d.drop_off_intro(key)


def test_category_keys_match_the_data_file():
    import json
    from pathlib import Path

    data = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "finland_waste_categories.json").read_text(encoding="utf-8")
    )
    ids = {c["id"] for c in data["categories"]}
    assert set(d.MATERIAL_CHOICES) <= ids
    assert {"construction_waste", "garden_waste"} <= ids
    assert not ({"biowaste", "mixed_waste"} & set(d.MATERIAL_CHOICES))


def test_missing_api_key_explains_how_to_get_one(monkeypatch):
    monkeypatch.setattr(d, "get_api_key", lambda: None)
    with pytest.raises(d.MissingApiKeyError) as err:
        d.find_drop_off_points("paper", municipality="Espoo", fetcher=lambda u: _page())
    assert d.API_KEY_ENV_VAR in str(err.value)
    assert d.GET_API_KEY_URL in str(err.value)


def test_http_errors_become_friendly_messages_without_leaking_the_key(monkeypatch):
    def deny(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", deny)
    with pytest.raises(d.DropOffError) as err:
        d._fetch_json("https://api.kierratys.info/collectionspots/?api_key=SECRET123")
    assert "API key" in str(err.value)
    assert "SECRET123" not in str(err.value)

    def offline(request, timeout=None):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(d.DropOffError, match="Could not reach"):
        d._fetch_json("https://api.kierratys.info/collectionspots/?api_key=SECRET123")


def test_opening_hours_html_is_turned_into_plain_text():
    assert d._clean_html("<p>Mon-Fri 8-16<br>Sat&nbsp;closed</p>") == "Mon-Fri 8-16, Sat closed"
    assert d._clean_html(None) == ""
    assert d._clean_html("x" * 500).endswith("...")


def test_malformed_spots_are_skipped_not_fatal():
    payload = _page(
        _spot("Good", 24.9, 60.2),
        {"name": ""},  # no name
        "not a dict",
        _spot("No coordinates", 0, 0, geometry=None),
    )
    points = d._parse_results(payload)
    assert [p.name for p in points] == ["Good", "No coordinates"]
    assert points[1].google_maps_url is None


def test_unexpected_payload_shape_gives_no_results():
    assert d._parse_results({"unexpected": True}) == []
    assert d._parse_results(None) == []


def test_haversine_helsinki_to_tampere_is_about_160_km():
    assert 155 < d.haversine_km(60.1699, 24.9384, 61.4978, 23.7610) < 170


@pytest.mark.parametrize(
    "text, expected",
    [
        ("60.17000, 24.94000", (60.17, 24.94)),
        ("  60.1,24.9 ", (60.1, 24.9)),
        ("denied", None),
        ("", None),
        ("95.0, 24.9", None),
    ],
)
def test_parse_location(text, expected):
    assert d.parse_location(text) == expected


def test_markdown_has_attribution_directions_and_distance():
    spot = _spot("Sortti Oy", 24.9384, 60.18)
    points = d.find_drop_off_points(
        "hazardous_waste", lat=HELSINKI[0], lon=HELSINKI[1], api_key="SECRET123",
        fetcher=lambda url: _page(spot),
    )
    text = d.format_results_markdown("hazardous_waste", points, by_location=True)
    assert "Sortti Oy" in text
    assert "km)" in text
    assert "google.com/maps/dir" in text
    assert "Kierrätys.info" in text
    assert "Mon-Fri 8-16, Sat closed" in text
    assert "SECRET123" not in text
    assert "Accepts: Vaarallinen jäte" in text


def test_markdown_for_text_search_warns_results_are_not_sorted():
    text = d.format_results_markdown("paper", [d._parse_spot(_spot("A", 24.9, 60.2))], by_location=False)
    assert "not sorted by distance" in text


def test_lookup_wrappers_never_raise():
    def broken(url):
        raise d.DropOffError("Could not reach Kierrätys.info.")

    assert "Could not reach" in d.lookup_by_text("paper", "Espoo", api_key="KEY", fetcher=broken)
    assert "Could not reach" in d.lookup_by_location(
        "paper", "60.2, 24.9", api_key="KEY", fetcher=broken
    )
    assert "blocked" in d.lookup_by_location("paper", "denied")
    assert "Use my location" in d.lookup_by_location("paper", "")
    assert "municipality" in d.lookup_by_text("paper", "", "", api_key="KEY", fetcher=broken)
