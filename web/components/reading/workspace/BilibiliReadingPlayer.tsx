'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ReadingMediaController } from '@/lib/reading-media-controller'
import { bilibiliEmbedUrl, type BilibiliSource } from '@/lib/reading-video-sources'

/** How long to wait for the embed to load before calling it blocked. */
const EMBED_LOAD_TIMEOUT_MS = 12_000

/**
 * Bilibili playback, within what the platform actually allows.
 *
 * The official external player is a cross-origin iframe with no public
 * JavaScript API. We can *start* it at a timestamp — that is why seeking
 * remounts the frame — but we never learn where it goes afterwards, and we
 * cannot drive play/pause. The controller reports `tracksPosition: false` so
 * the surfaces that follow playback can say so instead of showing a position
 * that never moves.
 */
export function BilibiliReadingPlayer({
  source,
  startSeconds,
  duration,
  title,
  onController,
  onTime,
  onError,
}: {
  source: BilibiliSource
  startSeconds: number
  duration: number
  title: string
  onController(controller: ReadingMediaController | null): void
  onTime(seconds: number, duration: number): void
  onError(error: string): void
}) {
  const { t } = useTranslation()
  const [playerStart, setPlayerStart] = useState(startSeconds)
  const [loaded, setLoaded] = useState(false)
  const timeRef = useRef(startSeconds)

  const controller = useMemo<ReadingMediaController>(
    () => ({
      currentTime: () => timeRef.current,
      duration: () => duration,
      playbackRate: () => 1,
      seek: seconds => {
        const next = Math.min(duration || Number.POSITIVE_INFINITY, Math.max(0, seconds))
        timeRef.current = next
        setPlayerStart(next)
        onTime(next, duration)
      },
      // The cross-origin embed exposes no playback-rate API. Keep the shared
      // controller honest without pretending the command reached Bilibili.
      setPlaybackRate: () => undefined,
      play: () => undefined,
      pause: () => undefined,
      destroy: () => undefined,
      tracksPosition: false,
    }),
    [duration, onTime]
  )

  useEffect(() => {
    onController(controller)
    onTime(timeRef.current, duration)
    return () => onController(null)
  }, [controller, duration, onController, onTime])

  // A blocked embed renders as a silent black rectangle — the iframe's own
  // `onError` does not fire for a frame the remote host refuses to frame. If
  // nothing has loaded by the deadline, say so rather than leaving the reader
  // staring at nothing.
  useEffect(() => {
    if (loaded) return
    const timer = window.setTimeout(() => {
      onError(
        t(
          'This Bilibili video would not load in an embedded player. Open it on Bilibili; DeepTutor can still use its captions.'
        )
      )
    }, EMBED_LOAD_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [loaded, onError, t])

  return (
    <iframe
      src={bilibiliEmbedUrl(source, playerStart)}
      title={title}
      className="aspect-video h-full w-full border-0 bg-black"
      allow="autoplay; fullscreen; picture-in-picture"
      allowFullScreen
      loading="eager"
      referrerPolicy="strict-origin-when-cross-origin"
      onLoad={() => setLoaded(true)}
      onError={() => onError(t('This Bilibili video could not be loaded.'))}
    />
  )
}
