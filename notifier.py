"""
Notifications Telegram en direct (optionnel).
Si TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID ne sont pas définis, le bot continue silencieusement.
"""

import logging
import requests
import config

logger = logging.getLogger("CryptoPaperBot")


def send_telegram(message: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning("Échec notification Telegram (%s) : %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("Erreur réseau Telegram : %s", exc)
