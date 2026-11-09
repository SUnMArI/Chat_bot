"""Server-side speech for the web UI, so voice works the same in every browser.

- text_to_speech: Microsoft Edge neural voices (edge-tts), including Khmer.
- speech_to_text: Google's free web speech recognition (SpeechRecognition), including Khmer.

Both are free and need no API key, but they call online services.
"""

import asyncio
import io
import time

import edge_tts
import speech_recognition as sr

# Language code from the web UI -> neural voices; the second is a backup.
VOICES = {
    "en-US": ["en-US-JennyNeural", "en-US-AriaNeural"],
    "km-KH": ["km-KH-SreymomNeural", "km-KH-PisethNeural"],
}
TTS_ATTEMPTS = 3

MAX_TTS_CHARS = 2000


class SpeechError(Exception):
    """The online speech service failed (network, quota, ...)."""


def text_to_speech(text: str, lang: str) -> bytes:
    """Return MP3 audio of `text` spoken in `lang`.

    The free service now and then returns no audio, so failed attempts are
    retried, with the backup voice on the last try.
    """
    primary, backup = VOICES.get(lang, VOICES["en-US"])

    async def collect(voice: str) -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text[:MAX_TTS_CHARS], voice).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    error = None
    for attempt in range(TTS_ATTEMPTS):
        voice = backup if attempt == TTS_ATTEMPTS - 1 else primary
        try:
            audio = asyncio.run(collect(voice))
            if audio:
                return audio
            error = "no audio received"
        except Exception as e:
            error = e
        time.sleep(0.3 * (attempt + 1))
    raise SpeechError(f"text-to-speech failed: {error}")


def speech_to_text(wav: bytes, lang: str) -> str:
    """Transcribe WAV audio. Returns "" if no words were recognised."""
    try:
        with sr.AudioFile(io.BytesIO(wav)) as source:
            audio = sr.Recognizer().record(source)
    except Exception as e:
        raise ValueError(f"unreadable audio: {e}") from e

    try:
        return sr.Recognizer().recognize_google(audio, language=lang if lang in VOICES else "en-US")
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        raise SpeechError(f"speech recognition failed: {e}") from e
