"""
Agent 5: Audio Producer (Phase 1 — gTTS)
Converts podcast script to MP3 using gTTS for Phase 1 validation.
Phase 2 will upgrade to Chatterbox TTS (HuggingFace) with pydub post-processing.

Flow:
  1. Load podcast_script.json
  2. For each segment, split plain text into chunks
  3. TTS each chunk
  4. Concatenate with silence between segments/articles
  5. Export MP3
"""
import io
import os
import re
from pathlib import Path

import structlog
from gtts import gTTS
from pydub import AudioSegment

from models.podcast import Episode, PodcastScript

log = structlog.get_logger(__name__)

_SILENCE_BETWEEN_SEGMENTS_MS = 1500
_SILENCE_BETWEEN_ARTICLES_MS = 800


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
        duration_sec = len(full_audio) // 1000

        # Export
        episode_number = script.episode_number
        output_path = os.path.join(workspace, f"episode_{episode_number}.mp3")
        full_audio.export(output_path, format="mp3", bitrate="128k")

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
