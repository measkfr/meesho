import asyncio, base64, json, os, time, uuid
import httpx
import meesho_api as M

API = "https://prod.meeshoapi.com/api"


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


async def inspect_fod(xo):
  dev = M.random_device()
  ua = (
      f"Dalvik/2.1.0 (Linux; U; Android {dev['os_version']}; {dev['model']}"
      " Build/) Cronet/137.0.7100.61"
  )
  async with httpx.AsyncClient(timeout=15) as c:
    r = await c.post(
        f"{M.MEESHO_API}/1.0/anonymous/fod-personalisation",
        headers=M._api_headers(
            uuid.uuid4().hex,
            xo,
            "anonymous",
            gaid=dev["gaid"],
            session_count=dev["session_count"],
            ua=ua,
        ),
        json=M._fod_body(dev),
    )
    if r.status_code == 200:
      raw = r.json()
      # Print full offer structure to check for hidden banners, min cart values, or conditions
      offer_data = raw.get("offer", raw)
      return offer_data
    return None


async def main():
  seen_offers = set()
  for i in range(15):
    b = fresh()
    xo = b.get("xoox", {}).get("xo", "")
    if not xo:
      continue
    mod = b.get("anonymous_user_id_mod_100")
    offer = await inspect_fod(xo)
    bucket = offer.get("bucket") if isinstance(offer, dict) else offer
    seen_offers.add(bucket)
    print(f"Sample {i+1} | mod={mod} | bucket={bucket}")
    time.sleep(1.5)

  print(f"\nUnique buckets observed in current rollout: {seen_offers}")


asyncio.run(main())
