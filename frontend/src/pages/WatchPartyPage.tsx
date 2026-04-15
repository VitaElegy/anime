import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, Check, CheckCircle2, Clock3, Film, Loader2, MessageSquare, RefreshCw, Tv, UserPlus, Users, X } from 'lucide-react'
import {
  acceptFriendRequest,
  acceptRoomInvitation,
  createWatchRoom,
  dismissRoomInvitation,
  getDirectMessages,
  getWatchLobby,
  heartbeatPresence,
  listMediaLibrary,
  listWatchHistory,
  prepareMediaHls,
  rejectFriendRequest,
  removeFriend,
  scanMediaLibrary,
  sendDirectMessage,
  sendFriendRequest,
} from '@/api'
import { useAuth } from '@/contexts/useAuth'
import type { DirectMessage, MediaAsset, WatchHistoryItem, WatchLobbyOverview, WatchLobbyRoom } from '@/types'
import { cn, formatBytes } from '@/lib/utils'

function formatUpdatedAt(ts: number): string {
  if (!ts) return '未知'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function formatRelativeTime(ts: number): string {
  if (!ts) return '刚刚'
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

function formatPosition(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function trimError(message: string): string {
  if (!message) return ''
  return message.length > 200 ? `${message.slice(0, 200)}...` : message
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return '操作失败，请稍后重试'
}

type LoadFailure = {
  key: 'library' | 'lobby' | 'history'
  label: string
  message: string
}

function isBlocked(asset: MediaAsset): boolean {
  return !asset.watch_enabled || asset.recommended_mode === 'blocked' || asset.probe_status === 'failed'
}

function blockReason(asset: MediaAsset): string {
  return trimError(asset.watch_block_reason || asset.probe_error || asset.last_error || '片源暂时不可用')
}

function modeLabel(asset: MediaAsset): string {
  if (isBlocked(asset)) return '不可用于同看'
  return asset.recommended_mode === 'direct_play' ? '可直放' : '建议预转 HLS'
}

function probeStatusLabel(status: MediaAsset['probe_status']): string {
  switch (status) {
    case 'ready':
      return '解析正常'
    case 'failed':
      return '解析失败'
    case 'unavailable':
      return '探测受限'
    default:
      return '待探测'
  }
}

function hlsStatusLabel(status: MediaAsset['hls_status']): string {
  switch (status) {
    case 'ready':
      return 'HLS 已就绪'
    case 'preparing':
      return 'HLS 准备中'
    case 'error':
      return 'HLS 失败'
    default:
      return '尚未准备'
  }
}

function socialStatusText(item: { current_room_name?: string; current_page?: string; status_text?: string }) {
  if (item.current_room_name) return `正在 ${item.current_room_name}`
  if (item.status_text) return item.status_text
  if (item.current_page === 'watch_room') return '正在房间内'
  if (item.current_page === 'watch_lobby') return '正在大厅'
  return '在线'
}

function buildLoadWarning(failures: LoadFailure[]): string {
  if (failures.length === 0) return ''
  return `${failures.map((failure) => `${failure.label}：${trimError(failure.message)}`).join('；')}。其余内容已保留，可稍后重试。`
}

async function fetchLobbyHistoryBundle(isAuthenticated: boolean) {
  const [overviewResult, watchHistoryResult] = await Promise.allSettled([
    getWatchLobby(),
    isAuthenticated ? listWatchHistory(6) : Promise.resolve([] as WatchHistoryItem[]),
  ])
  const failures: LoadFailure[] = []

  const overview = overviewResult.status === 'fulfilled' ? overviewResult.value : null
  if (overviewResult.status === 'rejected') {
    failures.push({
      key: 'lobby',
      label: '放映大厅',
      message: extractErrorMessage(overviewResult.reason),
    })
  }

  const watchHistory = watchHistoryResult.status === 'fulfilled' ? watchHistoryResult.value : null
  if (watchHistoryResult.status === 'rejected') {
    failures.push({
      key: 'history',
      label: '观看记录',
      message: extractErrorMessage(watchHistoryResult.reason),
    })
  }

  return { overview, watchHistory, failures }
}

async function fetchWatchPartyBundle(forceScan: boolean, isAuthenticated: boolean) {
  const [libraryResult, overviewResult, watchHistoryResult] = await Promise.allSettled([
    forceScan ? scanMediaLibrary() : listMediaLibrary(),
    getWatchLobby(),
    isAuthenticated ? listWatchHistory(6) : Promise.resolve([] as WatchHistoryItem[]),
  ])
  const failures: LoadFailure[] = []

  const library = libraryResult.status === 'fulfilled' ? libraryResult.value : null
  if (libraryResult.status === 'rejected') {
    failures.push({
      key: 'library',
      label: '媒体库',
      message: extractErrorMessage(libraryResult.reason),
    })
  }

  const overview = overviewResult.status === 'fulfilled' ? overviewResult.value : null
  if (overviewResult.status === 'rejected') {
    failures.push({
      key: 'lobby',
      label: '放映大厅',
      message: extractErrorMessage(overviewResult.reason),
    })
  }

  const watchHistory = watchHistoryResult.status === 'fulfilled' ? watchHistoryResult.value : null
  if (watchHistoryResult.status === 'rejected') {
    failures.push({
      key: 'history',
      label: '观看记录',
      message: extractErrorMessage(watchHistoryResult.reason),
    })
  }

  return { library, overview, watchHistory, failures }
}

export default function WatchPartyPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const chatListRef = useRef<HTMLDivElement | null>(null)
  const [assets, setAssets] = useState<MediaAsset[]>([])
  const [history, setHistory] = useState<WatchHistoryItem[]>([])
  const [rooms, setRooms] = useState<WatchLobbyRoom[]>([])
  const [lobby, setLobby] = useState<WatchLobbyOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [roomsLoading, setRoomsLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [preparingId, setPreparingId] = useState('')
  const [hostName, setHostName] = useState('elegy')
  const [roomName, setRoomName] = useState('')
  const [selectedMediaId, setSelectedMediaId] = useState('')
  const [showMineOnly, setShowMineOnly] = useState(false)
  const [actionMessage, setActionMessage] = useState('')
  const [actionTone, setActionTone] = useState<'info' | 'error'>('info')
  const [loadWarning, setLoadWarning] = useState('')
  const [libraryLoadError, setLibraryLoadError] = useState('')
  const [lobbyLoadError, setLobbyLoadError] = useState('')
  const [historyLoadError, setHistoryLoadError] = useState('')
  const [friendUsername, setFriendUsername] = useState('')
  const [friendBusy, setFriendBusy] = useState(false)
  const [friendActionId, setFriendActionId] = useState(0)
  const [roomInviteActionId, setRoomInviteActionId] = useState(0)
  const [removingFriendId, setRemovingFriendId] = useState(0)
  const [selectedFriendId, setSelectedFriendId] = useState(0)
  const [chatMessages, setChatMessages] = useState<DirectMessage[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const [sendingMessage, setSendingMessage] = useState(false)
  const [chatDraft, setChatDraft] = useState('')

  const applyLobby = useCallback((overview: WatchLobbyOverview) => {
    setLobby(overview)
    setRooms(overview.rooms)
    setSelectedFriendId((current) => {
      if (current && overview.friends.some((item) => item.user_id === current)) return current
      return overview.friends[0]?.user_id || 0
    })
  }, [])

  const loadLobbySnapshot = useCallback(async (silent = false) => {
    if (!silent) setRoomsLoading(true)
    try {
      const { overview, watchHistory, failures } = await fetchLobbyHistoryBundle(Boolean(user))
      const lobbyFailure = failures.find((failure) => failure.key === 'lobby')
      const historyFailure = failures.find((failure) => failure.key === 'history')

      if (overview) {
        applyLobby(overview)
        setLobbyLoadError('')
      } else if (lobbyFailure) {
        setLobbyLoadError(lobbyFailure.message)
      }

      if (watchHistory) {
        setHistory(watchHistory)
        setHistoryLoadError('')
      } else if (historyFailure) {
        setHistoryLoadError(historyFailure.message)
      }

      setLoadWarning(buildLoadWarning(failures))
    } catch (error) {
      const message = extractErrorMessage(error)
      setLobbyLoadError(message)
      setHistoryLoadError(message)
      setLoadWarning(`放映大厅：${trimError(message)}。其余内容已保留，可稍后重试。`)
    } finally {
      if (!silent) setRoomsLoading(false)
    }
  }, [applyLobby, user])

  const load = useCallback(async (forceScan = false) => {
    if (forceScan) setRefreshing(true)
    setRoomsLoading(true)
    try {
      const { library, overview, watchHistory, failures } = await fetchWatchPartyBundle(forceScan, Boolean(user))
      const libraryFailure = failures.find((failure) => failure.key === 'library')
      const lobbyFailure = failures.find((failure) => failure.key === 'lobby')
      const historyFailure = failures.find((failure) => failure.key === 'history')

      if (library) {
        setAssets(library.items)
        setLibraryLoadError('')
        setSelectedMediaId((current) => {
          const currentAsset = library.items.find((item) => item.media_id === current)
          if (currentAsset) return current
          return (
            library.items.find((item) => !isBlocked(item))?.media_id ||
            library.items.find((item) => item.watch_enabled)?.media_id ||
            library.items[0]?.media_id ||
            ''
          )
        })
      } else if (libraryFailure) {
        setLibraryLoadError(libraryFailure.message)
      }

      if (overview) {
        applyLobby(overview)
        setLobbyLoadError('')
      } else if (lobbyFailure) {
        setLobbyLoadError(lobbyFailure.message)
      }

      if (watchHistory) {
        setHistory(watchHistory)
        setHistoryLoadError('')
      } else if (historyFailure) {
        setHistoryLoadError(historyFailure.message)
      }

      setLoadWarning(buildLoadWarning(failures))
    } catch (error) {
      const message = extractErrorMessage(error)
      setLibraryLoadError(message)
      setLobbyLoadError(message)
      setHistoryLoadError(message)
      setLoadWarning(`媒体库：${trimError(message)}。当前页面部分内容可能不是最新状态。`)
    } finally {
      setLoading(false)
      setRoomsLoading(false)
      setRefreshing(false)
    }
  }, [applyLobby, user])

  useEffect(() => {
    void load(false)
  }, [load])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadLobbySnapshot(true)
    }, 15000)
    return () => window.clearInterval(timer)
  }, [loadLobbySnapshot])

  useEffect(() => {
    if (user?.username) {
      setHostName(user.username)
    }
  }, [user?.username])

  useEffect(() => {
    if (!user && showMineOnly) {
      setShowMineOnly(false)
    }
  }, [showMineOnly, user])

  const selectedAsset = assets.find((item) => item.media_id === selectedMediaId) || null
  const selectedAssetBlocked = Boolean(selectedAsset && isBlocked(selectedAsset))
  const onlineUsers = lobby?.online_users || []
  const friends = lobby?.friends || []
  const incomingRequests = lobby?.incoming_requests || []
  const outgoingRequests = lobby?.outgoing_requests || []
  const incomingRoomInvitations = lobby?.incoming_room_invitations || []
  const outgoingRoomInvitations = lobby?.outgoing_room_invitations || []
  const selectedFriend = friends.find((item) => item.user_id === selectedFriendId) || null
  const visibleRooms = showMineOnly && user ? rooms.filter((item) => item.owner_user_id === user.id) : rooms
  const sortedRooms = [...visibleRooms].sort((left, right) => {
    const leftMine = user && left.owner_user_id === user.id ? 1 : 0
    const rightMine = user && right.owner_user_id === user.id ? 1 : 0
    return rightMine - leftMine || right.updated_at - left.updated_at
  })

  const loadConversation = useCallback(async (friendUserId: number) => {
    if (!user || !friendUserId) {
      setChatMessages([])
      return
    }
    setChatLoading(true)
    try {
      const messages = await getDirectMessages(friendUserId, 80)
      setChatMessages(messages)
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setChatLoading(false)
    }
  }, [user])

  useEffect(() => {
    if (!user) return

    const heartbeat = async () => {
      try {
        await heartbeatPresence({
          page: 'watch_lobby',
          status_text: selectedAsset ? `在大厅挑片：${selectedAsset.title}` : '在放映大厅',
        })
      } catch {
        /* best effort */
      }
    }

    void heartbeat()
    const timer = window.setInterval(() => {
      void heartbeat()
    }, 30000)
    return () => window.clearInterval(timer)
  }, [selectedAsset, user])

  useEffect(() => {
    if (!user || !selectedFriendId) {
      setChatMessages([])
      return
    }
    void loadConversation(selectedFriendId)
  }, [loadConversation, selectedFriendId, user])

  useEffect(() => {
    if (!user || !selectedFriendId) return
    const timer = window.setInterval(() => {
      void loadConversation(selectedFriendId)
    }, 8000)
    return () => window.clearInterval(timer)
  }, [loadConversation, selectedFriendId, user])

  useEffect(() => {
    setChatDraft('')
  }, [selectedFriendId])

  useEffect(() => {
    const element = chatListRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }, [chatMessages.length, selectedFriendId])

  const handlePrepare = async (asset: MediaAsset) => {
    if (isBlocked(asset)) return
    setPreparingId(asset.media_id)
    setActionMessage('')
    try {
      await prepareMediaHls(asset.media_id, asset.hls_status === 'error')
      setActionTone('info')
      setActionMessage(`已开始为《${asset.title}》准备 HLS，稍后会自动刷新状态。`)
      await load()
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setPreparingId('')
    }
  }

  const handleCreateRoom = async (asset: MediaAsset | null) => {
    if (!asset || isBlocked(asset)) return
    setCreating(true)
    setActionMessage('')
    try {
      const room = await createWatchRoom({
        name: roomName.trim() || `一起看 · ${asset.title}`,
        host_name: hostName.trim() || 'guest',
        media_id: asset.media_id,
      })
      navigate(`/watch/${room.room_id}`)
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setCreating(false)
    }
  }

  const handleSendFriendRequest = async (targetUsername?: string) => {
    const username = (targetUsername ?? friendUsername).trim()
    if (!username) return
    setFriendBusy(true)
    setActionMessage('')
    try {
      const request = await sendFriendRequest(username)
      setActionTone('info')
      setActionMessage(
        request.status === 'accepted'
          ? `已和 ${username} 成为好友。`
          : `好友申请已发送给 ${username}。`
      )
      setFriendUsername('')
      await loadLobbySnapshot()
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setFriendBusy(false)
    }
  }

  const handleIncomingRequest = async (requestId: number, action: 'accept' | 'reject') => {
    setFriendActionId(requestId)
    setActionMessage('')
    try {
      if (action === 'accept') {
        await acceptFriendRequest(requestId)
        setActionTone('info')
        setActionMessage('好友申请已通过。')
      } else {
        await rejectFriendRequest(requestId)
        setActionTone('info')
        setActionMessage('好友申请已拒绝。')
      }
      await loadLobbySnapshot()
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setFriendActionId(0)
    }
  }

  const handleRoomInvitation = async (invitationId: number, roomId: string, action: 'accept' | 'dismiss') => {
    setRoomInviteActionId(invitationId)
    setActionMessage('')
    try {
      if (action === 'accept') {
        await acceptRoomInvitation(invitationId)
        setActionTone('info')
        setActionMessage('邀请已接受，正在进入房间。')
        await loadLobbySnapshot(true)
        navigate(`/watch/${roomId}`)
      } else {
        await dismissRoomInvitation(invitationId)
        setActionTone('info')
        setActionMessage('邀请已忽略。')
        await loadLobbySnapshot()
      }
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setRoomInviteActionId(0)
    }
  }

  const handleRemoveFriend = async () => {
    if (!selectedFriend) return
    const targetId = selectedFriend.user_id
    const targetUsername = selectedFriend.username
    setRemovingFriendId(targetId)
    setActionMessage('')
    try {
      await removeFriend(targetId)
      setActionTone('info')
      setActionMessage(`已将 ${targetUsername} 从好友列表中移除。`)
      setChatMessages([])
      await loadLobbySnapshot()
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setRemovingFriendId(0)
    }
  }

  const handleSendChatMessage = async () => {
    if (!selectedFriend || !chatDraft.trim()) return
    setSendingMessage(true)
    setActionMessage('')
    try {
      const message = await sendDirectMessage(selectedFriend.user_id, chatDraft.trim())
      setChatMessages((items) => [...items, message])
      setChatDraft('')
      await loadLobbySnapshot()
    } catch (error) {
      setActionTone('error')
      setActionMessage(extractErrorMessage(error))
    } finally {
      setSendingMessage(false)
    }
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-accent-cyan/15 via-bg-secondary to-accent-primary/10 p-6">
        <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Tv className="h-5 w-5 text-accent-cyan" />
              <h1 className="text-2xl font-bold">同看中心</h1>
            </div>
            <p className="max-w-2xl text-sm text-text-secondary">
              先扫描本地下载目录，再从左侧明确选一个“待建房片源”。解析失败的文件会直接标红展示原因，并禁用建房、转码和观看。
            </p>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-bg-card/80 px-3 py-1 text-text-secondary">1. 刷新媒体库</span>
              <span className="rounded-full bg-bg-card/80 px-3 py-1 text-text-secondary">2. 设为待建房片源</span>
              <span className="rounded-full bg-bg-card/80 px-3 py-1 text-text-secondary">3. 创建房间</span>
            </div>
          </div>
          <button
            onClick={() => load(true)}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-bg-card px-3 py-2 text-xs text-text-secondary transition-colors hover:text-text-primary"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            刷新媒体库
          </button>
        </div>
      </div>

      {actionMessage && (
        <div
          className={cn(
            'flex items-start gap-2 rounded-xl px-4 py-3 text-sm',
            actionTone === 'error' ? 'bg-danger/8 text-danger' : 'bg-accent-cyan/10 text-accent-cyan'
          )}
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{actionMessage}</span>
        </div>
      )}

      {loadWarning && (
        <div className="flex items-start gap-2 rounded-xl bg-warning/10 px-4 py-3 text-sm text-warning">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{loadWarning}</span>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <Film className="h-4 w-4 text-accent-primary" />
            <h2 className="text-lg font-semibold">本地片源</h2>
            <span className="text-xs text-text-muted">{assets.length} 个文件</span>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-7 w-7 animate-spin text-accent-primary" />
            </div>
          ) : libraryLoadError && assets.length === 0 ? (
            <div className="space-y-3 rounded-xl border border-danger/20 bg-danger/5 p-5 text-sm text-danger">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>媒体库暂时加载失败：{trimError(libraryLoadError)}</span>
              </div>
              <button
                onClick={() => void load(false)}
                className="inline-flex rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
              >
                重试媒体库
              </button>
            </div>
          ) : assets.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-8 text-sm text-text-muted">
              当前还没有可用片源。等下载目录里有 `mp4/mkv/webm` 之类文件后，这里会自动识别并给出播放建议。
            </div>
          ) : (
            <div className="space-y-3">
              {libraryLoadError && (
                <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                  <div className="flex min-w-0 items-start gap-2">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>媒体库刷新失败，当前展示的是上次成功加载的片源快照。</span>
                  </div>
                  <button
                    onClick={() => void load(false)}
                    className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                  >
                    重试媒体库
                  </button>
                </div>
              )}
              {assets.map((asset) => {
                const selected = selectedMediaId === asset.media_id
                const preparing = preparingId === asset.media_id || asset.hls_status === 'preparing'
                const blocked = isBlocked(asset)
                return (
                  <div
                    key={asset.media_id}
                    className={cn(
                      'rounded-xl border p-4 transition-colors',
                      selected ? 'border-accent-primary bg-accent-primary/5' : 'border-border bg-bg-card'
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1 space-y-2">
                        <p className="text-sm font-medium break-all">{asset.title}</p>
                        <div className="flex flex-wrap items-center gap-2 text-[11px]">
                          <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">{asset.container || 'unknown'}</span>
                          <span
                            className={cn(
                              'rounded-full px-2 py-0.5',
                              blocked
                                ? 'bg-danger/10 text-danger'
                                : asset.recommended_mode === 'direct_play'
                                  ? 'bg-success/10 text-success'
                                  : 'bg-warning/10 text-warning'
                            )}
                          >
                            {modeLabel(asset)}
                          </span>
                          <span
                            className={cn(
                              'rounded-full px-2 py-0.5',
                              asset.probe_status === 'ready'
                                ? 'bg-success/10 text-success'
                                : asset.probe_status === 'failed'
                                  ? 'bg-danger/10 text-danger'
                                  : 'bg-bg-secondary text-text-secondary'
                            )}
                          >
                            {probeStatusLabel(asset.probe_status)}
                          </span>
                          <span
                            className={cn(
                              'rounded-full px-2 py-0.5',
                              asset.hls_status === 'ready'
                                ? 'bg-success/10 text-success'
                                : asset.hls_status === 'error'
                                  ? 'bg-danger/10 text-danger'
                                  : 'bg-accent-cyan/10 text-accent-cyan'
                            )}
                          >
                            {hlsStatusLabel(asset.hls_status)}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted">
                          <span>{formatBytes(asset.size)}</span>
                          <span>{asset.relative_path}</span>
                          <span>更新于 {formatUpdatedAt(asset.modified_at)}</span>
                        </div>
                        {blocked ? (
                          <div className="flex items-start gap-2 rounded-lg bg-danger/8 px-3 py-2 text-xs text-danger">
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span className="break-all">片源不可用于同看：{blockReason(asset)}</span>
                          </div>
                        ) : asset.last_error ? (
                          <div className="flex items-start gap-2 rounded-lg bg-danger/8 px-3 py-2 text-xs text-danger">
                            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span className="break-all">{trimError(asset.last_error)}</span>
                          </div>
                        ) : null}
                      </div>

                      <div className="flex shrink-0 flex-wrap gap-2">
                        <button
                          onClick={() => setSelectedMediaId(asset.media_id)}
                          disabled={blocked}
                          className={cn(
                            'rounded-lg px-3 py-2 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                            selected
                              ? 'bg-accent-cyan text-white'
                              : 'bg-bg-secondary text-text-secondary hover:text-text-primary'
                          )}
                        >
                          {blocked ? '片源不可用' : selected ? '当前待建房片源' : '设为待建房片源'}
                        </button>
                        {asset.recommended_mode === 'pretranscode_hls' && (
                          <button
                            onClick={() => handlePrepare(asset)}
                            disabled={preparing || blocked}
                            className="rounded-lg bg-bg-secondary px-3 py-2 text-xs text-text-secondary hover:text-text-primary disabled:opacity-60"
                          >
                            {preparing ? '准备中...' : asset.hls_status === 'ready' ? '重建 HLS' : '准备 HLS'}
                          </button>
                        )}
                        <button
                          onClick={() => handleCreateRoom(asset)}
                          disabled={creating || blocked}
                          className="rounded-lg bg-accent-primary px-3 py-2 text-xs font-medium text-white hover:bg-accent-primary/90 disabled:opacity-60"
                        >
                          {blocked ? '不可建房' : '直接建房'}
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        <section className="space-y-4">
          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-accent-secondary" />
              <h2 className="text-lg font-semibold">创建房间</h2>
            </div>

            <div className="rounded-xl bg-bg-secondary px-4 py-3 text-xs text-text-secondary">
              <p className="font-medium text-text-primary">如何开始</p>
              <p className="mt-1">从左侧点击“设为待建房片源”，再填写主持人和房间名。解析失败的文件只会展示错误，不会进入同看流程。</p>
              <p className="mt-2">
                {user
                  ? `当前已登录账号 ${user.username}，新房间会自动绑定到这个账号。`
                  : '当前未登录，仍然可以建房，但房间只会记录昵称，不会绑定到账号。'}
              </p>
            </div>

            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-text-muted">主持人</label>
                <input
                  value={hostName}
                  onChange={(e) => setHostName(e.target.value)}
                  className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                  placeholder="你的昵称"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-text-muted">房间名</label>
                <input
                  value={roomName}
                  onChange={(e) => setRoomName(e.target.value)}
                  className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                  placeholder="例如：今晚一起看 Maid-san"
                />
              </div>
              <div className="rounded-lg bg-bg-secondary px-3 py-3 text-xs text-text-secondary">
                {selectedAsset ? (
                  <>
                    <div className="flex items-center gap-2">
                      {selectedAssetBlocked ? (
                        <AlertCircle className="h-4 w-4 text-danger" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4 text-success" />
                      )}
                      <p className="font-medium text-text-primary">当前待建房片源</p>
                    </div>
                    <p className="mt-2 break-all">{selectedAsset.title}</p>
                    <p className="mt-2 text-text-muted">
                      方案：{selectedAsset.recommended_mode === 'direct_play' ? '直放' : selectedAsset.recommended_mode === 'pretranscode_hls' ? '预转 HLS' : '不可播放'}
                    </p>
                    <p className="mt-2 text-text-muted">房主身份：{hostName.trim() || '未填写'}{user ? `，账号归属 ${user.username}` : '，当前为匿名房间'}</p>
                    {selectedAssetBlocked && (
                      <p className="mt-2 text-danger">当前片源不可建房：{blockReason(selectedAsset)}</p>
                    )}
                  </>
                ) : (
                  '先从左侧点“设为待建房片源”，再创建房间。'
                )}
              </div>
              <button
                onClick={() => handleCreateRoom(selectedAsset)}
                disabled={!selectedAsset || selectedAssetBlocked || creating}
                className="w-full rounded-lg bg-accent-cyan px-3 py-2.5 text-sm font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
              >
                {creating ? '创建中...' : selectedAssetBlocked ? '当前片源不可建房' : '用当前片源建房'}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">放映大厅</h2>
                <p className="mt-1 text-xs text-text-muted">
                  当前在线 {onlineUsers.length} 人 · 活跃放映厅 {rooms.filter((item) => item.participant_count > 0).length} 个
                </p>
              </div>
              <span className="text-[11px] text-text-muted">
                {lobby?.generated_at ? `刷新于 ${formatUpdatedAt(lobby.generated_at)}` : '等待大厅数据'}
              </span>
            </div>

            {lobbyLoadError && lobby && (
              <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                <div className="flex min-w-0 items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>大厅刷新失败，当前展示的是上次成功加载的在线状态和房间列表。</span>
                </div>
                <button
                  onClick={() => void loadLobbySnapshot()}
                  className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                >
                  重试大厅
                </button>
              </div>
            )}

            {lobbyLoadError && !lobby ? (
              <div className="space-y-3 rounded-xl border border-danger/20 bg-danger/5 p-5 text-sm text-danger">
                <div className="flex items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>放映大厅暂时加载失败：{trimError(lobbyLoadError)}</span>
                </div>
                <button
                  onClick={() => void loadLobbySnapshot()}
                  className="inline-flex rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
                >
                  重试大厅
                </button>
              </div>
            ) : (
              <>
                {onlineUsers.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                    目前还没有登录用户在大厅或房间里在线。
                  </div>
                ) : (
                  <div className="space-y-2">
                    {onlineUsers.slice(0, 8).map((onlineUser) => {
                      const isSelf = Boolean(user && onlineUser.user_id === user.id)
                      return (
                        <div key={onlineUser.user_id} className="rounded-lg bg-bg-secondary px-3 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="text-sm font-medium text-text-primary">{onlineUser.username}</p>
                                {isSelf && <span className="rounded-full bg-accent-cyan/10 px-2 py-0.5 text-[10px] text-accent-cyan">你</span>}
                                {onlineUser.is_friend && !isSelf && <span className="rounded-full bg-accent-primary/10 px-2 py-0.5 text-[10px] text-accent-primary">好友</span>}
                                <span className="rounded-full bg-success/10 px-2 py-0.5 text-[10px] text-success">在线</span>
                              </div>
                              <p className="mt-1 text-xs text-text-secondary">{socialStatusText(onlineUser)}</p>
                              <p className="mt-1 text-[11px] text-text-muted">最近心跳 {formatRelativeTime(onlineUser.last_seen_at)}</p>
                            </div>
                            <div className="flex shrink-0 flex-wrap gap-2">
                              {onlineUser.current_room_id && (
                                <Link
                                  to={`/watch/${onlineUser.current_room_id}`}
                                  className="rounded-lg bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
                                >
                                  去房间
                                </Link>
                              )}
                              {user && !isSelf && !onlineUser.is_friend && (
                                <button
                                  onClick={() => void handleSendFriendRequest(onlineUser.username)}
                                  disabled={friendBusy}
                                  className="inline-flex items-center gap-1 rounded-lg bg-accent-primary px-3 py-2 text-xs font-medium text-white hover:bg-accent-primary/90 disabled:opacity-60"
                                >
                                  <UserPlus className="h-3.5 w-3.5" />
                                  加好友
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-sm font-medium text-text-primary">活跃放映厅</h3>
                    <span className="text-[11px] text-text-muted">按在线人数和最近活跃排序</span>
                  </div>
                  {rooms.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                      还没有放映厅，先建一个试试。
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {rooms.slice(0, 5).map((room) => (
                        <Link
                          key={`hall-${room.room_id}`}
                          to={`/watch/${room.room_id}`}
                          className="block rounded-lg bg-bg-secondary px-3 py-3 transition-colors hover:bg-bg-hover"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-sm font-medium text-text-primary">{room.name}</p>
                              <p className="mt-1 text-xs text-text-muted">
                                房主：{room.host_name || '未命名'} · {room.state.paused ? '暂停中' : '播放中'}
                              </p>
                              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-text-muted">
                                <span className="rounded-full bg-bg-card px-2 py-0.5">在线 {room.participant_count} 人</span>
                                {room.participant_usernames.slice(0, 3).map((name) => (
                                  <span key={`${room.room_id}-${name}`} className="rounded-full bg-bg-card px-2 py-0.5">{name}</span>
                                ))}
                              </div>
                            </div>
                            <span className="shrink-0 text-[11px] text-text-muted">{formatRelativeTime(room.updated_at)}</span>
                          </div>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-4">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-accent-cyan" />
              <h2 className="text-lg font-semibold">好友与聊天</h2>
            </div>

            {!user ? (
              <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                登录后就会出现在在线列表里，也可以加好友、收发私聊。
              </div>
            ) : (
              <>
                <div className="flex gap-2">
                  <input
                    value={friendUsername}
                    onChange={(event) => setFriendUsername(event.target.value)}
                    className="flex-1 rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                    placeholder="输入用户名发送好友申请"
                  />
                  <button
                    onClick={() => void handleSendFriendRequest()}
                    disabled={friendBusy || !friendUsername.trim()}
                    className="inline-flex items-center gap-1 rounded-lg bg-accent-primary px-3 py-2 text-sm font-medium text-white hover:bg-accent-primary/90 disabled:opacity-60"
                  >
                    <UserPlus className="h-4 w-4" />
                    添加
                  </button>
                </div>

                {(incomingRoomInvitations.length > 0 || outgoingRoomInvitations.length > 0) && (
                  <div className="space-y-3 rounded-xl bg-bg-secondary p-3">
                    {incomingRoomInvitations.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-text-primary">收到的房间邀请</p>
                        {incomingRoomInvitations.map((invitation) => (
                          <div key={invitation.invitation_id} className="rounded-lg bg-bg-card px-3 py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-text-primary">
                                  {invitation.sender_username} 邀请你进入「{invitation.room_name || invitation.room_id}」
                                </p>
                                {invitation.message && (
                                  <p className="mt-1 text-xs text-text-secondary">留言：{invitation.message}</p>
                                )}
                                <p className="mt-1 text-[11px] text-text-muted">{formatRelativeTime(invitation.updated_at)}</p>
                              </div>
                              <div className="flex shrink-0 gap-2">
                                <Link
                                  to={`/watch/${invitation.room_id}`}
                                  className="rounded-lg bg-bg-secondary px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
                                >
                                  看房间
                                </Link>
                                <button
                                  onClick={() => void handleRoomInvitation(invitation.invitation_id, invitation.room_id, 'accept')}
                                  disabled={roomInviteActionId === invitation.invitation_id}
                                  className="rounded-lg bg-accent-cyan px-3 py-2 text-xs font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
                                >
                                  进入房间
                                </button>
                                <button
                                  onClick={() => void handleRoomInvitation(invitation.invitation_id, invitation.room_id, 'dismiss')}
                                  disabled={roomInviteActionId === invitation.invitation_id}
                                  className="rounded-lg bg-bg-secondary px-3 py-2 text-xs text-text-secondary hover:text-text-primary disabled:opacity-60"
                                >
                                  忽略
                                </button>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {outgoingRoomInvitations.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-text-primary">已发出的房间邀请</p>
                        <div className="flex flex-wrap gap-2">
                          {outgoingRoomInvitations.map((invitation) => (
                            <Link
                              key={invitation.invitation_id}
                              to={`/watch/${invitation.room_id}`}
                              className="rounded-full bg-bg-card px-3 py-1 text-xs text-text-secondary hover:text-text-primary"
                            >
                              {invitation.recipient_username} · {invitation.room_name || invitation.room_id}
                            </Link>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {(incomingRequests.length > 0 || outgoingRequests.length > 0) && (
                  <div className="space-y-3 rounded-xl bg-bg-secondary p-3">
                    {incomingRequests.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-text-primary">收到的好友申请</p>
                        {incomingRequests.map((request) => (
                          <div key={request.request_id} className="flex items-center justify-between gap-3 rounded-lg bg-bg-card px-3 py-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-text-primary">{request.requester_username}</p>
                              <p className="text-[11px] text-text-muted">{formatRelativeTime(request.updated_at)}</p>
                            </div>
                            <div className="flex shrink-0 gap-2">
                              <button
                                onClick={() => void handleIncomingRequest(request.request_id, 'accept')}
                                disabled={friendActionId === request.request_id}
                                className="inline-flex items-center gap-1 rounded-lg bg-success px-3 py-2 text-xs font-medium text-white disabled:opacity-60"
                              >
                                <Check className="h-3.5 w-3.5" />
                                通过
                              </button>
                              <button
                                onClick={() => void handleIncomingRequest(request.request_id, 'reject')}
                                disabled={friendActionId === request.request_id}
                                className="inline-flex items-center gap-1 rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white disabled:opacity-60"
                              >
                                <X className="h-3.5 w-3.5" />
                                拒绝
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {outgoingRequests.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-text-primary">已发出的申请</p>
                        <div className="flex flex-wrap gap-2">
                          {outgoingRequests.map((request) => (
                            <span key={request.request_id} className="rounded-full bg-bg-card px-3 py-1 text-xs text-text-secondary">
                              {request.target_username}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div className="grid gap-3 xl:grid-cols-[220px_1fr]">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-text-primary">好友列表</p>
                      <span className="text-[11px] text-text-muted">{friends.length} 人</span>
                    </div>
                    {friends.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                        还没有好友。你可以先从在线列表里加人。
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {friends.map((friend) => (
                          <button
                            key={friend.user_id}
                            onClick={() => setSelectedFriendId(friend.user_id)}
                            className={cn(
                              'w-full rounded-lg border px-3 py-3 text-left transition-colors',
                              selectedFriendId === friend.user_id
                                ? 'border-accent-primary bg-accent-primary/6'
                                : 'border-border bg-bg-secondary hover:bg-bg-hover'
                            )}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-medium text-text-primary">{friend.username}</p>
                                <p className="mt-1 truncate text-[11px] text-text-muted">
                                  {friend.is_online ? socialStatusText(friend) : `最近在线 ${formatRelativeTime(friend.last_seen_at)}`}
                                </p>
                              </div>
                              <div className="shrink-0">
                                {friend.unread_count > 0 ? (
                                  <span className="rounded-full bg-accent-primary px-2 py-0.5 text-[10px] font-medium text-white">
                                    {friend.unread_count}
                                  </span>
                                ) : friend.is_online ? (
                                  <span className="rounded-full bg-success/10 px-2 py-0.5 text-[10px] text-success">在线</span>
                                ) : null}
                              </div>
                            </div>
                            {friend.last_message_preview && (
                              <p className="mt-2 truncate text-[11px] text-text-secondary">{friend.last_message_preview}</p>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="space-y-3">
                    {selectedFriend ? (
                      <>
                        <div className="rounded-lg bg-bg-secondary px-3 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-sm font-medium text-text-primary">{selectedFriend.username}</p>
                              <p className="mt-1 text-[11px] text-text-muted">
                                {selectedFriend.is_online ? socialStatusText(selectedFriend) : `最近在线 ${formatRelativeTime(selectedFriend.last_seen_at)}`}
                              </p>
                            </div>
                            <div className="flex shrink-0 flex-wrap gap-2">
                              {selectedFriend.current_room_id && (
                                <Link
                                  to={`/watch/${selectedFriend.current_room_id}`}
                                  className="rounded-lg bg-bg-card px-3 py-2 text-xs text-text-secondary hover:text-text-primary"
                                >
                                  去 TA 的房间
                                </Link>
                              )}
                              <button
                                onClick={() => void handleRemoveFriend()}
                                disabled={removingFriendId === selectedFriend.user_id}
                                className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger hover:bg-danger/15 disabled:opacity-60"
                              >
                                {removingFriendId === selectedFriend.user_id ? '移除中...' : '删除好友'}
                              </button>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-xl border border-border bg-bg-secondary p-3">
                          {chatLoading ? (
                            <div className="flex items-center justify-center py-12">
                              <Loader2 className="h-5 w-5 animate-spin text-accent-primary" />
                            </div>
                          ) : chatMessages.length === 0 ? (
                            <div className="py-12 text-center text-sm text-text-muted">
                              还没有聊天记录，先打个招呼吧。
                            </div>
                          ) : (
                            <div ref={chatListRef} className="max-h-72 space-y-2 overflow-y-auto pr-1">
                              {chatMessages.map((message) => (
                                <div
                                  key={message.message_id}
                                  className={cn('flex', message.is_mine ? 'justify-end' : 'justify-start')}
                                >
                                  <div
                                    className={cn(
                                      'max-w-[85%] rounded-2xl px-3 py-2 text-sm',
                                      message.is_mine
                                        ? 'bg-accent-primary text-white'
                                        : 'bg-bg-card text-text-primary'
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
                          )}
                        </div>

                        <div className="flex gap-2">
                          <input
                            value={chatDraft}
                            onChange={(event) => setChatDraft(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' && !event.shiftKey) {
                                event.preventDefault()
                                void handleSendChatMessage()
                              }
                            }}
                            className="flex-1 rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                            placeholder={`给 ${selectedFriend.username} 发消息`}
                          />
                          <button
                            onClick={() => void handleSendChatMessage()}
                            disabled={sendingMessage || !chatDraft.trim()}
                            className="rounded-lg bg-accent-cyan px-4 py-2 text-sm font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
                          >
                            {sendingMessage ? '发送中...' : '发送'}
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="rounded-lg border border-dashed border-border px-4 py-10 text-sm text-text-muted">
                        选择一个好友后，就可以直接在这里聊天。
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="rounded-xl border border-border bg-bg-card p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">最近观看</h2>
                <p className="mt-1 text-xs text-text-muted">
                  {user ? '会自动记录当前账号在同看房间里的最近进度。' : '登录后会自动记录你的观看进度。'}
                </p>
              </div>
              {user && <span className="text-xs text-text-muted">{history.length} 条</span>}
            </div>

            {!user ? (
              <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                当前未登录，观看记录不会保存到账号。
              </div>
            ) : historyLoadError && history.length === 0 ? (
              <div className="space-y-3 rounded-lg border border-danger/20 bg-danger/5 px-4 py-5 text-sm text-danger">
                <div className="flex items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>观看记录暂时加载失败：{trimError(historyLoadError)}</span>
                </div>
                <button
                  onClick={() => void loadLobbySnapshot()}
                  className="inline-flex w-fit rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
                >
                  重试记录
                </button>
              </div>
            ) : history.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border px-4 py-5 text-sm text-text-muted">
                还没有观看记录。进入房间播放一会儿，这里就会出现最近进度。
              </div>
            ) : (
              <div className="space-y-2">
                {historyLoadError && (
                  <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-warning/20 bg-warning/8 px-4 py-3 text-sm text-warning">
                    <div className="flex min-w-0 items-start gap-2">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>观看记录刷新失败，当前展示的是上次成功加载的进度快照。</span>
                    </div>
                    <button
                      onClick={() => void loadLobbySnapshot()}
                      className="shrink-0 rounded-lg bg-warning px-3 py-2 text-xs font-medium text-white hover:bg-warning/90"
                    >
                      重试记录
                    </button>
                  </div>
                )}
                {history.map((entry) => (
                  <Link
                    key={entry.entry_id}
                    to={entry.room_id ? `/watch/${entry.room_id}` : '/watch'}
                    className="block rounded-lg bg-bg-secondary px-3 py-3 transition-colors hover:bg-bg-hover"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-text-primary">{entry.media_title || entry.media_id || '未知片源'}</p>
                        <p className="mt-1 text-xs text-text-muted">
                          房间：{entry.room_name || entry.room_id || '未命名'}
                        </p>
                        <p className="mt-1 text-xs text-text-muted">
                          进度：{formatPosition(entry.position_seconds)}
                          {entry.duration_seconds > 0 ? ` / ${formatPosition(entry.duration_seconds)}` : ''}
                          {entry.paused ? ' · 已暂停' : ' · 播放中'}
                        </p>
                      </div>
                      <div className="shrink-0 text-right text-[11px] text-text-muted">
                        <p>{entry.playback_mode === 'hls' ? 'HLS' : '直放'}</p>
                        <p className="mt-1">更新于 {formatUpdatedAt(entry.updated_at)}</p>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Clock3 className="h-4 w-4 text-accent-gold" />
              <h2 className="text-lg font-semibold">{showMineOnly ? '我的房间' : '现有房间'}</h2>
              <span className="text-xs text-text-muted">{visibleRooms.length} 个</span>
              {user ? (
                <div className="ml-auto flex items-center gap-2">
                  <button
                    onClick={() => setShowMineOnly(false)}
                    className={cn(
                      'rounded-full px-3 py-1 text-xs transition-colors',
                      !showMineOnly
                        ? 'bg-accent-primary/12 text-accent-primary'
                        : 'bg-bg-secondary text-text-secondary hover:text-text-primary'
                    )}
                  >
                    全部房间
                  </button>
                  <button
                    onClick={() => setShowMineOnly(true)}
                    className={cn(
                      'rounded-full px-3 py-1 text-xs transition-colors',
                      showMineOnly
                        ? 'bg-accent-primary/12 text-accent-primary'
                        : 'bg-bg-secondary text-text-secondary hover:text-text-primary'
                    )}
                  >
                    我的房间
                  </button>
                </div>
              ) : (
                <span className="ml-auto text-xs text-text-muted">登录后可筛选你的房间</span>
              )}
            </div>

            {roomsLoading && !loading ? (
              <div className="flex items-center justify-center rounded-xl border border-dashed border-border p-6">
                <Loader2 className="h-5 w-5 animate-spin text-accent-primary" />
              </div>
            ) : lobbyLoadError && !lobby ? (
              <div className="space-y-3 rounded-xl border border-danger/20 bg-danger/5 p-6 text-sm text-danger">
                <div className="flex items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>房间列表暂时不可用，因为大厅数据加载失败：{trimError(lobbyLoadError)}</span>
                </div>
                <button
                  onClick={() => void loadLobbySnapshot()}
                  className="inline-flex w-fit rounded-lg bg-danger px-3 py-2 text-xs font-medium text-white hover:bg-danger/90"
                >
                  重试大厅
                </button>
              </div>
            ) : visibleRooms.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border p-6 text-sm text-text-muted">
                {showMineOnly ? '你还没有创建过绑定到当前账号的房间。' : '还没有同看房间，建一个试试。'}
              </div>
            ) : (
              sortedRooms.map((room) => (
                <Link
                  key={room.room_id}
                  to={`/watch/${room.room_id}`}
                  className="block rounded-xl border border-border bg-bg-card p-4 transition-colors hover:border-accent-primary/40"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="text-sm font-medium">{room.name}</p>
                      <p className="text-xs text-text-muted">房主：{room.host_name || '未命名'}</p>
                      <p className="text-xs text-text-muted">
                        账号归属：{room.owner_username || '匿名房间'}
                        {user && room.owner_user_id === user.id ? ' · 这是你的房间' : ''}
                      </p>
                      <div className="flex flex-wrap gap-2 text-[11px]">
                        <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">
                          {room.state.playback_mode === 'hls' ? 'HLS 房间' : '直放房间'}
                        </span>
                        <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">
                          {room.state.paused ? '已暂停' : '播放中'}
                        </span>
                        <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">
                          在线 {room.participant_count} 人
                        </span>
                        {room.owner_username && (
                          <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-text-secondary">
                            账号房主 {room.owner_username}
                          </span>
                        )}
                        {user && room.owner_user_id === user.id && (
                          <span className="rounded-full bg-accent-primary/10 px-2 py-0.5 text-accent-primary">
                            我的房间
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-right text-xs text-text-muted">
                      <p>{room.room_id}</p>
                      <p className="mt-1">更新于 {formatUpdatedAt(room.updated_at)}</p>
                    </div>
                  </div>
                  {room.participant_usernames.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-text-muted">
                      {room.participant_usernames.map((name) => (
                        <span key={`${room.room_id}-viewer-${name}`} className="rounded-full bg-bg-secondary px-2 py-0.5">
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                </Link>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
