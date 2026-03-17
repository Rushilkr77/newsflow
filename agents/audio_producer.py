"""
Agent 5: Audio Producer (Phase 2 — Chatterbox TTS + F5-TTS fallback)
Converts podcast script to MP3 using Chatterbox TTS (free, local HuggingFace inference).
Falls back to F5-TTS (free, local) if Chatterbox is unavailable, then gTTS as last resort.

Flow:
  1. Load podcast_script.json
  2. For each segment, split plain text into ≤300-char chunks (Chatterbox limit)
  3. TTS each chunk → AudioSegment
  4. Concatenate with silence between segments/articles
  5. Normalize loudness to -16 LUFS
  6. Export MP3 128kbps 44.1kHz with ID3 tags
"""
import io
import os
import re
import shutil
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydub import AudioSegment

from models.podcast import Episode, PodcastScript

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Load TTS config from tts_config.yaml
# ---------------------------------------------------------------------------

def _load_tts_config() -> dict[str, Any]:
    config_path = Path(__file__).parent.parent / "config" / "tts_config.yaml"
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.warning("tts_config_load_failed", error=str(e))
        return {}


_TTS_CFG = _load_tts_config()
_PRIMARY_CFG: dict = _TTS_CFG.get("primary", {})
_FALLBACK_CFG: dict = _TTS_CFG.get("fallback", {})
_OUTPUT_CFG: dict = _TTS_CFG.get("output", {})

_SILENCE_BETWEEN_SEGMENTS_MS: int = _OUTPUT_CFG.get("silence_between_segments_ms", 1500)
_SILENCE_BETWEEN_ARTICLES_MS: int = _OUTPUT_CFG.get("silence_between_articles_ms", 800)
_NORMALIZE_LOUDNESS: bool = _OUTPUT_CFG.get("normalize_loudness", True)
_TARGET_LUFS: float = float(_OUTPUT_CFG.get("target_lufs", -16))
_OUTPUT_FORMAT: str = _OUTPUT_CFG.get("format", "mp3")
_OUTPUT_BITRATE: str = str(_OUTPUT_CFG.get("bitrate", "128k"))

# Max chars per TTS call per provider (from tts_config.yaml)
_CHATTERBOX_MAX_CHARS: int = _PRIMARY_CFG.get("params", {}).get("max_chars_per_call", 300)

# Per-segment provider routing: segment_type → "chatterbox" | "f5_tts"
# Loaded from tts_config.yaml segment_routing block.
# Hardcoded defaults kick in for any segment not listed in config.
_DEFAULT_LONG_SEGMENTS: frozenset = frozenset({"ai_updates", "funding", "india_tech", "product_strategy"})
_SEGMENT_ROUTING: dict[str, str] = {}
for _provider_key, _segments in _TTS_CFG.get("segment_routing", {}).items():
    for _seg in (_segments or []):
        _SEGMENT_ROUTING[_seg] = _provider_key  # "chatterbox" or "f5_tts"


# Ensure pydub can find ffmpeg on Windows after a winget install (PATH not refreshed yet)
def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        return
    winget_base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for pkg in winget_base.glob("Gyan.FFmpeg*"):
        for ffmpeg_bin in pkg.glob("*/bin/ffmpeg.exe"):
            os.environ["PATH"] = str(ffmpeg_bin.parent) + os.pathsep + os.environ.get("PATH", "")
            log.info("ffmpeg_path_set", path=str(ffmpeg_bin.parent))
            return
    log.warning("ffmpeg_not_found", hint="Install via: winget install Gyan.FFmpeg")

_ensure_ffmpeg()


# ---------------------------------------------------------------------------
# TTS Providers
# ---------------------------------------------------------------------------

class ChatterboxProvider:
    """
    Primary TTS using ResembleAI/Chatterbox (free, local HuggingFace inference).
    Max 300 chars per call — aggressive chunking required.
    Output: wav tensor → converted to AudioSegment via scipy.
    """

    def __init__(self, params: dict):
        self.exaggeration: float = params.get("exaggeration", 0.4)
        self.cfg_weight: float = params.get("cfgw", 0.5)
        self.temperature: float = params.get("temperature", 0.7)
        self.voice_reference: str | None = params.get("voice_reference") or None
        self._model = None
        self._sample_rate: int = 24000  # Chatterbox default output sample rate

    def _get_model(self):
        if self._model is None:
            from chatterbox.tts import ChatterboxTTS  # type: ignore[import]
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
            log.info("chatterbox_model_loading", device=device)
            self._model = ChatterboxTTS.from_pretrained(device=device)
            log.info("chatterbox_model_ready")
        return self._model

    def synthesize(self, text: str) -> AudioSegment:
        import numpy as np
        from scipy.io import wavfile  # type: ignore[import]

        model = self._get_model()
        wav = model.generate(
            text,
            audio_prompt_path=self.voice_reference,
            exaggeration=self.exaggeration,
            cfg_weight=self.cfg_weight,
            temperature=self.temperature,
        )
        # wav is a torch tensor of shape (1, samples) or (samples,)
        wav_np: "np.ndarray" = wav.squeeze().cpu().numpy()

        # Convert float32 [-1, 1] → int16
        wav_int16 = (wav_np * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        wavfile.write(buf, self._sample_rate, wav_int16)
        buf.seek(0)
        return AudioSegment.from_wav(buf)


class F5TTSProvider:
    """
    Fallback TTS using F5-TTS (SWivid/F5-TTS — free, local inference).

    Why F5-TTS over ElevenLabs for podcast flow:
    - Handles 800-char chunks natively → cross-sentence prosody is preserved
    - speed=1.05 targets ~150 WPM — natural gym-listening pace
    - seed=-1 adds subtle variation between chunks (avoids robotic repetition)
    - Fully local: no API key, no rate limits, works offline

    Voice cloning: set voice_reference + voice_reference_text in tts_config.yaml
    to lock in a consistent host voice across every episode.
    """

    def __init__(self, config: dict):
        params = config.get("params", {})
        self.model_type: str = config.get("model", "F5-TTS")
        self.speed: float = params.get("speed", 1.05)
        self.seed: int = params.get("seed", -1)
        self.voice_reference: str | None = config.get("voice_reference") or None
        self.voice_reference_text: str | None = config.get("voice_reference_text") or None
        self._model = None

    def _get_model(self):
        if self._model is None:
            from f5_tts.api import F5TTS  # type: ignore[import]
            log.info("f5tts_model_loading", model_type=self.model_type)
            self._model = F5TTS(model_type=self.model_type)
            log.info("f5tts_model_ready")
        return self._model

    def _resolve_reference(self) -> tuple[str, str]:
        """
        Return (ref_audio_path, ref_text).
        Falls back to the package's bundled English reference if none configured.
        """
        if self.voice_reference and self.voice_reference_text:
            return self.voice_reference, self.voice_reference_text

        # Use F5-TTS bundled default reference (ships with the package)
        try:
            import importlib.resources as pkg_resources
            ref_dir = Path(str(pkg_resources.files("f5_tts"))) / "infer" / "examples" / "basic"
            ref_wav = str(ref_dir / "basic_ref_en.wav")
            ref_txt_path = ref_dir / "basic_ref_en.txt"
            ref_txt = ref_txt_path.read_text().strip() if ref_txt_path.exists() else (
                "Some call me nature, others call me mother nature."
            )
            if Path(ref_wav).exists():
                return ref_wav, ref_txt
        except Exception:
            pass

        raise RuntimeError(
            "F5-TTS requires a voice reference. Either set voice_reference + "
            "voice_reference_text in config/tts_config.yaml, or ensure the f5-tts "
            "package is installed with its bundled reference audio."
        )

    def synthesize(self, text: str) -> AudioSegment:
        import numpy as np
        from scipy.io import wavfile  # type: ignore[import]

        model = self._get_model()
        ref_audio, ref_text = self._resolve_reference()

        wav, sr, _ = model.infer(
            ref_file=ref_audio,
            ref_text=ref_text,
            gen_text=text,
            speed=self.speed,
            seed=self.seed,
        )

        # wav is a numpy float32 array
        wav_np: "np.ndarray" = np.array(wav).squeeze()
        wav_int16 = (wav_np * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        wavfile.write(buf, sr, wav_int16)
        buf.seek(0)
        return AudioSegment.from_wav(buf)


class GTTSProvider:
    """Last-resort fallback using gTTS (free but lower quality)."""

    def synthesize(self, text: str) -> AudioSegment:
        from gtts import gTTS  # type: ignore[import]

        mp3_bytes = io.BytesIO()
        tts = gTTS(text=text, lang="en", slow=False)
        tts.write_to_fp(mp3_bytes)
        mp3_bytes.seek(0)
        return AudioSegment.from_mp3(mp3_bytes)


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------

class AudioProducerAgent:
    def __init__(self):
        self._chatterbox: ChatterboxProvider | None = None
        self._f5tts: F5TTSProvider | None = None
        self._gtts: GTTSProvider | None = None
        self._active_provider: str = "unknown"

    def run(self, script: PodcastScript, workspace: str) -> Episode:
        log.info("audio_producer_start", segments=len(script.segments))

        audio_segments: list[AudioSegment] = []
        segment_silence = AudioSegment.silent(duration=_SILENCE_BETWEEN_SEGMENTS_MS)

        for i, segment in enumerate(script.segments):
            log.info(
                "processing_segment",
                segment_type=segment.segment_type,
                chars=len(segment.content_plain),
            )
            try:
                seg_audio = self._segment_to_audio(segment.content_plain, segment.segment_type)
                if i > 0:
                    audio_segments.append(segment_silence)
                audio_segments.append(seg_audio)
            except Exception as e:
                log.error(
                    "segment_tts_failed",
                    segment_type=segment.segment_type,
                    error=str(e),
                )

        if not audio_segments:
            raise RuntimeError("No audio segments produced — TTS failed for all segments")

        full_audio = sum(audio_segments[1:], audio_segments[0])

        if _NORMALIZE_LOUDNESS:
            full_audio = self._normalize_loudness(full_audio)

        duration_sec = len(full_audio) // 1000

        # Duration quality checks
        if duration_sec < 1800:  # < 30 min
            log.warning("episode_too_short", duration_sec=duration_sec, min_expected_sec=1800)
        elif duration_sec > 7200:  # > 120 min
            log.warning("episode_too_long", duration_sec=duration_sec, max_expected_sec=7200)

        episode_number = script.episode_number
        output_path = os.path.join(workspace, f"episode_{episode_number}.mp3")

        full_audio.export(
            output_path,
            format=_OUTPUT_FORMAT,
            bitrate=_OUTPUT_BITRATE,
            tags={
                "title": f"NewsFlow Episode {episode_number} — {script.date}",
                "artist": "NewsFlow AI",
                "album": "NewsFlow Daily",
                "track": str(episode_number),
            },
        )

        file_size = Path(output_path).stat().st_size
        all_source_ids = list(
            {sid for seg in script.segments for sid in seg.source_article_ids}
        )

        log.info(
            "audio_producer_complete",
            duration_sec=duration_sec,
            file_path=output_path,
            file_size_mb=round(file_size / 1024 / 1024, 1),
            provider=self._active_provider,
        )

        return Episode(
            episode_number=episode_number,
            date=script.date,
            duration_sec=duration_sec,
            file_path=output_path,
            file_size_bytes=file_size,
            article_count=len(all_source_ids),
            sources_used=list({seg.segment_type for seg in script.segments}),
        )

    # -------------------------------------------------------------------------
    # TTS dispatch: segment-aware routing with fallback
    # -------------------------------------------------------------------------

    def _segment_to_audio(self, text: str, segment_type: str = "") -> AudioSegment:
        """
        Route each segment to its designated TTS provider, then fall back if needed.

        Routing (from tts_config.yaml segment_routing, with hardcoded defaults):
          Chatterbox — cold_open, intro, quick_hits, closing  (punchy/expressive)
          F5-TTS     — ai_updates, funding, india_tech, product_strategy  (long-form prosody)

        Fallback chain: designated provider → other provider → gTTS
        """
        designated = _SEGMENT_ROUTING.get(
            segment_type,
            "f5_tts" if segment_type in _DEFAULT_LONG_SEGMENTS else "chatterbox",
        )
        log.info("tts_provider_selected", segment_type=segment_type, provider=designated)

        if designated == "chatterbox":
            primary_fn, fallback_fn = self._synthesize_chatterbox, self._synthesize_f5tts
        else:
            primary_fn, fallback_fn = self._synthesize_f5tts, self._synthesize_chatterbox

        try:
            return primary_fn(text)
        except Exception as e:
            log.warning("primary_tts_failed", segment_type=segment_type,
                        provider=designated, error=str(e))

        try:
            return fallback_fn(text)
        except Exception as e:
            log.warning("fallback_tts_failed", segment_type=segment_type, error=str(e))

        return self._synthesize_gtts(text)

    def _synthesize_chatterbox(self, text: str) -> AudioSegment:
        if self._chatterbox is None:
            self._chatterbox = ChatterboxProvider(_PRIMARY_CFG.get("params", {}))

        chunks = _chunk_text(text, max_chars=_CHATTERBOX_MAX_CHARS)
        parts: list[AudioSegment] = []
        article_silence = AudioSegment.silent(duration=_SILENCE_BETWEEN_ARTICLES_MS)

        for chunk in chunks:
            if not chunk.strip():
                continue
            audio = self._chatterbox.synthesize(chunk)
            if parts:
                parts.append(article_silence)
            parts.append(audio)

        if not parts:
            return AudioSegment.silent(duration=500)

        self._active_provider = "chatterbox"
        return sum(parts[1:], parts[0])

    def _synthesize_f5tts(self, text: str) -> AudioSegment:
        """
        F5-TTS fallback — 800-char chunks preserve cross-sentence prosody.
        At speed=1.05 this targets ~150 WPM, natural for gym listening.
        Larger chunks than Chatterbox mean fewer inference calls and smoother
        intonation across sentence boundaries within a paragraph.
        """
        if self._f5tts is None:
            self._f5tts = F5TTSProvider(_FALLBACK_CFG)

        f5_max_chars: int = _FALLBACK_CFG.get("params", {}).get("max_chars_per_call", 800)
        chunks = _chunk_text(text, max_chars=f5_max_chars)
        parts: list[AudioSegment] = []
        article_silence = AudioSegment.silent(duration=_SILENCE_BETWEEN_ARTICLES_MS)

        for chunk in chunks:
            if not chunk.strip():
                continue
            audio = self._f5tts.synthesize(chunk)
            if parts:
                parts.append(article_silence)
            parts.append(audio)

        if not parts:
            return AudioSegment.silent(duration=500)

        self._active_provider = "f5tts"
        return sum(parts[1:], parts[0])

    def _synthesize_gtts(self, text: str) -> AudioSegment:
        if self._gtts is None:
            self._gtts = GTTSProvider()

        chunks = _chunk_text(text, max_chars=500)
        parts: list[AudioSegment] = []

        for chunk in chunks:
            if not chunk.strip():
                continue
            try:
                parts.append(self._gtts.synthesize(chunk))
            except Exception as e:
                log.warning("gtts_chunk_failed", chunk_preview=chunk[:50], error=str(e))

        if not parts:
            return AudioSegment.silent(duration=500)

        self._active_provider = "gtts"
        return sum(parts[1:], parts[0])

    # -------------------------------------------------------------------------
    # Loudness normalization
    # -------------------------------------------------------------------------

    def _normalize_loudness(self, audio: AudioSegment) -> AudioSegment:
        """
        Normalize to _TARGET_LUFS.
        Primary: pyloudnorm (ITU-R BS.1770-4).
        Fallback: pydub normalize() + gain offset heuristic.
        """
        try:
            import numpy as np
            import pyloudnorm as pyln

            rate = audio.frame_rate
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            channels = audio.channels
            samples = samples.reshape(-1, channels) / (2 ** (audio.sample_width * 8 - 1))

            meter = pyln.Meter(rate)
            loudness = meter.integrated_loudness(samples)

            if loudness == float("-inf"):
                return audio  # silent segment — skip

            gain_db = min(_TARGET_LUFS - loudness, 20.0)  # never boost > +20 dB
            log.debug(
                "loudness_normalized",
                measured_lufs=round(loudness, 1),
                target_lufs=_TARGET_LUFS,
                gain_db=round(gain_db, 1),
            )
            return audio.apply_gain(gain_db)

        except ImportError:
            normalized = audio.normalize()
            offset_db = _TARGET_LUFS - (-14.0)
            log.debug("loudness_normalized_fallback", offset_db=round(offset_db, 1))
            return normalized.apply_gain(offset_db)

        except Exception as e:
            log.warning("loudness_normalization_failed", error=str(e))
            return audio


# ---------------------------------------------------------------------------
# Shared text chunking utility
# ---------------------------------------------------------------------------

def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text at sentence boundaries to stay under max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            if len(sentence) > max_chars:
                # Hard-split oversized single sentence
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i : i + max_chars])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks
