"""
Feature: after an item has been checked, find the nearest drop-off
point for its waste category. It is meant for everything that cannot be
recycled at home (hazardous waste, electronics, textiles, construction waste,
garden waste) and, with a softer message, for packaging materials such as glass,
metal, paper, cardboard and plastic when the home has no collection for them.
Biowaste and mixed waste go in the household bins, so they get no drop-off section.

The category comes from the answer the user just received (its id in
data/finland_waste_categories.json), so the user is never asked again what
they want to drop off.

Data source
-----------
Kierrätys.info open API v3.1, maintained by Suomen Kiertovoima ry (KIVO):
https://api.kierratys.info/  (read-only, needs a free API key).
Each team member registers their own key at
https://api.kierratys.info/get_apikey/ and puts it in their local .env file:

    KIERRATYS_INFO_API_KEY=<your key>

The key is never committed (.env is gitignored). The API does not label places
as "ekopiste", "sorttiasema" or "hazardous waste station"; it lists generic
collection spots with the material codes each one accepts, so this module
searches by material code instead.

Privacy
-------
A location (coordinates, municipality or postal code) is used only to build the
request to Kierrätys.info. It is not stored, not written to the history file
and never sent to the language model.
"""
import html
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

try:  # python-dotenv is a project dependency; tolerate its absence in isolated test runs
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

API_BASE_URL = "https://api.kierratys.info/collectionspots/"
API_KEY_ENV_VAR = "KIERRATYS_INFO_API_KEY"
GET_API_KEY_URL = "https://api.kierratys.info/get_apikey/"

REQUEST_TIMEOUT_S = 10
SEARCH_RADII_M = (10_000, 30_000, 100_000)  # widen the search until something is found
RADIUS_FETCH_LIMIT = 100
TEXT_FETCH_LIMIT = 10
DEFAULT_MAX_RESULTS = 5

ATTRIBUTION = (
    "_Source: Kierrätys.info (Suomen Kiertovoima ry). Opening hours and accepted "
    "materials can change, so check before you go._"
)

# Waste category id -> (label shown to the user, Kierrätys.info material code).
# The keys are the category ids in data/finland_waste_categories.json, so the
# category of a checked item can be passed straight in. Codes are from the
# Kierrätys.info API v3.1 documentation. Biowaste (bio bin) and mixed waste are
# left out on purpose: they go in the household bins.
MATERIAL_CHOICES: dict[str, tuple[str, int]] = {
    "hazardous_waste": ("Hazardous waste", 108),
    "electrical_equipment": ("Electrical and electronic equipment", 109),
    "textiles": ("Worn-out textiles", 113),
    "construction_waste": ("Construction and renovation waste", 119),
    "garden_waste": ("Garden waste", 101),
    "paper": ("Paper", 103),
    "cardboard": ("Cardboard and cartons", 105),
    "glass": ("Glass", 107),
    "metal": ("Metal", 106),
    "plastic": ("Plastic packaging", 111),
}

_PACKAGING_WORDS = {
    "paper": "paper",
    "cardboard": "cardboard and cartons",
    "glass": "glass",
    "metal": "metal",
    "plastic": "plastic packaging",
}

# Short, positive text shown above the finder, per category.
DROP_OFF_INTRO: dict[str, str] = {
    "hazardous_waste": (
        "Good news: hazardous waste can be handled safely and its materials recovered. "
        "It cannot go in your household bins, so take it to a hazardous waste collection point."
    ),
    "electrical_equipment": (
        "Old electronics contain valuable metals that get reused. They cannot go in your "
        "household bins, but a collection point near you will take them."
    ),
    "textiles": (
        "Worn-out textiles can still become raw material. If they are no longer wearable, "
        "a textile collection point near you will take them. Wearable clothes are better donated."
    ),
    "construction_waste": (
        "Bricks, concrete and other renovation waste do not go in household bins, but they "
        "can be crushed and reused. Take small amounts to a waste station near you."
    ),
    "garden_waste": (
        "Garden waste can become compost and mulch, and composting at home is often the easiest "
        "option. If you cannot, a waste station near you may take it. **Note:** the rules differ "
        "between municipalities and waste companies, so always check your own waste company's instructions."
    ),
}
for _key, _word in _PACKAGING_WORDS.items():
    DROP_OFF_INTRO[_key] = (
        f"Good news: {_word} is fully recyclable. If your home or building has no collection for it, "
        "you can take it to a public collection point near you."
    )


def supports_drop_off(category_id: Optional[str]) -> bool:
    """True if there is a drop-off section for this waste category id."""
    return category_id in MATERIAL_CHOICES


def drop_off_intro(category_id: Optional[str]) -> str:
    """The short positive text for a category, or an empty string if it has no drop-off section."""
    return DROP_OFF_INTRO.get(category_id or "", "")


class DropOffError(Exception):
    """Raised for any expected failure. The message is safe to show to the user."""


class MissingApiKeyError(DropOffError):
    """Raised when no Kierrätys.info API key is configured."""


@dataclass
class DropOffPoint:
    name: str
    operator: str
    address: str
    postal_code: str
    municipality: str
    latitude: Optional[float]
    longitude: Optional[float]
    materials: list
    opening_hours: str
    staffed: Optional[bool]
    distance_km: Optional[float] = None

    @property
    def google_maps_url(self) -> Optional[str]:
        if self.latitude is None or self.longitude is None:
            return None
        return f"https://www.google.com/maps/dir/?api=1&destination={self.latitude},{self.longitude}"

    @property
    def osm_url(self) -> Optional[str]:
        if self.latitude is None or self.longitude is None:
            return None
        return f"https://www.openstreetmap.org/?mlat={self.latitude}&mlon={self.longitude}#map=16/{self.latitude}/{self.longitude}"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    radius_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def get_api_key() -> Optional[str]:
    key = os.getenv(API_KEY_ENV_VAR, "").strip()
    return key or None


def _clean_html(text: Optional[str], max_len: int = 240) -> str:
    """Opening hours come as HTML; turn them into one short plain-text line."""
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", ", ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*(,\s*)+", ", ", text).strip(" ,")
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def _clean_municipality(value: Optional[str]) -> str:
    # The API matches municipality names case-sensitively; Finnish names start with a capital.
    value = (value or "").strip()
    return value[:1].upper() + value[1:]


def _clean_postal_code(value: Optional[str]) -> str:
    value = re.sub(r"\s+", "", value or "")
    if value and not re.fullmatch(r"\d{5}", value):
        raise DropOffError("A Finnish postal code has 5 digits, for example 33100.")
    return value


def parse_location(text: Optional[str]) -> Optional[tuple[float, float]]:
    """Parses 'lat, lon' (as filled in by the browser) into floats, or None."""
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", text or "")
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


# --------------------------------------------------------------------------
# API access
# --------------------------------------------------------------------------

def build_request_url(
    material_code: int,
    api_key: str,
    *,
    municipality: str = "",
    postal_code: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_m: Optional[int] = None,
    limit: int = RADIUS_FETCH_LIMIT,
) -> str:
    """Builds the /collectionspots/ URL. Note the API wants point=lon,lat (not lat,lon)."""
    params = {"api_key": api_key, "material": str(material_code), "limit": str(limit)}
    if municipality:
        params["municipality"] = municipality
    if postal_code:
        params["postal_code"] = postal_code
    if lat is not None and lon is not None and radius_m:
        params["point"] = f"{lon:.5f},{lat:.5f}"
        params["dist"] = str(int(radius_m))
    return API_BASE_URL + "?" + urllib.parse.urlencode(params, safe=",")


def _fetch_json(url: str) -> dict:
    """GET a URL and parse JSON. Errors are re-raised without the URL, which contains the API key."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "WasteBuddy-course-project/1.0", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise DropOffError(
                f"Kierrätys.info did not accept the API key. Check {API_KEY_ENV_VAR} in your .env file."
            ) from None
        raise DropOffError(
            f"Kierrätys.info returned an error (HTTP {err.code}). Please try again later."
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DropOffError(
            "Could not reach Kierrätys.info. Check your internet connection and try again."
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise DropOffError(
            "Kierrätys.info sent a response that could not be read. Please try again later."
        ) from None


def _parse_spot(raw: object, origin: Optional[tuple[float, float]] = None) -> Optional[DropOffPoint]:
    """Turns one API result into a DropOffPoint. Returns None for unusable entries."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    geometry = raw.get("geometry")
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    lat = lon = None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lon, lat = float(coords[0]), float(coords[1])  # GeoJSON order is lon, lat
        except (TypeError, ValueError):
            lat = lon = None

    materials = [
        str(m["name"])
        for m in (raw.get("materials") or [])
        if isinstance(m, dict) and m.get("name")
    ]
    occupied = raw.get("occupied")
    distance = None
    if origin is not None and lat is not None and lon is not None:
        distance = round(haversine_km(origin[0], origin[1], lat, lon), 1)

    return DropOffPoint(
        name=name,
        operator=str(raw.get("operator") or "").strip(),
        address=str(raw.get("address") or "").strip(),
        postal_code=str(raw.get("postal_code") or "").strip(),
        municipality=str(raw.get("municipality") or "").strip(),
        latitude=lat,
        longitude=lon,
        materials=materials,
        opening_hours=_clean_html(raw.get("opening_hours_en") or raw.get("opening_hours_fi")),
        staffed=occupied if isinstance(occupied, bool) else None,
        distance_km=distance,
    )


def _parse_results(payload: object, origin: Optional[tuple[float, float]] = None) -> list:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    points = (_parse_spot(item, origin) for item in results)
    return [p for p in points if p is not None]


# --------------------------------------------------------------------------
# Public lookup functions
# --------------------------------------------------------------------------

def find_drop_off_points(
    material_key: str,
    *,
    municipality: Optional[str] = None,
    postal_code: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    max_results: Optional[int] = None,
    api_key: Optional[str] = None,
    fetcher: Optional[Callable[[str], dict]] = None,
) -> list:
    """
    Finds drop-off points that accept the chosen material.

    With lat/lon it searches in widening circles (10, 30, then 100 km) and
    returns the closest points first. With a municipality and/or postal code it
    returns the first matches from the API, which does not document any sorting.
    Raises DropOffError (message safe to show) on expected failures.
    `fetcher` and `api_key` exist so tests can run without network or a real key.
    """
    if material_key not in MATERIAL_CHOICES:
        raise DropOffError("Check an item first. There is no drop-off point to look for yet.")
    key = api_key or get_api_key()
    if not key:
        raise MissingApiKeyError(
            "The drop-off finder is not set up on this computer yet. Get a free API key at "
            f"{GET_API_KEY_URL} and add this line to your .env file: {API_KEY_ENV_VAR}=<your key>"
        )
    fetch = fetcher or _fetch_json
    code = MATERIAL_CHOICES[material_key][1]

    if lat is not None and lon is not None:
        origin = (lat, lon)
        for radius in SEARCH_RADII_M:
            url = build_request_url(code, key, lat=lat, lon=lon, radius_m=radius)
            points = _parse_results(fetch(url), origin)
            if points:
                points.sort(key=lambda p: (p.distance_km is None, p.distance_km or 0.0))
                return points[: max_results or DEFAULT_MAX_RESULTS]
        return []

    municipality = _clean_municipality(municipality)
    postal_code = _clean_postal_code(postal_code)
    if not municipality and not postal_code:
        raise DropOffError("Enter a municipality or a postal code, or use your location.")
    url = build_request_url(
        code, key, municipality=municipality, postal_code=postal_code, limit=TEXT_FETCH_LIMIT
    )
    return _parse_results(fetch(url))[: max_results or TEXT_FETCH_LIMIT]


def format_results_markdown(material_key: str, points: list, *, by_location: bool) -> str:
    """Formats results for display. Pure function: no network, no state."""
    label = MATERIAL_CHOICES[material_key][0]
    heading = f"### Drop-off points: {label}"
    if not points:
        hint = (
            "Nothing found within 100 km. Kierrätys.info only covers Finland."
            if by_location
            else "Check the spelling of the municipality, try a nearby one, or use your location instead."
        )
        return f"{heading}\n\nNo drop-off points found. {hint}\n\n{ATTRIBUTION}"

    lines = [heading, ""]
    if not by_location:
        lines += ["_Results are not sorted by distance. Use your location to see the nearest ones first._", ""]
    for index, p in enumerate(points, start=1):
        distance = f" ({p.distance_km} km)" if p.distance_km is not None else ""
        lines.append(f"**{index}. {p.name}**{distance}")
        place = ", ".join(part for part in (p.address, f"{p.postal_code} {p.municipality}".strip()) if part)
        if place:
            lines.append(f"- Address: {place}")
        if p.operator:
            lines.append(f"- Operator: {p.operator}")
        if p.opening_hours:
            lines.append(f"- Opening hours: {p.opening_hours}")
        if p.staffed is not None:
            lines.append("- " + ("Staffed during opening hours" if p.staffed else "Unstaffed"))
        if p.materials:
            shown = ", ".join(p.materials[:8]) + (" ..." if len(p.materials) > 8 else "")
            lines.append(f"- Accepts: {shown}")
        if p.google_maps_url:
            lines.append(f"- Directions: [Google Maps]({p.google_maps_url}) | [OpenStreetMap]({p.osm_url})")
        lines.append("")
    lines.append(ATTRIBUTION)
    return "\n".join(lines)


def lookup_by_text(material_key: str, municipality: str = "", postal_code: str = "", **kwargs) -> str:
    """UI entry point: search by municipality / postal code. Never raises."""
    try:
        points = find_drop_off_points(
            material_key, municipality=municipality, postal_code=postal_code, **kwargs
        )
    except DropOffError as err:
        return f"### Drop-off points\n\n{err}"
    return format_results_markdown(material_key, points, by_location=False)


def lookup_by_location(material_key: str, location_text: str, **kwargs) -> str:
    """UI entry point: search near 'lat, lon' text from the browser. Never raises."""
    coords = parse_location(location_text)
    if coords is None:
        if (location_text or "").strip() == "denied":
            message = "Location sharing was blocked in the browser. Enter a municipality or postal code instead."
        elif (location_text or "").strip() == "unavailable":
            message = "Your location could not be detected. Enter a municipality or postal code instead."
        else:
            message = "Press 'Use my location' first, or enter a municipality or postal code."
        return f"### Drop-off points\n\n{message}"
    try:
        points = find_drop_off_points(material_key, lat=coords[0], lon=coords[1], **kwargs)
    except DropOffError as err:
        return f"### Drop-off points\n\n{err}"
    return format_results_markdown(material_key, points, by_location=True)
