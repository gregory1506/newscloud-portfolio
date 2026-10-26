"""FEC open API client — no API key required.

Returns party-level fundraising aggregates per state and election cycle.
Degrades gracefully on API errors: callers receive None rather than raising.

Burst-resilient: per-state calls are paced so a full 50-state daily run stays
under the API's per-minute limit, and HTTP 429 responses are retried with
bounded exponential backoff, respecting Retry-After when present.
"""

from __future__ import annotations

from shared.external_calls import track_external_call

import csv
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

_BASE = "https://api.open.fec.gov/v1"
_BULK_BASE = "https://www.fec.gov/files/bulk-downloads"
_TIMEOUT = 20

# Registered keys are still burst-limited; pace per-state calls so a 50-state
# run does not trip the limit partway through (observed as mid-run HTTP 429s).
_REQUEST_PACE_SECONDS = float(os.environ.get("FEC_REQUEST_PACE_SECONDS", "1.0"))
_MAX_429_RETRIES = 4
_RETRY_BACKOFF_BASE_SECONDS = 2.0

_DEM_PARTY_CODES = {"DEM", "D", "dem"}
_REP_PARTY_CODES = {"REP", "R", "rep"}


def _sleep_paced() -> None:
    time.sleep(_REQUEST_PACE_SECONDS)


def _get_with_retry(url: str) -> bytes:
    """GET with bounded retry on HTTP 429 and exponential backoff.

    Respects the Retry-After header when present. Any non-429 error or a 429
    that exhausts the retry budget propagates to the caller's graceful
    degradation handler.
    """
    for attempt in range(_MAX_429_RETRIES + 1):
        try:
            with track_external_call("fec", detail=url) as call:
                try:
                    with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
                        return resp.read()
                except urllib.error.HTTPError as exc:
                    if exc.code == 429:
                        call["status"] = "rate_limited"
                    raise
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= _MAX_429_RETRIES:
                raise
            headers = getattr(exc, "hdrs", None) or getattr(exc, "headers", None) or {}
            delay = _RETRY_BACKOFF_BASE_SECONDS * (2**attempt)
            try:
                delay = max(float(headers.get("Retry-After")), delay)
            except (TypeError, ValueError):
                pass
            print(f"FEC 429 for {url}; retry {attempt + 1}/{_MAX_429_RETRIES} in {delay:.1f}s")
            time.sleep(delay)


def get_state_party_fundraising(state: str, cycle: int) -> dict:
    """Return aggregated fundraising totals for Democrat and Republican committees in a state.

    state — two-letter postal abbreviation, e.g. "PA".
    cycle — four-digit election cycle year, e.g. 2026.

    Returns a dict with keys dem_fundraising, rep_fundraising, fec_coverage.
    All numeric values are None when the API is unavailable.
    """
    api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    params = {
        "state": state,
        "cycle": str(cycle),
        "sort": "-receipts",
        "per_page": "100",
        "api_key": api_key,
    }
    url = f"{_BASE}/totals/pac-party/?{urllib.parse.urlencode(params)}"
    _sleep_paced()
    try:
        raw = _get_with_retry(url)
        data = json.loads(raw.decode("utf-8"))
        results = data.get("results", [])
        dem = sum(
            float(r.get("receipts") or 0)
            for r in results
            if r.get("party") in _DEM_PARTY_CODES
        )
        rep = sum(
            float(r.get("receipts") or 0)
            for r in results
            if r.get("party") in _REP_PARTY_CODES
        )
        return {
            "dem_fundraising": dem,
            "rep_fundraising": rep,
            "fec_coverage": 1.0 if results else 0.0,
        }
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        print(f"FEC totals/{state}/{cycle}: {exc}")
        return {"dem_fundraising": None, "rep_fundraising": None, "fec_coverage": 0.0}


def _fec_get(path: str, params: dict) -> dict | None:
    """GET one FEC API page. Returns parsed JSON or None on failure."""
    params = dict(params)
    params["api_key"] = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    url = f"{_BASE}{path}?{urllib.parse.urlencode(params, doseq=True)}"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        print(f"FEC {path}: {exc}")
        return None


def get_candidates(state: str, cycle: int, office: str) -> list[dict] | None:
    """Return active candidates for a state, cycle, and office.

    ``office`` is an FEC office code: ``"H"`` (House) or ``"S"`` (Senate).
    Includes challengers and open-seat candidates, not just incumbents.
    Returns None when the API is unavailable so callers can degrade.
    """
    office = office.strip().upper()
    if office not in {"H", "S"}:
        raise ValueError(f"Unsupported FEC office: {office!r}")
    candidates: list[dict] = []
    page = 1
    while True:
        data = _fec_get(
            "/candidates/",
            {
                "state": state,
                "office": office,
                "cycle": str(cycle),
                "is_active_candidate": "true",
                "per_page": "100",
                "page": str(page),
            },
        )
        if data is None:
            return None
        for r in data.get("results", []):
            district = str(r.get("district") or "").zfill(2)
            candidates.append(
                {
                    "candidate_id": r.get("candidate_id", ""),
                    "name": r.get("name", ""),
                    "party": r.get("party", ""),
                    "office": office,
                    "district": f"{state}-{district}" if office == "H" else None,
                    "committee_names": [
                        str(c.get("name", "")).upper()
                        for c in (r.get("principal_committees") or [])
                        if c.get("name")
                    ],
                }
            )
        pagination = data.get("pagination", {})
        if page >= int(pagination.get("pages") or 1):
            return candidates
        page += 1


def get_house_candidates(state: str, cycle: int) -> list[dict] | None:
    """Return active House candidates for a state and cycle."""
    return get_candidates(state, cycle, "H")


def get_senate_candidates(state: str, cycle: int) -> list[dict] | None:
    """Return active Senate candidates for a state and cycle."""
    return get_candidates(state, cycle, "S")


def get_candidate_totals(candidate_id: str, cycle: int) -> dict:
    """Return a candidate's cycle financial totals.

    Uses the FEC ``/candidate/{id}/totals/`` endpoint (no key required for
    low-volume use). Returns the most recent cycle row with ``receipts``,
    ``disbursements``, ``cash_on_hand``, and ``fec_coverage``. Numeric values
    are None when the API is unavailable, so callers degrade rather than
    treating a failed lookup as zero dollars.
    """
    empty = {
        "candidate_id": candidate_id,
        "cycle": cycle,
        "receipts": None,
        "disbursements": None,
        "cash_on_hand": None,
        "fec_coverage": 0.0,
    }
    data = _fec_get(
        f"/candidate/{urllib.parse.quote(candidate_id)}/totals/",
        {"cycle": str(cycle), "per_page": "1", "page": "1"},
    )
    if data is None:
        return empty
    results = data.get("results") or []
    if not results:
        return empty
    row = results[0]

    def _number(key: str) -> float | None:
        value = row.get(key)
        return None if value is None else float(value)

    return {
        "candidate_id": candidate_id,
        "cycle": cycle,
        "receipts": _number("receipts"),
        "disbursements": _number("disbursements"),
        "cash_on_hand": _number("cash_on_hand_end_period"),
        "fec_coverage": 1.0,
    }


def _pipe_rows(payload: bytes, filename: str):
    """Yield pipe-delimited rows from one named file in an FEC bulk ZIP."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        with archive.open(filename) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
            yield from csv.reader(text, delimiter="|")


def parse_house_candidate_bulk(
    candidate_zip: bytes,
    committee_zip: bytes,
    cycle: int,
) -> dict[str, list[dict]]:
    """Join the FEC candidate and committee master files into a House roster.

    The candidate API does not return principal-committee names. The candidate
    master file supplies the principal committee ID (CAND_PCC), which is joined
    to the committee master file's CMTE_ID/CMTE_NM fields. Only current House
    candidates for the requested election year are retained.
    """
    committee_names = {
        row[0].strip(): row[1].strip().upper()
        for row in _pipe_rows(committee_zip, "cm.txt")
        if len(row) > 1 and row[0].strip() and row[1].strip()
    }
    roster: dict[str, list[dict]] = {}
    for row in _pipe_rows(candidate_zip, "cn.txt"):
        if len(row) < 10:
            continue
        candidate_id, name, party, election_year, state, office, district = (
            value.strip() for value in row[:7]
        )
        status = row[8].strip()
        principal_committee_id = row[9].strip()
        committee_name = committee_names.get(principal_committee_id)
        if (
            election_year != str(cycle)
            or office != "H"
            or status != "C"
            or not state
            or not candidate_id
            or not committee_name
        ):
            continue
        roster.setdefault(state, []).append({
            "candidate_id": candidate_id,
            "name": name,
            "party": party,
            "district": f"{state}-{district.zfill(2)}",
            "committee_names": [committee_name],
        })
    return {state: roster[state] for state in sorted(roster)}


def get_candidate_master_rows(cycle: int) -> list[list[str]] | None:
    """Return every field row of the FEC candidate master file (``cn<yy>.txt``).

    The API's candidate endpoints omit ``CAND_ICI`` (incumbent/challenger/open),
    which is what tells us whether a sitting member is on the ballot. Returns
    None on any fetch or archive error.
    """
    suffix = str(cycle)[-2:]
    url = f"{_BULK_BASE}/{cycle}/cn{suffix}.zip"
    try:
        payload = _get_with_retry(url)
        text = zipfile.ZipFile(io.BytesIO(payload)).read("cn.txt").decode("latin-1")
    except (
        urllib.error.URLError,
        zipfile.BadZipFile,
        KeyError,
        UnicodeError,
        ValueError,
    ) as exc:
        print(f"FEC bulk candidate master/{cycle}: {exc}")
        return None
    return [line.split("|") for line in text.splitlines()]


def get_house_candidate_roster(cycle: int) -> dict[str, list[dict]] | None:
    """Return the nationwide current House roster from two official bulk files.

    This replaces 50 rate-limited candidate API calls in the weekly digital-ad
    refresh with two small authoritative downloads. Returns None on any fetch
    or archive error so the caller can fail the refresh without claiming full
    digital coverage.
    """
    suffix = str(cycle)[-2:]
    candidate_url = f"{_BULK_BASE}/{cycle}/cn{suffix}.zip"
    committee_url = f"{_BULK_BASE}/{cycle}/cm{suffix}.zip"
    try:
        return parse_house_candidate_bulk(
            _get_with_retry(candidate_url),
            _get_with_retry(committee_url),
            cycle,
        )
    except (
        urllib.error.URLError,
        zipfile.BadZipFile,
        KeyError,
        UnicodeError,
        ValueError,
    ) as exc:
        print(f"FEC bulk House roster/{cycle}: {exc}")
        return None


def get_state_independent_expenditures(
    state: str, min_date: str, max_date: str, *, office: str = "H"
) -> dict[str, dict] | None:
    """Aggregate Schedule E independent expenditures per candidate.

    Outside money supporting or opposing named candidates, filed within
    24-48 hours. ``office`` is the FEC office code (``H`` House, ``S`` Senate);
    Schedule E covers both, so the same rolling window applies per chamber.
    One paginated query per state. Returns None on failure.
    """
    totals: dict[str, dict] = {}
    page = 1
    while True:
        data = _fec_get(
            "/schedules/schedule_e/",
            {
                "candidate_office_state": state,
                "candidate_office": office,
                "min_date": min_date,
                "max_date": max_date,
                "per_page": "100",
                "page": str(page),
            },
        )
        if data is None:
            return None
        for r in data.get("results", []):
            cid = r.get("candidate_id")
            if not cid:
                continue
            bucket = totals.setdefault(cid, {"support": 0.0, "oppose": 0.0})
            amount = float(r.get("expenditure_amount") or 0)
            if r.get("support_oppose_indicator") == "S":
                bucket["support"] += amount
            else:
                bucket["oppose"] += amount
        pagination = data.get("pagination", {})
        if page >= int(pagination.get("pages") or 1):
            return totals
        page += 1
