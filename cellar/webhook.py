"""Discord webhook alerts (opt-in). The URL is only ever sent to Discord."""

import threading

import requests

from . import log, store

GREEN, RED, YELLOW, BLURPLE = 0x57F287, 0xED4245, 0xFEE75C, 0x5865F2
_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
             "https://canary.discord.com/api/webhooks/", "https://ptb.discord.com/api/webhooks/")


def looks_like_webhook(url: str) -> bool:
    return bool(url) and url.strip().lower().startswith(_PREFIXES)


def enabled() -> bool:
    return store.settings.webhook and looks_like_webhook(store.settings.webhook_url)


def post(url: str, title: str, desc: str, color: int, sync: bool = False) -> str:
    body = {"username": "Cellar", "embeds": [{"title": title, "description": desc, "color": color}]}

    def go():
        try:
            r = requests.post(url.strip(), json=body, timeout=10)
            if r.status_code >= 300:
                log.write(f"Discord webhook returned HTTP {r.status_code}")
                return f"HTTP {r.status_code}"
            return ""
        except Exception as ex:
            log.write(f"Discord webhook failed: {ex}")
            return str(ex)

    if sync:
        return go()
    threading.Thread(target=go, daemon=True).start()
    return ""


def send(title: str, desc: str, color: int) -> None:
    if enabled():
        post(store.settings.webhook_url, title, desc, color)
