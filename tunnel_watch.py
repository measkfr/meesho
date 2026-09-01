import json
import os
import re
import subprocess
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE_DIR, "bot_config.json")
TUNNEL_LOG = os.path.join(BASE_DIR, "cloudflared.log")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
ENV_PATH = os.path.join(BASE_DIR, "current_tunnel_url")


def read_current_url():
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            u = f.read().strip()
            return u if u.startswith("https://") else None
    except Exception:
        return None


def write_current_url(url):
    try:
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(url)
    except Exception:
        pass


def read_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def detect_from_log():
    try:
        with open(TUNNEL_LOG, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        content = ""
    urls = URL_RE.findall(content)
    return urls[-1] if urls else None


def is_alive(url):
    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status in (200, 301, 302, 307, 308)
    except Exception:
        return False


def main():
    print("tunnel_watch=start", flush=True)
    while True:
        url = detect_from_log()
        if url and read_current_url() != url:
            if is_alive(url):
                cfg = read_cfg()
                changed = cfg.get("shop_url", "").rstrip("/") != url
                cfg["shop_url"] = url
                write_cfg(cfg)
                write_current_url(url)
                print("tunnel_url=%s changed=%s" % (url, changed), flush=True)
                if changed:
                    try:
                        refresh_menu(url)
                    except Exception as e:
                        print("refresh_menu_error=%s" % e, flush=True)
        time.sleep(10)


def refresh_menu(url):
    """Re-set the Telegram webapp menu button to the new URL so the sidebar
    button also points to the current tunnel."""
    try:
        cfg = read_cfg()
        token = os.environ.get("BOT_TOKEN", cfg.get("token", ""))
        if not token:
            return
        api = "https://api.telegram.org/bot" + token + "/setChatMenuButton"
        import urllib.request
        payload = json.dumps({
            "menu_button": {
                "type": "web_app",
                "text": "🛍️ Open Shop",
                "web_app": {"url": url},
            }
        }).encode()
        req = urllib.request.Request(api, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print("menu_button_updated=%s" % url, flush=True)
    except Exception as e:
        print("menu_button_error=%s" % e, flush=True)


if __name__ == "__main__":
    main()
