import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Clock3, Film, Loader2, MessageSquare, RefreshCw, Tv, UserPlus, Users, X, Send } from 'lucide-react'
import {
  acceptRoomInvitation,
  createWatchRoom,
  dismissRoomInvitation,
  getDirectMessages,
  getWatchLobby,
  heartbeatPresence,
  listMediaLibrary,
  listWatchHistory,
  prepareMediaHls,
  removeFriend,
  scanMediaLibrary,
  sendDirectMessage,
  sendFriendRequest,
} from '@/api'
import { useAuth } from '@/contexts/useAuth'
import type { DirectMessage, MediaAsset, WatchHistoryItem, WatchLobbyOverview, WatchLobbyRoom } from '@/types'
import { cn, formatBytes } from '@/lib/utils'
import {
  extractErrorMessage,
  formatDateTime as formatUpdatedAt,
  getAssetBlockReason as blockReason,
  isAssetBlocked,
  shortError,
  socialStatusText,
} from '@/lib/watchFormatters'

function trimError(message: string): string {
  return shortError(message, 200)
}

type LoadFailure = {
  key: 'library' | 'lobby' | 'history'
  label: string
  message: string
}

function isBlocked(asset: MediaAsset): boolean {
  return isAssetBlocked(asset)
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
    case 'queued':
      return 'HLS 排队中'
    case 'preparing':
      return 'HLS 准备中'
    case 'error':
      return 'HLS 失败'
    default:
      return '尚未准备'
  }
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
  const [rooms, setRooms] = useState<WatchLobbyRoom[]>([])
  const [lobby, setLobby] = useState<WatchLobbyOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [preparingId, setPreparingId] = useState('')
  const [hostName, setHostName] = useState('elegy')
  const [roomName, setRoomName] = useState('')
  const [selectedMediaId, setSelectedMediaId] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [actionTone, setActionTone] = useState<'info' | 'error'>('info')
  const [loadWarning, setLoadWarning] = useState('')
  const [libraryLoadError, setLibraryLoadError] = useState('')
  const [lobbyLoadError, setLobbyLoadError] = useState('')
  const [friendUsername, setFriendUsername] = useState('')
  const [friendBusy, setFriendBusy] = useState(false)
  const [roomInviteActionId, setRoomInviteActionId] = useState(0)
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

  const loadLobbySnapshot = useCallback(async () => {
    try {
      const { overview, failures } = await fetchLobbyHistoryBundle(Boolean(user))
      const lobbyFailure = failures.find((failure) => failure.key === 'lobby')

      if (overview) {
        applyLobby(overview)
        setLobbyLoadError('')
      } else if (lobbyFailure) {
        setLobbyLoadError(lobbyFailure.message)
      }

      setLoadWarning(buildLoadWarning(failures))
    } catch (error) {
      const message = extractErrorMessage(error)
      setLobbyLoadError(message)
      setLoadWarning(`放映大厅：${trimError(message)}。其余内容已保留，可稍后重试。`)
    } finally {
      /* noop */
    }
  }, [applyLobby, user])

  const load = useCallback(async (forceScan = false) => {
    if (forceScan) setRefreshing(true)
    try {
      const { library, overview, failures } = await fetchWatchPartyBundle(forceScan, Boolean(user))
      const libraryFailure = failures.find((failure) => failure.key === 'library')
      const lobbyFailure = failures.find((failure) => failure.key === 'lobby')

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

      setLoadWarning(buildLoadWarning(failures))
    } catch (error) {
      const message = extractErrorMessage(error)
      setLibraryLoadError(message)
      setLobbyLoadError(message)
      setLoadWarning(`媒体库：${trimError(message)}。当前页面部分内容可能不是最新状态。`)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [applyLobby, user])

  useEffect(() => {
    void load(false)
  }, [load])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadLobbySnapshot()
    }, 15000)
    return () => window.clearInterval(timer)
  }, [loadLobbySnapshot])

  useEffect(() => {
    if (user?.username) {
      setHostName(user.username)
    }
  }, [user?.username])

  const selectedAsset = assets.find((item) => item.media_id === selectedMediaId) || null
  const selectedAssetBlocked = Boolean(selectedAsset && isBlocked(selectedAsset))
  const onlineUsers = lobby?.online_users || []
  const friends = lobby?.friends || []
  const incomingRoomInvitations = lobby?.incoming_room_invitations || []
  const selectedFriend = friends.find((item) => item.user_id === selectedFriendId) || null

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

  const handleRoomInvitation = async (invitationId: number, roomId: string, action: 'accept' | 'dismiss') => {
    setRoomInviteActionId(invitationId)
    setActionMessage('')
    try {
      if (action === 'accept') {
        await acceptRoomInvitation(invitationId)
        setActionTone('info')
        setActionMessage('邀请已接受，正在进入房间。')
        await loadLobbySnapshot()
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
      /* noop */
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

  const [activeTab, setActiveTab] = useState<'lobby' | 'create' | 'social'>('lobby')

  return (
    <div className="max-w-[1600px] mx-auto space-y-8 animate-in fade-in duration-700 pb-12">
      {/* Hero Banner */}
      <div className="relative overflow-hidden rounded-[2.5rem] border border-white/10 bg-black/40 p-8 md:p-12 shadow-2xl backdrop-blur-2xl group">
        <div className="absolute -inset-full bg-gradient-to-br from-accent-cyan/20 via-accent-primary/10 to-transparent blur-[100px] opacity-50 group-hover:opacity-70 transition-all duration-1000" />
        <div className="absolute -top-40 -right-40 h-[30rem] w-[30rem] rounded-full bg-accent-cyan/20 blur-[120px] mix-blend-screen" />
        <div className="absolute -bottom-40 -left-40 h-[30rem] w-[30rem] rounded-full bg-accent-primary/20 blur-[120px] mix-blend-screen" />
        
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-8">
          <div className="space-y-6">
            <div className="inline-flex items-center gap-3 rounded-2xl bg-white/5 px-4 py-2 border border-white/10 backdrop-blur-md shadow-inner">
              <Tv className="h-5 w-5 text-accent-cyan animate-pulse" />
              <span className="text-sm font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-accent-cyan to-white">WATCH PARTY</span>
            </div>
            <h1 className="text-4xl md:text-5xl font-black text-white tracking-tight drop-shadow-xl">
              同看大厅
            </h1>
            <p className="max-w-2xl text-base md:text-lg text-white/70 font-medium leading-relaxed">
              在这里发现正在一起看番的伙伴。你可以加入别人的放映室，或者从本地媒体库发起自己的专属同看房间。
            </p>
          </div>
          <button
            onClick={() => load(true)}
            className="group relative flex shrink-0 items-center gap-3 rounded-2xl border border-white/20 bg-white/10 px-8 py-4 text-sm font-bold text-white shadow-xl backdrop-blur-md transition-all hover:bg-white/20 hover:scale-105 hover:shadow-2xl hover:shadow-white/10 overflow-hidden"
          >
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000" />
            {refreshing ? <Loader2 className="h-5 w-5 animate-spin" /> : <RefreshCw className="h-5 w-5 transition-transform duration-500 group-hover:rotate-180" />}
            重新扫描
          </button>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="flex flex-wrap items-center justify-center gap-4">
        <div className="flex rounded-3xl bg-black/40 border border-white/10 p-1.5 backdrop-blur-xl shadow-xl">
          <button
            onClick={() => setActiveTab('lobby')}
            className={cn(
              "flex items-center gap-3 rounded-full px-8 py-3.5 text-sm font-bold transition-all duration-300",
              activeTab === 'lobby' 
                ? "bg-gradient-to-r from-accent-gold/80 to-accent-gold text-black shadow-lg shadow-accent-gold/20 scale-105" 
                : "text-white/60 hover:text-white hover:bg-white/5"
            )}
          >
            <Tv className={cn("h-5 w-5", activeTab === 'lobby' && "animate-pulse")} />
            大厅动态
          </button>
          <button
            onClick={() => setActiveTab('create')}
            className={cn(
              "flex items-center gap-3 rounded-full px-8 py-3.5 text-sm font-bold transition-all duration-300",
              activeTab === 'create' 
                ? "bg-gradient-to-r from-accent-cyan to-accent-primary text-white shadow-lg shadow-accent-cyan/20 scale-105" 
                : "text-white/60 hover:text-white hover:bg-white/5"
            )}
          >
            <Film className={cn("h-5 w-5", activeTab === 'create' && "animate-pulse")} />
            发起同看
          </button>
          <button
            onClick={() => setActiveTab('social')}
            className={cn(
              "flex items-center gap-3 rounded-full px-8 py-3.5 text-sm font-bold transition-all duration-300",
              activeTab === 'social' 
                ? "bg-gradient-to-r from-accent-primary to-accent-secondary text-white shadow-lg shadow-accent-primary/20 scale-105" 
                : "text-white/60 hover:text-white hover:bg-white/5"
            )}
          >
            <MessageSquare className={cn("h-5 w-5", activeTab === 'social' && "animate-pulse")} />
            好友与聊天
          </button>
        </div>
      </div>

      {/* Messages */}
      {(actionMessage || loadWarning) && (
        <div className="space-y-4 max-w-4xl mx-auto">
          {actionMessage && (
            <div className={cn(
              'flex items-center gap-4 rounded-2xl border px-6 py-4 backdrop-blur-xl animate-in slide-in-from-top-4',
              actionTone === 'error' ? 'border-danger/40 bg-danger/10 text-danger shadow-[0_0_30px_rgba(239,68,68,0.15)]' : 'border-accent-cyan/40 bg-accent-cyan/10 text-accent-cyan shadow-[0_0_30px_rgba(0,242,254,0.15)]'
            )}>
              {actionTone === 'error' ? <X className="h-6 w-6" /> : <CheckCircle2 className="h-6 w-6" />}
              <span className="font-bold text-base">{actionMessage}</span>
            </div>
          )}
          {loadWarning && (
            <div className="flex items-center gap-4 rounded-2xl border border-warning/40 bg-warning/10 px-6 py-4 backdrop-blur-xl text-warning animate-in slide-in-from-top-4 shadow-[0_0_30px_rgba(245,158,11,0.15)]">
              <AlertCircle className="h-6 w-6" />
              <span className="font-bold text-base">{loadWarning}</span>
            </div>
          )}
        </div>
      )}

      {/* Tab Content: Lobby */}
      {activeTab === 'lobby' && (
        <div className="animate-in fade-in slide-in-from-bottom-8 duration-500 max-w-6xl mx-auto space-y-8">
          <div className="rounded-[2rem] border border-white/10 bg-black/40 p-8 md:p-10 shadow-2xl backdrop-blur-2xl">
            <div className="flex items-center justify-between mb-10">
              <div className="flex items-center gap-4">
                <div className="rounded-xl bg-gradient-to-br from-accent-gold/30 to-accent-gold/10 p-3 border border-accent-gold/30 shadow-lg">
                  <Tv className="h-7 w-7 text-accent-gold drop-shadow-md" />
                </div>
                <h2 className="text-3xl font-black text-white">大厅动态</h2>
              </div>
              <div className="flex flex-col items-end">
                <span className="text-xs font-bold text-white/40 mb-1">数据快照时间</span>
                <span className="rounded-full bg-white/5 border border-white/10 px-4 py-1.5 text-xs font-bold text-white/70">
                  {lobby?.generated_at ? formatUpdatedAt(lobby.generated_at) : '等待数据'}
                </span>
              </div>
            </div>

            {incomingRoomInvitations.length > 0 && (
              <div className="mb-8 rounded-[1.5rem] border border-accent-gold/25 bg-white/[0.02] p-6 shadow-inner backdrop-blur-md">
                <div className="flex items-center justify-between mb-5">
                  <h3 className="flex items-center gap-3 text-lg font-black text-white/90 tracking-wide">
                    收到的房间邀请
                    <span className="rounded-full bg-accent-gold/20 text-accent-gold px-3 py-1 text-xs">{incomingRoomInvitations.length}</span>
                  </h3>
                </div>
                <div className="space-y-4">
                  {incomingRoomInvitations.map((inv) => (
                    <div key={inv.invitation_id} className="flex flex-col md:flex-row md:items-center justify-between gap-4 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
                      <div className="min-w-0 space-y-1.5">
                        <p className="font-bold text-white">{inv.sender_username} 邀请你进入「{inv.room_name}」</p>
                        {inv.message && <p className="text-sm font-medium text-white/50">留言：{inv.message}</p>}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 shrink-0">
                        <Link to={`/watch/${inv.room_id}`} className="rounded-xl bg-white/10 px-4 py-2 text-xs font-bold text-white hover:bg-white/20 transition-colors">看房间</Link>
                        <button onClick={() => void handleRoomInvitation(inv.invitation_id, inv.room_id, 'accept')} disabled={roomInviteActionId === inv.invitation_id} className="rounded-xl bg-accent-primary px-4 py-2 text-xs font-bold text-white hover:bg-accent-primary/80 disabled:opacity-50 transition-colors">接受</button>
                        <button onClick={() => void handleRoomInvitation(inv.invitation_id, inv.room_id, 'dismiss')} disabled={roomInviteActionId === inv.invitation_id} className="rounded-xl bg-white/5 border border-white/10 px-4 py-2 text-xs font-bold text-white/80 hover:bg-white/10 disabled:opacity-50 transition-colors">忽略</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {lobbyLoadError && !lobby ? (
              <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-danger/30 bg-danger/10 p-8 text-center backdrop-blur-md">
                <p className="text-base font-bold text-danger">放映大厅暂时加载失败：{trimError(lobbyLoadError)}</p>
                <button onClick={() => void loadLobbySnapshot()} className="rounded-xl bg-danger px-6 py-2.5 text-sm font-bold text-white shadow-lg shadow-danger/20 transition-all hover:bg-danger/90 hover:scale-105">
                  重试大厅
                </button>
              </div>
            ) : (
              <div className="grid lg:grid-cols-2 gap-12">
                {/* Active Rooms */}
                <div className="space-y-6">
                  <h3 className="flex items-center gap-3 text-lg font-black text-white/90 tracking-wide border-b border-white/10 pb-4">
                    活跃放映室
                    <span className="rounded-full bg-accent-gold/20 text-accent-gold px-3 py-1 text-xs">{rooms.length}</span>
                  </h3>
                  {rooms.length === 0 ? (
                    <div className="rounded-[1.5rem] border border-dashed border-white/10 p-12 text-center flex flex-col items-center justify-center gap-4 bg-white/[0.01]">
                      <Film className="h-12 w-12 text-white/10" />
                      <span className="text-base font-bold text-white/30">当前没有放映室正在播放</span>
                      <button onClick={() => setActiveTab('create')} className="mt-2 text-accent-gold hover:text-accent-gold/80 font-bold text-sm underline underline-offset-4">去创建一个吧</button>
                    </div>
                  ) : (
                    <div className="space-y-4 max-h-[600px] overflow-y-auto custom-scrollbar pr-2">
                      {rooms.map(room => (
                         <Link key={room.room_id} to={`/watch/${room.room_id}`} className="block group rounded-2xl border border-white/5 bg-white/[0.03] p-5 transition-all hover:bg-white/[0.06] hover:border-accent-gold/30 hover:shadow-[0_0_20px_rgba(245,158,11,0.15)] hover:-translate-y-1">
                            <div className="flex justify-between items-start gap-4">
                               <div className="min-w-0 space-y-3">
                                 <p className="font-bold text-lg text-white truncate group-hover:text-accent-gold transition-colors">{room.name}</p>
                                 <div className="flex items-center gap-2">
                                   <div className="h-6 w-6 rounded-full bg-white/10 flex items-center justify-center text-xs font-black text-white">{room.host_name.charAt(0).toUpperCase()}</div>
                                   <p className="text-sm font-medium text-white/60">房主: <span className="text-white/80 font-bold">{room.host_name}</span></p>
                                 </div>
                               </div>
                               <div className="flex flex-col items-end gap-3 shrink-0">
                                  <span className={cn('rounded-lg px-3 py-1.5 text-xs font-black tracking-wide shadow-sm', room.state.paused ? 'bg-warning/20 text-warning border border-warning/30' : 'bg-success/20 text-success border border-success/30')}>
                                    {room.state.paused ? '⏸ 暂停' : '▶ 播放中'}
                                  </span>
                                  <span className="flex items-center gap-1.5 rounded-lg bg-white/5 border border-white/10 px-3 py-1.5 text-xs font-bold text-white/70">
                                    <Users className="h-3.5 w-3.5" />
                                    {room.participant_count}
                                  </span>
                               </div>
                            </div>
                         </Link>
                      ))}
                    </div>
                  )}
                </div>

                {/* Online Users */}
                <div className="space-y-6">
                  <h3 className="flex items-center gap-3 text-lg font-black text-white/90 tracking-wide border-b border-white/10 pb-4">
                    在线用户
                    <span className="rounded-full bg-accent-cyan/20 text-accent-cyan px-3 py-1 text-xs">{onlineUsers.length}</span>
                  </h3>
                  {onlineUsers.length === 0 ? (
                    <div className="rounded-[1.5rem] border border-dashed border-white/10 p-12 text-center text-base font-bold text-white/30 bg-white/[0.01]">
                      静悄悄的
                    </div>
                  ) : (
                     <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-h-[600px] overflow-y-auto custom-scrollbar pr-2">
                       {onlineUsers.map((onlineUser) => {
                          const isSelf = Boolean(user && onlineUser.user_id === user.id)
                          return (
                            <div key={onlineUser.user_id} className="group flex flex-col justify-between rounded-2xl border border-white/5 bg-white/[0.03] p-5 shadow-sm hover:bg-white/[0.06] hover:border-white/10 transition-all h-[140px]">
                               <div>
                                 <div className="flex items-center gap-3 min-w-0 mb-3">
                                   <div className="h-10 w-10 shrink-0 flex items-center justify-center rounded-full bg-gradient-to-br from-white/10 to-white/5 border border-white/10 shadow-inner font-black text-lg text-white">
                                     {onlineUser.username.charAt(0).toUpperCase()}
                                   </div>
                                   <div className="min-w-0 flex flex-col">
                                     <div className="flex items-center gap-2">
                                       <span className="font-bold text-base text-white truncate">{onlineUser.username}</span>
                                     </div>
                                     <p className="text-xs font-medium text-white/50 truncate mt-1">{socialStatusText(onlineUser)}</p>
                                   </div>
                                 </div>
                               </div>
                               <div className="flex gap-2 shrink-0 justify-end">
                                  {isSelf && <span className="rounded-lg bg-accent-cyan/20 px-3 py-1.5 text-xs font-bold text-accent-cyan">这是你</span>}
                                  {!isSelf && onlineUser.is_friend && <span className="rounded-lg bg-accent-primary/20 px-3 py-1.5 text-xs font-bold text-accent-primary">我的好友</span>}
                                  {onlineUser.current_room_id && (
                                     <Link to={`/watch/${onlineUser.current_room_id}`} className="rounded-xl bg-white/10 px-4 py-2 text-xs font-bold text-white hover:bg-white/20 transition-colors shadow-sm">去围观</Link>
                                  )}
                                  {user && !isSelf && !onlineUser.is_friend && (
                                     <button onClick={() => void handleSendFriendRequest(onlineUser.username)} disabled={friendBusy} className="rounded-xl bg-accent-primary px-4 py-2 text-xs font-bold text-white hover:bg-accent-primary/80 transition-colors shadow-lg shadow-accent-primary/20">加好友</button>
                                  )}
                               </div>
                            </div>
                          )
                       })}
                     </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab Content: Create Room */}
      {activeTab === 'create' && (
        <div className="animate-in fade-in slide-in-from-bottom-8 duration-500 grid gap-8 xl:grid-cols-[1fr_450px]">
          {/* Left Column - Library */}
          <section className="space-y-6">
            <div className="flex items-center justify-between bg-black/40 border border-white/10 p-6 rounded-[2rem] backdrop-blur-xl">
              <div className="flex items-center gap-4">
                <div className="rounded-2xl bg-gradient-to-br from-accent-primary/20 to-accent-secondary/20 p-3 border border-accent-primary/30 shadow-lg shadow-accent-primary/20">
                  <Film className="h-6 w-6 text-accent-primary" />
                </div>
                <h2 className="text-2xl font-black text-white tracking-wide">本地片源库</h2>
                <span className="rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-bold text-white/80 backdrop-blur-md shadow-inner">{assets.length} 个文件</span>
              </div>
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-32 rounded-[2rem] border border-white/5 bg-white/[0.02] backdrop-blur-md shadow-inner">
                <div className="relative flex flex-col items-center gap-6">
                  <Loader2 className="h-14 w-14 animate-spin text-accent-primary" />
                  <div className="absolute top-0 animate-pulse rounded-full bg-accent-primary/50 blur-2xl h-14 w-14" />
                  <p className="text-white/50 font-bold tracking-widest">扫描中...</p>
                </div>
              </div>
            ) : libraryLoadError && assets.length === 0 ? (
              <div className="space-y-5 rounded-[2rem] border border-danger/30 bg-danger/10 p-8 shadow-inner backdrop-blur-md">
                <div className="flex items-start gap-4">
                  <AlertCircle className="h-8 w-8 text-danger shrink-0 drop-shadow-md" />
                  <div className="space-y-2">
                    <h3 className="text-xl font-black text-danger">媒体库暂时加载失败：{trimError(libraryLoadError)}</h3>
                  </div>
                </div>
                <button
                  onClick={() => void load(false)}
                  className="rounded-xl bg-danger px-8 py-3 text-sm font-bold text-white shadow-xl shadow-danger/20 transition-all hover:bg-danger/90 hover:scale-105"
                >
                  重试媒体库
                </button>
              </div>
            ) : assets.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-[2rem] border border-white/5 bg-white/[0.02] p-24 text-center shadow-inner backdrop-blur-md">
                <div className="rounded-full bg-white/5 p-6 mb-6">
                  <Film className="h-16 w-16 text-white/20" />
                </div>
                <p className="text-xl font-bold text-white/70">当前还没有可用片源</p>
                <p className="mt-3 text-sm text-white/40 max-w-sm">下载目录里有视频文件后，这里会自动识别并给出播放建议。</p>
              </div>
            ) : (
              <div className="space-y-5">
                {libraryLoadError && (
                  <div className="flex items-center justify-between gap-4 rounded-2xl border border-warning/30 bg-warning/10 p-5 backdrop-blur-md shadow-inner">
                    <div className="flex items-center gap-3">
                      <AlertCircle className="h-5 w-5 text-warning shrink-0" />
                      <span className="font-bold text-warning text-sm">媒体库刷新失败，当前展示的是历史快照。</span>
                    </div>
                    <button onClick={() => void load(false)} className="rounded-xl bg-warning px-5 py-2 text-xs font-bold text-black shadow-lg transition-all hover:bg-warning/90 hover:scale-105">
                      重试
                    </button>
                  </div>
                )}
                
                <div className="grid grid-cols-1 gap-4">
                  {assets.map((asset) => {
                    const selected = selectedMediaId === asset.media_id
                    const preparing = preparingId === asset.media_id || asset.hls_status === 'preparing' || asset.hls_status === 'queued'
                    const blocked = isBlocked(asset)
                    return (
                      <div
                        key={asset.media_id}
                        className={cn(
                          'group relative overflow-hidden rounded-[1.5rem] border p-6 shadow-sm transition-all duration-300 backdrop-blur-xl',
                          selected ? 'border-accent-cyan/40 bg-accent-cyan/10 shadow-[0_0_30px_rgba(0,242,254,0.1)] scale-[1.01]' : 'border-white/5 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06] hover:shadow-xl hover:-translate-y-0.5'
                        )}
                      >
                        {selected && <div className="absolute inset-0 bg-gradient-to-r from-accent-cyan/10 via-transparent to-transparent pointer-events-none" />}
                        {selected && <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-accent-cyan shadow-[0_0_15px_#00f2fe]" />}
                        
                        <div className="relative z-10 flex flex-col md:flex-row gap-6 justify-between items-start md:items-center">
                          <div className="flex-1 space-y-4 min-w-0">
                            <p className="text-lg font-bold text-white leading-snug break-all drop-shadow-md">
                              {asset.title}
                            </p>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-lg border border-white/10 bg-white/10 px-2.5 py-1 text-[11px] font-bold text-white shadow-inner">{asset.container || 'unknown'}</span>
                              <span
                                className={cn(
                                  'rounded-lg border px-2.5 py-1 text-[11px] font-bold shadow-sm backdrop-blur-md',
                                  blocked
                                    ? 'border-danger/30 bg-danger/20 text-danger'
                                    : asset.recommended_mode === 'direct_play'
                                      ? 'border-success/30 bg-success/20 text-success'
                                      : 'border-warning/30 bg-warning/20 text-warning'
                                )}
                              >
                                {modeLabel(asset)}
                              </span>
                              <span
                                className={cn(
                                  'rounded-lg border px-2.5 py-1 text-[11px] font-bold shadow-sm backdrop-blur-md',
                                  asset.probe_status === 'ready'
                                    ? 'border-success/30 bg-success/20 text-success'
                                    : asset.probe_status === 'failed'
                                      ? 'border-danger/30 bg-danger/20 text-danger'
                                      : 'border-white/10 bg-white/5 text-white/70'
                                )}
                              >
                                {probeStatusLabel(asset.probe_status)}
                              </span>
                              <span
                                className={cn(
                                  'rounded-lg border px-2.5 py-1 text-[11px] font-bold shadow-sm backdrop-blur-md',
                                  asset.hls_status === 'ready'
                                    ? 'border-success/30 bg-success/20 text-success'
                                    : asset.hls_status === 'error'
                                      ? 'border-danger/30 bg-danger/20 text-danger'
                                      : 'border-accent-cyan/30 bg-accent-cyan/20 text-accent-cyan'
                                )}
                              >
                                {hlsStatusLabel(asset.hls_status)}
                              </span>
                            </div>
                            
                            <div className="flex flex-wrap items-center gap-3 text-[12px] font-medium text-white/50">
                              <span className="flex items-center gap-1 rounded-md bg-black/30 px-2 py-1"><Clock3 className="h-3 w-3" />{formatUpdatedAt(asset.modified_at)}</span>
                              <span className="rounded-md bg-black/30 px-2 py-1">{formatBytes(asset.size)}</span>
                              <span className="rounded-md bg-black/30 px-2 py-1 truncate max-w-[250px]" title={asset.relative_path}>{asset.relative_path}</span>
                            </div>

                            {blocked ? (
                              <div className="inline-flex items-start gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-2.5 text-xs font-bold text-danger backdrop-blur-md">
                                <AlertCircle className="h-4 w-4 shrink-0" />
                                <span className="break-all">{blockReason(asset)}</span>
                              </div>
                            ) : asset.last_error ? (
                              <div className="inline-flex items-start gap-2 rounded-xl border border-danger/20 bg-danger/10 px-4 py-2.5 text-xs font-bold text-danger backdrop-blur-md">
                                <AlertCircle className="h-4 w-4 shrink-0" />
                                <span className="break-all">{trimError(asset.last_error)}</span>
                              </div>
                            ) : null}
                          </div>

                          <div className="flex flex-col sm:flex-row md:flex-col gap-3 shrink-0 w-full md:w-[160px]">
                            <button
                              onClick={() => setSelectedMediaId(asset.media_id)}
                              disabled={blocked}
                              className={cn(
                                'w-full rounded-xl border px-6 py-3 text-sm font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm',
                                selected
                                  ? 'border-accent-cyan/50 bg-accent-cyan text-black shadow-[0_0_15px_rgba(0,242,254,0.4)] hover:bg-accent-cyan/90 hover:scale-105'
                                  : 'border-white/10 bg-white/5 text-white hover:bg-white/10 hover:border-white/30 hover:scale-105'
                              )}
                            >
                              {blocked ? '片源不可用' : selected ? '已设为片源' : '设为待建房片源'}
                            </button>
                            {asset.recommended_mode === 'pretranscode_hls' && (
                              <button
                                onClick={() => handlePrepare(asset)}
                                disabled={preparing || blocked}
                                className="w-full rounded-xl border border-white/10 bg-white/5 px-6 py-3 text-sm font-bold text-white shadow-sm transition-all hover:bg-white/10 hover:border-white/30 hover:scale-105 disabled:opacity-50"
                              >
                                {preparing ? '转码中...' : asset.hls_status === 'ready' ? '重新生成 HLS' : '生成 HLS'}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </section>

          {/* Right Column - Create Room Panel */}
          <section>
            <div className="sticky top-24 relative overflow-hidden rounded-[2rem] border border-white/10 bg-black/40 p-8 shadow-2xl backdrop-blur-2xl">
              <div className="absolute top-0 right-0 -mr-20 -mt-20 h-64 w-64 rounded-full bg-accent-cyan/20 blur-[80px] pointer-events-none" />
              <div className="absolute bottom-0 left-0 -ml-20 -mb-20 h-64 w-64 rounded-full bg-accent-primary/20 blur-[80px] pointer-events-none" />
              
              <div className="relative z-10">
                <div className="flex items-center gap-4 mb-8">
                  <div className="rounded-xl bg-gradient-to-br from-accent-cyan/30 to-accent-primary/30 p-3 border border-white/10 shadow-lg">
                    <Users className="h-6 w-6 text-white drop-shadow-md" />
                  </div>
                  <h2 className="text-2xl font-black text-white">配置放映室</h2>
                </div>

                <div className="space-y-6">
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-white/70 ml-1">主持人昵称</label>
                    <input
                      value={hostName}
                      onChange={(e) => setHostName(e.target.value)}
                      className="w-full rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-base font-bold text-white outline-none focus:border-accent-cyan focus:bg-white/10 focus:shadow-[0_0_15px_rgba(0,242,254,0.15)] transition-all placeholder-white/30"
                      placeholder="你的昵称"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-white/70 ml-1">房间名称</label>
                    <input
                      value={roomName}
                      onChange={(e) => setRoomName(e.target.value)}
                      className="w-full rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-base font-bold text-white outline-none focus:border-accent-cyan focus:bg-white/10 focus:shadow-[0_0_15px_rgba(0,242,254,0.15)] transition-all placeholder-white/30"
                      placeholder="例如：今晚一起看 Maid-san"
                    />
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/40 p-6 shadow-inner">
                    {selectedAsset ? (
                      <div className="space-y-4">
                        <div className="flex items-center gap-2">
                          {selectedAssetBlocked ? (
                            <AlertCircle className="h-6 w-6 text-danger" />
                          ) : (
                            <CheckCircle2 className="h-6 w-6 text-accent-cyan" />
                          )}
                          <p className="text-base font-black text-white">已锁定片源</p>
                        </div>
                        <p className="text-sm text-accent-cyan font-bold break-all leading-relaxed bg-accent-cyan/10 rounded-xl p-4 border border-accent-cyan/20">{selectedAsset.title}</p>
                        <div className="flex flex-wrap gap-2 text-xs font-bold text-white/60">
                          <span className="rounded-lg bg-white/10 border border-white/5 px-3 py-1.5">方案：{selectedAsset.recommended_mode === 'direct_play' ? '直放' : selectedAsset.recommended_mode === 'pretranscode_hls' ? '预转 HLS' : '不可播放'}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center py-8 space-y-4">
                        <Film className="h-10 w-10 text-white/20" />
                        <p className="text-sm font-bold text-white/50">请从左侧列表选择你要放映的片源</p>
                      </div>
                    )}
                  </div>

                  <button
                    onClick={() => handleCreateRoom(selectedAsset)}
                    disabled={!selectedAsset || selectedAssetBlocked || creating}
                    className="w-full group relative overflow-hidden rounded-[1.5rem] bg-gradient-to-r from-accent-cyan via-accent-primary to-accent-secondary p-[2px] transition-all hover:scale-[1.03] active:scale-[0.98] disabled:opacity-50 disabled:hover:scale-100 shadow-[0_0_30px_rgba(0,242,254,0.2)] mt-8"
                  >
                    <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                    <div className="relative flex items-center justify-center gap-2 rounded-[22px] bg-black/40 px-4 py-5 backdrop-blur-xl">
                      <span className="text-xl font-black text-transparent bg-clip-text bg-gradient-to-r from-white to-white/90">
                        {creating ? '正在创建...' : selectedAssetBlocked ? '片源不可建房' : '🚀 立即创建放映室'}
                      </span>
                    </div>
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* Tab Content: Social */}
      {activeTab === 'social' && (
        <div className="animate-in fade-in slide-in-from-bottom-8 duration-500 max-w-5xl mx-auto">
          <div className="rounded-[2.5rem] border border-white/10 bg-black/40 p-8 md:p-10 shadow-2xl backdrop-blur-2xl">
            <div className="flex items-center gap-4 mb-8">
              <div className="rounded-xl bg-gradient-to-br from-accent-primary/30 to-accent-secondary/30 p-3 border border-white/10 shadow-lg">
                <MessageSquare className="h-7 w-7 text-white drop-shadow-md" />
              </div>
              <h2 className="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-white to-white/70">社交与聊天</h2>
            </div>
            
            {!user ? (
               <div className="rounded-3xl border border-dashed border-white/10 p-16 text-center flex flex-col items-center justify-center gap-6 bg-white/[0.01]">
                 <UserPlus className="h-16 w-16 text-white/10" />
                 <span className="text-lg font-bold text-white/40">登录后即可加好友、畅聊</span>
               </div>
            ) : (
               <div className="space-y-8">
                  <div className="flex flex-col md:flex-row gap-4 bg-white/5 p-4 rounded-3xl border border-white/10 backdrop-blur-md">
                    <input 
                      value={friendUsername} 
                      onChange={e => setFriendUsername(e.target.value)} 
                      className="flex-1 rounded-2xl border border-white/10 bg-black/40 px-6 py-4 text-base font-bold text-white focus:bg-black/60 focus:border-accent-primary focus:shadow-[0_0_15px_rgba(99,102,241,0.15)] outline-none transition-all placeholder-white/30" 
                      placeholder="输入用户名添加好友..." 
                    />
                    <button 
                      onClick={() => void handleSendFriendRequest()} 
                      disabled={friendBusy || !friendUsername.trim()} 
                      className="rounded-2xl bg-gradient-to-br from-accent-primary to-accent-secondary px-8 py-4 text-base font-bold text-white shadow-lg hover:scale-105 hover:shadow-accent-primary/30 transition-all disabled:opacity-50 disabled:hover:scale-100 whitespace-nowrap"
                    >
                      发送申请
                    </button>
                  </div>

                  {friends.length === 0 ? (
                     <div className="rounded-3xl border border-dashed border-white/10 p-16 text-center text-base font-bold text-white/40 bg-white/[0.01] flex flex-col items-center gap-4">
                       <Users className="h-12 w-12 text-white/10" />
                       暂无好友，去大厅里偶遇一个吧
                     </div>
                  ) : (
                     <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
                        <div className="space-y-4">
                           <p className="text-sm font-black text-white/60 mb-2 tracking-widest pl-2">我的好友 ({friends.length})</p>
                           <div className="space-y-3 max-h-[600px] overflow-y-auto pr-2 custom-scrollbar">
                             {friends.map(friend => (
                               <button 
                                 key={friend.user_id} 
                                 onClick={() => setSelectedFriendId(friend.user_id)} 
                                 className={cn(
                                   'w-full text-left rounded-[1.5rem] p-4 border transition-all duration-300', 
                                   selectedFriendId === friend.user_id 
                                     ? 'border-accent-primary/50 bg-accent-primary/20 shadow-inner scale-[1.02]' 
                                     : 'border-white/5 bg-white/[0.02] hover:bg-white/[0.06] hover:border-white/20'
                                 )}
                               >
                                  <div className="flex justify-between items-center mb-2">
                                    <span className="font-bold text-base text-white truncate drop-shadow-sm">{friend.username}</span>
                                    {friend.is_online && <span className="h-3 w-3 rounded-full bg-success border-2 border-black shadow-[0_0_10px_#22c55e]"></span>}
                                  </div>
                                  {friend.last_message_preview ? (
                                    <p className="text-xs font-medium text-white/50 truncate">{friend.last_message_preview}</p>
                                  ) : (
                                    <p className="text-xs font-medium text-white/30 italic">没有聊天记录</p>
                                  )}
                               </button>
                             ))}
                           </div>
                        </div>

                        {selectedFriend ? (
                           <div className="flex flex-col rounded-[2rem] border border-white/10 bg-black/40 overflow-hidden shadow-inner h-[600px]">
                              {/* Chat Header */}
                              <div className="flex justify-between items-center bg-white/5 p-6 border-b border-white/10 backdrop-blur-md">
                                 <div className="flex items-center gap-4">
                                   <div className="h-12 w-12 rounded-full bg-gradient-to-br from-white/20 to-white/5 flex items-center justify-center font-black text-xl text-white border border-white/20 shadow-inner">
                                     {selectedFriend.username.charAt(0).toUpperCase()}
                                   </div>
                                   <div>
                                     <span className="font-black text-lg text-white tracking-wide block">{selectedFriend.username}</span>
                                     <span className="text-xs font-bold text-success">在线状态已隐藏</span>
                                   </div>
                                 </div>
                                 <button onClick={() => void handleRemoveFriend()} className="rounded-xl px-4 py-2 bg-danger/10 text-xs font-bold text-danger hover:bg-danger hover:text-white transition-colors border border-danger/20">删除好友</button>
                              </div>
                              {/* Chat Body */}
                              <div ref={chatListRef} className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar bg-gradient-to-b from-transparent to-white/[0.02]">
                                {chatMessages.length === 0 && !chatLoading && (
                                   <div className="h-full flex flex-col items-center justify-center text-sm font-bold text-white/30 gap-3">
                                     <MessageSquare className="h-10 w-10 opacity-20" />
                                     打个招呼吧~
                                   </div>
                                )}
                                {chatMessages.map(msg => (
                                   <div key={msg.message_id} className={cn('flex', msg.is_mine ? 'justify-end' : 'justify-start')}>
                                     <div className={cn(
                                       'max-w-[75%] px-6 py-4 text-base shadow-lg', 
                                       msg.is_mine 
                                         ? 'bg-gradient-to-br from-accent-primary to-accent-secondary text-white rounded-3xl rounded-tr-sm' 
                                         : 'bg-white/10 text-white rounded-3xl rounded-tl-sm backdrop-blur-md border border-white/5'
                                     )}>
                                        <p className="break-words font-medium leading-relaxed">{msg.body}</p>
                                     </div>
                                   </div>
                                ))}
                              </div>
                              {/* Chat Input */}
                              <div className="p-5 bg-white/5 border-t border-white/10 backdrop-blur-md">
                                 <div className="flex gap-4">
                                   <input 
                                     value={chatDraft} 
                                     onChange={e => setChatDraft(e.target.value)} 
                                     onKeyDown={(e) => { if(e.key === 'Enter') handleSendChatMessage()}} 
                                     className="flex-1 rounded-2xl bg-black/60 border border-white/10 px-6 py-4 text-base font-bold text-white outline-none focus:border-accent-primary focus:bg-black/80 transition-all placeholder-white/30" 
                                     placeholder={`发送给 ${selectedFriend.username}...`} 
                                   />
                                   <button 
                                     onClick={() => void handleSendChatMessage()} 
                                     disabled={!chatDraft.trim() || sendingMessage} 
                                     className="rounded-2xl bg-gradient-to-br from-accent-primary to-accent-secondary px-6 text-white shadow-lg shadow-accent-primary/20 hover:scale-105 hover:shadow-[0_0_20px_rgba(99,102,241,0.4)] transition-all disabled:opacity-50 disabled:hover:scale-100 flex items-center justify-center"
                                   >
                                     {sendingMessage ? <Loader2 className="h-6 w-6 animate-spin" /> : <Send className="h-6 w-6" />}
                                   </button>
                                 </div>
                              </div>
                           </div>
                        ) : (
                          <div className="flex flex-col items-center justify-center rounded-[2rem] border border-dashed border-white/10 bg-white/[0.01] h-[600px] space-y-6">
                            <MessageSquare className="h-16 w-16 text-white/10" />
                            <p className="text-base font-bold text-white/40">在左侧选择好友开始聊天</p>
                          </div>
                        )}
                     </div>
                  )}
               </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
