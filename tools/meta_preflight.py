"""Preflight checks for public Meta review URLs and app icon.

Local:
    python tools/meta_preflight.py
After a real deploy:
    python tools/meta_preflight.py --url https://YOUR-APP.onrender.com

Does not require or send application credentials.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
PAGES = {
    "/meta": "meta-meta.html",
    "/privacy": "meta-privacy.html",
    "/terms": "meta-terms.html",
    "/data-deletion": "meta-data-deletion.html",
}
ICON = ROOT / "app" / "static" / "ai-writer-icon.png"
EMAIL = b"jefrocrypto@gmail.com"


def local_check() -> bool:
    ok = True
    for url, filename in PAGES.items():
        path = ROOT / "app" / "static" / filename
        exists = path.is_file()
        if exists:
            data = path.read_bytes()
            exists = EMAIL in data and b'lang="en"' in data and b'lang="ru"' in data
        print(("OK" if exists else "FAIL") + f" local {url}")
        ok &= exists
    try:
        png = ICON.read_bytes()
        valid = png[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", png[16:24]) if valid else (0, 0)
        icon_ok = valid and (w, h) == (1024, 1024) and len(png) <= 5_000_000
    except (OSError, ValueError, struct.error):
        icon_ok = False
    print(("OK" if icon_ok else "FAIL") + " icon 1024x1024 PNG <= 5 MB")
    return bool(ok and icon_ok)


def remote_check(origin: str) -> bool:
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise SystemExit("Use HTTPS origin only, e.g. https://your-app.onrender.com")
    base = f"https://{parsed.netloc}"
    paths = list(PAGES) + ["/static/ai-writer-icon.png", "/healthz"]
    ok = True
    for path in paths:
        try:
            req = Request(base + path, headers={"User-Agent": "AIWriter-Meta-Preflight/1.0"})
            with urlopen(req, timeout=85) as res:
                status = res.status
                # Check content to avoid treating a proxy login page as policy.
                data = res.read(3_000_000)
                if path == "/healthz":
                    good = status == 200 and b'"ok"' in data
                elif path.endswith(".png"):
                    good = status == 200 and data.startswith(b"\x89PNG\r\n\x1a\n")
                else:
                    good = status == 200 and EMAIL in data and b'<html' in data
                print(("OK" if good else "FAIL") + f" remote {path} (HTTP {status})")
                ok &= good
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"FAIL remote {path}: {str(exc)[:160]}")
            ok = False
    if ok:
        print("\nPaste the following into Meta App settings:")
        for label, path in [("Privacy Policy", "/privacy"), ("Terms", "/terms"), ("Data Deletion Instructions", "/data-deletion"), ("OAuth Redirect URI", "/auth/threads/callback")]:
            print(f"  {label}: {base}{path}")
    return bool(ok)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check AI Writer's Meta App Review readiness.")
    parser.add_argument("--url", help="Deployed HTTPS origin (optional)")
    args = parser.parse_args()
    local_ok = local_check()
    remote_ok = remote_check(args.url) if args.url else True
    raise SystemExit(0 if local_ok and remote_ok else 1)


if __name__ == "__main__":
    main()
