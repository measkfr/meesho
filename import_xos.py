"""Bulk-import real anonymous xo captures into the rotation pool.

Each line/element should be a Meesho anonymous `xo` header value (the long
`eyJ0eXBl...` string) captured from a fresh-install `fod-personalisation`
request BEFORE the user logs in. Every new identity = a new FOD bucket.

Usage:
    python3 import_xos.py <file-or-paste>...
      - file path(s): each line = one xo
      - OR paste values directly as args:  python3 import_xos.py 'eyJ0eXBl...' 'eyJ0eXBl...'

It also auto-scans `Meesho1/*.har` / `M/*.har` for any open-meesho-result
HARs and extracts every distinct anonymous xo from fod-personalisation calls.
New identities are saved to the pool dir; duplicates are skipped.
"""
import base64
import json
import os
import re
import sys

POOL_DIR = "/data/data/com.termux/files/home/.cache/opencode/tmp/xos"
os.makedirs(POOL_DIR, exist_ok=True)


def xo_user_id(xo: str):
    try:
        inner = json.loads(base64.urlsafe_b64decode(xo.split(".")[1] + "=" * (-len(xo.split(".")[1]) % 4)))
        jwt = inner.get("jwt", "")
        payload = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=" * (-len(jwt.split(".")[1]) % 4)))
        return str(payload.get("https://meesho.com/anonymous_user_id", ""))
    except Exception:
        return ""


def save(xo: str):
    uid = xo_user_id(xo) or "anon-unknown"
    # skip logged-in xos
    if uid == "c39c37ce" or (xo and "c39c37ce" in xo):
        print(f"  SKIP (logged-in identity): {uid[:8]}")
        return False
    if any(uid == xo_user_id(open(os.path.join(POOL_DIR, f)).read().strip())
           for f in os.listdir(POOL_DIR) if f.endswith(".txt")):
        print(f"  DUPLICATE (already in pool): {uid[:8]}")
        return False
    name = f"cap_{uid[:8]}_{len([f for f in os.listdir(POOL_DIR) if f.endswith('.txt')])+1}.txt"
    with open(os.path.join(POOL_DIR, name), "w") as fh:
        fh.write(xo.strip())
    print(f"  SAVED NEW identity {uid[:8]} -> {name}")
    return True


def from_har(path):
    try:
        data = json.load(open(path))
    except Exception as e:
        print(f"  (skip {path}: {e})")
        return
    found = set()
    for e in data.get("log", {}).get("entries", []):
        u = e.get("request", {}).get("url", "")
        if "fod-personalisation" in u:
            for h in e.get("request", {}).get("headers", []) or []:
                if h.get("name", "").lower() == "xo" and h.get("value"):
                    found.add(h["value"])
    print(f"  HAR {os.path.basename(path)}: {len(found)} xo(s)")
    for x in found:
        save(x)


def main():
    saved = 0
    items = sys.argv[1:]
    if not items:
        # scan HARs automatically
        for base in [os.path.expanduser("~/Meesho1"), os.path.expanduser("~/M")]:
            if os.path.isdir(base):
                for fn in os.listdir(base):
                    if fn.endswith(".har"):
                        print(f"Scanning {base}/{fn}")
                        from_har(os.path.join(base, fn))
        return
    for it in items:
        if os.path.isfile(it):
            print(f"File {it}:")
            for line in open(it).read().splitlines():
                line = line.strip()
                if line and line.startswith("eyJ0eXBl") and save(line):
                    saved += 1
        else:
            if it.startswith("eyJ0eXBl") and save(it):
                saved += 1
    print(f"\nDone. {saved} new identity(s) imported. The live rotation picks them up within a minute.")


if __name__ == "__main__":
    main()
