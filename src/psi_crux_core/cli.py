"""
`psi-crux` CLI. FEAT-014/015/016, REQ-CLI-001/002, REQ-RET-002.
  doctor  — validate config + keys + API enablement + paths (JSON + human; non-zero on fail)
  init    — guided setup; detect gcloud and OFFER to auto-provision; print the MCP client config
  keyring — key-ring stats
  prune   — delete raw run artifacts older than --keep-days
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time

from .config import Config


def _has_gcloud() -> bool:
    if not shutil.which("gcloud"):
        return False
    try:
        out = subprocess.run(["gcloud", "auth", "list", "--format=value(account)"],
                             capture_output=True, text=True, timeout=10)
        return bool(out.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return False


def _check_key(key: str, timeout: float = 15.0) -> tuple[bool, str]:
    """Lightweight CrUX ping. 200/404 = key+API OK; 403 = API not enabled / bad key."""
    import httpx
    try:
        r = httpx.post("https://chromeuxreport.googleapis.com/v1/records:queryRecord",
                       params={"key": key}, json={"origin": "https://www.google.com"}, timeout=timeout)
        if r.status_code in (200, 404):
            return True, "key valid, CrUX API enabled"
        if r.status_code == 403:
            return False, "403 — API not enabled on the key's project, or key invalid"
        return False, f"unexpected status {r.status_code}"
    except httpx.HTTPError as e:
        return False, f"network error: {e}"


def cmd_doctor(_args) -> int:
    cfg = Config.resolve()
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": ok, "detail": detail})

    keys = cfg.psi_api_keys or cfg.crux_api_keys
    add("keys_configured", bool(keys), f"{len(keys)} key(s)" if keys else "set PSI_API_KEYS / CRUX_API_KEYS")
    if keys:
        ok, detail = _check_key(keys[0].split(":", 1)[0])
        add("api_enablement", ok, detail)
    art = cfg.artifact_root
    try:
        art.mkdir(parents=True, exist_ok=True)
        (art / ".probe").write_text("ok")
        (art / ".probe").unlink()
        add("artifact_writable", True, str(art))
    except OSError as e:
        add("artifact_writable", False, str(e))

    ok_all = all(c["ok"] for c in checks)
    print(json.dumps({"ok": ok_all, "checks": checks}, indent=2))
    print("\n" + ("✅ all checks passed" if ok_all else "❌ some checks failed — see above"),
          file=sys.stderr)
    return 0 if ok_all else 1


def cmd_init(_args) -> int:
    print("psi-crux init — setup helper\n")
    if _has_gcloud():
        print("✔ gcloud detected + authenticated. I can auto-provision (enable the PageSpeed")
        print("  Insights + Chrome UX Report APIs and mint a restricted key) on your active project:\n")
        print("    gcloud services enable pagespeedonline.googleapis.com chromeuxreport.googleapis.com")
        print("    gcloud services api-keys create --display-name=psi-crux-mcp \\")
        print("      --api-target=service=pagespeedonline.googleapis.com \\")
        print("      --api-target=service=chromeuxreport.googleapis.com\n")
        print("  Run those (they touch your GCP project), then set PSI_API_KEYS=<key>.")
    else:
        print("gcloud not detected. Manual setup:")
        print("  1. https://console.cloud.google.com → create/pick a project")
        print("  2. APIs & Services → Library → enable 'PageSpeed Insights API' + 'Chrome UX Report API'")
        print("  3. Credentials → Create Credentials → API key → copy it")
        print("  4. export PSI_API_KEYS=<key>   (or key:project_id, comma-separated for a ring)\n")
    print("MCP client config (paste into Claude/Cursor):")
    print(json.dumps({"mcpServers": {"psi-crux": {
        "command": "uvx", "args": ["psi-crux-mcp"],
        "env": {"PSI_API_KEYS": "your-key"}}}}, indent=2))
    return 0


def cmd_keyring(_args) -> int:
    cfg = Config.resolve()
    from .keyring import Keyring
    keys = cfg.psi_api_keys or cfg.crux_api_keys
    if not keys:
        print("no keys configured", file=sys.stderr)
        return 1
    print(json.dumps(Keyring.from_pairs(keys).stats(), indent=2))
    return 0


def cmd_prune(args) -> int:
    cfg = Config.resolve()
    runs = cfg.artifact_root / "runs"
    if not runs.is_dir():
        print("nothing to prune")
        return 0
    cutoff = time.time() - args.keep_days * 86400
    removed = 0
    for d in runs.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
            removed += 1
    print(f"pruned {removed} run(s) older than {args.keep_days}d")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="psi-crux")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("keyring").set_defaults(func=cmd_keyring)
    pr = sub.add_parser("prune")
    pr.add_argument("--keep-days", type=int, default=1)
    pr.set_defaults(func=cmd_prune)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
