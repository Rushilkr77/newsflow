'use client'

import { useState, useRef, useEffect, useCallback } from 'react'

interface AudioPlayerProps {
  src?: string
  title?: string
  className?: string
}

function PlayIcon() {
  return (
    <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor" aria-hidden>
      <path d="M0 1.5C0 0.672 0.895 0.167 1.6 0.6l10 6a1 1 0 0 1 0 1.8l-10 6C0.895 14.833 0 14.328 0 13.5v-12z" />
    </svg>
  )
}

function PauseIcon() {
  return (
    <svg width="11" height="13" viewBox="0 0 11 13" fill="currentColor" aria-hidden>
      <rect x="0" y="0" width="4" height="13" rx="1" />
      <rect x="7" y="0" width="4" height="13" rx="1" />
    </svg>
  )
}

function formatTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function AudioPlayer({
  src,
  title = 'Sample episode',
  className = '',
}: AudioPlayerProps) {
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState<number | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [hasError, setHasError] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)

  const toggle = useCallback(() => {
    const audio = audioRef.current
    if (!audio || hasError) return
    if (playing) {
      audio.pause()
    } else {
      audio.play().catch(() => setHasError(true))
    }
    setPlaying((p) => !p)
  }, [playing, hasError])

  const seek = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current
    const track = progressRef.current
    if (!audio || !track || !duration) return
    const rect = track.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    audio.currentTime = ratio * duration
    setCurrentTime(audio.currentTime)
  }, [duration])

  const progress = duration ? currentTime / duration : 0

  const displayDuration = duration !== null ? formatTime(duration) : '2:00'
  const displayCurrent = currentTime > 0 ? formatTime(currentTime) : null

  return (
    <div className={`flex items-center gap-4 ${className}`}>
      {src && (
        <audio
          ref={audioRef}
          src={src}
          onLoadedMetadata={() => setDuration(audioRef.current?.duration ?? null)}
          onTimeUpdate={() => setCurrentTime(audioRef.current?.currentTime ?? 0)}
          onEnded={() => { setPlaying(false); setCurrentTime(0) }}
          onError={() => setHasError(true)}
          preload="metadata"
        />
      )}

      <button
        onClick={toggle}
        className="play-btn"
        aria-label={playing ? 'Pause' : 'Play sample episode'}
        disabled={hasError}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-2">
          <span className="font-serif text-sm text-ink leading-none">{title}</span>
          <span className="font-mono text-2xs text-ink-muted leading-none">
            {displayCurrent ? `${displayCurrent} / ${displayDuration}` : displayDuration}
          </span>
        </div>
        {/* Progress track */}
        <div
          ref={progressRef}
          className="progress-track"
          onClick={seek}
          role="progressbar"
          aria-valuenow={Math.round(progress * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="progress-fill"
            style={{ transform: `scaleX(${progress})` }}
          />
        </div>
      </div>
    </div>
  )
}
