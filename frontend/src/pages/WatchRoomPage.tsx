import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Copy, Loader2, MessageSquare, Pause, Play, RefreshCw, Tv, Users, Settings2, PlayCircle, HardDrive, FastForward, SkipForward, Film, Activity, Volume2, VolumeX, Gauge } from 'lucide-react'
import {
  getMediaAsset,
  getRoomMessages,
  getWatchLobby,
  getWatchResume,
  getWatchRoom,
  heartbeatPresence,
  listMediaLibrary,
  prepareMediaHls,
  scanMediaLibrary,
  sendRoomInvitation,
  sendRoomMessage,
  syncWatchProgress,
  updateWatchRoomState,
} from '@/api'
import { useAuth } from '@/contexts/useAuth'
import type { FriendSummary, MediaAsset, OnlineUser, RoomInvitation, RoomMessage, WatchHistoryItem, WatchRoom } from '@/types'
import { cn, formatBytes } from '@/lib/utils'
import { useRoomEventStream } from '@/lib/useRoomEventStream'
import {
  extractErrorMessage,
  extractErrorStatus,
  formatDateTime,
  formatPosition,
  formatRelativeTime,
  getAssetBlockReason as blockReason,
  isAssetBlocked as isBlocked,
  shortError,
  socialStatusText,
} from '@/lib/watchFormatters'

export default function WatchRoomPage() {
  const { roomId = '' } = useParams()
  const { user } = useAuth()
  const roomRef = useRef<WatchRoom | null>(null)
  const personalHistoryRef = useRef<WatchHistoryItem | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  // Track the video element's mounted state so the playback-src effect can
  // re-run once React swaps the placeholder for the real <video>. Without
  // this, `videoRef.current` flips null → Element silently and the src
  // assignment in the effect below is missed entirely.
  const [videoElementReady, setVideoElementReady] = useState(false)
  const setVideoNode = useCallback((node: HTMLVideoElement | null) => {
    videoRef.current = node
    setVideoElementReady(Boolean(node))
  }, [])
  const roomChatListRef = useRef<HTMLDivElement | null>(null)
  const hlsRef = useRef<{ destroy: () => void } | null>(null)
  const personalSyncRunningRef = useRef(false)

  // --- Activity feed ---------------------------------------------------------
  // Small ephemeral toasts shown above the video ("alice 暂停了视频",
  // "bob 切到了 EP02" etc.) so everyone in the room can see who is driving
  // the session. Built purely from diffs of successive `room.state` snapshots
  // — no new backend API, no server-side event stream.
  type RoomActivity = {
    id: number
    actor: string
    kind: 'pause' | 'resume' | 'seek' | 'rate' | 'media' | 'mode'
    message: string
    at: number
  }
  const [activities, setActivities] = useState<RoomActivity[]>([])
  const prevRoomStateRef = useRef<WatchRoom['state'] | null>(null)
  const activityIdRef = useRef(0)
  // Short-lived memo of actor+kind so rapid scrubs / repeated rate tweaks
  // collapse into one toast instead of spamming the feed.
  const lastActivityRef = useRef<Map<string, number>>(new Map())

  // Shown when the browser blocks both unmuted AND muted autoplay — a large
  // overlay that, on click, triggers a real play() within a user gesture.
  const [needsPlayUnlock, setNeedsPlayUnlock] = useState(false)

  // Custom control bar driven by timeupdate / durationchange / volumechange —
  // we no longer expose native <video controls>, so we own rendering of the
  // play button, progress slider, volume and rate menu.
  const [playerUI, setPlayerUI] = useState({
    currentTime: 0,
    duration: 0,
    muted: false,
    volume: 1,
  })
  const pendingSeekRef = useRef<number | null>(null)
  const roomPresenceReadyRef = useRef(true)
  const roomPresenceRequestRef = useRef<Promise<boolean> | null>(null)
  const roomPresenceContextRef = useRef('')

  const [room, setRoom] = useState<WatchRoom | null>(null)
  const [asset, setAsset] = useState<MediaAsset | null>(null)
  const [personalHistory, setPersonalHistory] = useState<WatchHistoryItem | null>(null)
  const [libraryAssets, setLibraryAssets] = useState<MediaAsset[]>([])
  const [assetQuery, setAssetQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [switchingMediaId, setSwitchingMediaId] = useState('')
  const [playerHint, setPlayerHint] = useState('')
  const [roomLoadError, setRoomLoadError] = useState('')
  const [assetLoadError, setAssetLoadError] = useState('')
  const [socialLoadError, setSocialLoadError] = useState('')
  const [roomChatError, setRoomChatError] = useState('')
  const [socialReady, setSocialReady] = useState(false)
  const [roomChatReady, setRoomChatReady] = useState(false)
  const [roomParticipants, setRoomParticipants] = useState<OnlineUser[]>([])
  const [friends, setFriends] = useState<FriendSummary[]>([])
  const [outgoingInvites, setOutgoingInvites] = useState<RoomInvitation[]>([])
  const [inviteMessage, setInviteMessage] = useState('')
  const [invitingFriendId, setInvitingFriendId] = useState(0)
  const [roomMessages, setRoomMessages] = useState<RoomMessage[]>([])
  const [roomMessageDraft, setRoomMessageDraft] = useState('')
  const [sendingRoomMessage, setSendingRoomMessage] = useState(false)
  const [roomPresenceReady, setRoomPresenceReady] = useState(true)
  const [roomPresencePending, setRoomPresencePending] = useState(false)
  const [roomPresenceError, setRoomPresenceError] = useState('')

  const loadLibrary = useCallback(async (forceScan = false) => {
    setLibraryLoading(true)
    try {
      const response = forceScan ? await scanMediaLibrary() : await listMediaLibrary()
      setLibraryAssets(response.items)
    } catch {
      /* 片源库加载失败时保留旧快照，不阻塞房间页面 */
    } finally {
      setLibraryLoading(false)
    }
  }, [])

  const load = useCallback(async (silent = false) => {
    try {
      const nextRoom = await getWatchRoom(roomId)
      setRoom(nextRoom)
      setRoomLoadError('')
      if (nextRoom.state.media_id) {
        const [nextAsset, nextHistory] = await Promise.allSettled([
          getMediaAsset(nextRoom.state.media_id),
          user ? getWatchResume(nextRoom.room_id, nextRoom.state.media_id).catch(() => null) : Promise.resolve(null),
        ])

        if (nextAsset.status === 'fulfilled') {
          setAsset(nextAsset.value)
          setAssetLoadError('')
        } else {
          const message = extractErrorMessage(nextAsset.reason)
          setAssetLoadError(message)
          setAsset((current) => (current?.media_id === nextRoom.state.media_id ? current : null))
        }

        if (nextHistory.status === 'fulfilled') {
          setPersonalHistory(nextHistory.value)
        } else {
          const canReuseHistory = Boolean(
            personalHistoryRef.current &&
            personalHistoryRef.current.room_id === nextRoom.room_id &&
            personalHistoryRef.current.media_id === nextRoom.state.media_id
          )
          if (!canReuseHistory) {
            setPersonalHistory(null)
          }
        }
      } else {
        setAsset(null)
        setAssetLoadError('')
        setPersonalHistory(null)
      }
    } catch (error) {
      const status = extractErrorStatus(error)
      const message = extractErrorMessage(error)
      setRoomLoadError(message)
      if (status === 404 || !roomRef.current) {
        setRoom(null)
        setAsset(null)
        setAssetLoadError('')
        setPersonalHistory(null)
        setRoomParticipants([])
        setFriends([])
        setOutgoingInvites([])
        setRoomMessages([])
        setSocialReady(false)
        setRoomChatReady(false)
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }, [roomId, user])

  const loadSocialContext = useCallback(async () => {
    try {
      const overview = await getWatchLobby()
      setRoomParticipants(overview.online_users.filter((item) => item.current_room_id === roomId))
      setFriends(overview.friends || [])
      setOutgoingInvites(overview.outgoing_room_invitations || [])
      setSocialReady(true)
      setSocialLoadError('')
    } catch (error) {
      setSocialLoadError(extractErrorMessage(error))
    } finally {
      /* noop */
    }
  }, [roomId])

  const loadRoomChat = useCallback(async () => {
    try {
      const messages = await getRoomMessages(roomId, 100)
      setRoomMessages(messages)
      setRoomChatReady(true)
      setRoomChatError('')
    } catch (error) {
      setRoomChatError(extractErrorMessage(error))
    } finally {
      /* noop */
    }
  }, [roomId])

  useEffect(() => {
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => { void load(false) })
  }, [load])

  useRoomEventStream(roomId, Boolean(roomId), {
    onRoomState: (nextRoom) => {
      setRoom((current) => {
        const mediaChanged = !current || current.state.media_id !== nextRoom.state.media_id
        if (mediaChanged) {
          void load(true)
        }
        return nextRoom
      })
      setRoomLoadError('')
    },
    onRoomMessage: (message) => {
      setRoomMessages((items) => {
        if (items.some((item) => item.message_id === message.message_id)) return items
        const enriched = { ...message, is_mine: Boolean(user && message.sender_user_id === user.id) }
        return [...items, enriched]
      })
    },
  })

  useEffect(() => {
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => { void loadLibrary() })
  }, [loadLibrary, roomId])

  useEffect(() => {
    roomRef.current = room
  }, [room])

  useEffect(() => {
    personalHistoryRef.current = personalHistory
  }, [personalHistory])

  useEffect(() => {
    roomPresenceReadyRef.current = roomPresenceReady
  }, [roomPresenceReady])

  useEffect(() => {
    roomPresenceContextRef.current = `${room?.room_id || ''}:${user?.id || 0}`
  }, [room?.room_id, user?.id])

  const currentRoomId = room?.room_id || ''
  const ownerUserId = room?.owner_user_id || 0
  const currentUserId = user?.id || 0

  useEffect(() => {
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      setRoomParticipants([])
      setFriends([])
      setOutgoingInvites([])
      setRoomMessages([])
      setInviteMessage('')
      setRoomMessageDraft('')
      setRoomLoadError('')
      setAssetLoadError('')
      setSocialLoadError('')
      setRoomChatError('')
      setSocialReady(false)
      setRoomChatReady(false)
    })
  }, [roomId])

  useEffect(() => {
    const requiresRoomPresence = Boolean(currentUserId && currentRoomId && ownerUserId !== currentUserId)
    roomPresenceRequestRef.current = null
    roomPresenceReadyRef.current = !requiresRoomPresence
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => {
      setRoomPresenceReady(!requiresRoomPresence)
      setRoomPresencePending(requiresRoomPresence)
      setRoomPresenceError('')
    })
  }, [currentRoomId, currentUserId, ownerUserId])

  useEffect(() => {
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => { void loadSocialContext() })
    const timer = window.setInterval(() => {
      void loadSocialContext()
    }, 12000)
    return () => window.clearInterval(timer)
  }, [loadSocialContext, user?.id])

  useEffect(() => {
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => { void loadRoomChat() })
  }, [loadRoomChat, user?.id])

  const assetBlocked = isBlocked(asset)
  const assetBlockReason = blockReason(asset)
  const isOwner = Boolean(user && room && room.owner_user_id === user.id)
  const resumeOffset = personalHistory && room ? Math.abs(personalHistory.position_seconds - room.state.position_seconds) : 0
  const inviteableFriends = friends.filter((friend) => friend.user_id !== user?.id)
  const currentRoomParticipantIds = new Set(roomParticipants.map((item) => item.user_id))
  const outgoingInviteFriendIds = new Set(
    outgoingInvites
      .filter((item) => item.room_id === roomId && item.status === 'pending')
      .map((item) => item.recipient_user_id)
  )
  const normalizedAssetQuery = assetQuery.trim().toLowerCase()
  const candidateAssets = [...libraryAssets]
    .sort((left, right) => {
      const leftCurrent = room && left.media_id === room.state.media_id ? 1 : 0
      const rightCurrent = room && right.media_id === room.state.media_id ? 1 : 0
      const leftWatchable = isBlocked(left) ? 0 : 1
      const rightWatchable = isBlocked(right) ? 0 : 1
      return rightCurrent - leftCurrent || rightWatchable - leftWatchable || right.modified_at - left.modified_at
    })
    .filter((item) => {
      if (!normalizedAssetQuery) return true
      const haystack = `${item.title} ${item.relative_path}`.toLowerCase()
      return haystack.includes(normalizedAssetQuery)
    })
    .slice(0, 8)

  const syncPersonalProgress = useCallback(async (
    roomSnapshot: WatchRoom,
    force = false,
    options?: { preferRoomPosition?: boolean; pausedOverride?: boolean }
  ) => {
    if (!user || !roomSnapshot.state.media_id || personalSyncRunningRef.current) return
    if (!force && document.visibilityState === 'hidden') return
    personalSyncRunningRef.current = true
    try {
      const currentTime = videoRef.current?.currentTime
      const resolvedPosition = options?.preferRoomPosition
        ? roomSnapshot.state.position_seconds
        : Number.isFinite(currentTime)
          ? currentTime
          : roomSnapshot.state.position_seconds
      const resolvedPaused = options?.pausedOverride ?? (videoRef.current ? videoRef.current.paused : roomSnapshot.state.paused)
      const historyEntry = await syncWatchProgress({
        room_id: roomSnapshot.room_id,
        media_id: roomSnapshot.state.media_id,
        playback_mode: roomSnapshot.state.playback_mode,
        position_seconds: resolvedPosition,
        paused: resolvedPaused,
      })
      setPersonalHistory(historyEntry)
    } catch {
      /* 忽略同步失败，不打断当前播放 */
    } finally {
      personalSyncRunningRef.current = false
    }
  }, [user])

  const jumpToPosition = (seconds: number) => {
    const video = videoRef.current
    pendingSeekRef.current = Math.max(0, seconds)
    if (!video) return
    if (video.readyState >= 1) {
      video.currentTime = pendingSeekRef.current
      pendingSeekRef.current = null
    }
  }

  const handleResumeToPersonalProgress = () => {
    if (!personalHistory) return
    jumpToPosition(personalHistory.position_seconds)
    setPlayerHint(`已将播放器定位到你的个人进度 ${formatPosition(personalHistory.position_seconds)}。`)
  }

  useEffect(() => {
    if (!user || !room?.room_id || !room.state.media_id) {
      return
    }
    void syncPersonalProgress(room, true, { preferRoomPosition: true, pausedOverride: room.state.paused })
    const timer = window.setInterval(() => {
      void syncPersonalProgress(room)
    }, 15000)
    return () => window.clearInterval(timer)
  }, [room, syncPersonalProgress, user])

  const sendRoomPresenceHeartbeat = useCallback(async (options?: { requireReady?: boolean }) => {
    if (!user || !room) return false
    if (roomPresenceRequestRef.current) return roomPresenceRequestRef.current

    const requiresRoomPresence = room.owner_user_id !== user.id
    const contextKey = `${room.room_id}:${user.id}`

    if (options?.requireReady && requiresRoomPresence) {
      setRoomPresencePending(true)
      setRoomPresenceError('')
    }

    const request = (async () => {
      try {
        await heartbeatPresence({
          room_id: room.room_id,
          room_name: room.name,
          page: 'watch_room',
          status_text: room.state.paused ? '在房间待机' : '正在同看',
        })

        if (requiresRoomPresence && roomPresenceContextRef.current === contextKey && !roomPresenceReadyRef.current) {
          roomPresenceReadyRef.current = true
          setRoomPresenceReady(true)
          setRoomPresencePending(false)
          setRoomPresenceError('')
        }

        return true
      } catch (error) {
        if (requiresRoomPresence && roomPresenceContextRef.current === contextKey && !roomPresenceReadyRef.current) {
          roomPresenceReadyRef.current = false
          setRoomPresenceReady(false)
          setRoomPresencePending(false)
          setRoomPresenceError(extractErrorMessage(error))
        }
        return false
      }
    })()

    roomPresenceRequestRef.current = request
    request.finally(() => {
      if (roomPresenceRequestRef.current === request) {
        roomPresenceRequestRef.current = null
      }
    })
    return request
  }, [room, user])

  const ensureRoomPresence = useCallback(async () => {
    if (!room) return false
    if (!user || room.owner_user_id === user.id || roomPresenceReadyRef.current) return true

    const ready = await sendRoomPresenceHeartbeat({ requireReady: true })
    if (!ready) {
      setPlayerHint(roomPresenceError || '正在确认你已进入这个房间，请稍后重试。')
    }
    return ready
  }, [room, roomPresenceError, sendRoomPresenceHeartbeat, user])

  useEffect(() => {
    if (!user || !room) return

    void sendRoomPresenceHeartbeat({ requireReady: room.owner_user_id !== user.id && !roomPresenceReadyRef.current })
    const timer = window.setInterval(() => {
      void sendRoomPresenceHeartbeat({ requireReady: room.owner_user_id !== user.id && !roomPresenceReadyRef.current })
    }, 30000)
    return () => window.clearInterval(timer)
  }, [room, sendRoomPresenceHeartbeat, user])

  useEffect(() => {
    const element = roomChatListRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }, [roomMessages.length])

  useEffect(() => {
    const video = videoRef.current
    const playbackUrl = room?.state.playback_url || ''
    const playbackMode = room?.state.playback_mode || 'direct_play'
    let cancelled = false

    if (hlsRef.current) {
      hlsRef.current.destroy()
      hlsRef.current = null
    }

    if (!video) return
    if (!playbackUrl || assetBlocked) {
      video.removeAttribute('src')
      video.load()
      return
    }

    if (playbackMode === 'hls') {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = playbackUrl
      } else {
        void import('hls.js').then(({ default: Hls }) => {
          if (cancelled) return
          if (Hls.isSupported()) {
            const hls = new Hls()
            hlsRef.current = hls
            hls.loadSource(playbackUrl)
            hls.attachMedia(video)
            hls.on(Hls.Events.ERROR, (_event, data) => {
              if (data.fatal) {
                setPlayerHint('当前 HLS 播放遇到错误，可能是片源损坏或播放列表尚未准备好。')
              }
            })
          } else {
            setPlayerHint('当前浏览器不支持 HLS 播放。')
          }
        })
      }
    } else {
      video.src = playbackUrl
      // Explicit load() ensures metadata starts fetching immediately even
      // when preload defaults keep the element idle on first mount.
      video.load()
    }

    return () => {
      cancelled = true
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
    }
    // `videoElementReady` is the critical dependency here: when the component
    // first mounts `room` is null so we render a placeholder (no <video> in
    // the DOM yet). Once `room` resolves and the real <video> mounts, our
    // callback ref flips `videoElementReady` to true, re-running this effect
    // so we can actually assign `src`.
  }, [assetBlocked, room?.state.playback_mode, room?.state.playback_url, videoElementReady])

  // ---------------------------------------------------------------------------
  // Multi-viewer sync: apply authoritative room state to the local <video>.
  //
  // After the watchparty / syncplay architecture deep-dive we moved to a
  // single-entry-point model: only the custom control bar drives state
  // changes (it calls updateWatchRoomState directly). We therefore no
  // longer need echo suppression — the <video> element doesn't have native
  // `controls`, so the only way `paused / currentTime / playbackRate` ever
  // changes is from this effect's own assignments, and there's nobody to
  // loop back to us.
  //
  // Rules:
  //   - Only seek when the remote position differs from the local position
  //     by more than `SEEK_THRESHOLD_SECONDS` (avoid fighting playback clock).
  //   - Only play / pause when the remote paused flag diverges from local.
  //   - Mirror playbackRate if it drifted.
  //   - Respect the browser's autoplay gesture requirement: fall back to
  //     muted playback, then to a big click-to-unlock overlay.
  // ---------------------------------------------------------------------------
  const SEEK_THRESHOLD_SECONDS = 1.5
  useEffect(() => {
    if (!videoElementReady) return
    const video = videoRef.current
    if (!video) return
    if (!room?.state.playback_url) return
    if (assetBlocked) return

    const targetPos = Number(room.state.position_seconds) || 0
    const remotePaused = Boolean(room.state.paused)
    const targetRate = Number(room.state.playback_rate) || 1

    // Wait until metadata is known before seeking, otherwise `currentTime = x`
    // gets silently clamped to 0 and we lose the intended jump. Stash the
    // request in `pendingSeekRef` and replay it from `onLoadedMetadata`.
    if (video.readyState < 1) {
      pendingSeekRef.current = targetPos
    } else if (Math.abs(video.currentTime - targetPos) > SEEK_THRESHOLD_SECONDS) {
      video.currentTime = targetPos
    }

    const localPaused = video.paused
    if (remotePaused && !localPaused) {
      video.pause()
    } else if (!remotePaused && localPaused) {
      const tryPlay = (): Promise<void> => {
        const p = video.play()
        return p && typeof p.then === 'function' ? p : Promise.resolve()
      }
      tryPlay().catch(() => {
        // Autoplay rejected (no user gesture yet). Fall back to muted
        // autoplay so the viewer stays in sync; user can unmute from the
        // custom control bar.
        try {
          video.muted = true
        } catch {
          /* ignore */
        }
        tryPlay()
          .then(() => {
            setNeedsPlayUnlock(false)
            setPlayerHint('已为你静音播放以保持同步，点击音量按钮可解除静音。')
          })
          .catch(() => {
            setNeedsPlayUnlock(true)
            setPlayerHint('浏览器阻止了自动播放，请点一下视频加入同步。')
          })
      })
    }

    if (Math.abs(video.playbackRate - targetRate) > 0.01) {
      video.playbackRate = targetRate
    }
  }, [
    videoElementReady,
    assetBlocked,
    room?.state.playback_url,
    room?.state.paused,
    room?.state.position_seconds,
    room?.state.playback_rate,
    room?.state.updated_at,
  ])

  // ---------------------------------------------------------------------------
  // Cosmetic: push playback telemetry (currentTime / duration / volume / mute)
  // into React state so the custom control bar can render a progress slider
  // that actually moves. These events are **display only** — they do not
  // broadcast to the room; broadcasting is done by `sendRoomCommand` when
  // the user interacts with one of our custom controls.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!videoElementReady) return
    const video = videoRef.current
    if (!video) return
    const update = () => {
      setPlayerUI({
        currentTime: video.currentTime || 0,
        duration: isFinite(video.duration) ? video.duration : 0,
        muted: video.muted,
        volume: video.volume,
      })
    }
    update()
    const throttledTimeUpdate = (() => {
      let last = 0
      return () => {
        const now = Date.now()
        if (now - last < 250) return
        last = now
        update()
      }
    })()
    video.addEventListener('timeupdate', throttledTimeUpdate)
    video.addEventListener('durationchange', update)
    video.addEventListener('volumechange', update)
    video.addEventListener('loadedmetadata', update)
    return () => {
      video.removeEventListener('timeupdate', throttledTimeUpdate)
      video.removeEventListener('durationchange', update)
      video.removeEventListener('volumechange', update)
      video.removeEventListener('loadedmetadata', update)
    }
  }, [videoElementReady])

  // ---------------------------------------------------------------------------
  // Activity feed: diff successive `room.state` snapshots to produce toasts
  // like "alice 暂停了视频" or "bob 切到了 葬送的芙莉莲 36". Rules:
  //   - Skip the actor's own actions (no self-noise)
  //   - Same actor+kind within 2s collapses to a single toast (rate tweaks,
  //     scrub chatter, etc.)
  //   - Toasts auto-expire after 4s
  //   - First snapshot (no previous state) doesn't produce any toast
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const curr = room?.state
    const prev = prevRoomStateRef.current
    if (!curr) return

    // Always snapshot the latest so the next run has something to diff.
    prevRoomStateRef.current = curr

    if (!prev) return

    const actor = curr.updated_by || ''
    if (!actor) return
    // Suppress self-narration — don't tell users what they just did.
    if (user?.username && actor === user.username) return

    const ACTIVITY_TTL_MS = 4000
    const COLLAPSE_WINDOW_MS = 2000
    const now = Date.now()

    const push = (kind: RoomActivity['kind'], message: string) => {
      const memoKey = `${actor}::${kind}`
      const lastAt = lastActivityRef.current.get(memoKey) || 0
      if (now - lastAt < COLLAPSE_WINDOW_MS) return
      lastActivityRef.current.set(memoKey, now)

      activityIdRef.current += 1
      const id = activityIdRef.current
      setActivities((prev) => [...prev.slice(-2), { id, actor, kind, message, at: now }])
      window.setTimeout(() => {
        setActivities((prev) => prev.filter((a) => a.id !== id))
      }, ACTIVITY_TTL_MS)
    }

    // 1. Media change (highest priority — announce first)
    if (curr.media_id && curr.media_id !== prev.media_id) {
      push('media', `切换了片源`)
    }

    // 2. Playback mode change
    if (curr.playback_mode !== prev.playback_mode) {
      const mode = curr.playback_mode === 'hls' ? 'HLS 流' : '直链播放'
      push('mode', `切到了 ${mode}`)
    }

    // 3. Pause flag flipped
    if (curr.paused !== prev.paused) {
      push(curr.paused ? 'pause' : 'resume', curr.paused ? '暂停了视频' : '恢复了播放')
    }

    // 4. Rate change (threshold 0.05 to ignore float noise)
    if (Math.abs((curr.playback_rate || 1) - (prev.playback_rate || 1)) > 0.05) {
      push('rate', `把倍速调到 ${(curr.playback_rate || 1).toFixed(2).replace(/\.?0+$/, '')}x`)
    }

    // 5. Seek (threshold 3s — smaller diffs are just natural playback progress)
    const dPos = (curr.position_seconds || 0) - (prev.position_seconds || 0)
    const dWallMs = Math.max(1, (curr.updated_at || now) - (prev.updated_at || now))
    const expectedDrift = ((curr.playback_rate || 1) * dWallMs) / 1000
    // A "seek" is a position jump that can't be explained by natural playback
    // between the two snapshots. Use a generous 3s slack to cover buffering.
    if (Math.abs(dPos - expectedDrift) > 3) {
      push('seek', `跳到了 ${formatPosition(curr.position_seconds || 0)}`)
    }
  }, [
    room?.state.media_id,
    room?.state.playback_mode,
    room?.state.paused,
    room?.state.position_seconds,
    room?.state.playback_rate,
    room?.state.updated_at,
    room?.state.updated_by,
    room?.state,
    user?.username,
  ])

  // Single entry point for every user-driven control (play/pause button, seek
  // slider, rate menu). It (1) optimistically updates local <video>, (2) PUTs
  // the new state to the server, (3) folds in the authoritative response.
  // Because this is the ONLY way viewer state ever changes, we no longer need
  // echo-suppression flags — same architecture as watchparty / syncplay.
  const sendRoomCommand = async (
    patch: { paused?: boolean; position_seconds?: number; playback_rate?: number },
  ) => {
    const current = roomRef.current
    if (!current) return
    const video = videoRef.current
    // Optimistic local apply — makes the action feel instant instead of
    // waiting for the server round-trip.
    if (video) {
      if (patch.paused === true && !video.paused) video.pause()
      if (patch.paused === false && video.paused) void video.play().catch(() => undefined)
      if (typeof patch.position_seconds === 'number' && video.readyState >= 1) {
        video.currentTime = patch.position_seconds
      }
      if (typeof patch.playback_rate === 'number') {
        video.playbackRate = patch.playback_rate
      }
    }
    try {
      const next = await updateWatchRoomState(current.room_id, {
        media_id: current.state.media_id || undefined,
        paused: patch.paused ?? current.state.paused,
        position_seconds: patch.position_seconds ?? (video?.currentTime ?? current.state.position_seconds),
        playback_rate: patch.playback_rate ?? current.state.playback_rate,
        updated_by: user?.username || 'web',
      })
      setRoom(next)
    } catch (err) {
      const msg = extractErrorMessage(err)
      if (/403|401|permission|权限|未登录|forbidden/i.test(msg)) {
        setPlayerHint(`同步失败：${msg}`)
      }
    }
  }

  const refreshPlaybackUrl = async () => {
    if (!room) return
    if (!(await ensureRoomPresence())) return
    setBusy(true)
    try {
      const nextRoom = await updateWatchRoomState(room.room_id, {
        media_id: room.state.media_id,
        updated_by: user?.username || 'web',
      })
      setRoom(nextRoom)
      if (nextRoom.state.media_id) {
        const nextAsset = await getMediaAsset(nextRoom.state.media_id)
        setAsset(nextAsset)
        if (user) {
          await syncPersonalProgress(nextRoom, true)
        }
      }
      setPlayerHint('房间片源状态已刷新。')
    } catch (error) {
      setPlayerHint(extractErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const handlePrepareHls = async () => {
    if (!asset) return
    if (!(await ensureRoomPresence())) return
    setBusy(true)
    try {
      await prepareMediaHls(asset.media_id, asset.hls_status === 'error')
      await load()
      setPlayerHint('已触发 HLS 准备。')
    } catch (error) {
      setPlayerHint(extractErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const handleSwitchAsset = async (nextAsset: MediaAsset) => {
    if (!room || isBlocked(nextAsset) || switchingMediaId) return
    if (!(await ensureRoomPresence())) return
    setBusy(true)
    setSwitchingMediaId(nextAsset.media_id)
    try {
      let preparedAsset = nextAsset
      const needsPrepare = nextAsset.recommended_mode === 'pretranscode_hls' && nextAsset.hls_status !== 'ready'
      if (needsPrepare) {
        preparedAsset = await prepareMediaHls(nextAsset.media_id, nextAsset.hls_status === 'error')
      }

      const nextRoom = await updateWatchRoomState(room.room_id, {
        media_id: nextAsset.media_id,
        updated_by: user?.username || 'web',
      })
      setRoom(nextRoom)

      const refreshedAsset = await getMediaAsset(nextAsset.media_id)
      setAsset(refreshedAsset)
      setLibraryAssets((items) => items.map((item) => (item.media_id === refreshedAsset.media_id ? refreshedAsset : item)))
      const nextResume = user ? await getWatchResume(nextRoom.room_id, nextAsset.media_id).catch(() => null) : null
      setPersonalHistory(nextResume)
      pendingSeekRef.current = null
      setPlayerHint(
        needsPrepare && preparedAsset.hls_status !== 'ready'
          ? `已切换到《${refreshedAsset.title}》，并开始准备 HLS。稍后点“重新同步房间片源”刷新播放地址。`
          : `已切换到《${refreshedAsset.title}》。`
      )
    } catch (error) {
      setPlayerHint(extractErrorMessage(error))
    } finally {
      setBusy(false)
      setSwitchingMediaId('')
    }
  }

  const copyInviteLink = async () => {
    if (!room) return
    const url = `${window.location.origin}/watch/${room.room_id}`
    try {
      await navigator.clipboard.writeText(url)
      setPlayerHint('邀请链接已复制。')
    } catch {
      setPlayerHint(url)
    }
  }

  const handleInviteFriend = async (friend: FriendSummary) => {
    if (!room || !user) return
    if (!(await ensureRoomPresence())) return
    setInvitingFriendId(friend.user_id)
    try {
      await sendRoomInvitation(room.room_id, friend.user_id, inviteMessage.trim())
      setInviteMessage('')
      setPlayerHint(`已向 ${friend.username} 发出房间邀请。`)
      await loadSocialContext()
    } catch (error) {
      setPlayerHint(extractErrorMessage(error))
    } finally {
      setInvitingFriendId(0)
    }
  }

  const handleSendRoomChatMessage = async () => {
    if (!room || !roomMessageDraft.trim()) return
    if (!(await ensureRoomPresence())) return
    setSendingRoomMessage(true)
    try {
      const message = await sendRoomMessage(room.room_id, roomMessageDraft.trim())
      setRoomMessages((items) => [...items, message])
      setRoomMessageDraft('')
    } catch (error) {
      setPlayerHint(extractErrorMessage(error))
    } finally {
      setSendingRoomMessage(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="relative">
          <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
          <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
        </div>
      </div>
    )
  }

  if (!room) {
    return (
      <div className="rounded-3xl border border-white/5 bg-white/[0.01] p-12 text-center shadow-inner backdrop-blur-sm mt-8 max-w-2xl mx-auto">
        <Tv className="mx-auto mb-6 h-16 w-16 text-text-muted opacity-20" />
        <p className="text-xl font-bold text-white tracking-wide">房间不存在或已解散</p>
        <Link to="/watch" className="mt-6 inline-flex items-center gap-2 rounded-xl bg-accent-primary px-6 py-3 text-sm font-bold text-white hover:scale-105 transition-all shadow-lg hover:shadow-accent-primary/30">返回同看中心</Link>
      </div>
    )
  }

  const canAttemptPlayback = Boolean(room.state.playback_url) && !assetBlocked
  const roomPresenceRequired = Boolean(user && room.owner_user_id !== user.id)
  const roomInteractionLocked = roomPresenceRequired && !roomPresenceReady
  const controlsDisabled = busy || !room.state.media_id || assetBlocked || roomInteractionLocked

  return (
    <div className="max-w-[1400px] mx-auto space-y-6 animate-in fade-in duration-500">
      
      {/* Header */}
      <div className="relative overflow-hidden rounded-[2rem] border border-white/10 bg-black/40 p-6 shadow-2xl backdrop-blur-xl">
        <div className="absolute inset-0 bg-gradient-to-r from-accent-primary/20 via-transparent to-accent-cyan/10" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="rounded-xl bg-accent-primary/20 p-2 border border-accent-primary/30">
                 <Tv className="h-6 w-6 text-accent-primary" />
              </div>
              <h1 className="text-3xl font-black text-white tracking-wide">{room.name}</h1>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm font-medium text-white/70">
              <span className="flex items-center gap-1"><Users className="h-4 w-4" /> 房主: {room.host_name || '未命名'}</span>
              <span className="h-1 w-1 rounded-full bg-white/30" />
              <span>账号: {room.owner_username || '匿名'}</span>
              <span className="h-1 w-1 rounded-full bg-white/30" />
              <span>ID: {room.room_id}</span>
              {isOwner && <span className="rounded-md bg-accent-cyan/20 px-2 py-0.5 text-xs text-accent-cyan border border-accent-cyan/30">你的房间</span>}
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to="/watch" className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-bold text-white transition-all hover:bg-white/10 hover:shadow-lg">
              <ArrowLeft className="h-4 w-4" />返回大厅
            </Link>
            <button onClick={copyInviteLink} className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-bold text-white transition-all hover:bg-white/10 hover:shadow-lg">
              <Copy className="h-4 w-4" />复制链接
            </button>
            <button onClick={() => void load(false)} className="group flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-bold text-white transition-all hover:bg-white/10 hover:shadow-lg">
              <RefreshCw className="h-4 w-4 transition-transform group-hover:rotate-180" />刷新
            </button>
          </div>
        </div>
      </div>

      {roomLoadError && (
        <div className="flex items-center justify-between gap-4 rounded-2xl border border-warning/30 bg-warning/10 p-5 shadow-lg backdrop-blur-md animate-in slide-in-from-top-2">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-warning">房间状态刷新失败：{shortError(roomLoadError)}</p>
              <p className="text-xs font-medium text-warning/70 mt-1">当前展示的是上次成功同步的房间快照。</p>
            </div>
          </div>
          <button onClick={() => void load(false)} className="rounded-xl bg-warning px-4 py-2 text-sm font-bold text-black shadow-lg transition-all hover:bg-warning/90 hover:scale-105 shrink-0">重试</button>
        </div>
      )}

      {roomInteractionLocked && (
        <div className={cn('flex items-center justify-between gap-4 rounded-2xl border p-5 shadow-lg backdrop-blur-md animate-in slide-in-from-top-2', roomPresencePending ? 'border-accent-cyan/30 bg-accent-cyan/10' : 'border-warning/30 bg-warning/10')}>
          <div className="flex items-start gap-3">
            <AlertCircle className={cn("h-5 w-5 shrink-0 mt-0.5", roomPresencePending ? 'text-accent-cyan' : 'text-warning')} />
            <div>
              <p className={cn("font-bold", roomPresencePending ? 'text-accent-cyan' : 'text-warning')}>
                {roomPresencePending ? '正在确认你已进入这个房间。' : `进入房间确认失败：${shortError(roomPresenceError)}`}
              </p>
              <p className={cn("text-xs font-medium mt-1", roomPresencePending ? 'text-accent-cyan/70' : 'text-warning/70')}>
                在首次房间心跳成功前，聊天、邀请、切换片源和写入播放状态会先锁定，避免直接触发权限错误。
              </p>
            </div>
          </div>
          {!roomPresencePending && (
            <button onClick={() => void sendRoomPresenceHeartbeat({ requireReady: true })} className="rounded-xl bg-warning px-4 py-2 text-sm font-bold text-black shadow-lg transition-all hover:bg-warning/90 hover:scale-105 shrink-0">
              重新确认
            </button>
          )}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        {/* Left Column - Video Player & Controls */}
        <section className="space-y-6">
          
          {assetLoadError && (
             <div className={cn('flex items-center justify-between gap-4 rounded-2xl border p-5 shadow-lg backdrop-blur-md', asset ? 'border-warning/30 bg-warning/10' : 'border-danger/30 bg-danger/10')}>
                <div className="flex items-start gap-3">
                   <AlertCircle className={cn('h-5 w-5 shrink-0 mt-0.5', asset ? 'text-warning' : 'text-danger')} />
                   <div>
                      <p className={cn('font-bold', asset ? 'text-warning' : 'text-danger')}>
                         {asset ? '当前片源详情刷新失败，正在显示快照。' : `当前房间已绑定片源，但片源详情加载失败：${shortError(assetLoadError)}`}
                      </p>
                   </div>
                </div>
                <button onClick={() => void load(false)} className={cn('rounded-xl px-4 py-2 text-sm font-bold shadow-lg transition-all hover:scale-105 shrink-0', asset ? 'bg-warning text-black' : 'bg-danger text-white')}>
                   {asset ? '重试' : '重读片源详情'}
                </button>
             </div>
          )}

          {assetBlocked && (
             <div className="flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger/10 p-5 shadow-inner backdrop-blur-md">
                <AlertCircle className="h-5 w-5 text-danger shrink-0 mt-0.5" />
                <div>
                   <p className="font-bold text-danger">当前片源已被禁用</p>
                   <p className="text-sm text-danger/80 mt-1 font-medium">{assetBlockReason}</p>
                </div>
             </div>
          )}

          <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-black shadow-2xl ring-1 ring-white/5">
            {/* Activity toasts — who is driving the session right now */}
            {activities.length > 0 && (
              <div className="pointer-events-none absolute left-3 right-3 top-3 z-20 flex flex-col items-start gap-2">
                {activities.map((act) => {
                  const ActIcon =
                    act.kind === 'pause' ? Pause
                    : act.kind === 'resume' ? Play
                    : act.kind === 'seek' ? SkipForward
                    : act.kind === 'rate' ? FastForward
                    : act.kind === 'media' ? Film
                    : Activity
                  const tone =
                    act.kind === 'pause' ? 'bg-amber-500/90 border-amber-300/50'
                    : act.kind === 'resume' ? 'bg-emerald-500/90 border-emerald-300/50'
                    : act.kind === 'seek' ? 'bg-sky-500/90 border-sky-300/50'
                    : act.kind === 'rate' ? 'bg-fuchsia-500/90 border-fuchsia-300/50'
                    : act.kind === 'media' ? 'bg-accent-primary/90 border-white/30'
                    : 'bg-white/20 border-white/30'
                  return (
                    <div
                      key={act.id}
                      className={cn(
                        'flex items-center gap-2 rounded-full border px-4 py-1.5 text-xs font-bold text-white shadow-lg backdrop-blur-md transition-all animate-in fade-in slide-in-from-top-2',
                        tone,
                      )}
                    >
                      <ActIcon className="h-3.5 w-3.5" />
                      <span className="max-w-[60vw] truncate">
                        <span className="font-extrabold">{act.actor}</span> {act.message}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
            {canAttemptPlayback ? (
              <>
                <video
                  ref={setVideoNode}
                  playsInline
                  preload="auto"
                  className="aspect-video w-full bg-black"
                  onClick={() => {
                    // Tap the video itself to toggle play/pause — matches the
                    // usual YouTube / Netflix convention now that we've hidden
                    // native controls.
                    if (!room) return
                    void sendRoomCommand({ paused: !room.state.paused })
                  }}
                  onLoadedMetadata={() => {
                    if (!videoRef.current) return
                    const resumePosition = pendingSeekRef.current ?? room.state.position_seconds
                    if (resumePosition > 0 && Math.abs(videoRef.current.currentTime - resumePosition) > 1) {
                      videoRef.current.currentTime = resumePosition
                    }
                    pendingSeekRef.current = null
                  }}
                  onEnded={() => {
                    if (room) void syncPersonalProgress(room, true)
                  }}
                />
                {needsPlayUnlock && !room.state.paused && (
                  <button
                    type="button"
                    onClick={() => {
                      const v = videoRef.current
                      if (!v) return
                      // We're inside a real user gesture now, so play() will
                      // be allowed — even unmuted.
                      v.play().then(() => {
                        setNeedsPlayUnlock(false)
                        setPlayerHint('')
                      }).catch(() => {
                        try { v.muted = true } catch { /* ignore */ }
                        v.play().then(() => {
                          setNeedsPlayUnlock(false)
                          setPlayerHint('已为你静音播放以保持同步，点击音量按钮可解除静音。')
                        }).catch(() => {
                          setPlayerHint('无法启动播放，请检查浏览器权限。')
                        })
                      })
                    }}
                    className="absolute inset-0 z-10 flex cursor-pointer flex-col items-center justify-center gap-4 bg-black/60 backdrop-blur-sm transition-all hover:bg-black/70"
                  >
                    <div className="rounded-full bg-accent-primary p-6 shadow-2xl shadow-accent-primary/50 ring-4 ring-white/20 transition-transform hover:scale-110">
                      <Play className="h-12 w-12 text-white" fill="currentColor" />
                    </div>
                    <p className="text-lg font-bold text-white">点击加入同步观看</p>
                    <p className="text-sm font-medium text-white/70">浏览器要求点一下才能开始播放</p>
                  </button>
                )}
              </>
            ) : (
              <div className="flex aspect-video items-center justify-center bg-gradient-to-br from-black to-bg-secondary p-8 text-center shadow-inner">
                <div className="space-y-4">
                  <PlayCircle className="mx-auto h-16 w-16 text-white/20" />
                  <p className="text-lg font-bold text-white/60">
                    {assetBlocked ? `不可播放：${assetBlockReason}` : '没有可播放地址'}
                  </p>
                  <p className="text-sm font-medium text-white/40">
                    {!assetBlocked && '可能需要先预转 HLS，或等待片源解析完成。'}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Custom sync-aware control bar.
              We own every interaction (play / seek / rate / volume) so that
              the room always goes through `sendRoomCommand`. No native
              <video controls> means no back-channel user actions that we
              would otherwise have to detect and de-echo. */}
          {canAttemptPlayback && (
            <div className="space-y-3 rounded-2xl border border-white/5 bg-black/30 p-4 shadow-lg backdrop-blur-md">
              {/* Progress slider */}
              <div className="flex items-center gap-3">
                <span className="w-14 text-right text-xs font-bold tabular-nums text-white/80">
                  {formatPosition(playerUI.currentTime)}
                </span>
                <input
                  type="range"
                  min={0}
                  max={Math.max(1, playerUI.duration)}
                  step={0.1}
                  value={Math.min(playerUI.currentTime, playerUI.duration || 0)}
                  disabled={controlsDisabled || !playerUI.duration}
                  onChange={(e) => {
                    // Preview the new time locally while dragging — don't PUT
                    // on every pixel, only on release (onMouseUp/onKeyUp).
                    setPlayerUI((p) => ({ ...p, currentTime: Number(e.target.value) }))
                  }}
                  onMouseUp={(e) => {
                    void sendRoomCommand({ position_seconds: Number((e.target as HTMLInputElement).value) })
                  }}
                  onKeyUp={(e) => {
                    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                      void sendRoomCommand({ position_seconds: Number((e.target as HTMLInputElement).value) })
                    }
                  }}
                  onTouchEnd={(e) => {
                    void sendRoomCommand({ position_seconds: Number((e.target as HTMLInputElement).value) })
                  }}
                  className="h-1.5 flex-1 appearance-none rounded-full bg-white/10 accent-accent-primary disabled:opacity-40 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent-primary [&::-webkit-slider-thumb]:shadow-lg"
                />
                <span className="w-14 text-xs font-bold tabular-nums text-white/50">
                  {formatPosition(playerUI.duration)}
                </span>
              </div>

              {/* Play / rate / volume / misc row */}
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={() => {
                    if (!room) return
                    void sendRoomCommand({ paused: !room.state.paused })
                  }}
                  disabled={controlsDisabled}
                  aria-label="写入播放状态"
                  title={room?.state.paused ? '播放 (广播给所有人)' : '暂停 (广播给所有人)'}
                  className="flex items-center gap-2 rounded-xl bg-accent-primary px-4 py-2.5 text-sm font-bold text-white shadow-lg transition-all hover:bg-accent-primary/90 hover:scale-105 disabled:opacity-50 disabled:hover:scale-100"
                >
                  {room?.state.paused
                    ? <><Play className="h-4 w-4" fill="currentColor" /> 播放</>
                    : <><Pause className="h-4 w-4" fill="currentColor" /> 暂停</>}
                </button>

                {/* Rate menu */}
                <div className="flex items-center gap-1 rounded-xl bg-white/5 p-1">
                  <Gauge className="h-4 w-4 ml-2 text-white/60" />
                  {[0.5, 0.75, 1, 1.25, 1.5, 2].map((r) => {
                    const active = Math.abs((room?.state.playback_rate ?? 1) - r) < 0.01
                    return (
                      <button
                        key={r}
                        onClick={() => void sendRoomCommand({ playback_rate: r })}
                        disabled={controlsDisabled}
                        className={cn(
                          'rounded-lg px-2 py-1 text-xs font-bold transition-all',
                          active
                            ? 'bg-accent-primary text-white shadow'
                            : 'text-white/60 hover:bg-white/10 hover:text-white',
                          'disabled:opacity-40',
                        )}
                      >
                        {r}x
                      </button>
                    )
                  })}
                </div>

                {/* Volume (local only — doesn't broadcast) */}
                <button
                  onClick={() => {
                    const v = videoRef.current
                    if (!v) return
                    v.muted = !v.muted
                  }}
                  title={playerUI.muted ? '取消静音' : '静音'}
                  className="flex items-center gap-2 rounded-xl bg-white/5 p-2.5 text-white/80 transition-all hover:bg-white/10 hover:text-white"
                >
                  {playerUI.muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
                </button>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={playerUI.muted ? 0 : playerUI.volume}
                  onChange={(e) => {
                    const v = videoRef.current
                    if (!v) return
                    v.muted = false
                    v.volume = Number(e.target.value)
                  }}
                  className="h-1 w-24 appearance-none rounded-full bg-white/10 accent-white [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white"
                />

                <div className="ml-auto flex items-center gap-2">
                  <button onClick={refreshPlaybackUrl} disabled={controlsDisabled} className="rounded-xl bg-white/5 px-4 py-2.5 text-xs font-bold text-white/80 transition-all hover:bg-white/10 hover:text-white disabled:opacity-50">
                    <RefreshCw className="inline-block h-3.5 w-3.5 mr-1" /> 重新同步片源
                  </button>
                  {asset && asset.recommended_mode === 'pretranscode_hls' && !assetBlocked && (
                    <button onClick={handlePrepareHls} disabled={busy || asset.hls_status === 'preparing' || asset.hls_status === 'queued' || roomInteractionLocked} className="rounded-xl bg-gradient-to-r from-accent-cyan to-[#00f2fe] px-4 py-2.5 text-xs font-bold text-white shadow-lg transition-all hover:scale-105 disabled:opacity-50 disabled:hover:scale-100">
                      {asset.hls_status === 'queued' ? 'HLS 排队中' : asset.hls_status === 'preparing' ? asset.hls_progress > 0 ? `HLS 准备中 ${asset.hls_progress}%` : 'HLS 准备中' : '准备 HLS'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {playerHint && (
            <div className="rounded-xl bg-accent-cyan/20 border border-accent-cyan/30 px-5 py-3 text-sm font-bold text-accent-cyan shadow-inner backdrop-blur-sm animate-in fade-in">
              {playerHint}
            </div>
          )}

          {/* Asset Info Card */}
          <div className="rounded-2xl border border-white/5 bg-black/20 p-6 shadow-xl backdrop-blur-md">
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl bg-accent-primary/20 p-2 border border-accent-primary/30">
                <HardDrive className="h-5 w-5 text-accent-primary" />
              </div>
              <h2 className="text-xl font-bold text-white">当前片源</h2>
            </div>
            {asset ? (
               <div className="space-y-4">
                 <div className="space-y-1">
                    <p className="text-lg font-bold text-white">{asset.title}</p>
                    <p className="text-sm font-medium text-white/50">{asset.relative_path}</p>
                 </div>
                 <div className="flex flex-wrap gap-2 text-xs font-bold">
                    <span className="rounded-md bg-white/10 px-2 py-1 text-white/80">{asset.container || 'unknown'}</span>
                    <span className="rounded-md bg-white/10 px-2 py-1 text-white/80">{formatBytes(asset.size)}</span>
                    <span className={cn('rounded-md px-2 py-1', asset.direct_play_supported ? 'bg-success/20 text-success' : 'bg-warning/20 text-warning')}>{asset.direct_play_supported ? '可直放' : '需 HLS'}</span>
                    <span className={cn('rounded-md px-2 py-1', asset.probe_status === 'failed' ? 'bg-danger/20 text-danger' : 'bg-white/10 text-white/80')}>{asset.probe_status === 'failed' ? '解析失败' : asset.probe_status === 'ready' ? '解析正常' : '待探测'}</span>
                    <span className="rounded-md bg-accent-cyan/20 px-2 py-1 text-accent-cyan">{asset.hls_status}</span>
                 </div>
                 {assetBlocked && (
                    <div className="flex items-center gap-2 rounded-xl bg-danger/20 p-3 text-sm font-bold text-danger border border-danger/30">
                       <AlertCircle className="h-4 w-4 shrink-0" /> {assetBlockReason}
                    </div>
                 )}
                 {asset.last_error && (
                    <div className="flex items-center gap-2 rounded-xl bg-danger/20 p-3 text-sm font-bold text-danger border border-danger/30">
                       <AlertCircle className="h-4 w-4 shrink-0" /> {shortError(asset.last_error)}
                    </div>
                 )}
               </div>
            ) : (
               <p className="text-sm font-medium text-white/50">当前房间还没有绑定片源。</p>
            )}
          </div>

          {/* Quick Switch */}
          <div className="rounded-2xl border border-white/5 bg-black/20 p-6 shadow-xl backdrop-blur-md">
            <div className="flex items-center justify-between gap-4 mb-5">
              <div className="flex items-center gap-3">
                 <div className="rounded-xl bg-accent-gold/20 p-2 border border-accent-gold/30">
                   <Settings2 className="h-5 w-5 text-accent-gold" />
                 </div>
                 <h2 className="text-xl font-bold text-white">快速换源</h2>
              </div>
              <button onClick={() => void loadLibrary(true)} disabled={libraryLoading} className="group flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-bold text-white transition-all hover:bg-white/10 hover:shadow-lg disabled:opacity-50">
                {libraryLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4 transition-transform group-hover:rotate-180" />}重扫片源
              </button>
            </div>
            
            <input value={assetQuery} onChange={e => setAssetQuery(e.target.value)} placeholder="搜索片源标题或文件名" className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-bold text-white outline-none focus:border-accent-primary focus:bg-white/10 transition-all mb-4" />
            
            {libraryLoading && libraryAssets.length === 0 ? (
               <div className="flex items-center justify-center py-10"><Loader2 className="h-8 w-8 animate-spin text-accent-primary" /></div>
            ) : candidateAssets.length === 0 ? (
               <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm font-medium text-white/50">没有匹配的片源。你可以先重扫媒体库，或者换个关键词试试。</div>
            ) : (
               <div className="space-y-3">
                  {candidateAssets.map(candidate => {
                     const candidateBlocked = isBlocked(candidate)
                     const currentSelected = room.state.media_id === candidate.media_id
                     return (
                        <div key={candidate.media_id} className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 rounded-xl border border-white/5 bg-white/[0.02] p-4 transition-all hover:bg-white/5 hover:border-white/20">
                           <div className="min-w-0 flex-1">
                              <p className="text-sm font-bold text-white truncate">{candidate.title}</p>
                              <p className="text-xs font-medium text-white/50 truncate mt-1">{candidate.relative_path}</p>
                              <div className="flex flex-wrap gap-2 text-[10px] font-bold mt-2">
                                 {currentSelected && <span className="rounded bg-accent-primary/80 px-1.5 py-0.5 text-white">当前片源</span>}
                                 <span className="rounded bg-white/10 px-1.5 py-0.5 text-white/80">{candidate.direct_play_supported ? '可直放' : '需 HLS'}</span>
                                 <span className="rounded bg-white/10 px-1.5 py-0.5 text-white/80">{candidate.hls_status}</span>
                              </div>
                           </div>
                           <button onClick={() => void handleSwitchAsset(candidate)} disabled={roomInteractionLocked || candidateBlocked || currentSelected || Boolean(switchingMediaId)} aria-label={currentSelected ? '当前片源' : undefined} className="w-full md:w-auto shrink-0 rounded-xl bg-accent-primary px-4 py-2.5 text-sm font-bold text-white hover:scale-105 hover:shadow-lg transition-all disabled:opacity-50 disabled:hover:scale-100 disabled:cursor-not-allowed">
                              {switchingMediaId === candidate.media_id ? '切换中...' : currentSelected ? '已选择' : '切换到此源'}
                           </button>
                        </div>
                     )
                  })}
               </div>
            )}
          </div>
        </section>

        {/* Right Column - Status, Social, Chat */}
        <section className="space-y-6">
          
          {/* Room Status */}
          <div className="rounded-2xl border border-white/5 bg-black/20 p-6 shadow-xl backdrop-blur-md">
            <h2 className="text-lg font-bold text-white mb-4">房间状态</h2>
            <div className="grid grid-cols-2 gap-3 text-sm font-bold">
               <div className="rounded-xl bg-white/5 p-4 border border-white/5">
                  <p className="text-white/50 text-xs mb-1">播放模式</p>
                  <p className="text-white">{room.state.playback_mode === 'hls' ? 'HLS' : '直放'}</p>
               </div>
               <div className="rounded-xl bg-white/5 p-4 border border-white/5">
                  <p className="text-white/50 text-xs mb-1">状态</p>
                  <p className={cn("text-white", room.state.paused ? 'text-warning' : 'text-success')}>{room.state.paused ? '已暂停' : '播放中'}</p>
               </div>
               <div className="rounded-xl bg-white/5 p-4 border border-white/5">
                  <p className="text-white/50 text-xs mb-1">位置</p>
                  <p className="text-white">{formatPosition(room.state.position_seconds)}</p>
               </div>
               <div className="rounded-xl bg-white/5 p-4 border border-white/5">
                  <p className="text-white/50 text-xs mb-1">最近更新</p>
                  <p className="text-white text-xs mt-1 leading-tight">{formatDateTime(room.state.updated_at)}</p>
               </div>
            </div>
            
            <div className="mt-4 rounded-xl bg-white/5 p-4 border border-white/5">
               <div className="flex justify-between items-center mb-2">
                 <p className="text-white/50 text-xs font-bold">我的续播位置</p>
                 <button onClick={handleResumeToPersonalProgress} disabled={!canAttemptPlayback || !personalHistory} className="rounded-lg bg-accent-cyan/80 px-3 py-1.5 text-xs font-bold text-white hover:bg-accent-cyan transition-all disabled:opacity-50 shadow-md">恢复进度</button>
               </div>
               <p className="text-white font-bold text-sm">
                 {user ? personalHistory ? `${formatPosition(personalHistory.position_seconds)}` : '还没有记录' : '登录后可用'}
               </p>
               {user && personalHistory && (
                  <p className="mt-1 text-xs font-medium text-white/50">当前相差 {formatPosition(resumeOffset)}</p>
               )}
            </div>
          </div>

          {/* Participants & Social */}
          <div className="rounded-2xl border border-white/5 bg-black/20 p-6 shadow-xl backdrop-blur-md">
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl bg-accent-secondary/20 p-2 border border-accent-secondary/30">
                <Users className="h-5 w-5 text-accent-secondary" />
              </div>
              <h2 className="text-xl font-bold text-white">房间成员与邀请</h2>
            </div>

            {socialLoadError && !socialReady && (
              <div className="flex items-center justify-between gap-4 rounded-xl border border-warning/30 bg-warning/10 p-4 mb-5 backdrop-blur-md">
                <div className="flex items-center gap-3">
                  <AlertCircle className="h-5 w-5 text-warning shrink-0" />
                  <p className="font-bold text-warning text-sm">房间成员与邀请暂时加载失败：{shortError(socialLoadError)}</p>
                </div>
                <button onClick={() => void loadSocialContext()} className="rounded-lg bg-warning px-4 py-2 text-xs font-bold text-black transition-all hover:bg-warning/90 shrink-0">重试成员状态</button>
              </div>
            )}
            
            {socialReady && (
               <div className="mb-6">
                  <h3 className="text-sm font-bold text-white mb-3">当前在线成员</h3>
                  {roomParticipants.length === 0 ? (
                     <div className="rounded-xl border border-dashed border-white/10 p-5 text-center text-sm font-medium text-white/50">目前还没有登录用户在这个房间里心跳在线。</div>
                  ) : (
                     <div className="space-y-3">
                        {roomParticipants.map(p => (
                           <div key={p.user_id} className="flex items-center justify-between rounded-xl bg-white/5 p-3 border border-white/5">
                              <div>
                                 <p className="font-bold text-sm text-white">{p.username}</p>
                                 <p className="text-[10px] text-white/50 font-medium mt-0.5">{socialStatusText(p)}</p>
                              </div>
                           </div>
                        ))}
                     </div>
                  )}
               </div>
            )}

            <div className="border-t border-white/10 pt-5">
               <h3 className="text-sm font-bold text-white mb-3">邀请好友</h3>
               {outgoingInvites.filter((item) => item.room_id === roomId && item.status === 'pending').length > 0 && (
                  <p className="text-xs font-bold text-accent-cyan mb-3">你已向 {outgoingInvites.filter((item) => item.room_id === roomId && item.status === 'pending').length} 位好友发出待处理邀请</p>
               )}
               {!user ? (
                  <div className="rounded-xl border border-dashed border-white/10 p-5 text-center text-xs font-medium text-white/50">登录后可邀请好友进房</div>
               ) : inviteableFriends.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-white/10 p-5 text-center text-xs font-medium text-white/50">你还没有好友，去大厅加一个吧</div>
               ) : (
                  <div className="space-y-3">
                     <input value={inviteMessage} onChange={e => setInviteMessage(e.target.value)} disabled={roomInteractionLocked} placeholder="邀请留言（可选）" className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm font-bold text-white focus:bg-white/10 focus:border-accent-primary outline-none transition-all" />
                     {inviteableFriends.map(f => {
                        const inRoom = currentRoomParticipantIds.has(f.user_id)
                        const invited = outgoingInviteFriendIds.has(f.user_id)
                        return (
                           <div key={f.user_id} className="flex items-center justify-between rounded-xl bg-white/5 p-3 border border-white/5">
                              <span className="font-bold text-sm text-white">{f.username}</span>
                              <button onClick={() => void handleInviteFriend(f)} disabled={roomInteractionLocked || inRoom || invited || invitingFriendId === f.user_id} className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-bold text-white disabled:opacity-50 shadow-md">
                                 {inRoom ? '已在房间' : invited ? '已邀请' : '邀请'}
                              </button>
                           </div>
                        )
                     })}
                  </div>
               )}
            </div>
          </div>

          {/* Chat */}
          <div className="rounded-2xl border border-white/5 bg-black/20 p-6 shadow-xl backdrop-blur-md flex flex-col h-[500px]">
            <div className="flex items-center gap-3 mb-5 shrink-0">
              <div className="rounded-xl bg-accent-cyan/20 p-2 border border-accent-cyan/30">
                <MessageSquare className="h-5 w-5 text-accent-cyan" />
              </div>
              <h2 className="text-xl font-bold text-white">房间聊天</h2>
            </div>

            {roomChatError && !roomChatReady && (
              <div className="flex items-center justify-between gap-4 rounded-xl border border-warning/30 bg-warning/10 p-4 mb-4 backdrop-blur-md">
                <div className="flex items-center gap-3">
                  <AlertCircle className="h-5 w-5 text-warning shrink-0" />
                  <p className="font-bold text-warning text-sm">房间聊天暂时加载失败：{shortError(roomChatError)}</p>
                </div>
                <button onClick={() => void loadRoomChat()} className="rounded-lg bg-warning px-4 py-2 text-xs font-bold text-black transition-all hover:bg-warning/90 shrink-0">重试聊天</button>
              </div>
            )}
            
            <div className="flex-1 rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden flex flex-col">
               <div ref={roomChatListRef} className="flex-1 overflow-y-auto p-4 space-y-4">
                  {roomChatReady && roomMessages.length === 0 ? (
                     <div className="flex h-full items-center justify-center text-sm font-medium text-white/40">房间里还没有聊天记录，先发第一条消息吧。</div>
                  ) : (
                     roomMessages.map(msg => (
                        <div key={msg.message_id} className={cn('flex', msg.is_mine ? 'justify-end' : 'justify-start')}>
                           <div className={cn('max-w-[85%] rounded-2xl px-4 py-2.5 text-sm', msg.is_mine ? 'bg-accent-primary text-white rounded-br-sm' : 'bg-white/10 text-white rounded-bl-sm')}>
                              <p className="break-words font-medium">{msg.body}</p>
                              <p className={cn("text-[10px] mt-1 font-bold", msg.is_mine ? 'text-white/60' : 'text-white/40')}>
                                 {msg.is_mine ? '我' : msg.sender_username} · {formatRelativeTime(msg.created_at)}
                              </p>
                           </div>
                        </div>
                     ))
                  )}
               </div>
               
               <div className="p-3 bg-white/5 border-t border-white/10">
                  <div className="flex gap-2">
                     <input value={roomMessageDraft} onChange={e => setRoomMessageDraft(e.target.value)} onKeyDown={(e) => { if(e.key === 'Enter') handleSendRoomChatMessage() }} disabled={!user || roomInteractionLocked} className="flex-1 rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm font-bold text-white focus:bg-black/60 focus:border-accent-primary outline-none transition-all disabled:opacity-50" placeholder={!user ? '登录后可发言' : roomInteractionLocked ? '正在确认进入房间，暂时不能发消息' : '发一条消息...'} />
                     <button onClick={() => void handleSendRoomChatMessage()} disabled={!user || roomInteractionLocked || !roomMessageDraft.trim() || sendingRoomMessage} className="rounded-xl bg-accent-cyan px-5 py-2.5 text-sm font-bold text-white disabled:opacity-50 hover:scale-105 shadow-lg transition-transform">发送</button>
                  </div>
               </div>
            </div>
          </div>
          
        </section>
      </div>
    </div>
  )
}
