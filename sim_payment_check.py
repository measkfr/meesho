"""Simulation harness: verify the UNIVERSAL PAYMENT CHECK logic against the real
Meesho HAR responses, bit by bit. Doesn't hit the network — injects HAR payloads
into the classifier to prove each state is decided correctly."""
import asyncio
import sys
sys.path.insert(0, ".")
import app

PASS = 0
FAIL = 0
CASES = []


def check(name, got, want):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    CASES.append((ok, name, got, want))


def run_v3_cases():
    # HAR #243-246 real responses through the classifier
    check("v3 SUCCESS -> confirmed",
          app._v3_state("SUCCESS"), "confirmed")
    check("v3 PENDING -> pending",
          app._v3_state("PENDING"), "pending")
    check("v3 FAILURE -> failed",
          app._v3_state("FAILURE"), "failed")
    check("v3 EXPIRED -> failed",
          app._v3_state("EXPIRED"), "failed")
    check("v3 empty -> pending",
          app._v3_state(""), "pending")
    check("v3 None -> pending",
          app._v3_state(None), "pending")
    check("v3 CHARGED -> confirmed",
          app._v3_state("CHARGED"), "confirmed")
    check("v3 CANCELLED -> failed",
          app._v3_state("CANCELLED"), "failed")
    check("v3 INITIATED -> pending",
          app._v3_state("INITIATED"), "pending")
    check("v3 lowercase success -> confirmed",
          app._v3_state("success"), "confirmed")
    check("v3 'ORDERED' -> pending (NOT paid!)",
          app._v3_state("ORDERED"), "pending")


def run_juspay_id_cases():
    # extract JUSPAY order_id (the /api/v3/payments/{id} identifier)
    order = {
        "txn": {"order_id": "NKJ6OZGFBWQFZFBGTZDQ", "client_auth_token": "tkn_x"},
    }
    check("extract juspay id from txn.order_id (long) -> id found",
          app._find_juspay_order_id(order), "NKJ6OZGFBWQFZFBGTZDQ")
    check("extract from txn str (JSON)",
          app._find_juspay_order_id({"txn": '{"order_id": "AB123"}', "order_num": "1"}),
          "AB123")
    check("no juspay id -> empty",
          app._find_juspay_order_id({"txn": {}, "order_num": "1"}), "")


def run_pending_word_classification():
    # _PENDING_WORDS from _real_order_state: "ordered" must be pending, never paid
    check("preorders status 'ordered' is pending",
          "ordered" in app._PENDING_WORDS, True)
    check("preorders status 'pending' is pending",
          "pending" in app._PENDING_WORDS, True)
    check("'paid' is in _PAID_WORDS",
          "paid" in app._PAID_WORDS, True)
    check("'confirmed' is in _PAID_WORDS",
          "confirmed" in app._PAID_WORDS, True)
    check("'order_num alone is NOT a paid flag",
          app._dict_has_paid_flag({"order_num": "325549816238346112"}), False)
    check("explicit paid flag detected",
          app._dict_has_paid_flag({"payment_status": "paid"}), True)


async def run_live_simulation():
    """Feed the exact HAR v3 bodies through _v3_payment_status by monkeypatching
    the HTTP call, proving the end-to-end classifier path."""
    har_responses = {
        "NKJ6RMQ67LPQLWZREV5Q": {"success": True, "status": "SUCCESS"},
        "NKJ6OZGFBWQFZFBGTZDQ": {"success": True, "status": "PENDING"},
        "DEAD": {"success": True, "status": "FAILURE"},
    }
    orig = app.meesho_request
    orig_headers = app._active_headers
    app._active_headers = lambda: {"authorization": "sim"}

    class FakeResp:
        def __init__(self, d):
            self._d = d
            self.status_code = 200

        def json(self):
            return self._d

    async def fake_meesho_request(method, url, **kw):
        jid = url.split("/payments/")[1].split("/")[0]
        d = har_responses.get(jid, {"success": True, "status": "PENDING"})
        return FakeResp(d)

    app.meesho_request = fake_meesho_request
    try:
        created = await app._v3_payment_status("NKJ6OZGFBWQFZFBGTZDQ")
        check("live v3 PENDING via fake HTTP", app._v3_state(created.get("status")), "pending")
        created2 = await app._v3_payment_status("NKJ6RMQ67LPQLWZREV5Q")
        check("live v3 SUCCESS via fake HTTP", app._v3_state(created2.get("status")), "confirmed")
        created3 = await app._v3_payment_status("DEAD")
        check("live v3 FAILURE (merchant dead) via fake HTTP",
              app._v3_state(created3.get("status")), "failed")
    finally:
        app.meesho_request = orig
        app._active_headers = orig_headers


async def run_universal_simulation():
    """Full _universal_payment_check end-to-end: stub the v3 endpoint AND
    _real_order_state so we can drive each HAR scenario (pending -> confirmed ->
    failed) and assert the final state."""
    orig = app._v3_payment_status
    orig_ros = app._real_order_state
    orig_headers = app._active_headers
    app._active_headers = lambda: {"authorization": "sim"}

    scenarios = {
        "QR_PENDING": "PENDING",
        "QR_PAID": "SUCCESS",
        "QR_DEAD": "FAILURE",
    }

    async def fake_v3(jid):
        st = scenarios.get(jid, "PENDING")
        return {"status": st, "success": True, "live": True, "raw": {"status": st}}

    app._v3_payment_status = fake_v3

    async def no_real_order_state(onum=None):
        return None

    app._real_order_state = no_real_order_state

    order = {
        "order_num": "325549816238346112", "payment_mode": "upi",
        "txn": {"order_id": ""},
    }
    try:
        # 1) QR created, unpaid -> PENDING
        order["juspay_order_id"] = "QR_PENDING"
        res = await app._universal_payment_check(order)
        check("universal: initial QR unpaid -> pending", res["state"], "pending")

        # 2) user scanned + paid -> SUCCESS
        order["juspay_order_id"] = "QR_PAID"
        res = await app._universal_payment_check(order)
        check("universal: scanned+paid -> confirmed", res["state"], "confirmed")

        # 3) merchant dead / payment failed -> FAILURE
        order["juspay_order_id"] = "QR_DEAD"
        res = await app._universal_payment_check(order)
        check("universal: merchant dead -> failed", res["state"], "failed")

        # 4) COD is placed without payment
        cod = {"order_num": "325551216941719168", "payment_mode": "cod"}
        res = await app._universal_payment_check(cod)
        check("universal: COD -> confirmed", res["state"], "confirmed")

        # 5) no juspay id + real_order_state returns pending -> pending
        async def pending_ros(onum=None):
            return {"state": "pending", "status": "ordered", "live": True}

        app._real_order_state = pending_ros
        empty = {"order_num": "X", "payment_mode": "upi", "txn": {}}
        res = await app._universal_payment_check(empty)
        check("universal: fallback real_order_state pending", res["state"], "pending")
    finally:
        app._v3_payment_status = orig
        app._real_order_state = orig_ros
        app._active_headers = orig_headers


run_v3_cases()
run_juspay_id_cases()
run_pending_word_classification()
asyncio.run(run_live_simulation())
asyncio.run(run_universal_simulation())

print(f"\n===== SIMULATION RESULT: {PASS} passed, {FAIL} failed =====")
for ok, name, got, want in CASES:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}")
    if not ok:
        print(f"         got={got!r} want={want!r}")
