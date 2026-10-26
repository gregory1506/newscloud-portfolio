"""Render a chamber's seats as a PNG map for the board email.

Email clients strip SVG and run no JavaScript, so the email needs a raster. The
GeoJSON is display-ready — the continental states sit at their true lon/lat, and
Alaska, Hawaii and the District of Columbia are pre-positioned in insets inside the
"Inset Box" feature — so a linear mapping with a latitude aspect correction is
enough and no projection library is needed.

Pillow rather than matplotlib: polygons plus a supersample give clean edges for a few
megabytes of image instead of tens.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
GEOJSON_PATH = ROOT / "docs" / "assets" / "us-states.geojson"

# Cropped to the continental states plus the inset box that holds Alaska and Hawaii.
LON_MIN, LON_MAX = -128.3, -66.9
LAT_MIN, LAT_MAX = 24.3, 47.5
# The x axis is scaled by cos(latitude) so the map is not stretched horizontally.
ASPECT_LATITUDE = 39.0

UNMONITORED_FILL = "#dad4cb"
NO_RACE_FILL = "#f2ede4"
# Visible against both the coloured and the uncoloured fills, so a state with no race
# in this chamber still reads as a state.
STATE_OUTLINE = "#e0d8cc"
SUPERSAMPLE = 4

# Puerto Rico sits at its true position, below the continental frame, so it cannot be
# drawn here; callers that include it should say so.
UNMAPPED = ("Puerto Rico",)

# Postal codes for the states the map can draw, so a caller may pass either form.
_POSTAL_BY_NAME = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def _name_for_postal(value: Any) -> str:
    """The GeoJSON's display name for a postal code such as ``US-TX``."""
    postal = str(value or "").strip().upper()
    if not postal:
        return ""
    if not postal.startswith("US-"):
        return ""
    code = postal[3:]
    for name in _rings_by_state():
        if _POSTAL_BY_NAME.get(name) == code:
            return name
    return ""


def _rings_by_state() -> dict[str, list[list[tuple[float, float]]]]:
    """Outer rings per state name, skipping the inset box itself and the frame."""
    payload = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    shapes: dict[str, list[list[tuple[float, float]]]] = {}
    for feature in payload["features"]:
        name = str((feature.get("properties") or {}).get("name") or "")
        if not name or name == "Inset Box":
            continue
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        # Only the outer ring of each polygon: a hole would need a compositing pass and
        # none of these states is drawn with one at this size.
        shapes[name] = [
            [(float(point[0]), float(point[1])) for point in polygon[0]]
            for polygon in polygons
            if polygon
        ]
    return shapes


def _project(width: int, height: int):
    """lon/lat -> pixel, fitting the frame to the canvas without distortion."""
    import math

    x_scale = math.cos(math.radians(ASPECT_LATITUDE))
    span_x = (LON_MAX - LON_MIN) * x_scale
    span_y = LAT_MAX - LAT_MIN

    def point(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - LON_MIN) * x_scale / span_x * width
        y = (LAT_MAX - lat) / span_y * height
        return x, y

    return point


def map_path(chamber: str, run_date: str) -> str:
    """The path the email links to, relative to the site's ``/data`` root.

    The board app fetches ``../data/board/...``, so anything written under the board
    data directory ships with the site and needs no other host.
    """
    return f"board/maps/{chamber}-{run_date}.png"


def _fill_for(race: dict[str, Any], colors: dict[str, str]) -> str:
    """A band colour when the race has monitored coverage, grey when it does not.

    The rating renormalizes missing inputs to a neutral score, so an unmonitored seat
    must never be painted as a band.
    """
    if not race.get("has_signal"):
        return UNMONITORED_FILL
    return colors.get(str(race.get("rating_band") or ""), UNMONITORED_FILL)


# Census regions, so a House grid carries some geography rather than alphabetical
# order. Within a region states are alphabetical; districts are numeric.
_REGION_STATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Northeast", ("CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA")),
    ("Midwest", ("IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD")),
    (
        "South",
        (
            "DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS",
            "TN", "AR", "LA", "OK", "TX",
        ),
    ),
    ("West", ("AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA")),
)
_HOUSE_ORDER = {
    postal: index
    for index, (_region, postals) in enumerate(_REGION_STATES)
    for postal in postals
}


def render_house_grid(
    races: Iterable[dict[str, Any]],
    *,
    colors: dict[str, str],
    width: int = 600,
    tile: int = 14,
    gap: int = 2,
    state_gap: int = 9,
) -> bytes:
    """One square per House district, grouped by state in census-region order.

    A 435-district choropleth needs licensed 2026 boundaries; a grid needs none. At
    this size it shows the colour distribution and where tossups cluster rather than
    pretending to be a geographic map, which is why the email labels it.
    """
    rows: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for race in races:
        postal = str(race.get("state") or "").removeprefix("US-")
        if not postal:
            continue
        rows.setdefault((_HOUSE_ORDER.get(postal, len(_HOUSE_ORDER)), 0), []).append(race)
    for key in rows:
        rows[key].sort(key=lambda item: int(item.get("district") or 0))

    step = tile + gap
    placed: list[tuple[int, int, str]] = []
    x = 0
    y = 0
    for key in sorted(rows):
        for race in rows[key]:
            if x + tile > width:
                x = 0
                y += step
            placed.append((x, y, _fill_for(race, colors)))
            x += step
        x += state_gap
        if x + tile > width:
            x = 0
            y += step
    height = y + tile

    image = Image.new("RGB", (width * SUPERSAMPLE, height * SUPERSAMPLE), NO_RACE_FILL)
    draw = ImageDraw.Draw(image)
    for x, y, fill in placed:
        draw.rectangle(
            [x * SUPERSAMPLE, y * SUPERSAMPLE, (x + tile) * SUPERSAMPLE - 1, (y + tile) * SUPERSAMPLE - 1],
            fill=fill,
        )
    image = image.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def canvas_size(width: int = 600) -> tuple[int, int]:
    """The canvas for a given width, so the frame is never distorted."""
    import math

    span_x = (LON_MAX - LON_MIN) * math.cos(math.radians(ASPECT_LATITUDE))
    span_y = LAT_MAX - LAT_MIN
    return width, max(1, round(width * span_y / span_x))


def render_chamber_map(
    races: Iterable[dict[str, Any]],
    *,
    colors: dict[str, str],
    width: int = 600,
    unmapped: Iterable[str] = UNMAPPED,
) -> bytes:
    """A PNG of the states, filled by the band each race carries.

    A state with no race in this chamber is left as background; a race with no
    monitored coverage is filled with the unmonitored colour, never a band colour,
    because the rating renormalizes missing inputs to a neutral score.
    """
    height = canvas_size(width)[1]
    scale = SUPERSAMPLE
    image = Image.new("RGB", (width * scale, height * scale), NO_RACE_FILL)
    draw = ImageDraw.Draw(image)
    project = _project(width * scale, height * scale)

    # A state can appear once per chamber; the first race wins if it somehow appears
    # twice, and an unmonitored seat is never painted as a band. Rows may carry the
    # state as a display name or as a postal code, so both are accepted.
    fill_by_state: dict[str, str] = {}
    for race in races:
        name = str(race.get("state_name") or "") or _name_for_postal(race.get("state"))
        if not name or name in fill_by_state:
            continue
        if not race.get("has_signal"):
            fill_by_state[name] = UNMONITORED_FILL
        else:
            band = str(race.get("rating_band") or "")
            fill_by_state[name] = colors.get(band, UNMONITORED_FILL)

    skipped = set(unmapped)
    for name, rings in _rings_by_state().items():
        if name in skipped:
            continue
        fill = fill_by_state.get(name, NO_RACE_FILL)
        for ring in rings:
            draw.polygon([project(lon, lat) for lon, lat in ring], fill=fill, outline=STATE_OUTLINE)

    image = image.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
