# AI Chatbot

Chat with Claude by typing or by voice, in English or Khmer (ខ្មែរ).

- `web.py` – web UI with a mic button and an EN / ខ្មែរ switch
- `main.py` – terminal chatbot (type `/voice` for voice mode)
- `loan_tools.py` – tools the AI can call: a loan payment calculator and
  `send_loan_lead_to_telegram`, which the AI uses after the customer confirms their details
- `telegram_bot.py` – formats and sends the lead to the loan team's Telegram chat
- `speech.py` – voice for the web UI, done on the server so it works in every
  browser: Microsoft Edge neural voices speak replies (including Khmer), and
  Google's free speech recognition turns the mic recording into text. Both are
  free online services with no API key.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add requirements-voice.txt for terminal voice mode
cp .env.example .env                     # then put your API key in .env
python web.py                            # open http://localhost:8000 in Chrome or Edge
```

## Settings

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (required) |
| `APP_PASSWORD` | If set, visitors must enter this password to chat |
| `MAX_MESSAGES_PER_HOUR` | Messages each visitor may send per hour (default 30) |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather (for loan leads) |
| `TELEGRAM_CHAT_ID` | Chat or group that receives loan leads |
| `PORT` | Set by hosting services; the server then listens on all interfaces |

## Telegram lead bot

When a customer wants a loan, the assistant collects their name, phone, address,
loan type, amount, term and monthly income, reads them back for confirmation, and
then posts the lead to your loan team's Telegram chat.

1. In Telegram, open **@BotFather**, send `/newbot`, and follow the steps. Copy the token
   into `.env` as `TELEGRAM_BOT_TOKEN=...`.
2. Create a group for the loan team (or use an existing one), add the bot, and send any
   message in the group.
3. Run `python telegram_bot.py`. It lists the chats the bot can see; copy the group's line
   (a group id looks like `-1001234567890`) into `.env` as `TELEGRAM_CHAT_ID=...`.
4. Run `python telegram_bot.py --test` to send a sample lead, then restart `python web.py`.

If the bot doesn't see group messages, open @BotFather → `/setprivacy` → your bot → **Disable**,
or mention the bot in the group, then run step 3 again.

## Deploy free on Render

1. Push this repo to GitHub (`.env` is ignored, so your key is not uploaded).
2. On [render.com](https://render.com) choose **New → Blueprint** and pick the repo.
   Render reads `render.yaml` and asks for `ANTHROPIC_API_KEY`, `APP_PASSWORD`,
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Open the `https://….onrender.com` link. The mic works there because it is HTTPS.

Free services sleep after ~15 minutes idle, so the first visit afterwards takes
30–60 seconds. Chat history is kept in memory and resets when the server restarts.
# Chat_bot
