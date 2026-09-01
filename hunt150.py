import asyncio, base64, json, os, time, uuid
import httpx
import meesho_api as M

API = "https://prod.meeshoapi.com/api"
pool = "/data/data/com.termux/files/home/.cache/opencode/tmp/xos"

def dj(seg):
    return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))

def fresh(app_ver="28.9", ver_code="853"):
    h = {
        "app-gaid": str(uuid.uuid4()),
        "app-session-count": "1",
        "authorization": "32c4d8137cn9eb493a1921f203173080",
        "app-version": app_ver,
        "app-version-code": ver_code,
        "instance-id": str(uuid.uuid4()),
        "country-iso": "in",
        "application-id": "com.meesho.supply",
        "app-session-id": str(uuid.uuid4()),
        "app-sdk-version": "33",
        "app-client-id": "android",
        "xo": "",
        "meesho-user-context": "anonymous",
        "content-type": "application/json; charset=UTF-8",
        "user-agent": "okhttp/4.9.0",
    }
    with httpx.Client(timeout=15) as c:
        return c.get(f"{API}/1.0/anonymous/config", headers=h).json()

async def main():
    for i in range(30):
        try:
            b = fresh("28.9", "853")
            xo = b.get("xoox", {}).get("xo", "")
            if not xo or len(xo) < 100:
                continue
            mod = b.get("anonymous_user_id_mod_100")
            if mod is None:
                continue
            if not (90 <= mod <= 99):
                continue
            dev = M.random_device()
            ua = f"Dalvik/2.1.0 (Linux; U; Android {dev['os_version']}; {dev['model']} Build/) Cronet/137.0.7100.61"
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{M.MEESHO_API}/1.0/anonymous/fod-personalisation",
                    headers=M._api_headers(uuid.uuid4().hex, xo, "anonymous", gaid=dev["gaid"], session_count=dev["session_count"], ua=ua),
                    json=M._fod_body(dev),
                )
                if r.status_code == 200:
                    raw = r.json()
                    offer = raw.get("surgical_first_order_discount_v3", {}).get("offer", {})
                    bucket = offer.get("max_offer_value")
                    print(f"MOD 90-99: mod={mod} bucket={bucket} offer_text={offer.get('offer_text')}")
                    for k, v in offer.items():
                        print(f"  offer.{k} = {v}")
                    raw_str = json.dumps(raw)
                    for sk in ["minimum", "min_order", "min_order_value", "MOV", "price_threshold", "cond"]:
                        if sk in raw_str.lower():
                            for line in raw_str.split("\n"):
                                if sk in line.lower():
                                    print(f"  MIN LINE: {line[:200]}")
                    print(f"  raw top keys: {list(raw.keys())[:15]}")
                else:
                    print(f"mod={mod} status={r.status_code}")
        except Exception as e:
            print(f"err: {e}")
        await asyncio.sleep(2)

asyncio.run(main())