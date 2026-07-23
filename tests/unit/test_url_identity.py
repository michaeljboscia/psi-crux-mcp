"""URL identity — history-safe canonicalization. REQ-URL-001."""
from psi_crux_core.url_identity import UrlIdentity, canonicalize


def test_surface_forms_collapse_to_one_canonical():
    a = canonicalize("https://example.com")
    b = canonicalize("https://example.com/")
    c = canonicalize("https://example.com/index.html")
    d = canonicalize("https://example.com/?utm_source=x&utm_campaign=y")
    e = canonicalize("https://EXAMPLE.COM")   # host case-insensitive (scheme preserved, not forced)
    assert a == b == c == d == e, f"{a} {b} {c} {d} {e}"


def test_content_params_preserved():
    assert canonicalize("https://example.com/p?id=42") != canonicalize("https://example.com/p")
    assert "id=42" in canonicalize("https://example.com/p?id=42")


def test_scheme_defaulted():
    assert canonicalize("example.com").startswith("https://")


def test_identity_fields():
    idn = UrlIdentity.of("https://example.com/?utm_source=x", final_url="https://example.com/home")
    assert idn.storage_key_url == idn.canonical_url == "https://example.com"
    assert idn.final_url == "https://example.com/home"
