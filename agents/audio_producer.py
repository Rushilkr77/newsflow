"""
Agent 5: Audio Producer
Converts podcast script to MP3. Primary: Google Cloud TTS Neural2 (cloud, free tier 4M chars/mo).
Fallback: Chatterbox TTS (local, HuggingFace). Last resort: gTTS.

Flow:
  1. Load podcast_script.json
  2. For each segment, route to TTS provider (gcloud primary, chatterbox fallback, gtts last resort)
  3. GCloud: send content_ssml wrapped in <speak>; Chatterbox/F5: plain text chunks ≤300 chars
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
_GCLOUD_CFG: dict = _TTS_CFG.get("gcloud", {})
_OUTPUT_CFG: dict = _TTS_CFG.get("output", {})

_PRIMARY_PROVIDER: str = _PRIMARY_CFG.get("provider", "chatterbox")
_FALLBACK_PROVIDER: str = _FALLBACK_CFG.get("provider", "f5_tts")

_SILENCE_BETWEEN_SEGMENTS_MS: int = _OUTPUT_CFG.get("silence_between_segments_ms", 1500)
_SILENCE_BETWEEN_ARTICLES_MS: int = _OUTPUT_CFG.get("silence_between_articles_ms", 150)
_HONOR_SSML_BREAKS: bool = _OUTPUT_CFG.get("honor_ssml_breaks", False)
_TRIM_SILENCE: bool = _OUTPUT_CFG.get("trim_silence", True)
_NORMALIZE_LOUDNESS: bool = _OUTPUT_CFG.get("normalize_loudness", True)
_TARGET_LUFS: float = float(_OUTPUT_CFG.get("target_lufs", -16))
_OUTPUT_FORMAT: str = _OUTPUT_CFG.get("format", "mp3")
_OUTPUT_BITRATE: str = str(_OUTPUT_CFG.get("bitrate", "128k"))

_CLEANUP_CFG: dict = _TTS_CFG.get("cleanup", {})
_CLEANUP_ENABLED: bool = _CLEANUP_CFG.get("enabled", True)
_NOISE_REDUCE_PROP: float = float(_CLEANUP_CFG.get("noise_reduce_prop", 0.75))
_HIGHPASS_HZ: int = int(_CLEANUP_CFG.get("highpass_hz", 80))

# Max chars per TTS call per provider (from tts_config.yaml)
_CHATTERBOX_MAX_CHARS: int = _PRIMARY_CFG.get("params", {}).get("max_chars_per_call", 300)

# Per-segment provider routing: segment_type → provider name
# Loaded from tts_config.yaml segment_routing block.
_DEFAULT_LONG_SEGMENTS: frozenset = frozenset({"ai_updates", "funding", "india_tech", "product_strategy"})
_SEGMENT_ROUTING: dict[str, str] = {}
for _provider_key, _segments in _TTS_CFG.get("segment_routing", {}).items():
    for _seg in (_segments or []):
        _SEGMENT_ROUTING[_seg] = _provider_key

# Providers are disabled when no segments are assigned to them.
_CHATTERBOX_DISABLED: bool = not _TTS_CFG.get("segment_routing", {}).get("chatterbox")
_F5TTS_DISABLED: bool = not _TTS_CFG.get("segment_routing", {}).get("f5_tts")
_GCLOUD_DISABLED: bool = not _TTS_CFG.get("segment_routing", {}).get("gcloud")


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
        if getattr(self, "_permanently_failed", False):
            raise RuntimeError("Chatterbox disabled after prior load failure")
        if self._model is None:
            from chatterbox.tts import ChatterboxTTS  # type: ignore[import]
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                elif torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
            except ImportError:
                device = "cpu"
            log.info("chatterbox_model_loading", device=device)
            try:
                self._model = ChatterboxTTS.from_pretrained(device=device)
            except Exception:
                self._permanently_failed = True
                raise
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
        if getattr(self, "_permanently_failed", False):
            raise RuntimeError("F5-TTS disabled after prior load failure")
        if self._model is None:
            from f5_tts.api import F5TTS  # type: ignore[import]
            log.info("f5tts_model_loading", model_type=self.model_type)
            try:
                self._model = F5TTS(model=self.model_type)
            except Exception:
                self._permanently_failed = True
                raise
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
            import f5_tts as _f5_pkg
            # f5_tts is a namespace package (__file__ is None), use __path__ instead
            ref_dir = Path(list(_f5_pkg.__path__)[0]) / "infer" / "examples" / "basic"
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


class GCloudProvider:
    """Google Cloud TTS Neural2 — primary provider (4M chars/mo free tier).

    Requires GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service-account JSON
    (or a GCP API key via GOOGLE_TTS_API_KEY). install: pip install google-cloud-texttospeech
    """

    def __init__(self, params: dict):
        self._voice_name: str = params.get("voice_name", "en-US-Neural2-J")
        self._language_code: str = params.get("language_code", "en-US")
        self._speaking_rate: float = float(params.get("speaking_rate", 0.92))
        self._pitch: float = float(params.get("pitch", -1.0))
        self._sample_rate: int = int(params.get("sample_rate_hertz", 24000))
        effects_cfg = params.get("effects_profile_id", [])
        self._effects_profile: list[str] = effects_cfg if isinstance(effects_cfg, list) else [effects_cfg]
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import texttospeech  # type: ignore[import]
            api_key = os.getenv("GOOGLE_TTS_API_KEY")
            if api_key:
                from google.api_core import gapic_v1
                self._client = texttospeech.TextToSpeechClient(
                    client_options={"api_key": api_key}
                )
            else:
                self._client = texttospeech.TextToSpeechClient()
        return self._client

    def synthesize(self, text: str, is_ssml: bool = False) -> AudioSegment:
        from google.cloud import texttospeech  # type: ignore[import]

        client = self._get_client()
        if is_ssml:
            synth_input = texttospeech.SynthesisInput(ssml=text)
        else:
            synth_input = texttospeech.SynthesisInput(text=text)

        voice = texttospeech.VoiceSelectionParams(
            language_code=self._language_code,
            name=self._voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            speaking_rate=self._speaking_rate,
            pitch=self._pitch,
            sample_rate_hertz=self._sample_rate,
            effects_profile_id=self._effects_profile,
        )
        response = client.synthesize_speech(
            input=synth_input, voice=voice, audio_config=audio_config
        )
        return AudioSegment.from_wav(io.BytesIO(response.audio_content))


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------

class AudioProducerAgent:
    def __init__(self):
        self._chatterbox: ChatterboxProvider | None = None
        self._f5tts: F5TTSProvider | None = None
        self._gtts: GTTSProvider | None = None
        self._gcloud: GCloudProvider | None = None
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
                ssml_src = segment.content_ssml if _HONOR_SSML_BREAKS else None
                seg_audio = self._segment_to_audio(segment.content_plain, segment.segment_type, ssml_src)
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

        # Duration quality checks (target 40-50 min)
        if duration_sec < 1200:  # < 20 min — likely TTS failure
            log.warning("episode_too_short", duration_sec=duration_sec, min_expected_sec=1200)
        elif duration_sec > 4200:  # > 70 min
            log.warning("episode_too_long", duration_sec=duration_sec, max_expected_sec=4200)

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

    def _segment_to_audio(self, text: str, segment_type: str = "", ssml: str | None = None) -> AudioSegment:
        """
        Route each segment to its designated TTS provider, then fall back if needed.

        Routing (from tts_config.yaml segment_routing, with hardcoded defaults):
          Chatterbox — opener, quick_hits, closing, ai_updates, funding, india_tech, product_strategy
          F5-TTS     — (none by default; assign segments in tts_config.yaml to enable)

        Fallback chain: designated provider → other provider → gTTS

        ssml: when provided and honor_ssml_breaks is True, <break> tags are converted to
              actual silence intervals between TTS chunks for non-SSML providers.
        """
        designated = _SEGMENT_ROUTING.get(
            segment_type,
            "f5_tts" if segment_type in _DEFAULT_LONG_SEGMENTS else "chatterbox",
        )
        log.info("tts_provider_selected", segment_type=segment_type, provider=designated)

        def chatterbox_fn(t: str) -> AudioSegment:
            return self._synthesize_chatterbox(t, ssml=ssml)

        def gcloud_fn(t: str) -> AudioSegment:
            return self._synthesize_gcloud(t, ssml=ssml)

        # Build [primary, fallback, last_resort] based on config + disabled flags.
        # gTTS is always the last-resort if it hasn't been selected as an earlier tier.
        if designated == "gcloud" and not _GCLOUD_DISABLED:
            candidates = [gcloud_fn]
            if not _CHATTERBOX_DISABLED:
                candidates.append(chatterbox_fn)
            elif not _F5TTS_DISABLED:
                candidates.append(self._synthesize_f5tts)
            candidates.append(self._synthesize_gtts)
        elif _CHATTERBOX_DISABLED and _F5TTS_DISABLED and _GCLOUD_DISABLED:
            candidates = [self._synthesize_gtts]
        elif designated == "chatterbox" and not _CHATTERBOX_DISABLED:
            candidates = [chatterbox_fn, self._synthesize_gtts]
        elif _CHATTERBOX_DISABLED:
            candidates = [self._synthesize_f5tts, self._synthesize_gtts]
        elif _F5TTS_DISABLED:
            candidates = [chatterbox_fn, self._synthesize_gtts]
        else:
            candidates = [self._synthesize_f5tts, chatterbox_fn, self._synthesize_gtts]

        last_err: Exception = RuntimeError("no candidates")
        for fn in candidates:
            try:
                result = fn(text)
                return result
            except Exception as e:
                log.warning("tts_provider_failed", provider=fn.__name__ if hasattr(fn, "__name__") else str(fn), error=str(e))
                last_err = e

        raise last_err

    def _synthesize_chatterbox(self, text: str, ssml: str | None = None) -> AudioSegment:
        if self._chatterbox is None:
            self._chatterbox = ChatterboxProvider(_PRIMARY_CFG.get("params", {}))

        # When honor_ssml_breaks is on and SSML content available, split on <break> tags
        # and insert corresponding silence between synthesized chunks.
        if ssml and _HONOR_SSML_BREAKS:
            chunks_with_pauses = _split_on_ssml_breaks(ssml)
        else:
            chunks_with_pauses = [(chunk, _SILENCE_BETWEEN_ARTICLES_MS) for chunk in _chunk_text(text, max_chars=_CHATTERBOX_MAX_CHARS)]

        parts: list[AudioSegment] = []
        for chunk_text_content, trailing_silence_ms in chunks_with_pauses:
            for sub_chunk in _chunk_text(chunk_text_content, max_chars=_CHATTERBOX_MAX_CHARS):
                if not sub_chunk.strip():
                    continue
                audio = self._chatterbox.synthesize(sub_chunk)
                if _TRIM_SILENCE:
                    audio = self._trim_silence(audio)
                audio = self._clean_audio(audio)
                parts.append(audio)
            if parts and trailing_silence_ms > 0:
                parts.append(AudioSegment.silent(duration=trailing_silence_ms))

        if not parts:
            return AudioSegment.silent(duration=500)

        self._active_provider = "chatterbox"
        return sum(parts[1:], parts[0])

    def _synthesize_gcloud(self, text: str, ssml: str | None = None) -> AudioSegment:
        """Google Cloud TTS Neural2. Sends full SSML when available (GCloud handles it natively).

        GCloud limit is 5000 bytes/request — much larger than Chatterbox chunks, so we only
        split if the content exceeds 4500 chars. SSML breaks are handled by GCloud natively;
        no need for _split_on_ssml_breaks here.
        """
        if self._gcloud is None:
            self._gcloud = GCloudProvider(_GCLOUD_CFG.get("params", _GCLOUD_CFG))

        parts: list[AudioSegment] = []
        silence = AudioSegment.silent(duration=_SILENCE_BETWEEN_ARTICLES_MS)

        if ssml and _HONOR_SSML_BREAKS:
            # Escape bare & that appear in text nodes (e.g. "R&D") — invalid XML otherwise.
            # Only escape & not already part of an entity reference (&amp; &lt; etc).
            ssml = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', ssml)
            # Wrap in <speak> root as GCloud requires, then send as one SSML request
            # (or chunk if extremely long — GCloud 5000-byte limit is generous).
            _GCLOUD_MAX_BYTES = 4500
            content = f"<speak>{ssml}</speak>"
            if len(content.encode()) <= _GCLOUD_MAX_BYTES:
                audio = self._synthesize_gcloud_chunk(content, is_ssml=True)
                parts.append(audio)
            else:
                # Split on breaks for chunking, send each chunk as SSML
                for chunk_text_content, trailing_ms in _split_on_ssml_breaks(ssml):
                    chunk_ssml = f"<speak>{chunk_text_content}</speak>"
                    audio = self._synthesize_gcloud_chunk(chunk_ssml, is_ssml=True)
                    parts.append(audio)
                    if trailing_ms > 0:
                        parts.append(AudioSegment.silent(duration=trailing_ms))
        else:
            for chunk in _chunk_text(text, max_chars=4000):
                if not chunk.strip():
                    continue
                audio = self._synthesize_gcloud_chunk(chunk, is_ssml=False)
                if parts:
                    parts.append(silence)
                parts.append(audio)

        if not parts:
            return AudioSegment.silent(duration=500)

        self._active_provider = "gcloud"
        return sum(parts[1:], parts[0])

    def _synthesize_gcloud_chunk(self, text: str, is_ssml: bool) -> AudioSegment:
        """Single GCloud TTS API call. On SSML rejection, retries with plain text."""
        try:
            return self._gcloud.synthesize(text, is_ssml=is_ssml)  # type: ignore[union-attr]
        except Exception as e:
            if is_ssml and "Invalid SSML" in str(e):
                plain = re.sub(r"<[^>]+>", "", text).strip()
                log.warning("gcloud_ssml_invalid_retry_plain", chars=len(plain), error=str(e)[:80])
                return self._gcloud.synthesize(plain, is_ssml=False)  # type: ignore[union-attr]
            raise

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
            audio = self._trim_silence(audio)
            audio = self._clean_audio(audio)
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
    # Per-chunk silence trimming and noise cleanup
    # -------------------------------------------------------------------------

    def _trim_silence(self, audio: AudioSegment, threshold_db: float = -40.0, chunk_ms: int = 10) -> AudioSegment:
        """Trim Chatterbox trailing/leading silence from each synthesized chunk."""
        from pydub.silence import detect_leading_silence
        start_trim = detect_leading_silence(audio, silence_threshold=threshold_db, chunk_size=chunk_ms)
        end_trim = detect_leading_silence(audio.reverse(), silence_threshold=threshold_db, chunk_size=chunk_ms)
        duration = len(audio)
        if start_trim + end_trim >= duration:
            return audio  # all silence — preserve as-is
        return audio[start_trim : duration - end_trim]

    def _clean_audio(self, audio: AudioSegment) -> AudioSegment:
        """Spectral noise reduction + high-pass filter for Chatterbox static cleanup."""
        if not _CLEANUP_ENABLED:
            return audio
        try:
            import numpy as np
            import noisereduce as nr

            rate = audio.frame_rate
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
            samples /= 2 ** (audio.sample_width * 8 - 1)

            reduced = nr.reduce_noise(
                y=samples,
                sr=rate,
                stationary=False,
                prop_decrease=_NOISE_REDUCE_PROP,
            )

            reduced_int16 = (reduced * 32767).clip(-32768, 32767).astype(np.int16)
            cleaned = audio._spawn(
                reduced_int16.tobytes(),
                overrides={"sample_width": 2, "frame_rate": rate, "channels": audio.channels},
            )
            cleaned = cleaned.high_pass_filter(_HIGHPASS_HZ)
            log.debug("audio_cleanup_applied", noise_reduce_prop=_NOISE_REDUCE_PROP, highpass_hz=_HIGHPASS_HZ)
            return cleaned
        except ImportError:
            log.warning("audio_cleanup_fallback", reason="noisereduce not installed — applying highpass only")
            return audio.high_pass_filter(_HIGHPASS_HZ)
        except Exception as e:
            log.warning("audio_cleanup_failed", error=str(e))
            return audio

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

def _split_on_ssml_breaks(ssml: str) -> list[tuple[str, int]]:
    """Split SSML content on <break> tags, returning (plain_text, trailing_silence_ms) pairs.

    Strips all other SSML tags so each plain_text chunk is clean for TTS.
    The trailing_silence_ms is the duration of the <break> that follows the chunk.
    The final chunk has no trailing break, so its silence defaults to 0.
    """
    import re as _re
    _BREAK_RE = _re.compile(r'<break\s+time="(\d+)ms"\s*/>', _re.IGNORECASE)
    _TAG_RE = _re.compile(r"<[^>]+>")

    parts = _BREAK_RE.split(ssml)
    # _BREAK_RE.split alternates: [text, ms, text, ms, ..., text]
    result: list[tuple[str, int]] = []
    i = 0
    while i < len(parts):
        raw_chunk = parts[i]
        plain = _TAG_RE.sub("", raw_chunk).strip()
        trailing_ms = int(parts[i + 1]) if i + 1 < len(parts) else 0
        if plain:
            result.append((plain, trailing_ms))
        i += 2

    return result if result else [(_TAG_RE.sub("", ssml).strip(), 0)]


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
