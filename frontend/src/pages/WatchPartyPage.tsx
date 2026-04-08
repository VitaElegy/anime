import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Tv,
  Mic,
  MicOff,
  Send,
  Play,
  Pause,
  Users,
  Plus,
  LogIn,
  LogOut,
  Copy,
  Volume2,
  VolumeX,
  Link,
  Crown,
} from 'lucide-react'
import { cn } from '@/lib/utils'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PeerInfo {
  user_id: string
  nickname: string
  is_host: boolean
}

interface ChatMessage {
  type: 'chat'
  user_id: string
  nickname: string
  content: string
  timestamp: number
}

interface RoomInfo {
  room_id: string
  name: string
  peer_count: number
  video_url: string
  video_title: string
  is_playing: boolean
  current_time: number
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const API_BASE = '/api/watchparty'
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/watchparty/ws`

const ICE_SERVERS: RTCConfiguration = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
  ],
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function WatchPartyPage() {
  // Connection state
  const [phase, setPhase] = useState<'lobby' | 'room'>('lobby')
  const [nickname, setNickname] = useState(() => localStorage.getItem('wp_nick') || '')
  const [roomList, setRoomList] = useState<RoomInfo[]>([])
  const [newRoomName, setNewRoomName] = useState('')
  const [joinRoomId, setJoinRoomId] = useState('')

  // Room state
  const [roomId, setRoomId] = useState('')
  const [roomName, setRoomName] = useState('')
  const [userId, setUserId] = useState('')
  const [isHost, setIsHost] = useState(false)
  const [peers, setPeers] = useState<PeerInfo[]>([])
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')

  // Video state
  const [videoUrl, setVideoUrl] = useState('')
  const [videoUrlInput, setVideoUrlInput] = useState('')
  const [isPlaying, setIsPlaying] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const ignoreEventsRef = useRef(false)

  // Voice state
  const [voiceEnabled, setVoiceEnabled] = useState(false)
  const [muted, setMuted] = useState(true)
  const localStreamRef = useRef<MediaStream | null>(null)
  const peerConnectionsRef = useRef<Map<string, RTCPeerConnection>>(new Map())
  const remoteAudiosRef = useRef<Map<string, HTMLAudioElement>>(new Map())

  // WebSocket
  const wsRef = useRef<WebSocket | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)

  // ── Fetch rooms ──
  const fetchRooms = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/rooms`)
      const data = await res.json()
      setRoomList(data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchRooms()
    const iv = setInterval(fetchRooms, 5000)
    return () => clearInterval(iv)
  }, [fetchRooms])

  // Auto scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  // ── WebSocket handlers ──
  const connectRoom = useCallback((rid: string) => {
    const nick = nickname || '匿名用户'
    localStorage.setItem('wp_nick', nick)

    const ws = new WebSocket(`${WS_BASE}/${rid}?nickname=${encodeURIComponent(nick)}`)
    wsRef.current = ws

    ws.onopen = () => {
      setPhase('room')
      setRoomId(rid)
    }

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      handleWsMessage(msg)
    }

    ws.onclose = () => {
      cleanupVoice()
      setPhase('lobby')
      setRoomId('')
      wsRef.current = null
    }

    ws.onerror = () => ws.close()
  }, [nickname])

  const handleWsMessage = useCallback((msg: any) => {
    switch (msg.type) {
      case 'init':
        setUserId(msg.user_id)
        setIsHost(msg.is_host)
        setRoomName(msg.room?.name || '')
        setPeers(msg.peers || [])
        setChatMessages(msg.chat_history || [])
        if (msg.room?.video_url) {
          setVideoUrl(msg.room.video_url)
          setVideoUrlInput(msg.room.video_url)
        }
        break

      case 'peer_joined':
        setPeers(msg.peers || [])
        // Initiate WebRTC voice with the new peer if voice is on
        if (voiceEnabled && localStreamRef.current) {
          createOffer(msg.user_id)
        }
        break

      case 'peer_left':
        setPeers(msg.peers || [])
        closePeerConnection(msg.user_id)
        break

      case 'host_changed':
        setIsHost(prev => msg.user_id === userId ? true : prev)
        setPeers(prev => prev.map(p => ({ ...p, is_host: p.user_id === msg.user_id })))
        break

      case 'video_change':
        setVideoUrl(msg.url || '')
        setVideoUrlInput(msg.url || '')
        break

      case 'play':
        ignoreEventsRef.current = true
        setIsPlaying(true)
        if (videoRef.current) {
          videoRef.current.currentTime = msg.time
          videoRef.current.play().catch(() => {})
        }
        setTimeout(() => { ignoreEventsRef.current = false }, 300)
        break

      case 'pause':
        ignoreEventsRef.current = true
        setIsPlaying(false)
        if (videoRef.current) {
          videoRef.current.currentTime = msg.time
          videoRef.current.pause()
        }
        setTimeout(() => { ignoreEventsRef.current = false }, 300)
        break

      case 'seek':
        ignoreEventsRef.current = true
        if (videoRef.current) {
          videoRef.current.currentTime = msg.time
        }
        setTimeout(() => { ignoreEventsRef.current = false }, 300)
        break

      case 'sync_state':
        if (videoRef.current && msg.video_url) {
          setVideoUrl(msg.video_url)
          videoRef.current.currentTime = msg.current_time
          if (msg.is_playing) videoRef.current.play().catch(() => {})
        }
        break

      case 'chat':
        setChatMessages(prev => [...prev.slice(-199), msg])
        break

      // WebRTC signaling
      case 'rtc_offer':
        handleRtcOffer(msg.from, msg.sdp)
        break
      case 'rtc_answer':
        handleRtcAnswer(msg.from, msg.sdp)
        break
      case 'rtc_ice_candidate':
        handleIceCandidate(msg.from, msg.candidate)
        break
    }
  }, [voiceEnabled, userId])

  // ── Video player events ──
  const onVideoPlay = () => {
    if (ignoreEventsRef.current) return
    wsRef.current?.send(JSON.stringify({
      type: 'play',
      time: videoRef.current?.currentTime || 0,
    }))
    setIsPlaying(true)
  }

  const onVideoPause = () => {
    if (ignoreEventsRef.current) return
    wsRef.current?.send(JSON.stringify({
      type: 'pause',
      time: videoRef.current?.currentTime || 0,
    }))
    setIsPlaying(false)
  }

  const onVideoSeeked = () => {
    if (ignoreEventsRef.current) return
    wsRef.current?.send(JSON.stringify({
      type: 'seek',
      time: videoRef.current?.currentTime || 0,
    }))
  }

  // Host sends periodic time updates
  useEffect(() => {
    if (!isHost || !videoRef.current) return
    const iv = setInterval(() => {
      if (videoRef.current && !videoRef.current.paused) {
        wsRef.current?.send(JSON.stringify({
          type: 'time_update',
          time: videoRef.current.currentTime,
        }))
      }
    }, 3000)
    return () => clearInterval(iv)
  }, [isHost])

  const changeVideo = () => {
    if (!videoUrlInput.trim()) return
    setVideoUrl(videoUrlInput.trim())
    wsRef.current?.send(JSON.stringify({
      type: 'video_change',
      url: videoUrlInput.trim(),
      title: '',
    }))
  }

  // ── Chat ──
  const sendChat = () => {
    if (!chatInput.trim()) return
    wsRef.current?.send(JSON.stringify({ type: 'chat', content: chatInput.trim() }))
    setChatInput('')
  }

  // ── WebRTC Voice Chat ──
  const createPeerConnection = (targetUid: string): RTCPeerConnection => {
    const pc = new RTCPeerConnection(ICE_SERVERS)

    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => {
        pc.addTrack(track, localStreamRef.current!)
      })
    }

    pc.onicecandidate = (e) => {
      if (e.candidate) {
        wsRef.current?.send(JSON.stringify({
          type: 'rtc_ice_candidate',
          target: targetUid,
          candidate: e.candidate,
        }))
      }
    }

    pc.ontrack = (e) => {
      let audio = remoteAudiosRef.current.get(targetUid)
      if (!audio) {
        audio = new Audio()
        audio.autoplay = true
        remoteAudiosRef.current.set(targetUid, audio)
      }
      audio.srcObject = e.streams[0]
    }

    peerConnectionsRef.current.set(targetUid, pc)
    return pc
  }

  const createOffer = async (targetUid: string) => {
    const pc = createPeerConnection(targetUid)
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    wsRef.current?.send(JSON.stringify({
      type: 'rtc_offer',
      target: targetUid,
      sdp: pc.localDescription,
    }))
  }

  const handleRtcOffer = async (fromUid: string, sdp: any) => {
    if (!localStreamRef.current) return
    const pc = createPeerConnection(fromUid)
    await pc.setRemoteDescription(new RTCSessionDescription(sdp))
    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    wsRef.current?.send(JSON.stringify({
      type: 'rtc_answer',
      target: fromUid,
      sdp: pc.localDescription,
    }))
  }

  const handleRtcAnswer = async (fromUid: string, sdp: any) => {
    const pc = peerConnectionsRef.current.get(fromUid)
    if (pc) {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp))
    }
  }

  const handleIceCandidate = async (fromUid: string, candidate: any) => {
    const pc = peerConnectionsRef.current.get(fromUid)
    if (pc && candidate) {
      await pc.addIceCandidate(new RTCIceCandidate(candidate))
    }
  }

  const closePeerConnection = (uid: string) => {
    const pc = peerConnectionsRef.current.get(uid)
    if (pc) {
      pc.close()
      peerConnectionsRef.current.delete(uid)
    }
    const audio = remoteAudiosRef.current.get(uid)
    if (audio) {
      audio.srcObject = null
      remoteAudiosRef.current.delete(uid)
    }
  }

  const toggleVoice = async () => {
    if (voiceEnabled) {
      cleanupVoice()
      setVoiceEnabled(false)
      setMuted(true)
      wsRef.current?.send(JSON.stringify({ type: 'voice_state', muted: true }))
    } else {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        localStreamRef.current = stream
        setVoiceEnabled(true)
        setMuted(false)
        wsRef.current?.send(JSON.stringify({ type: 'voice_state', muted: false }))

        // Create offers to all existing peers
        for (const p of peers) {
          if (p.user_id !== userId) {
            await createOffer(p.user_id)
          }
        }
      } catch (err) {
        console.error('Failed to get microphone:', err)
      }
    }
  }

  const toggleMute = () => {
    if (localStreamRef.current) {
      const audioTrack = localStreamRef.current.getAudioTracks()[0]
      if (audioTrack) {
        audioTrack.enabled = !audioTrack.enabled
        setMuted(!audioTrack.enabled)
        wsRef.current?.send(JSON.stringify({ type: 'voice_state', muted: !audioTrack.enabled }))
      }
    }
  }

  const cleanupVoice = () => {
    localStreamRef.current?.getTracks().forEach(t => t.stop())
    localStreamRef.current = null
    peerConnectionsRef.current.forEach(pc => pc.close())
    peerConnectionsRef.current.clear()
    remoteAudiosRef.current.forEach(a => { a.srcObject = null })
    remoteAudiosRef.current.clear()
  }

  // ── Room actions ──
  const createRoom = async () => {
    const name = newRoomName.trim() || '放映室'
    try {
      const res = await fetch(`${API_BASE}/rooms?name=${encodeURIComponent(name)}`, { method: 'POST' })
      const room = await res.json()
      connectRoom(room.room_id)
    } catch { /* ignore */ }
  }

  const joinRoom = (rid: string) => {
    connectRoom(rid)
  }

  const leaveRoom = () => {
    cleanupVoice()
    wsRef.current?.close()
    setPhase('lobby')
    setVideoUrl('')
    setVideoUrlInput('')
    fetchRooms()
  }

  const copyRoomId = () => {
    navigator.clipboard.writeText(roomId)
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupVoice()
      wsRef.current?.close()
    }
  }, [])

  /* ================================================================ */
  /*  RENDER                                                           */
  /* ================================================================ */

  // ── Lobby ──
  if (phase === 'lobby') {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 text-white">
            <Tv className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-text-primary">放映室</h1>
            <p className="text-sm text-text-secondary">和朋友一起看番，还能语音聊天</p>
          </div>
        </div>

        {/* Nickname */}
        <div className="rounded-xl border border-border bg-bg-secondary p-5 space-y-4">
          <label className="block text-sm font-medium text-text-secondary">你的昵称</label>
          <input
            value={nickname}
            onChange={e => setNickname(e.target.value)}
            placeholder="输入昵称..."
            className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
          />
        </div>

        {/* Create room */}
        <div className="rounded-xl border border-border bg-bg-secondary p-5 space-y-4">
          <h2 className="text-lg font-semibold text-text-primary">创建房间</h2>
          <div className="flex gap-2">
            <input
              value={newRoomName}
              onChange={e => setNewRoomName(e.target.value)}
              placeholder="房间名称（可选）"
              className="flex-1 rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
            />
            <button
              onClick={createRoom}
              className="flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-white hover:bg-accent-primary/90 transition-colors"
            >
              <Plus className="h-4 w-4" /> 创建
            </button>
          </div>
        </div>

        {/* Join room */}
        <div className="rounded-xl border border-border bg-bg-secondary p-5 space-y-4">
          <h2 className="text-lg font-semibold text-text-primary">加入房间</h2>
          <div className="flex gap-2">
            <input
              value={joinRoomId}
              onChange={e => setJoinRoomId(e.target.value)}
              placeholder="输入房间 ID..."
              className="flex-1 rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
            />
            <button
              onClick={() => joinRoom(joinRoomId)}
              disabled={!joinRoomId.trim()}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors disabled:opacity-50"
            >
              <LogIn className="h-4 w-4" /> 加入
            </button>
          </div>
        </div>

        {/* Room list */}
        {roomList.length > 0 && (
          <div className="rounded-xl border border-border bg-bg-secondary p-5 space-y-3">
            <h2 className="text-lg font-semibold text-text-primary">在线房间</h2>
            {roomList.map(r => (
              <div
                key={r.room_id}
                className="flex items-center justify-between rounded-lg border border-border bg-bg-primary p-3"
              >
                <div>
                  <div className="text-sm font-medium text-text-primary">{r.name}</div>
                  <div className="text-xs text-text-muted flex items-center gap-2 mt-0.5">
                    <Users className="h-3 w-3" /> {r.peer_count} 人在看
                    <span className="text-text-muted">· ID: {r.room_id}</span>
                  </div>
                </div>
                <button
                  onClick={() => joinRoom(r.room_id)}
                  className="rounded-lg bg-accent-primary/15 px-3 py-1.5 text-xs font-medium text-accent-primary hover:bg-accent-primary/25 transition-colors"
                >
                  加入
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ── Room view ──
  return (
    <div className="flex h-[calc(100vh-7rem)] gap-4">
      {/* Left: Video + Controls */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Room header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-pink-500 text-white">
              <Tv className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-text-primary">{roomName}</h2>
              <div className="flex items-center gap-2 text-xs text-text-muted">
                <span>ID: {roomId}</span>
                <button onClick={copyRoomId} className="hover:text-accent-primary"><Copy className="h-3 w-3" /></button>
                <span>· {peers.length} 人</span>
                {isHost && <span className="text-yellow-500 flex items-center gap-0.5"><Crown className="h-3 w-3" /> 房主</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Voice toggle */}
            <button
              onClick={voiceEnabled ? toggleMute : toggleVoice}
              className={cn(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                voiceEnabled
                  ? muted
                    ? 'bg-red-500/15 text-red-400 hover:bg-red-500/25'
                    : 'bg-green-500/15 text-green-400 hover:bg-green-500/25'
                  : 'bg-bg-hover text-text-secondary hover:text-text-primary'
              )}
            >
              {voiceEnabled ? (muted ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />) : <Mic className="h-3.5 w-3.5" />}
              {voiceEnabled ? (muted ? '已静音' : '通话中') : '开启语音'}
            </button>
            {voiceEnabled && (
              <button
                onClick={toggleVoice}
                className="rounded-lg bg-red-500/15 px-2 py-1.5 text-xs text-red-400 hover:bg-red-500/25 transition-colors"
                title="关闭语音"
              >
                <VolumeX className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              onClick={leaveRoom}
              className="flex items-center gap-1.5 rounded-lg bg-red-500/15 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/25 transition-colors"
            >
              <LogOut className="h-3.5 w-3.5" /> 离开
            </button>
          </div>
        </div>

        {/* Video URL input */}
        <div className="flex gap-2 mb-3">
          <div className="relative flex-1">
            <Link className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <input
              value={videoUrlInput}
              onChange={e => setVideoUrlInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && changeVideo()}
              placeholder="粘贴视频链接 (MP4 / m3u8 / WebM)..."
              className="w-full rounded-lg border border-border bg-bg-secondary pl-9 pr-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
            />
          </div>
          <button
            onClick={changeVideo}
            className="rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-white hover:bg-accent-primary/90 transition-colors"
          >
            播放
          </button>
        </div>

        {/* Video player */}
        <div className="relative flex-1 rounded-xl overflow-hidden bg-black border border-border">
          {videoUrl ? (
            <video
              ref={videoRef}
              src={videoUrl}
              className="w-full h-full object-contain"
              controls
              onPlay={onVideoPlay}
              onPause={onVideoPause}
              onSeeked={onVideoSeeked}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-text-muted gap-3">
              <Tv className="h-16 w-16 opacity-30" />
              <p className="text-sm">粘贴视频链接开始观看</p>
              <p className="text-xs opacity-60">支持 MP4、WebM、m3u8 格式</p>
            </div>
          )}
        </div>

        {/* Peers bar */}
        <div className="flex items-center gap-2 mt-3 overflow-x-auto">
          {peers.map(p => (
            <div
              key={p.user_id}
              className={cn(
                'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs border shrink-0',
                p.user_id === userId
                  ? 'border-accent-primary/50 bg-accent-primary/10 text-accent-primary'
                  : 'border-border bg-bg-secondary text-text-secondary'
              )}
            >
              {p.is_host && <Crown className="h-3 w-3 text-yellow-500" />}
              <span>{p.nickname}</span>
              {p.user_id === userId && <span className="opacity-50">(我)</span>}
            </div>
          ))}
        </div>
      </div>

      {/* Right: Chat panel */}
      <div className="w-72 flex flex-col rounded-xl border border-border bg-bg-secondary shrink-0">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Send className="h-4 w-4 text-text-muted" />
          <span className="text-sm font-medium text-text-primary">聊天</span>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2 text-sm">
          {chatMessages.map((msg, i) => (
            <div key={i}>
              <span className={cn(
                'font-medium',
                msg.user_id === userId ? 'text-accent-primary' : 'text-text-secondary'
              )}>
                {msg.nickname}
              </span>
              <span className="text-text-muted">: </span>
              <span className="text-text-primary break-all">{msg.content}</span>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        <div className="border-t border-border p-2">
          <div className="flex gap-1.5">
            <input
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendChat()}
              placeholder="发消息..."
              className="flex-1 rounded-lg border border-border bg-bg-primary px-2.5 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
            />
            <button
              onClick={sendChat}
              className="rounded-lg bg-accent-primary p-1.5 text-white hover:bg-accent-primary/90 transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
