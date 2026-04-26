"""
Text-to-Speech engine abstraction.

Provides a common TTSEngine interface with two concrete implementations:
  - ElevenLabsTTSEngine  — current (Phase 2)
  - AzureNeuralTTSEngine — Phase 5 migration target (stub)
  - MockTTSEngine        — testing / no-key fallback

The active engine is selected by the TTS_PROVIDER env var:
  TTS_PROVIDER=elevenlabs  (default)
  TTS_PROVIDER=azure
  TTS_PROVIDER=mock
"""

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_PROVIDER = os.getenv("TTS_PROVIDER", "elevenlabs").lower()
_ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")
_ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
_ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2")
_AZURE_KEY = os.getenv("AZURE_SPEECH_KEY", "")
_AZURE_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
_AZURE_VOICE = os.getenv("AZURE_TTS_VOICE", "en-US-BrianMultilingualNeural")

try:
    from elevenlabs.client import ElevenLabs as _ElevenLabsClient
    from elevenlabs import VoiceSettings as _VoiceSettings
    _ELEVENLABS_AVAILABLE = True
except ImportError:
    _ELEVENLABS_AVAILABLE = False
    logger.debug("elevenlabs package not installed — ElevenLabsTTSEngine unavailable")


class TTSEngine(ABC):
    """Abstract base class for all TTS engines."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """
        Convert text to audio bytes (MP3 or WAV).

        Args:
            text: The text to speak.

        Returns:
            Raw audio bytes.
        """

    def synthesize_to_file(self, text: str, output_path: str) -> str:
        """
        Synthesize text and save audio to a file.

        Args:
            text: The text to speak.
            output_path: Destination file path.

        Returns:
            The output_path that was written.
        """
        audio = self.synthesize(text)
        Path(output_path).write_bytes(audio)
        logger.info("action=tts_saved path=%s chars=%d", output_path, len(text))
        return output_path

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging."""


class ElevenLabsTTSEngine(TTSEngine):
    """ElevenLabs API text-to-speech engine."""

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """
        Args:
            api_key: ElevenLabs API key. Defaults to ELEVENLABS_API_KEY env var.
            voice_id: ElevenLabs voice ID. Defaults to ELEVENLABS_VOICE_ID env var.
            model: ElevenLabs model ID. Defaults to ELEVENLABS_MODEL env var.
        """
        if not _ELEVENLABS_AVAILABLE:
            raise ImportError(
                "elevenlabs package is not installed. Run: pip install elevenlabs"
            )
        self._api_key = api_key or _ELEVENLABS_KEY
        if not self._api_key:
            raise EnvironmentError("ELEVENLABS_API_KEY is not set.")
        self._voice_id = voice_id or _ELEVENLABS_VOICE_ID
        self._model = model or _ELEVENLABS_MODEL
        self._client = _ElevenLabsClient(api_key=self._api_key)
        logger.info("action=tts_init provider=elevenlabs voice=%s model=%s",
                    self._voice_id, self._model)

    def synthesize(self, text: str) -> bytes:
        """Call ElevenLabs API and return MP3 audio bytes."""
        logger.debug("action=tts_synthesize provider=elevenlabs chars=%d", len(text))
        audio_gen = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id=self._model,
            voice_settings=_VoiceSettings(stability=0.5, similarity_boost=0.75),
        )
        audio_bytes = b"".join(audio_gen)
        logger.info("action=tts_done provider=elevenlabs bytes=%d", len(audio_bytes))
        return audio_bytes

    @property
    def provider_name(self) -> str:
        return "elevenlabs"


class AzureNeuralTTSEngine(TTSEngine):
    """
    Azure Cognitive Services Neural TTS engine.

    Phase 5 migration target — replaces ElevenLabs for on-prem/ITAR deployments.
    Requires: pip install azure-cognitiveservices-speech
    """

    def __init__(
        self,
        key: str | None = None,
        region: str | None = None,
        voice: str | None = None,
    ) -> None:
        """
        Args:
            key: Azure Speech key. Defaults to AZURE_SPEECH_KEY env var.
            region: Azure region. Defaults to AZURE_SPEECH_REGION env var.
            voice: Voice name. Defaults to AZURE_TTS_VOICE env var.
        """
        try:
            import azure.cognitiveservices.speech as speechsdk  # type: ignore
            self._sdk = speechsdk
        except ImportError as e:
            raise ImportError(
                "azure-cognitiveservices-speech not installed. "
                "Run: pip install azure-cognitiveservices-speech"
            ) from e

        self._key = key or _AZURE_KEY
        self._region = region or _AZURE_REGION
        self._voice = voice or _AZURE_VOICE
        if not self._key:
            raise EnvironmentError("AZURE_SPEECH_KEY is not set.")
        logger.info("action=tts_init provider=azure voice=%s region=%s",
                    self._voice, self._region)

    def synthesize(self, text: str) -> bytes:
        """Call Azure Neural TTS and return WAV audio bytes."""
        import io
        logger.debug("action=tts_synthesize provider=azure chars=%d", len(text))
        config = self._sdk.SpeechConfig(subscription=self._key, region=self._region)
        config.speech_synthesis_voice_name = self._voice
        stream = self._sdk.AudioDataStream
        synth = self._sdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        result = synth.speak_text_async(text).get()
        if result.reason != self._sdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"Azure TTS failed: {result.reason}")
        audio_bytes = result.audio_data
        logger.info("action=tts_done provider=azure bytes=%d", len(audio_bytes))
        return audio_bytes

    @property
    def provider_name(self) -> str:
        return "azure"


class MockTTSEngine(TTSEngine):
    """
    No-op TTS engine for testing and simulation mode.

    Returns empty bytes; records what would have been spoken.
    """

    def __init__(self) -> None:
        self.utterances: list[str] = []
        logger.debug("action=tts_init provider=mock")

    def synthesize(self, text: str) -> bytes:
        self.utterances.append(text)
        logger.debug("action=tts_mock text=%r", text[:80])
        return b""

    @property
    def provider_name(self) -> str:
        return "mock"


def build_tts_engine() -> TTSEngine:
    """
    Factory — select and instantiate the configured TTS engine.

    Falls back to MockTTSEngine if no API key is available.
    """
    provider = _PROVIDER

    if provider == "azure":
        if _AZURE_KEY:
            return AzureNeuralTTSEngine()
        logger.warning("action=tts_fallback reason=no_azure_key using=mock")
        return MockTTSEngine()

    # Default: ElevenLabs
    if _ELEVENLABS_AVAILABLE and _ELEVENLABS_KEY and not _ELEVENLABS_KEY.startswith("your_"):
        return ElevenLabsTTSEngine()

    logger.warning("action=tts_fallback reason=no_elevenlabs_key using=mock")
    return MockTTSEngine()
