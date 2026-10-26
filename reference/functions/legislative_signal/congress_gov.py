"""Congress.gov v3 client for incremental legislative activity.

Congress.gov is used only for observable legislative activity, not as an
electoral, polling, or voter-sentiment signal. The client fetches bills changed
inside one UTC observation day and attributes introductions and substantive
actions published with up to three days of official metadata lag.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
import json
import urllib.error
import urllib.parse
import urllib.request

_BASE = "https://api.congress.gov/v3"
_TIMEOUT = 20
_PAGE_LIMIT = 250
_DETAIL_WORKERS = 8
_PUBLICATION_LAG_DAYS = 3

_SUBSTANTIVE_ACTION_TYPES = {"BecameLaw", "Committee", "Floor", "President", "Veto"}


def _get(path: str, api_key: str, params: dict | None = None) -> dict:
    query = {"api_key": api_key, "format": "json", **(params or {})}
    url = f"{_BASE}/{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": "newscloud/1.0"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _utc_window(run_date: str) -> tuple[str, str]:
    day = date.fromisoformat(run_date)
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    congress_format = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(congress_format), end.strftime(congress_format)


def _bill_path(bill: dict) -> str:
    return f"bill/{bill['congress']}/{str(bill['type']).lower()}/{bill['number']}"


def _iter_updated_bills(run_date: str, congress: int, api_key: str):
    start, end = _utc_window(run_date)
    offset = 0
    while True:
        data = _get(
            f"bill/{congress}",
            api_key,
            {
                "fromDateTime": start,
                "toDateTime": end,
                "sort": "updateDate+asc",
                "limit": str(_PAGE_LIMIT),
                "offset": str(offset),
            },
        )
        bills = data.get("bills", [])
        yield from bills
        total = int(data.get("pagination", {}).get("count", len(bills)))
        offset += len(bills)
        if not bills or offset >= total:
            break


def _same_day(value: str | None, run_date: str) -> bool:
    return bool(value and value[:10] == run_date)


def _within_publication_lag(value: str | None, observation_date: str) -> bool:
    if not value:
        return False
    event_day = date.fromisoformat(value[:10])
    observed_day = date.fromisoformat(observation_date)
    lag = (observed_day - event_day).days
    return 0 <= lag <= _PUBLICATION_LAG_DAYS


def _event_from_detail(detail: dict, actions: list[dict], observation_date: str) -> dict | None:
    bill = detail.get("bill", {})
    sponsors = bill.get("sponsors", [])
    if not sponsors:
        return None
    sponsor = sponsors[0]
    party = sponsor.get("party")
    state = sponsor.get("state")
    if party not in {"D", "R"} or not state:
        return None

    introduced = _within_publication_lag(
        bill.get("introducedDate"), observation_date
    )
    advanced = any(
        _within_publication_lag(action.get("actionDate"), observation_date)
        and action.get("type") in _SUBSTANTIVE_ACTION_TYPES
        for action in actions
    )
    if not introduced and not advanced:
        return None

    return {
        "bill_id": f"{bill.get('congress')}-{str(bill.get('type', '')).lower()}-{bill.get('number')}",
        "party": party,
        "state": state,
        "introduced": introduced,
        "advanced": advanced,
        "introduced_date": bill.get("introducedDate") if introduced else None,
        "latest_substantive_action_date": max(
            (
                action["actionDate"]
                for action in actions
                if _within_publication_lag(
                    action.get("actionDate"), observation_date
                )
                and action.get("type") in _SUBSTANTIVE_ACTION_TYPES
            ),
            default=None,
        ),
        "policy_area": (bill.get("policyArea") or {}).get("name"),
        "title": bill.get("title", ""),
    }


def _fetch_event(summary: dict, observation_date: str, api_key: str) -> dict | None:
    path = _bill_path(summary)
    detail = _get(path, api_key)
    latest_action = summary.get("latestAction") or {}
    actions = []
    if _within_publication_lag(
        latest_action.get("actionDate"), observation_date
    ):
        actions = _get(f"{path}/actions", api_key, {"limit": "250"}).get(
            "actions", []
        )
    return _event_from_detail(detail, actions, observation_date)


def get_daily_legislative_activity(
    run_date: str,
    congress: int,
    api_key: str | None,
) -> tuple[list[dict], bool]:
    """Return sponsor-attributed activity observed on one day and coverage.

    The boolean is true only when the Congress.gov query completed. An empty
    event list with true coverage means there was no attributable activity
    published in that observation window;
    false means the source was unavailable and must not be interpreted as zero.
    """
    if not api_key:
        return [], False
    try:
        summaries = list(_iter_updated_bills(run_date, congress, api_key))
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            fetched = executor.map(
                lambda summary: _fetch_event(summary, run_date, api_key), summaries
            )
            events = [event for event in fetched if event]
        return events, True
    except (urllib.error.URLError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"congress.gov legislative activity/{run_date}: {exc}")
        return [], False
