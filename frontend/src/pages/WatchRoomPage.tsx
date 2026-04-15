import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Copy, Loader2, MessageSquare, Pause, Play, RefreshCw, Tv, UserPlus, Users } from 'lucide-react'
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

function formatDateTime(ts: number): string {
  if (!ts) return '未知'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function formatPosition(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatRelativeTime(ts: number): string {
  if (!ts) return '刚刚'
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

function shortError(message: string): string {
  if (!message) return ''
  return message.length > 300 ? `${message.slice(0, 300)}...` : message
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return '操作失败，请稍后重试'
}

function extractErrorStatus(error: unknown): number | null {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { status?: number } }).response
    if (typeof response?.status === 'number') return response.status
  }
  return null
}

function isBlocked(asset: MediaAsset | null): boolean {
  return Boolean(asset && (!asset.watch_enabled || asset.recommended_mode === 'blocked' || asset.probe_status === 'failed'))
}

function blockReason(asset: MediaAsset | null): string {
  if (!asset) return ''
  return shortError(asset.watch_block_reason || asset.probe_error || asset.last_error || '片源暂时不可用')
}

function socialStatusText(item: { current_room_name?: string; current_page?: string; status_text?: string }) {
  if (item.current_room_name) return `正在 ${item.current_room_name}`
  if (item.status_text) return item.status_text
  if (item.current_page === 'watch_room') return '正在房间内'
  if (item.current_page === 'watch_lobby') return '正在大厅'
  return '在线'
}

export default function WatchRoomPage() {
  const { roomId = '' } = useParams()
  const { user } = useAuth()
  const roomRef = useRef<WatchRoom | null>(null)
  const personalHistoryRef = useRef<WatchHistoryItem | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const roomChatListRef = useRef<HTMLDivElement | null>(null)
  const hlsRef = useRef<{ destroy: () => void } | null>(null)
  const personalSyncRunningRef = useRef(false)
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
  const [socialLoading, setSocialLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [switchingMediaId, setSwitchingMediaId] = useState('')
  const [playerHint, setPlayerHint] = useState('')
  const [roomLoadError, setRoomLoadError] = useState('')
  const [assetLoadError, setAssetLoadError] = useState('')
  const [libraryLoadError, setLibraryLoadError] = useState('')
  const [socialLoadError, setSocialLoadError] = useState('')
  const [roomChatError, setRoomChatError] = useState('')
  const [libraryReady, setLibraryReady] = useState(false)
  const [socialReady, setSocialReady] = useState(false)
  const [roomChatReady, setRoomChatReady] = useState(false)
  const [personalSyncedAt, setPersonalSyncedAt] = useState(0)
  const [roomParticipants, setRoomParticipants] = useState<OnlineUser[]>([])
  const [friends, setFriends] = useState<FriendSummary[]>([])
  const [outgoingInvites, setOutgoingInvites] = useState<RoomInvitation[]>([])
  const [inviteMessage, setInviteMessage] = useState('')
  const [invitingFriendId, setInvitingFriendId] = useState(0)
  const [roomMessages, setRoomMessages] = useState<RoomMessage[]>([])
  const [roomMessagesLoading, setRoomMessagesLoading] = useState(false)
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
      setLibraryReady(true)
      setLibraryLoadError('')
    } catch (error) {
      setLibraryLoadError(extractErrorMessage(error))
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
          setPersonalSyncedAt(nextHistory.value?.updated_at || 0)
        } else {
          const canReuseHistory = Boolean(
            personalHistoryRef.current &&
            personalHistoryRef.current.room_id === nextRoom.room_id &&
            personalHistoryRef.current.media_id === nextRoom.state.media_id
          )
          if (!canReuseHistory) {
            setPersonalHistory(null)
            setPersonalSyncedAt(0)
          }
        }
      } else {
        setAsset(null)
        setAssetLoadError('')
        setPersonalHistory(null)
        setPersonalSyncedAt(0)
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
        setPersonalSyncedAt(0)
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
    if (!socialReady) setSocialLoading(true)
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
      setSocialLoading(false)
    }
  }, [roomId, socialReady])

  const loadRoomChat = useCallback(async (silent = false) => {
    if (!silent) setRoomMessagesLoading(true)
    try {
      const messages = await getRoomMessages(roomId, 100)
      setRoomMessages(messages)
      setRoomChatReady(true)
      setRoomChatError('')
    } catch (error) {
      setRoomChatError(extractErrorMessage(error))
    } finally {
      if (!silent) setRoomMessagesLoading(false)
    }
  }, [roomId])

  useEffect(() => {
    void load(false)
    const timer = setInterval(() => {
      void load(true)
    }, 5000)
    return () => clearInterval(timer)
  }, [load])

  useEffect(() => {
    void loadLibrary()
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
    setSocialLoading(true)
  }, [roomId])

  useEffect(() => {
    const requiresRoomPresence = Boolean(currentUserId && currentRoomId && ownerUserId !== currentUserId)
    roomPresenceRequestRef.current = null
    roomPresenceReadyRef.current = !requiresRoomPresence
    setRoomPresenceReady(!requiresRoomPresence)
    setRoomPresencePending(requiresRoomPresence)
    setRoomPresenceError('')
  }, [currentRoomId, currentUserId, ownerUserId])

  useEffect(() => {
    void loadSocialContext()
    const timer = window.setInterval(() => {
      void loadSocialContext()
    }, 12000)
    return () => window.clearInterval(timer)
  }, [loadSocialContext, user?.id])

  useEffect(() => {
    void loadRoomChat()
    const timer = window.setInterval(() => {
      void loadRoomChat(true)
    }, 5000)
    return () => window.clearInterval(timer)
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
      setPersonalSyncedAt(historyEntry.updated_at)
    } catch {
      // Keep playback UX smooth even if personal history sync fails.
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
      setPersonalSyncedAt(0)
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
    }

    return () => {
      cancelled = true
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
    }
  }, [assetBlocked, room?.state.playback_mode, room?.state.playback_url])

  const syncRoomState = async (paused: boolean) => {
    if (!room) return
    if (!(await ensureRoomPresence())) return
    const currentTime = videoRef.current?.currentTime || room.state.position_seconds || 0
    setBusy(true)
    try {
      const nextRoom = await updateWatchRoomState(room.room_id, {
        media_id: room.state.media_id,
        paused,
        position_seconds: currentTime,
        updated_by: user?.username || 'web',
      })
      setRoom(nextRoom)
      if (user && nextRoom.state.media_id) {
        await syncPersonalProgress(nextRoom, true)
      }
      setPlayerHint(paused ? '已写入暂停位置。' : '已写入播放位置。')
    } catch (error) {
      setPlayerHint(extractErrorMessage(error))
    } finally {
      setBusy(false)
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
      setPersonalSyncedAt(nextResume?.updated_at || 0)
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
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
      </div>
    )
  }

  if (!room) {
    return (
      <div className="rounded-xl border border-dashed border-border p-8 text-sm text-text-muted">
        房间不存在。<Link to="/watch" className="text-accent-primary">返回同看中心</Link>
      </div>
    )
  }

  const canAttemptPlayback = Boolean(room.state.playback_url) && !assetBlocked
  const roomPresenceRequired = Boolean(user && room.owner_user_id !== user.id)
  const roomInteractionLocked = roomPresenceRequired && !roomPresenceReady
  const controlsDisabled = busy || !room.state.media_id || assetBlocked || roomInteractionLocked

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Tv className="h-5 w-5 text-accent-cyan" />
            <h1 className="text-2xl font-bold">{room.name}</h1>
          </div>
          <p className="text-sm text-text-secondary">
            房主昵称：{room.host_name || '未命名'}，账号归属：{room.owner_username || '匿名房间'}，房间号：{room.room_id}
          </p>
          {isOwner && <p className="text-xs text-accent-primary">这是你创建的房间。</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/watch"
            className="flex items-center gap-1.5 rounded-lg border border-border bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回
          </Link>
          <button
            onClick={copyInviteLink}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
          >
            <Copy className="h-3.5 w-3.5" />
            复制邀请链接
          </button>
          <button
            onClick={() => void load(false)}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
        </div>
      </div>

      {roomLoadError && room && (
        <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl bg-warning/10 px-4 py-3 text-sm text-warning">
          <div className="flex min-w-0 items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p>房间状态刷新失败：{shortError(roomLoadError)}</p>
              <p className="mt-1 text-xs">当前展示的是上次成功同步的房间快照。</p>
            </div>
          </div>
          <button
            onClick={() => void load(false)}
            className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
          >
            重试房间状态
          </button>
        </div>
      )}

      {roomInteractionLocked && (
        <div
          className={cn(
            'flex flex-wrap items-start justify-between gap-3 rounded-xl px-4 py-3 text-sm',
            roomPresencePending ? 'bg-accent-primary/10 text-accent-primary' : 'bg-warning/10 text-warning'
          )}
        >
          <div className="flex min-w-0 items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p>{roomPresencePending ? '正在确认你已进入这个房间。' : `进入房间确认失败：${shortError(roomPresenceError)}`}</p>
              <p className="mt-1 text-xs">
                在首次房间心跳成功前，聊天、邀请、切换片源和写入播放状态会先锁定，避免直接触发权限错误。
              </p>
            </div>
          </div>
          {!roomPresencePending && (
            <button
              onClick={() => void sendRoomPresenceHeartbeat({ requireReady: true })}
              className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
            >
              重新确认已进入房间
            </button>
          )}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="space-y-4">
          {assetLoadError && (
            <div
              className={cn(
                'flex flex-wrap items-start justify-between gap-3 rounded-xl px-4 py-3 text-sm',
                asset ? 'bg-warning/10 text-warning' : 'bg-danger/8 text-danger'
              )}
            >
              <div className="flex min-w-0 items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p>
                    {asset
                      ? '当前片源详情刷新失败，正在显示上次成功同步的片源信息。'
                      : `当前房间已绑定片源，但片源详情加载失败：${shortError(assetLoadError)}`}
                  </p>
                  {asset && <p className="mt-1 text-xs">如果房主刚切换了片源，稍后重试即可同步到最新详情。</p>}
                </div>
              </div>
              <button
                onClick={() => void load(false)}
                className={cn(
                  'shrink-0 rounded-lg px-3 py-2 text-xs font-medium text-white',
                  asset ? 'bg-warning hover:bg-warning/90' : 'bg-danger hover:bg-danger/90'
                )}
              >
                重读片源详情
              </button>
            </div>
          )}

          {assetBlocked && (
            <div className="flex items-start gap-2 rounded-xl bg-danger/8 px-4 py-3 text-sm text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">当前片源已被禁用</p>
                <p className="mt-1">{assetBlockReason}</p>
              </div>
            </div>
          )}

          <div className="overflow-hidden rounded-2xl border border-border bg-black">
            {canAttemptPlayback ? (
              <video
                ref={videoRef}
                controls
                playsInline
                className="aspect-video w-full bg-black"
                onLoadedMetadata={() => {
                  if (!videoRef.current) return
                  const resumePosition = pendingSeekRef.current ?? room.state.position_seconds
                  if (resumePosition > 0 && Math.abs(videoRef.current.currentTime - resumePosition) > 1) {
                    videoRef.current.currentTime = resumePosition
                  }
                  pendingSeekRef.current = null
                }}
                onPause={() => {
                  if (room) void syncPersonalProgress(room, true)
                }}
                onEnded={() => {
                  if (room) void syncPersonalProgress(room, true)
                }}
              />
            ) : (
              <div className="flex aspect-video items-center justify-center px-6 text-center text-sm text-white/70">
                {assetBlocked
                  ? `当前片源不可播放：${assetBlockReason}`
                  : '当前没有可播放地址。通常是因为片源需要先预转 HLS，或者片源尚未准备好。'}
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => syncRoomState(false)}
              disabled={controlsDisabled}
              className="flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-2 text-xs font-medium text-white hover:bg-accent-primary/90 disabled:opacity-60"
            >
              <Play className="h-3.5 w-3.5" />
              写入播放状态
            </button>
            <button
              onClick={() => syncRoomState(true)}
              disabled={controlsDisabled}
              className="flex items-center gap-1.5 rounded-lg bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary disabled:opacity-60"
            >
              <Pause className="h-3.5 w-3.5" />
              写入暂停状态
            </button>
            <button
              onClick={refreshPlaybackUrl}
              disabled={controlsDisabled}
              className="rounded-lg bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary disabled:opacity-60"
            >
              重新同步房间片源
            </button>
            {asset && asset.recommended_mode === 'pretranscode_hls' && !assetBlocked && (
              <button
                onClick={handlePrepareHls}
                disabled={busy || asset.hls_status === 'preparing' || roomInteractionLocked}
                className="rounded-lg bg-accent-cyan px-3 py-2 text-xs font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
              >
                {asset.hls_status === 'preparing' ? 'HLS 准备中' : '准备 HLS'}
              </button>
            )}
          </div>

          {playerHint && (
            <div className="rounded-lg bg-accent-cyan/10 px-3 py-2 text-xs text-accent-cyan">
              {playerHint}
            </div>
          )}
        </section>

        <section className="space-y-4">
          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-3">
            <h2 className="text-lg font-semibold">房间状态</h2>
            <div className="grid grid-cols-2 gap-3 text-xs text-text-secondary">
              <div className="rounded-lg bg-bg-secondary p-3">
                <p className="text-text-muted">播放模式</p>
                <p className="mt-1 font-medium text-text-primary">{room.state.playback_mode === 'hls' ? 'HLS' : '直放'}</p>
              </div>
              <div className="rounded-lg bg-bg-secondary p-3">
                <p className="text-text-muted">状态</p>
                <p className="mt-1 font-medium text-text-primary">{room.state.paused ? '已暂停' : '播放中'}</p>
              </div>
              <div className="rounded-lg bg-bg-secondary p-3">
                <p className="text-text-muted">位置</p>
                <p className="mt-1 font-medium text-text-primary">{formatPosition(room.state.position_seconds)}</p>
              </div>
              <div className="rounded-lg bg-bg-secondary p-3">
                <p className="text-text-muted">最近更新</p>
                <p className="mt-1 font-medium text-text-primary">{formatDateTime(room.state.updated_at)}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs text-text-secondary">
              <div className="rounded-lg bg-bg-secondary p-3">
                <p className="text-text-muted">账号房主</p>
                <p className="mt-1 font-medium text-text-primary">{room.owner_username || '匿名房间'}</p>
              </div>
              <div className="rounded-lg bg-bg-secondary p-3">
                <p className="text-text-muted">最近操作人</p>
                <p className="mt-1 font-medium text-text-primary">{room.state.updated_by || '未知'}</p>
              </div>
            </div>
            <div className="rounded-lg bg-bg-secondary p-3 text-xs text-text-secondary">
              <p className="text-text-muted">个人观看记录</p>
              <p className="mt-1 font-medium text-text-primary">
                {user
                  ? personalSyncedAt
                    ? `已同步到你的账号 · ${formatDateTime(personalSyncedAt)}`
                    : '当前账号尚未同步到观看记录'
                  : '未登录时不会保存个人观看进度'}
              </p>
            </div>
            <div className="rounded-lg bg-bg-secondary p-3 text-xs text-text-secondary">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-text-muted">我的续播位置</p>
                  <p className="mt-1 font-medium text-text-primary">
                    {user
                      ? personalHistory
                        ? `${formatPosition(personalHistory.position_seconds)}${personalHistory.paused ? ' · 上次已暂停' : ' · 上次播放中'}`
                        : '还没有你的个人续播记录'
                      : '登录后可使用个人续播'}
                  </p>
                  {user && personalHistory && (
                    <p className="mt-1 text-text-muted">
                      当前房间进度 {formatPosition(room.state.position_seconds)}
                      {resumeOffset >= 5 ? ` · 相差 ${formatPosition(resumeOffset)}` : ' · 已基本同步'}
                    </p>
                  )}
                </div>
                <button
                  onClick={handleResumeToPersonalProgress}
                  disabled={!canAttemptPlayback || !personalHistory}
                  className="shrink-0 rounded-lg bg-accent-cyan px-3 py-2 text-xs font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
                >
                  恢复我的进度
                </button>
              </div>
            </div>
            <div className="rounded-lg bg-bg-secondary p-3 text-xs text-text-secondary">
              <p className="text-text-muted">播放地址</p>
              <p className="mt-1 break-all text-text-primary">{room.state.playback_url || '尚未生成'}</p>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-3">
            <h2 className="text-lg font-semibold">当前片源</h2>
            {asset ? (
              <>
                <div className="space-y-1">
                  <p className="text-sm font-medium break-all">{asset.title}</p>
                  <p className="text-xs text-text-muted break-all">{asset.relative_path}</p>
                </div>
                <div className="flex flex-wrap gap-2 text-[11px]">
                  <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">{asset.container || 'unknown'}</span>
                  <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">{formatBytes(asset.size)}</span>
                  <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">{asset.direct_play_supported ? '可直放' : '需 HLS'}</span>
                  <span className={asset.probe_status === 'failed' ? 'rounded-full bg-danger/10 px-2 py-0.5 text-danger' : 'rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary'}>
                    {asset.probe_status === 'failed' ? '解析失败' : asset.probe_status === 'ready' ? '解析正常' : '待探测'}
                  </span>
                  <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">{asset.hls_status}</span>
                </div>
                {assetBlocked && (
                  <div className="flex items-start gap-2 rounded-lg bg-danger/8 px-3 py-2 text-xs text-danger">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="break-all">{assetBlockReason}</span>
                  </div>
                )}
                {asset.last_error && (
                  <div className="flex items-start gap-2 rounded-lg bg-danger/8 px-3 py-2 text-xs text-danger">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="break-all">{shortError(asset.last_error)}</span>
                  </div>
                )}
                <Link
                  to="/watch"
                  className="inline-flex items-center gap-1.5 text-xs text-accent-primary hover:text-accent-primary/80"
                >
                  返回同看中心更换片源
                </Link>
              </>
            ) : (
              <p className="text-sm text-text-muted">当前房间还没有绑定片源。</p>
            )}
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-accent-cyan" />
              <h2 className="text-lg font-semibold">房间成员与邀请</h2>
            </div>

            {socialLoading && !socialReady ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 className="h-5 w-5 animate-spin text-accent-primary" />
              </div>
            ) : socialLoadError && !socialReady ? (
              <div className="space-y-3 rounded-lg border border-danger/20 bg-danger/5 px-4 py-5 text-sm text-danger">
                <div className="flex items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>房间成员与邀请暂时加载失败：{shortError(socialLoadError)}</span>
                </div>
                <button
                  onClick={() => void loadSocialContext()}
                  className="inline-flex w-fit rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
                >
                  重试成员状态
                </button>
              </div>
            ) : (
              <>
                {socialLoadError && socialReady && (
                  <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                    <div className="flex min-w-0 items-start gap-2">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>成员状态刷新失败，当前展示的是上次成功同步的成员和邀请快照。</span>
                    </div>
                    <button
                      onClick={() => void loadSocialContext()}
                      className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                    >
                      重试成员状态
                    </button>
                  </div>
                )}

                <div className="rounded-lg bg-bg-secondary p-3 text-xs text-text-secondary">
                  <p className="text-text-muted">当前在线成员</p>
                  <p className="mt-1 font-medium text-text-primary">{roomParticipants.length} 人在线</p>
                  {outgoingInviteFriendIds.size > 0 && (
                    <p className="mt-1 text-text-muted">你已向 {outgoingInviteFriendIds.size} 位好友发出待处理邀请</p>
                  )}
                </div>

                {roomParticipants.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                    目前还没有登录用户在这个房间里心跳在线。
                  </div>
                ) : (
                  <div className="space-y-2">
                    {roomParticipants.map((participant) => (
                      <div key={participant.user_id} className="rounded-lg bg-bg-secondary px-3 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-text-primary">{participant.username}</p>
                            <p className="mt-1 text-[11px] text-text-secondary">{socialStatusText(participant)}</p>
                          </div>
                          <span className="text-[11px] text-text-muted">{formatRelativeTime(participant.last_seen_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {!user ? (
                  <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                    登录后可以直接邀请好友进房间。
                  </div>
                ) : inviteableFriends.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                    你还没有好友，先去大厅加好友后就能一键邀请进房间。
                  </div>
                ) : (
                  <>
                    <input
                      value={inviteMessage}
                      onChange={(event) => setInviteMessage(event.target.value)}
                      disabled={roomInteractionLocked}
                      placeholder="邀请留言（可选）"
                      className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary disabled:opacity-60"
                    />
                    <div className="space-y-2">
                      {inviteableFriends.map((friend) => {
                        const alreadyInRoom = currentRoomParticipantIds.has(friend.user_id)
                        const alreadyInvited = outgoingInviteFriendIds.has(friend.user_id)
                        return (
                          <div key={friend.user_id} className="rounded-lg bg-bg-secondary px-3 py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-text-primary">{friend.username}</p>
                                <p className="mt-1 text-[11px] text-text-muted">
                                  {friend.is_online ? socialStatusText(friend) : `最近在线 ${formatRelativeTime(friend.last_seen_at)}`}
                                </p>
                              </div>
                              <div className="flex shrink-0 flex-wrap gap-2">
                                {friend.current_room_id && friend.current_room_id !== roomId && (
                                  <Link
                                    to={`/watch/${friend.current_room_id}`}
                                    className="rounded-lg bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
                                  >
                                    看 TA 在哪
                                  </Link>
                                )}
                                <button
                                  onClick={() => void handleInviteFriend(friend)}
                                  disabled={roomInteractionLocked || alreadyInRoom || alreadyInvited || invitingFriendId === friend.user_id}
                                  className={cn(
                                    'inline-flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-medium text-white disabled:opacity-60',
                                    alreadyInRoom || alreadyInvited ? 'bg-bg-card text-text-secondary' : 'bg-accent-primary hover:bg-accent-primary/90'
                                  )}
                                >
                                  <UserPlus className="h-3.5 w-3.5" />
                                  {alreadyInRoom ? '已在房间' : alreadyInvited ? '已邀请' : invitingFriendId === friend.user_id ? '邀请中...' : '邀请'}
                                </button>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {outgoingInviteFriendIds.size > 0 && (
                      <div className="rounded-lg bg-bg-secondary px-3 py-3 text-xs text-text-secondary">
                        未处理邀请会同步显示在大厅里，好友可以从大厅直接进入这个房间。
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-3">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-accent-primary" />
              <h2 className="text-lg font-semibold">房间聊天</h2>
            </div>

            <div className="rounded-xl border border-border bg-bg-secondary p-3">
              {roomMessagesLoading && !roomChatReady ? (
                <div className="flex items-center justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-accent-primary" />
                </div>
              ) : roomChatError && !roomChatReady ? (
                <div className="space-y-3 py-2 text-sm text-danger">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>房间聊天暂时加载失败：{shortError(roomChatError)}</span>
                  </div>
                  <button
                    onClick={() => void loadRoomChat()}
                    className="inline-flex rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
                  >
                    重试聊天
                  </button>
                </div>
              ) : roomMessages.length === 0 ? (
                <div className="space-y-3">
                  {roomChatError && roomChatReady && (
                    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                      <div className="flex min-w-0 items-start gap-2">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>聊天刷新失败，当前展示的是上次成功同步的聊天快照。</span>
                      </div>
                      <button
                        onClick={() => void loadRoomChat()}
                        className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                      >
                        重试聊天
                      </button>
                    </div>
                  )}
                  <div className="py-10 text-center text-sm text-text-muted">
                    房间里还没有聊天记录，先发第一条消息吧。
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  {roomChatError && roomChatReady && (
                    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                      <div className="flex min-w-0 items-start gap-2">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>聊天刷新失败，当前展示的是上次成功同步的聊天快照。</span>
                      </div>
                      <button
                        onClick={() => void loadRoomChat()}
                        className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                      >
                        重试聊天
                      </button>
                    </div>
                  )}
                  <div ref={roomChatListRef} className="max-h-72 space-y-2 overflow-y-auto pr-1">
                    {roomMessages.map((message) => (
                      <div key={message.message_id} className={cn('flex', message.is_mine ? 'justify-end' : 'justify-start')}>
                        <div
                          className={cn(
                            'max-w-[85%] rounded-2xl px-3 py-2 text-sm',
                            message.is_mine ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-primary'
                          )}
                        >
                          <p className="break-words">{message.body}</p>
                          <p className={cn('mt-1 text-[10px]', message.is_mine ? 'text-white/70' : 'text-text-muted')}>
                            {message.is_mine ? '我' : message.sender_username} · {formatRelativeTime(message.created_at)}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {!user ? (
              <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                登录后才能在房间里发消息。
              </div>
            ) : (
              <div className="flex gap-2">
                <input
                  value={roomMessageDraft}
                  onChange={(event) => setRoomMessageDraft(event.target.value)}
                  disabled={roomInteractionLocked}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      void handleSendRoomChatMessage()
                    }
                  }}
                  className="flex-1 rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary disabled:opacity-60"
                  placeholder={roomInteractionLocked ? '正在确认进入房间，暂时不能发消息' : '发一条房间消息'}
                />
                <button
                  onClick={() => void handleSendRoomChatMessage()}
                  disabled={roomInteractionLocked || sendingRoomMessage || !roomMessageDraft.trim()}
                  className="rounded-lg bg-accent-cyan px-4 py-2 text-sm font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
                >
                  {sendingRoomMessage ? '发送中...' : '发送'}
                </button>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">快速换源</h2>
                <p className="mt-1 text-xs text-text-muted">在房间内直接切换片源。可用片源会优先排在前面。</p>
              </div>
              <button
                onClick={() => void loadLibrary(true)}
                disabled={libraryLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary disabled:opacity-60"
              >
                {libraryLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                重扫片源
              </button>
            </div>

            <input
              value={assetQuery}
              onChange={(event) => setAssetQuery(event.target.value)}
              placeholder="搜索片源标题或文件名"
              className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
            />

            {libraryLoadError && libraryReady && (
              <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                <div className="flex min-w-0 items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>媒体库刷新失败，当前展示的是上次成功同步的片源快照。</span>
                </div>
                <button
                  onClick={() => void loadLibrary(false)}
                  className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                >
                  重试片源列表
                </button>
              </div>
            )}

            {libraryLoading && libraryAssets.length === 0 ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-accent-primary" />
              </div>
            ) : libraryLoadError && !libraryReady ? (
              <div className="space-y-3 rounded-lg border border-danger/20 bg-danger/5 px-4 py-5 text-sm text-danger">
                <div className="flex items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>片源列表暂时加载失败：{shortError(libraryLoadError)}</span>
                </div>
                <button
                  onClick={() => void loadLibrary(false)}
                  className="inline-flex w-fit rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
                >
                  重试片源列表
                </button>
              </div>
            ) : candidateAssets.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                没有匹配的片源。你可以先重扫媒体库，或者换个关键词试试。
              </div>
            ) : (
              <div className="space-y-2">
                {candidateAssets.map((candidate) => {
                  const candidateBlocked = isBlocked(candidate)
                  const currentSelected = room.state.media_id === candidate.media_id
                  return (
                    <div key={candidate.media_id} className="rounded-lg bg-bg-secondary px-3 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-text-primary">{candidate.title}</p>
                          <p className="mt-1 truncate text-xs text-text-muted">{candidate.relative_path}</p>
                          <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                            <span className="rounded-full bg-bg-card px-2 py-0.5 text-text-secondary">
                              {candidate.direct_play_supported ? '可直放' : candidate.recommended_mode === 'pretranscode_hls' ? '需 HLS' : '不可用'}
                            </span>
                            <span className="rounded-full bg-bg-card px-2 py-0.5 text-text-secondary">
                              {candidate.probe_status === 'failed' ? '解析失败' : candidate.probe_status === 'ready' ? '解析正常' : '待探测'}
                            </span>
                            <span className="rounded-full bg-bg-card px-2 py-0.5 text-text-secondary">{candidate.hls_status}</span>
                            {currentSelected && (
                              <span className="rounded-full bg-accent-primary/12 px-2 py-0.5 text-accent-primary">当前片源</span>
                            )}
                          </div>
                          {candidateBlocked && (
                            <p className="mt-2 text-xs text-danger">{blockReason(candidate)}</p>
                          )}
                        </div>
                        <button
                          onClick={() => void handleSwitchAsset(candidate)}
                          disabled={roomInteractionLocked || candidateBlocked || currentSelected || Boolean(switchingMediaId)}
                          className="shrink-0 rounded-lg bg-accent-primary px-3 py-2 text-xs font-medium text-white hover:bg-accent-primary/90 disabled:opacity-60"
                        >
                          {switchingMediaId === candidate.media_id
                            ? '切换中...'
                            : currentSelected
                              ? '当前片源'
                              : candidate.recommended_mode === 'pretranscode_hls' && candidate.hls_status !== 'ready'
                                ? '切换并准备 HLS'
                                : '切换到此片源'}
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
