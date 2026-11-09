"""AI Chatbot - talk to Claude by typing or by voice.

Commands:
  /voice   switch to voice mode (push-to-talk, replies are spoken)
  /text    switch to text mode
  /reset   forget the conversation
  /quit    exit
"""

import platform
import queue
import shutil
import subprocess
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import loan_tools

# Load ANTHROPIC_API_KEY (and any other settings) from a .env file next to this script.
load_dotenv(Path(__file__).with_name(".env"))

MODEL = "claude-opus-5-5"
SAMPLE_RATE = 16000

SYSTEM_PROMPT = f"""You are the PPCBank Loan Assistant, a friendly assistant that helps customers \
of Phnom Penh Commercial Bank (PPCBank) in Cambodia with loans. Customers talk to you in English \
or Khmer, by typing or by voice.

What you do:
- Answer general questions about loans: common loan types (home, car, business, personal), how \
the application process usually works, and the documents usually needed (ID card, proof of income, \
bank statements, collateral documents such as a land title).
- You do not have PPCBank's current interest rates, fees or product rules. Never state them as \
facts. When a customer wants a payment figure, call estimate_monthly_payment with an illustrative \
annual rate of {loan_tools.SAMPLE_ANNUAL_RATE}% (or a rate the customer gives), and say clearly that it is \
an estimate and a loan officer will confirm the real rate.
- When a customer wants to apply or be contacted, collect: full name, phone number, address \
(village or sangkat, district or khan, province or city), loan type, amount and currency (USD or \
KHR), term, and monthly income. Ask for a couple of missing details at a time, conversationally.
- Before sending, read the details back in one short summary and ask the customer to confirm. \
Only after they confirm, call send_loan_lead_to_telegram. Then tell them a loan officer will \
contact them soon. Never promise that the loan will be approved.
- If sending fails, apologise, say the details were not sent, and suggest trying again later or \
calling the bank. Never claim a lead was sent unless the tool says it was.
- Stay on banking and loan topics; politely steer other requests back.

Style: your replies may be read aloud by a text-to-speech engine, so write natural spoken \
sentences, keep answers concise, and avoid markdown, tables, code blocks and emoji. Reply in the \
language the customer uses unless a system message says otherwise."""

MAX_TOOL_ROUNDS = 5


class Chatbot:
    def __init__(self, source: str = "Terminal"):
        self.client = anthropic.Anthropic()
        self.source = source  # shown on Telegram leads, e.g. "Web chat"
        self.reset()

    def reset(self):
        self.messages = []
        self.language = None  # reply language currently in force
        self.tool_context = {"source": self.source, "leads_sent": 0}

    def ask(self, user_text: str, on_text=None, language: str | None = None, on_event=None) -> str:
        """Send a user message, run any tool calls, stream the reply, and return its text.

        If `language` is given (e.g. "Khmer"), Claude is asked to reply in it.
        `on_event("lead_sent")` is called when a loan lead reaches Telegram.

        The history is append-only: the top-level system prompt never changes, and a
        language switch is added as a mid-conversation system message instead.
        """
        start = len(self.messages)
        old_language = self.language
        self.messages.append({"role": "user", "content": user_text})
        if language and language != self.language:
            self.messages.append({"role": "system", "content": f"From now on, always reply in {language}, even if the customer writes in another language."})
            self.language = language
        self.tool_context["language"] = self.language

        texts = []

        def emit(t):
            texts.append(t)
            if on_text:
                on_text(t)

        rounds = 0
        try:
            while True:
                separator_needed = bool(texts)
                try:
                    with self.client.beta.messages.stream(
                        model=MODEL,
                        max_tokens=64000,
                        system=SYSTEM_PROMPT,
                        tools=loan_tools.TOOLS,
                        messages=self.messages,
                        output_config={"effort": "low"},
                        betas=["server-side-fallback-2026-07-01"],
                        fallbacks="default",
                    ) as stream:
                        for text in stream.text_stream:
                            if separator_needed:
                                emit(" ")
                                separator_needed = False
                            emit(text)
                        final = stream.get_final_message()
                except ValueError as e:
                    # With eager_input_streaming the SDK raises ValueError for a tool
                    # input it cannot parse at all.
                    raise RuntimeError("The assistant sent a malformed tool call. Please try again.") from e

                if final.stop_reason == "refusal":
                    if rounds == 0:
                        del self.messages[start:]
                        self.language = old_language
                    return "Sorry, I can't help with that one."

                tool_uses = [b for b in final.content if b.type == "tool_use"]
                if final.stop_reason != "tool_use" or not tool_uses:
                    # Append the full content (not just text) so thinking blocks stay intact.
                    self.messages.append({"role": "assistant", "content": final.content})
                    if final.stop_reason == "max_tokens":
                        emit(" (reply cut short)")
                    break

                rounds += 1
                if rounds > MAX_TOOL_ROUNDS:
                    raise RuntimeError("The assistant called too many tools in one turn.")

                # Run every tool call and send all results back in one user message.
                results = []
                for block in tool_uses:
                    content, is_error = loan_tools.run_tool(block.name, block.input, self.tool_context)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
                    if block.name == "send_loan_lead_to_telegram" and not is_error and on_event:
                        on_event("lead_sent")
                self.messages.append({"role": "assistant", "content": final.content})
                self.messages.append({"role": "user", "content": results})
        except Exception:
            if rounds == 0:
                # Nothing ran yet: forget this turn so the next one starts clean.
                del self.messages[start:]
                self.language = old_language
            # After a tool round the history ends with valid tool results, so keep it
            # (a lead may already have been sent and Claude should know that).
            raise

        return "".join(texts)


# ---------------------------------------------------------------- voice I/O

def record_until_enter() -> bytes:
    """Record from the microphone until the user presses Enter. Returns 16-bit PCM."""
    import sounddevice as sd

    chunks = queue.Queue()

    def callback(indata, frames, time_info, status):
        chunks.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                           callback=callback):
        input("🎙️  Listening... press Enter when you're done speaking.")

    audio = b""
    while not chunks.empty():
        audio += chunks.get()
    return audio


def transcribe(pcm: bytes) -> str:
    """Speech-to-text using Google's free web recognizer (via SpeechRecognition)."""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    audio = sr.AudioData(pcm, SAMPLE_RATE, 2)
    try:
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print(f"[speech recognition unavailable: {e}]")
        return ""


def speak(text: str):
    """Text-to-speech: macOS `say` if available, otherwise pyttsx3."""
    if not text.strip():
        return
    if platform.system() == "Darwin" and shutil.which("say"):
        subprocess.run(["say", text])
        return
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[text-to-speech unavailable: {e}]")


# ---------------------------------------------------------------- main loop

def main():
    bot = Chatbot()
    voice_mode = "--voice" in sys.argv

    print("🤖 AI Chatbot (Claude). Commands: /voice  /text  /reset  /quit")
    print(f"Mode: {'voice' if voice_mode else 'text'}\n")

    while True:
        try:
            if voice_mode:
                user_text = input("You (press Enter to talk, or type): ").strip()
                if not user_text:
                    user_text = transcribe(record_until_enter())
                    if not user_text:
                        print("(Didn't catch that - try again.)\n")
                        continue
                    print(f"You said: {user_text}")
            else:
                user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_text:
            continue
        command = user_text.lower()
        if command in ("/quit", "/exit"):
            print("Bye!")
            break
        if command == "/voice":
            voice_mode = True
            print("🔊 Voice mode on.\n")
            continue
        if command == "/text":
            voice_mode = False
            print("⌨️  Text mode on.\n")
            continue
        if command == "/reset":
            bot.reset()
            print("🧹 Conversation cleared.\n")
            continue

        print("Bot: ", end="", flush=True)
        try:
            reply = bot.ask(user_text, on_text=lambda t: print(t, end="", flush=True),
                            on_event=lambda e: print("\n[✓ Lead sent to Telegram]", flush=True))
        except anthropic.AuthenticationError:
            print("\n[Invalid or missing API key - set ANTHROPIC_API_KEY.]\n")
            continue
        except anthropic.RateLimitError:
            print("\n[Rate limited - wait a moment and try again.]\n")
            continue
        except anthropic.APIStatusError as e:
            print(f"\n[API error {e.status_code}: {e.message}]\n")
            continue
        except anthropic.APIConnectionError:
            print("\n[Network error - check your internet connection.]\n")
            continue
        print("\n")

        if voice_mode:
            speak(reply)


if __name__ == "__main__":
    main()
