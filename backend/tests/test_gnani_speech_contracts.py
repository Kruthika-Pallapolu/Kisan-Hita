"""Offline Gnani v3 contract tests. All provider HTTP is intercepted by MockTransport."""
import json
import re

import httpx
import pytest
import wave
from io import BytesIO
from pydantic import ValidationError

from app.core.config import Settings
from app.providers.gnani_speech import (
    GnaniPrismaV3Provider, GnaniTimbreV3Provider, SpeechProviderUnavailable,
)
from app.schemas.features import SpeechToTextRequest, TextToSpeechRequest
from app.services.container import build_container


def client_factory(handler):
    transport = httpx.MockTransport(handler)
    return lambda **kwargs: httpx.Client(transport=transport, **kwargs)


def valid_wav():
    output = BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(b"\x00\x00" * 160)
    return output.getvalue()


def stt_request(language="te", audio=None):
    audio = audio or valid_wav()
    return SpeechToTextRequest(filename="clip.wav", content_type="audio/wav", size_bytes=len(audio), language=language)


def test_prisma_v3_sends_documented_multipart_and_preserves_actual_unicode_transcript():
    def handler(request):
        body = request.read().decode("latin1")
        assert str(request.url) == "https://api.vachana.ai/stt/v3"
        assert request.headers["X-API-Key-ID"] == "local-test-key"
        assert re.search(r'name="audio_file"; filename="clip.wav"', body)
        for field, value in (("model", "prisma-v3.0"), ("language_code", "indic-auto"), ("format", "codemix")):
            assert re.search(rf'name="{field}"\r\n\r\n{re.escape(value)}', body)
        return httpx.Response(200, json={"success": True, "transcript": "రేపు వర్షం పడుతుందా?", "model": "prisma-v3.0", "detected_language_code": "te-IN"})

    provider = GnaniPrismaV3Provider("local-test-key", client_factory=client_factory(handler))
    audio = valid_wav()
    result = provider.transcribe(stt_request(audio=audio), audio)
    assert result.text == "రేపు వర్షం పడుతుందా?"
    assert result.language == "te-IN" and result.is_mock is False
    assert result.source == "Gnani Prisma v3.0" and result.confidence is None


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503, 504])
def test_prisma_provider_errors_are_safe_and_do_not_leak_response_bodies(status):
    provider = GnaniPrismaV3Provider("local-test-key", client_factory=client_factory(lambda _r: httpx.Response(status, text="private body and credential")))
    with pytest.raises(SpeechProviderUnavailable) as error:
        audio = valid_wav()
        provider.transcribe(stt_request(audio=audio), audio)
    assert "credential" not in str(error.value)


def test_prisma_rejects_unsupported_audio_incomplete_upload_and_malformed_response():
    provider = GnaniPrismaV3Provider("local-test-key", client_factory=client_factory(lambda _r: httpx.Response(200, json={"success": True})))
    with pytest.raises(SpeechProviderUnavailable, match="WAV, MP3"):
        provider.transcribe(SpeechToTextRequest(filename="clip.webm", content_type="audio/webm", size_bytes=1, language="en"), b"x")
    with pytest.raises(SpeechProviderUnavailable, match="empty or incomplete"):
        provider.transcribe(stt_request(), b"x")
    audio = valid_wav()
    with pytest.raises(SpeechProviderUnavailable, match="unreadable response"):
        provider.transcribe(stt_request(audio=audio), audio)


def test_prisma_timeout_is_reported_without_provider_details():
    provider = GnaniPrismaV3Provider("local-test-key", client_factory=client_factory(lambda _r: (_ for _ in ()).throw(httpx.ReadTimeout("private timeout detail"))))
    with pytest.raises(SpeechProviderUnavailable, match="could not be reached") as error:
        audio = valid_wav()
        provider.transcribe(stt_request(audio=audio), audio)
    assert "private timeout detail" not in str(error.value)


@pytest.mark.parametrize("language,locale", [
    ("te", "te-IN"), ("en", "en-IN"), ("hi", "hi-IN"), ("ta", "ta-IN"),
    ("kn", "kn-IN"), ("ml", "ml-IN"), ("mr", "mr-IN"),
])
def test_timbre_v3_uses_vasudha_for_each_selected_language(language, locale):
    audio = valid_wav()
    def handler(request):
        body = json.loads(request.read())
        assert str(request.url) == "https://api.vachana.ai/api/v1/tts/inference"
        assert request.headers["X-API-Key-ID"] == "local-test-key"
        assert body == {
            "text": "A clear, friendly spoken response.", "voice": "Vasudha", "model": "timbre-v3.0",
            "language": locale, "speed": 1.0,
            "audio_config": {"encoding": "linear_pcm", "container": "wav", "num_channels": 1, "sample_rate": 48000, "sample_width": 2},
        }
        return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})

    provider = GnaniTimbreV3Provider("local-test-key", client_factory=client_factory(handler))
    result = provider.synthesize(TextToSpeechRequest(text="A clear, friendly spoken response.", language=language))
    assert result.available and not result.is_mock and result.language == locale
    assert result.audio_base64 and result.source == "Gnani Timbre v3.0"


def test_timbre_provider_rejects_non_audio_and_safe_maps_errors_and_timeouts():
    request = TextToSpeechRequest(text="hello", language="en")
    malformed = GnaniTimbreV3Provider("local-test-key", client_factory=client_factory(lambda _r: httpx.Response(200, json={"success": True})))
    with pytest.raises(SpeechProviderUnavailable, match="invalid audio"):
        malformed.synthesize(request)
    provider_error = GnaniTimbreV3Provider("local-test-key", client_factory=client_factory(lambda _r: httpx.Response(403, json={"message": "private"})))
    with pytest.raises(SpeechProviderUnavailable, match="not authorized"):
        provider_error.synthesize(request)
    timeout = GnaniTimbreV3Provider("local-test-key", client_factory=client_factory(lambda _r: (_ for _ in ()).throw(httpx.ReadTimeout("private"))))
    with pytest.raises(SpeechProviderUnavailable, match="could not be reached"):
        timeout.synthesize(request)


def test_live_selection_requires_master_switch_and_backend_key(monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        build_container(Settings(speech_to_text_provider="prisma-live"))
    with pytest.raises(ValueError, match="GNANI_API_KEY is required"):
        build_container(Settings(speech_to_text_provider="prisma-live", text_to_speech_provider="timbre-live", gnani_live_api_enabled=True))
    with pytest.raises(ValueError, match="mock providers will not be substituted"):
        build_container(Settings(gnani_live_api_enabled=True))
    with pytest.raises(ValueError, match="disabled"):
        build_container(Settings(text_to_speech_provider="timbre-live"))
    with pytest.raises(ValidationError):
        SpeechToTextRequest(filename="clip", content_type="audio/wav", size_bytes=1, language="xx")


def test_disabled_live_providers_keep_mock_fallback_without_creating_http_client(monkeypatch):
    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("disabled voice providers must not make outbound HTTP")
    monkeypatch.setattr(httpx, "Client", forbidden_client)
    providers = build_container(Settings())
    stt = providers.speech_to_text.transcribe(stt_request(), b"audio")
    tts = providers.text_to_speech.synthesize(TextToSpeechRequest(text="hello", language="en"))
    assert stt.is_mock and not stt.text
    assert tts.is_mock and not tts.available
