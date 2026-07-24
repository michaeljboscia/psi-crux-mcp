"""
URL identity model. FEAT-017, REQ-URL-001. Four fields so history never splinters and the
storage key is stable: input_url (as given) · canonical_url (scheme enforced, trailing slash
normalized, KNOWN tracking params stripped, content params PRESERVED, leading `www.` folded
— the DB key) · final_url (where PSI's redirects landed) · storage_key_url (= canonical_url).
Never fetches to resolve.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking params that never change page content — safe to strip so URLs collapse.
_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "_ga", "ref", "ref_src",
}
_INDEX_DOCS = re.compile(r"/(index|default)\.(html?|php|aspx?)$", re.I)
# ANCHORED — `^www.` only. A bare .replace("www.", "") would corrupt `notwww.com` and
# `cdn.www.example.com`; that footgun cost the old collector ~18% of a backfill (harvest #43).
_WWW_PREFIX = re.compile(r"^www\.", re.I)


def canonicalize(url: str) -> str:
    """
    Deterministic canonical form. Content params kept; tracking params dropped; leading
    `www.` folded so `www.example.com` and `example.com` share ONE storage key (G4).
    Folding is identity-only — the fetch path still probes whichever host actually answers.
    """
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    parts = urlsplit(u)
    scheme = parts.scheme.lower() or "https"
    netloc = _WWW_PREFIX.sub("", parts.netloc.lower())
    path = _INDEX_DOCS.sub("/", parts.path)
    if path in ("", "/"):
        path = ""                        # root collapses: example.com == example.com/ == /index.html
    elif path.endswith("/"):
        path = path.rstrip("/")
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING]
    query = urlencode(sorted(kept))
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass(frozen=True)
class UrlIdentity:
    input_url: str
    canonical_url: str
    final_url: str | None = None

    @property
    def storage_key_url(self) -> str:
        return self.canonical_url

    @classmethod
    def of(cls, input_url: str, final_url: str | None = None) -> "UrlIdentity":
        return cls(input_url=input_url, canonical_url=canonicalize(input_url), final_url=final_url)
