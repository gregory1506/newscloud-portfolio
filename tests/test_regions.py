"""
Unit tests for the canonical U.S. region scope module.

Validates the exact scope contract required by the party-lane product:
  - exactly 50 ranked states
  - D.C. collected but excluded from rankings
  - TT and UK do not affect U.S. readiness
  - ordering is deterministic
  - display-name and slug coverage is complete

Run with: pytest tests/test_regions.py -m unit -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import regions

pytestmark = pytest.mark.unit


class TestRankedStates:
    def test_exactly_50_ranked_states(self):
        assert len(regions.US_RANKED_STATES) == 50

    def test_dc_not_in_ranked_states(self):
        assert regions.DC not in regions.US_RANKED_STATES

    def test_tt_not_in_ranked_states(self):
        assert "TT" not in regions.US_RANKED_STATES

    def test_uk_not_in_ranked_states(self):
        assert "UK" not in regions.US_RANKED_STATES

    def test_ranked_states_are_sorted_alphabetically(self):
        assert list(regions.US_RANKED_STATES) == sorted(regions.US_RANKED_STATES)

    def test_ranked_states_have_us_prefix(self):
        for code in regions.US_RANKED_STATES:
            assert code.startswith("US-"), f"{code!r} missing US- prefix"

    def test_no_duplicate_ranked_states(self):
        assert len(regions.US_RANKED_STATES) == len(set(regions.US_RANKED_STATES))

    def test_get_ranked_states_returns_list(self):
        result = regions.get_ranked_states()
        assert isinstance(result, list)
        assert len(result) == 50

    def test_get_ranked_states_with_limit(self):
        result = regions.get_ranked_states(limit=5)
        assert result == ["US-AK", "US-AL", "US-AR", "US-AZ", "US-CA"]

    def test_get_ranked_states_limit_zero(self):
        assert regions.get_ranked_states(limit=0) == []

    def test_get_ranked_states_limit_exceeds_count(self):
        assert len(regions.get_ranked_states(limit=100)) == 50

    def test_get_ranked_states_is_deterministic(self):
        assert regions.get_ranked_states() == regions.get_ranked_states()


class TestUsCollectionJurisdictions:
    def test_exactly_51_us_collection_jurisdictions(self):
        assert len(regions.US_COLLECTION_JURISDICTIONS) == 51

    def test_dc_included_in_collection(self):
        assert regions.DC in regions.US_COLLECTION_JURISDICTIONS

    def test_all_ranked_states_in_collection(self):
        collection_set = set(regions.US_COLLECTION_JURISDICTIONS)
        for state in regions.US_RANKED_STATES:
            assert state in collection_set

    def test_tt_not_in_collection(self):
        assert "TT" not in regions.US_COLLECTION_JURISDICTIONS

    def test_uk_not_in_collection(self):
        assert "UK" not in regions.US_COLLECTION_JURISDICTIONS


class TestAllRegions:
    def test_all_regions_has_53_entries(self):
        assert len(regions.ALL_REGIONS) == 53

    def test_all_regions_contains_tt_and_uk(self):
        assert "TT" in regions.ALL_REGIONS
        assert "UK" in regions.ALL_REGIONS

    def test_all_regions_no_duplicates(self):
        assert len(regions.ALL_REGIONS) == len(set(regions.ALL_REGIONS))


class TestPredicates:
    def test_is_ranked_state_true_for_state(self):
        assert regions.is_ranked_state("US-PA")

    def test_is_ranked_state_false_for_dc(self):
        assert not regions.is_ranked_state(regions.DC)

    def test_is_ranked_state_false_for_tt(self):
        assert not regions.is_ranked_state("TT")

    def test_is_ranked_state_false_for_uk(self):
        assert not regions.is_ranked_state("UK")

    def test_is_us_jurisdiction_true_for_state(self):
        assert regions.is_us_jurisdiction("US-GA")

    def test_is_us_jurisdiction_true_for_dc(self):
        assert regions.is_us_jurisdiction(regions.DC)

    def test_is_us_jurisdiction_false_for_tt(self):
        assert not regions.is_us_jurisdiction("TT")

    def test_is_us_jurisdiction_false_for_uk(self):
        assert not regions.is_us_jurisdiction("UK")

    def test_is_non_us_true_for_tt(self):
        assert regions.is_non_us("TT")

    def test_is_non_us_true_for_uk(self):
        assert regions.is_non_us("UK")

    def test_is_non_us_false_for_state(self):
        assert not regions.is_non_us("US-TX")

    def test_is_non_us_false_for_dc(self):
        assert not regions.is_non_us(regions.DC)


class TestUsReadiness:
    def _all_51(self) -> set[str]:
        return set(regions.US_COLLECTION_JURISDICTIONS)

    def test_ready_when_all_51_complete(self):
        assert regions.is_us_ready(self._all_51())

    def test_ready_when_tt_and_uk_also_complete(self):
        completed = self._all_51() | {"TT", "UK"}
        assert regions.is_us_ready(completed)

    def test_not_ready_when_one_state_missing(self):
        completed = self._all_51() - {"US-WI"}
        assert not regions.is_us_ready(completed)

    def test_not_ready_when_dc_missing(self):
        completed = self._all_51() - {regions.DC}
        assert not regions.is_us_ready(completed)

    def test_tt_failure_does_not_block_readiness(self):
        # TT failing must not prevent party synthesis from proceeding.
        completed = self._all_51()  # TT absent
        assert regions.is_us_ready(completed)

    def test_uk_failure_does_not_block_readiness(self):
        completed = self._all_51()  # UK absent
        assert regions.is_us_ready(completed)

    def test_empty_set_is_not_ready(self):
        assert not regions.is_us_ready(set())


class TestDisplayNamesAndSlugs:
    def test_display_name_coverage_includes_all_50_states(self):
        for code in regions.US_RANKED_STATES:
            assert code in regions.STATE_DISPLAY_NAMES, f"Missing display name for {code}"

    def test_display_name_coverage_includes_dc(self):
        assert regions.DC in regions.STATE_DISPLAY_NAMES

    def test_slug_coverage_includes_all_50_states(self):
        for code in regions.US_RANKED_STATES:
            assert code in regions.STATE_SLUGS, f"Missing slug for {code}"

    def test_slug_coverage_includes_dc(self):
        assert regions.DC in regions.STATE_SLUGS

    def test_slugs_are_url_safe(self):
        import re
        for code, slug in regions.STATE_SLUGS.items():
            assert re.fullmatch(r"[a-z0-9-]+", slug), f"Unsafe slug for {code}: {slug!r}"

    def test_display_names_are_nonempty_strings(self):
        for code, name in regions.STATE_DISPLAY_NAMES.items():
            assert isinstance(name, str) and name, f"Empty display name for {code}"
