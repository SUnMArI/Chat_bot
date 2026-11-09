"""Send loan leads to the loan team's Telegram chat.

Settings (environment variables or .env):
  TELEGRAM_BOT_TOKEN   token from @BotFather, e.g. 123456:ABC-DEF...
  TELEGRAM_CHAT_ID     chat that receives leads (a group id looks like -1001234567890)

Setup helper - run it yourself after adding the token to .env:
  python telegram_bot.py           list chats that have messaged the bot (to find the chat id)
  python telegram_bot.py --test    send a sample lead to TELEGRAM_CHAT_ID
"""

import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    """Telegram is not configured or rejected the message."""


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _call(method: str, payload: dict | None = None) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    req = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            data = json.load(e)
        except ValueError:
            raise TelegramError(f"Telegram HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise TelegramError(f"could not reach Telegram: {e}") from e
    if not data.get("ok"):
        raise TelegramError(data.get("description", "Telegram rejected the request"))
    return data["result"]


def send_message(text: str) -> None:
    if not is_configured():
        raise TelegramError("Telegram is not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    _call("sendMessage", {
        "chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def _money(amount: float, currency: str) -> str:
    if currency == "KHR":
        return f"{amount:,.0f} ៛"
    return f"${amount:,.2f}".replace(".00", "")


def format_lead(lead: dict) -> str:
    """Telegram HTML message for a loan lead. Every value is escaped."""
    e = lambda v: html.escape(str(v))  # noqa: E731
    cur = lead.get("currency", "USD")
    years, months = divmod(int(lead["term_months"]), 12)
    term = " ".join(p for p in (f"{years} yr" if years else "", f"{months} mo" if months else "") if p)

    lines = [
        f"🆕 <b>New loan lead · {e(lead['loan_type'])}</b>",
        "",
        f"<b>Customer:</b> {e(lead['full_name'])}",
        f"<b>Phone:</b> {e(lead['phone'])}",
        f"<b>Address:</b> {e(lead['address'])}",
        "",
        f"<b>Loan:</b> {e(_money(lead['loan_amount'], cur))} over {e(term)}",
        f"<b>Monthly income:</b> {e(_money(lead['monthly_income'], cur))}",
    ]
    if lead.get("estimated_monthly_payment"):
        lines.append(f"<b>Est. payment:</b> ~{e(_money(lead['estimated_monthly_payment'], cur))} / month (estimate)")
    if lead.get("notes"):
        lines.append(f"<b>Notes:</b> {e(lead['notes'])}")
    lines += [
        "",
        f"<b>Language:</b> {e(lead.get('language', '-'))}  ·  <b>Source:</b> {e(lead.get('source', '-'))}",
        f"<i>{e(datetime.now().strftime('%Y-%m-%d %H:%M'))}</i>",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- setup helper

def _main():
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(__file__).with_name(".env"))
    try:
        if "--test" in sys.argv:
            send_message(format_lead({
                "full_name": "Test Customer", "phone": "012 345 678",
                "address": "Boeung Keng Kang 1, Chamkarmon, Phnom Penh",
                "loan_type": "Home loan", "loan_amount": 30000, "currency": "USD",
                "term_months": 120, "monthly_income": 1200, "estimated_monthly_payment": 364,
                "language": "English", "source": "Setup test", "notes": "This is a test message.",
            }))
            print("✅ Test lead sent. Check your Telegram chat.")
            return
        me = _call("getMe")
        print(f"Bot: @{me['username']}")
        chats = {}
        for update in _call("getUpdates"):
            msg = update.get("message") or update.get("channel_post") or update.get("my_chat_member") or {}
            chat = msg.get("chat")
            if chat:
                chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
        if not chats:
            print("No chats yet. Add the bot to your loan team's group, send any message there, then run this again.")
        for chat_id, name in chats.items():
            print(f"  TELEGRAM_CHAT_ID={chat_id}    ({name})")
    except TelegramError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    _main()
