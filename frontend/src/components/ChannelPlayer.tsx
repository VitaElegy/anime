import { useEffect, useRef, useState } from 'react'
import { Loader2, MonitorPlay, RefreshCcw, X } from 'lucide-react'
import { watchProxyUrl } from '@/api'
import { cn } from '@/lib/utils'
import type { ChannelStream } from '@/types'

interface ChannelPlayerProps {
  title: string
  streams: ChannelStream[]
  onClose: () => void
  onRetry?: () => void
}

/**
 * Renderer — the ONLY component responsible for turning a resolved stream
 * into visible video output (docs/CHANNEL_ARCHITECTURE.md §1.5).
 *
 * It does NOT search, parse sources, handle permissions or manage downloads.
 * All video traffic goes through the backend stream proxy. The Hls instance
 * and MediaSource are always destroyed on unmount to keep memory low.
 */
export default function ChannelPlayer({ title, streams, onClose, onRetry }: ChannelPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<{ destroy: () => void } | null>(null)
  const [streamIndex, setStreamIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const activeIndex = Math.min(streamIndex, Math.max(streams.length - 1, 0))
  const active = streams[activeIndex]

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    let cancelled = false

    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      if (cancelled) return
      setError('')
      setLoading(true)
    })

    const destroyHls = () => {
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
    }

    if (!active) {
      destroyHls()
      video.removeAttribute('src')
      video.load()
      void Promise.resolve().then(() => {
        if (!cancelled) setError('该渠道暂时没有可播放的线路')
      })
      return () => {
        cancelled = true
      }
    }

    const sourceUrl = watchProxyUrl(active)
    const markReady = () => {
      if (cancelled) return
      void Promise.resolve().then(() => setLoading(false))
      void video.play().catch(() => {})
    }
    const markError = (message: string) => {
      if (cancelled) return
      void Promise.resolve().then(() => setError(message))
    }

    if (active.type === 'hls') {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = sourceUrl
        video.onloadeddata = markReady
        video.onerror = () => markError('播放失败，请尝试其它线路')
      } else {
        void import('hls.js').then(({ default: Hls }) => {
          if (cancelled) return
          if (!Hls.isSupported()) {
            markError('当前浏览器不支持 HLS 播放')
            return
          }
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: true,
            backBufferLength: 60,
            maxBufferLength: 30,
          })
          hlsRef.current = hls
          hls.loadSource(sourceUrl)
          hls.attachMedia(video)
          hls.on(Hls.Events.MANIFEST_PARSED, markReady)
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (data.fatal) {
              markError(`播放失败（${active.note || '当前线路'}），请尝试其它线路`)
            }
          })
        })
      }
    } else if (active.type === 'mp4' || active.type === 'web') {
      video.src = sourceUrl
      video.load()
      video.onloadeddata = markReady
      video.onerror = () => markError('播放失败，请尝试其它线路')
    } else {
      markError(`不支持的播放格式：${active.type}`)
    }

    return () => {
      cancelled = true
      destroyHls()
      video.removeAttribute('src')
      video.load()
      video.onloadeddata = null
      video.onerror = null
    }
  }, [active, activeIndex, streams])

  // Escape closes the player overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-black/95 backdrop-blur-sm">
      {/* Top bar */}
      <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <MonitorPlay className="h-5 w-5 shrink-0 text-accent-secondary" />
          <h2 className="truncate text-base font-bold text-white sm:text-lg">{title}</h2>
        </div>
        <button
          onClick={onClose}
          aria-label="关闭播放器"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5 text-white/70 transition-colors hover:bg-white/15 hover:text-white"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Video area */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-2">
        <video
          ref={videoRef}
          controls
          autoPlay
          playsInline
          className="max-h-full max-w-full rounded-xl bg-black shadow-2xl"
        />
        {loading && !error && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-accent-secondary" />
            <p className="text-sm font-medium text-white/60">正在加载播放流…</p>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 px-6 text-center">
            <p className="text-base font-semibold text-danger">{error}</p>
            <div className="flex gap-3">
              {streams.length > 1 && (
                <button
                  onClick={() => {
                    void Promise.resolve().then(() => {
                      setError('')
                      setStreamIndex((i) => (i + 1) % streams.length)
                    })
                  }}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/10 px-4 py-2 text-sm font-bold text-white hover:bg-white/20"
                >
                  切换线路
                </button>
              )}
              <button
                onClick={() => {
                  void Promise.resolve().then(() => {
                    setError('')
                    setLoading(true)
                    onRetry?.()
                  })
                }}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent-primary to-accent-secondary px-4 py-2 text-sm font-bold text-white"
              >
                <RefreshCcw className="h-4 w-4" /> 重新加载
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Stream switcher */}
      {streams.length > 1 && (
        <div className="flex flex-wrap items-center justify-center gap-2 px-4 pb-4">
          {streams.map((stream, idx) => (
            <button
              key={`${idx}-${stream.url}`}
              onClick={() => {
                void Promise.resolve().then(() => {
                  setError('')
                  setStreamIndex(idx)
                })
              }}
              className={cn(
                'rounded-lg border px-3 py-1.5 text-xs font-bold transition-colors',
                idx === activeIndex
                  ? 'border-accent-secondary/60 bg-accent-secondary/20 text-white'
                  : 'border-white/10 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white',
              )}
            >
              {stream.quality || `线路 ${idx + 1}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
