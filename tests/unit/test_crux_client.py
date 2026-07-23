"""
CI crux_client test with respx (no live key). The strong reality test the walking skeleton owed:
asserts the outbound request, keyring use, 404 no-data, and 429 cooldown — all mocked.
"""
import httpx
import respx

from psi_crux_core.crux_client import CRUX_QUERY_RECORD, CruxClient
from psi_crux_core.keyring import Keyring


def _client():
    return CruxClient(Keyring.from_pairs(["testkey:proj"]), timeout_s=5.0)


@respx.mock
def test_query_record_hits_endpoint_with_key_and_body():
    route = respx.post(CRUX_QUERY_RECORD).mock(
        return_value=httpx.Response(200, json={"record": {"metrics": {}}}))
    _client().query_record("https://example.com", "PHONE")
    req = route.calls.last.request
    assert req.url.params["key"] == "testkey"          # leased key used, not project id
    import json
    body = json.loads(req.content)
    assert body == {"origin": "https://example.com", "formFactor": "PHONE"}   # origin, not url


@respx.mock
def test_404_is_no_data_not_error():
    respx.post(CRUX_QUERY_RECORD).mock(return_value=httpx.Response(404))
    assert _client().query_record("https://no-traffic.invalid") is None


@respx.mock
def test_429_marks_cooldown():
    respx.post(CRUX_QUERY_RECORD).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}, json={}))
    kr = Keyring.from_pairs(["testkey:proj"])
    c = CruxClient(kr, timeout_s=5.0)
    try:
        c.query_record("https://example.com")
    except httpx.HTTPStatusError:
        pass
    assert kr.stats()[0]["total_429s"] == 1            # cooldown recorded from the 429
