# AI Chatbot

Chat with Claude by typing or by voice, in English or Khmer (ខ្មែរ).

- `web.py` – web UI with a mic button and an EN / ខ្មែរ switch
- `main.py` – terminal chatbot (type `/voice` for voice mode)

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
| `PORT` | Set by hosting services; the server then listens on all interfaces |

## Deploy free on Render

1. Push this repo to GitHub (`.env` is ignored, so your key is not uploaded).
2. On [render.com](https://render.com) choose **New → Blueprint** and pick the repo.
   Render reads `render.yaml` and asks for `ANTHROPIC_API_KEY` and `APP_PASSWORD`.
3. Open the `https://….onrender.com` link. The mic works there because it is HTTPS.

Free services sleep after ~15 minutes idle, so the first visit afterwards takes
30–60 seconds. Chat history is kept in memory and resets when the server restarts.
