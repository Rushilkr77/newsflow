"""
Agent 5: Audio Producer (Phase 1 — gTTS)
Converts podcast script to MP3 using gTTS for Phase 1 validation.
Phase 2 will upgrade to Chatterbox TTS (HuggingFace) with pydub post-processing.

Flow:
  1. Load podcast_script.json
  2. For each segment, split plain text into chunks
  3. TTS each chunk
  4. Concatenate with silence between segments/articles
  5. Normalize loudness (pyloudnorm → pydub fallback)
  6. Export MP3
"""
import io
import os
import re
import shutil
from pathlib import Path
from typing import Any

import structlog
import yaml
from gtts import gTTS
from pydub import AudioSegment

from models.podcast import Episode, PodcastScript

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Load output config from tts_config.yaml
# ---------------------------------------------------------------------------

def _load_tts_output_config() -> dict[str, Any]:
    config_path = Path(__file__).parent.parent / "config" / "tts_config.yaml"
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        return raw.get("output", {})
    except Exception as e:
        log.warning("tts_config_load_failed", error=str(e), hint="using defaults")
        return {}

_TTS_OUTPUT_CFG = _load_tts_output_config()

_SILENCE_BETWEEN_SEGMENTS_MS: int = _TTS_OUTPUT_CFG.get("silence_between_segments_ms", 1500)
_SILENCE_BETWEEN_ARTICLES_MS: int = _TTS_OUTPUT_CFG.get("silence_between_articles_ms", 800)
_NORMALIZE_LOUDNESS: bool = _TTS_OUTPUT_CFG.get("normalize_loudness", True)
_TARGET_LUFS: float = float(_TTS_OUTPUT_CFG.get("target_lufs", -16))
_OUTPUT_FORMAT: str = _TTS_OUTPUT_CFG.get("format", "mp3")
_OUTPUT_BITRATE: str = str(_TTS_OUTPUT_CFG.get("bitrate", "128k"))

# Ensure pydub can find ffmpeg on Windows after a winget install (PATH not refreshed yet)
def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        return
    # Common winget install location
    winget_base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for pkg in winget_base.glob("Gyan.FFmpeg*"):
        for ffmpeg_bin in pkg.glob("*/bin/ffmpeg.exe"):
            os.environ["PATH"] = str(ffmpeg_bin.parent) + os.pathsep + os.environ.get("PATH", "")
            log.info("ffmpeg_path_set", path=str(ffmpeg_bin.parent))
            return
    log.warning("ffmpeg_not_found", hint="Install via: winget install Gyan.FFmpeg")

_ensure_ffmpeg()


class AudioProducerAgent:
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
                seg_audio = self._text_to_audio(segment.content_plain)
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

        # Export
        episode_number = script.episode_number
        output_path = os.path.join(workspace, f"episode_{episode_number}.mp3")
        full_audio.export(output_path, format=_OUTPUT_FORMAT, bitrate=_OUTPUT_BITRATE)

        file_size = Path(output_path).stat().st_size
        all_source_ids = list(
            {
                sid
                for seg in script.segments
                for sid in seg.source_article_ids
            }
        )

        log.info(
            "audio_producer_complete",
            duration_sec=duration_sec,
            file_path=output_path,
            file_size_mb=round(file_size / 1024 / 1024, 1),
        )

        return Episode(
            episode_number=episode_number,
            date=script.date,
            duration_sec=duration_sec,
            file_path=output_path,
            file_size_bytes=file_size,
            article_count=len(all_source_ids),
            sources_used=list(
                {seg.segment_type for seg in script.segments}
            ),
        )

    def _normalize_loudness(self, audio: AudioSegment) -> AudioSegment:
        """
        Normalize audio to target LUFS.

        Primary: pyloudnorm (ITU-R BS.1770-4 integrated loudness measurement).
        Fallback: pydub normalize() + gain offset heuristic when pyloudnorm is
                  unavailable or numpy is not installed.
        """
        try:
            import numpy as np
            import pyloudnorm as pyln

            rate = audio.frame_rate
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            # pydub stores interleaved samples; reshape to (frames, channels)
            channels = audio.channels
            samples = samples.reshape(-1, channels) / (2 ** (audio.sample_width * 8 - 1))

            meter = pyln.Meter(rate)
            loudness = meter.integrated_loudness(samples)

            if loudness == float("-inf"):
                # Silent segment — skip
                return audio

            gain_db = _TARGET_LUFS - loudness
            # Safety clamp: never boost more than +20 dB (avoids clipping on very quiet clips)
            gain_db = min(gain_db, 20.0)
            log.debug(
                "loudness_normalized",
                measured_lufs=round(loudness, 1),
                target_lufs=_TARGET_LUFS,
                gain_db=round(gain_db, 1),
            )
            return audio.apply_gain(gain_db)

        except ImportError:
            # pyloudnorm / numpy not installed — pydub heuristic fallback
            normalized = audio.normalize()
            # pydub normalize peaks at 0 dBFS ≈ -14 LUFS for speech; offset to target
            offset_db = _TARGET_LUFS - (-14.0)
            log.debug("loudness_normalized_fallback", offset_db=round(offset_db, 1))
            return normalized.apply_gain(offset_db)

        except Exception as e:
            log.warning("loudness_normalization_failed", error=str(e))
            return audio

    def _text_to_audio(self, text: str) -> AudioSegment:
        """Convert plain text to AudioSegment using gTTS, chunked at 500 chars."""
        chunks = self._chunk_text(text, max_chars=500)
        audio_parts: list[AudioSegment] = []

        for chunk in chunks:
            if not chunk.strip():
                continue
            try:
                mp3_bytes = io.BytesIO()
                tts = gTTS(text=chunk, lang="en", slow=False)
                tts.write_to_fp(mp3_bytes)
                mp3_bytes.seek(0)
                audio_parts.append(AudioSegment.from_mp3(mp3_bytes))
            except Exception as e:
                log.warning("gtts_chunk_failed", chunk_preview=chunk[:50], error=str(e))

        if not audio_parts:
            return AudioSegment.silent(duration=500)

        return sum(audio_parts[1:], audio_parts[0])

    def _chunk_text(self, text: str, max_chars: int) -> list[str]:
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
                # If single sentence exceeds limit, split it hard
                if len(sentence) > max_chars:
                    for i in range(0, len(sentence), max_chars):
                        chunks.append(sentence[i : i + max_chars])
                else:
                    current = sentence

        if current:
            chunks.append(current)

        return chunks
