#!/usr/bin/env python3
"""5-hour auto-cancel side-task for the Meesho bot.

Every cycle it reads state/db.json, finds orders the bot placed (auto_cancel flag)
that are still locally cancellable, and tells the running server
(POST /api/orders/cancel, which executes the REAL Meesho cancel) to cancel them.
Survives uvicorn restarts (separate process). Resumes remaining time on restart
via state/autocancel.status.json. Hard-exits after WINDOW_HOURS (default 5).
"""
import json, os, sys, time, urllib.request

BASE = "/data/data/com.termux/files/home/Meesho-bot-main"
STATE_DIR = os.path.join(BASE, "state")
DB_FILE = os.path.join(STATE_DIR, "db.json")
LOG_FILE = os.path.join(STATE_DIR, "autocancel.log")
STATUS_FILE = os.path.join(STATE_DIR, "autocancel.status.json")
SERVER = "http://127.0.0.1:5000"
WINDOW = int(float(os.environ.get("AUTOCANCEL_HOURS", "5")) * 3600)
INTERVAL = int(os.environ.get("AUTOCANCEL_INTERVAL", "90"))
BLOCKED = ("CANCEL", "RTO", "RETURN", "DELIVERED")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def save_status(d):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, STATUS_FILE)
    except Exception:
        pass


def saas_login():
    """Log into the SaaS layer (admin) so cancellations use the tenant session."""
    import urllib.request
    body = json.dumps({"username": os.environ.get("ADMIN_USER", "admin"),
                       "password": os.environ.get("ADMIN_PASS", "admin123")}).encode()
    req = urllib.request.Request(SERVER + "/api/auth/login", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read() or "{}")
        if d.get("ok") and d.get("token"):
            return str(d["token"])
    except Exception as e:
        log(f"saas login failed: {e}")
    return None


def cancellable(o):
    blob = (str(o.get("status_text") or "") + " " + str(o.get("status_id") or "")).upper()
    return not any(b in blob for b in BLOCKED)


def main():
    st = load_status() or {}
    now = time.time()
    start = float(st.get("start", now))
    deadline = float(st.get("deadline", start + WINDOW))
    if deadline <= now and st:
        # expired run — a new (re)start begins a fresh window
        start = now
        deadline = now + WINDOW
    elif deadline <= now:
        deadline = now + WINDOW
    log(f"auto-cancel worker started. window={WINDOW}s, start={int(start)}, deadline={int(deadline)} "
        f"(ends {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(deadline))})")

    token = saas_login()
    if token:
        log("saas login OK — cancellations will be tenant-scoped (X-Session).")

    done = set(st.get("done") or [])
    summary = {"cycles": st.get("cycles", 0), "cancelled": st.get("cancelled", 0),
               "failed": st.get("failed", 0), "pending_retry": st.get("pending_retry", 0)}

    while True:
        now = time.time()
        save_status({"start": start, "deadline": deadline, "done": sorted(done), **summary})
        if now >= deadline:
            log(f"DEADLINE reached. {summary['cycles']} cycles, "
                f"{summary['cancelled']} cancelled live, {summary['pending_retry']} still pending, "
                f"{summary['failed']} failures. Exiting.")
            save_status({"start": start, "deadline": deadline, "done": sorted(done), **summary,
                         "finished": True})
            return 0

        summary["cycles"] += 1
        cycle = f"cycle {summary['cycles']} ({(deadline - now) / 60:.0f} min left)"
        found = 0

        try:
            with open(DB_FILE) as f:
                db = json.load(f)
        except Exception as e:
            log(f"{cycle}: cannot read db.json: {e}")
            time.sleep(INTERVAL)
            continue

        for ns, stt in (db.get("devices") or {}).items():
            if not isinstance(stt, dict):
                continue
            for o in (stt.get("orders") or []):
                if not isinstance(o, dict):
                    continue
                onum = str(o.get("order_num") or "")
                if not onum or onum in done or not o.get("auto_cancel"):
                    continue
                if not cancellable(o):
                    continue
                found += 1
                sub = str(o.get("sub_order_num") or f"{onum}_1")
                did = str(o.get("device_id") or "").strip() or (ns.rsplit(":", 1)[-1] or "default")
                body = json.dumps({"order_num": onum, "sub_order_num": sub}).encode()
                hdr = {"Content-Type": "application/json", "X-Device-ID": did}
                if token:
                    hdr["X-Session"] = token
                req = urllib.request.Request(
                    SERVER + "/api/orders/cancel", data=body, headers=hdr, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=40) as r:
                        resp = json.loads(r.read() or "{}")
                except Exception as e:
                    summary["failed"] += 1
                    log(f"{cycle}: order {onum}: server unreachable/error: {e}")
                    continue
                if resp.get("ok") and resp.get("live"):
                    done.add(onum)
                    summary["cancelled"] += 1
                    log(f"{cycle}: CANCELLED LIVE order {onum} (device {did})")
                elif resp.get("ok"):
                    # local-only cancellation (already cancelled before) — count as done
                    done.add(onum)
                    log(f"{cycle}: order {onum}: cancelled locally by server (live:{resp.get('live')})")
                else:
                    summary["pending_retry"] += 1
                    log(f"{cycle}: order {onum}: NOT cancellable yet — {resp.get('message','')[:100]}")
        if found:
            save_status({"start": start, "deadline": deadline, "done": sorted(done), **summary})
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("auto-cancel worker interrupted.")
        sys.exit(130)