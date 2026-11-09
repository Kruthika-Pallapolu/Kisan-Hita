"""Backend-only Prisma/Timbre adapters following the published REST contracts.

The adapters are never selected by default. Tests inject a local fake client;
ordinary development must not enable live traffic or supply provider keys.
"""
from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.schemas.features import (
    SpeechToTextRequest, SpeechToTextResponse, TextToSpeechRequest,
    TextToSpeechResponse,
)


class SpeechProviderUnavailable(RuntimeError):
    """A safe provider failure with no request body or credential details."""


class HttpResponse(Protocol):
    status_code: int
    content: bytes
    headers: Any
    def json(self) -> Any: ...


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> HttpResponse: ...


ClientFactory = Callable[..., Any]


def _api_error(response: HttpResponse) -> SpeechProviderUnavailable:
    if response.status_code in (401, 403):
        message = "The speech service is not authorized. Check its backend configuration."
    elif response.status_code == 429:
        message = "The speech service is busy. Please try again later."
    elif response.status_code >= 500:
        message = "The speech service is temporarily unavailable. Please try again later."
    else:
        message = "The speech request was not accepted. Check the audio or text settings."
    return SpeechProviderUnavailable(message)


class GnaniPrismaV3Provider:
    is_mock = False
    ENDPOINT = "https://api.vachana.ai/stt/v3"
    MODEL = "prisma-v3.0"
    LANGUAGE_CODE = "indic-auto"
    MIME_EXTENSIONS = {
        "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3",
        "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac",
        "audio/mp4": "m4a",
    }

    def __init__(self, api_key: str, *, client_factory: ClientFactory = httpx.Client):
        if not api_key.strip():
            raise ValueError("A backend API key is required for the explicitly enabled STT adapter.")
        self.__api_key = api_key
        self._client_factory = client_factory

    def transcribe(self, request: SpeechToTextRequest, audio: bytes) -> SpeechToTextResponse:
        language = request.language.lower().split("-", 1)[0]
        mime = request.content_type.lower().split(";", 1)[0]
        extension = self.MIME_EXTENSIONS.get(mime)
        if language not in {"te", "en", "hi", "ta", "kn", "ml", "mr"}:
            raise SpeechProviderUnavailable("Speech recognition is not configured for this language.")
        if not extension:
            raise SpeechProviderUnavailable("Choose a WAV, MP3, OGG, FLAC, AAC, or M4A audio recording.")
        if not audio or len(audio) != request.size_bytes:
            raise SpeechProviderUnavailable("The audio upload is empty or incomplete.")
        if mime in {"audio/wav", "audio/x-wav"} and (len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE"):
            raise SpeechProviderUnavailable("The WAV recording is not valid. Record your question again.")
        try:
            with self._client_factory(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                response = client.post(
                    self.ENDPOINT,
                    headers={"X-API-Key-ID": self.__api_key},
                    data={"model": self.MODEL, "language_code": self.LANGUAGE_CODE, "format": "codemix"},
                    files={"audio_file": (request.filename, audio, mime)},
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            raise SpeechProviderUnavailable("The speech service could not be reached in time. Please try again.") from None
        if not 200 <= response.status_code < 300:
            raise _api_error(response)
        try:
            body = response.json()
            transcript = body["transcript"]
            model = body.get("model")
            detected_language = body.get("detected_language_code", self.LANGUAGE_CODE)
            if (body.get("success") is not True or not isinstance(transcript, str)
                    or model != self.MODEL or not isinstance(detected_language, str)):
                raise ValueError("invalid response")
        except (ValueError, TypeError, KeyError):
            raise SpeechProviderUnavailable("The speech service returned an unreadable response.") from None
        return SpeechToTextResponse(
            text=transcript.strip(), language=detected_language, confidence=None, is_mock=False,
            source="Gnani Prisma v3.0", notice="Transcribed from the submitted audio recording.",
        )


class GnaniTimbreV3Provider:
    is_mock = False
    ENDPOINT = "https://api.vachana.ai/api/v1/tts/inference"
    MODEL = "timbre-v3.0"
    LANGUAGES = {"te": "te-IN", "en": "en-IN", "hi": "hi-IN", "ta": "ta-IN", "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN"}
    VOICE = "Vasudha"
    MAX_AUDIO_BYTES = 10 * 1024 * 1024

    def __init__(self, api_key: str, *, client_factory: ClientFactory = httpx.Client):
        if not api_key.strip():
            raise ValueError("A backend API key is required for the explicitly enabled TTS adapter.")
        self.__api_key = api_key
        self._client_factory = client_factory

    def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResponse:
        language = request.language.lower().split("-", 1)[0]
        locale = self.LANGUAGES.get(language)
        if not locale:
            raise SpeechProviderUnavailable("Speech output is not configured for this language.")
        payload = {
            "text": request.text,
            "voice": self.VOICE,
            "model": self.MODEL,
            "language": locale,
            "speed": 1.0,
            "audio_config": {
                "encoding": "linear_pcm", "container": "wav",
                "num_channels": 1, "sample_rate": 48000, "sample_width": 2,
            },
        }
        try:
            with self._client_factory(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                response = client.post(
                    self.ENDPOINT,
                    headers={"X-API-Key-ID": self.__api_key, "Content-Type": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            raise SpeechProviderUnavailable("The speech service could not be reached in time. Please try again.") from None
        if not 200 <= response.status_code < 300:
            raise _api_error(response)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if (not response.content or len(response.content) > self.MAX_AUDIO_BYTES or content_type != "audio/wav"
                or len(response.content) < 44 or response.content[:4] != b"RIFF" or response.content[8:12] != b"WAVE"):
            raise SpeechProviderUnavailable("The speech service returned an invalid audio file.")
        return TextToSpeechResponse(
            available=True, language=locale, audio_base64=b64encode(response.content).decode("ascii"),
            is_mock=False, source="Gnani Timbre v3.0", notice="Speech audio is ready to play.",
        )
