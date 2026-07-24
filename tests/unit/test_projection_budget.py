"""Projection byte budget + www storage-key folding. Harvest G4, G7."""
import json

from psi_crux_core.parsers.insights import InsightParseResult, InsightRow
from psi_crux_core.parsers.summary import PsiScan, project
from psi_crux_core.projection import MAX_RESULT_BYTES
from psi_crux_core.url_identity import canonicalize


def _scan(network_rows):
    return PsiScan(
        core={"performance_score": 50, "lcp": 3000.0, "cls": 0.2, "tbt": 400.0,
              "lighthouse_version": "13.4.0"},
        insights=InsightParseResult(rows=[
            InsightRow(f"key_{i}", f"audit-{i}-insight", "table", 0.5, float(i), 3, "ok", True)
            for i in range(40)
        ], compat_warnings=[]),
        network_rows=network_rows, bp_rows=[], resource_rows=[],
    )


def test_small_payload_is_not_truncated():
    _, data = project(_scan([]), "https://example.com", "run1")
    assert "projection" not in data


def test_oversized_payload_is_capped_under_budget():
    """G7: MAX_RESULT_BYTES was declared but never enforced; a fat details blob could blow it."""
    fat = [{"url": "https://example.com/" + "x" * 2000, "resource_type": "Script",
            "mime_type": "text/javascript", "transfer_size": i, "status_code": 200}
           for i in range(400)]
    _, data = project(_scan(fat), "https://example.com", "run2")
    assert len(json.dumps(data, default=str).encode()) <= MAX_RESULT_BYTES


def test_truncation_is_announced_never_silent():
    """A shrunk result that looks complete is the failure this whole pass exists to remove."""
    fat = [{"url": "https://example.com/" + "x" * 2000, "resource_type": "Script",
            "mime_type": "text/javascript", "transfer_size": i, "status_code": 200}
           for i in range(400)]
    _, data = project(_scan(fat), "https://example.com", "run3")
    assert data["projection"]["truncated"] is True
    assert "run3" in data["projection"]["note"]


def test_total_count_survives_truncation():
    """The capped list shrinks; total_count must still report the TRUE size."""
    fat = [{"url": "https://example.com/" + "x" * 2000, "resource_type": "Script",
            "mime_type": "text/javascript", "transfer_size": i, "status_code": 200}
           for i in range(400)]
    _, data = project(_scan(fat), "https://example.com", "run4")
    assert data["network"]["total_count"] == 400
    assert len(data["network"]["items"]) < 400


# --- G4: www folding ------------------------------------------------------------------------

def test_www_and_bare_share_one_storage_key():
    assert canonicalize("https://www.example.com") == canonicalize("https://example.com")


def test_www_folding_is_anchored_not_a_substring_replace():
    """A bare .replace('www.','') corrupted `notwww.com` and cost GTM ~18% of a backfill."""
    assert "notwww.com" in canonicalize("https://notwww.com/page")
    assert canonicalize("https://cdn.www.example.com") == "https://cdn.www.example.com"


def test_www_folding_preserves_path_and_content_params():
    assert canonicalize("https://www.example.com/a/b?id=7") == "https://example.com/a/b?id=7"
