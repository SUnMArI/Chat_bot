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

# Load ANTHROPIC_API_KEY (and any other settings) from a .env file next to this script.
load_dotenv(Path(__file__).with_name(".env"))

MODEL = "claude-opus-5-5"
SAMPLE_RATE = 16000

SYSTEM_PROMPT = (
    "You are a friendly, helpful conversational assistant. "
    "Your replies may be read aloud by a text-to-speech engine, so write in "
    "natural spoken sentences: keep answers concise, and avoid markdown, "
    "tables, code blocks, and emoji unless the user explicitly asks for them."
)


class Chatbot:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.messages = []

    def reset(self):
        self.messages = []

    def ask(self, user_text: str, on_text=None, language: str | None = None) -> str:
        """Send a user message, stream the reply, and return the full reply text.

        If `language` is given (e.g. "Khmer"), Claude is asked to reply in it.
        """
        system = SYSTEM_PROMPT
        if language:
            system += f" Always reply in {language}, even if the user writes in another language."
        self.messages.append({"role": "user", "content": user_text})
        try:
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=64000,
                system=system,
                messages=self.messages,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for text in stream.text_stream:
                    if on_text:
                        on_text(text)
                final = stream.get_final_message()
        except Exception:
            self.messages.pop()  # keep history valid so the next turn still works
            raise

        if final.stop_reason == "refusal":
            self.messages.pop()
            return "Sorry, I can't help with that one."

        # Append the full content (not just text) so thinking blocks stay intact.
        self.messages.append({"role": "assistant", "content": final.content})
        return "".join(b.text for b in final.content if b.type == "text")


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
            reply = bot.ask(user_text, on_text=lambda t: print(t, end="", flush=True))
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
