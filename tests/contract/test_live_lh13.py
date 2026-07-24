"""
Live contract test (REQ-COMPAT-008). Run weekly by .github/workflows/compat-drift.yml.
Fetches a LIVE PSI response and checks that every insight audit Google returns is known to our
registry. A new/renamed audit ID → the test fails → the workflow opens a drift issue.
Skipped automatically when no key is configured (so `pytest` in normal CI is unaffected).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

_KEY = os.getenv("PSI_API_KEYS", "").split(",")[0].strip()


@pytest.mark.skipif(not _KEY, reason="no PSI_API_KEYS — live contract test skipped")
def test_live_insight_ids_all_known_to_registry():
    from psi_crux_core.compat.registry import CompatRegistry
    from psi_crux_core.keyring import Keyring
    from psi_crux_core.psi_client import PsiClient

    reg = CompatRegistry.load()
    client = PsiClient(Keyring.from_pairs([_KEY]))
    payload = client.run_pagespeed("https://www.wikipedia.org", "mobile")
    audits = (payload.get("lighthouseResult") or {}).get("audits", {})
    insight_ids = [a for a in audits if a.endswith("-insight")]
    assert insight_ids, "no insight audits in the live response — schema shift?"

    unknown = [a for a in insight_ids if not reg.resolve(a).known]
    assert not unknown, (
        f"DRIFT: live PSI returned insight IDs not in registry {reg.version}: {unknown}. "
        "Update reference/fixtures/lh13-insight-registry.seed.json + registry.json (CalVer bump)."
    )
