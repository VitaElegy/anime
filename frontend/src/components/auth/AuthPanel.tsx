import { useState } from 'react'
import { Loader2, LogIn, UserPlus, Sparkles } from 'lucide-react'
import { useAuth } from '@/contexts/useAuth'
import { cn } from '@/lib/utils'

type AuthMode = 'login' | 'register'

function extractErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return '操作失败，请稍后重试'
}

interface AuthPanelProps {
  title?: string
  description?: string
  compact?: boolean
  onSuccess?: () => void
}

export function AuthPanel({
  title = '连接你的个人空间',
  description = '解锁个人收藏库，实现观看进度自动云同步、多端无缝切换。',
  compact = false,
  onSuccess,
}: AuthPanelProps) {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<AuthMode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [tone, setTone] = useState<'info' | 'error'>('info')

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setMessage('')
    try {
      if (mode === 'login') {
        await login(username, password)
        setTone('info')
        setMessage('登录成功。')
      } else {
        await register(username, password)
        setTone('info')
        setMessage('注册并登录成功。')
      }
      setPassword('')
      onSuccess?.()
    } catch (error) {
      setTone('error')
      setMessage(extractErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={cn('relative overflow-hidden rounded-[2rem] border border-white/10 bg-black/60 p-8 shadow-2xl backdrop-blur-2xl transition-all duration-500 hover:shadow-[0_0_40px_rgba(233,69,96,0.15)]', compact ? 'p-6' : 'p-8')}>
      <div className="absolute inset-0 bg-gradient-to-br from-accent-primary/10 via-transparent to-accent-cyan/10" />
      
      <div className="relative z-10 space-y-6">
        <div className="text-center space-y-3">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-primary/20 to-accent-secondary/20 border border-white/10 shadow-inner mb-4">
             <Sparkles className="h-6 w-6 text-accent-primary" />
          </div>
          <h3 className={cn('font-black text-white tracking-wide', compact ? 'text-xl' : 'text-2xl')}>{title}</h3>
          <p className={cn('text-white/60 font-medium leading-relaxed', compact ? 'text-xs' : 'text-sm')}>{description}</p>
        </div>

        <div className="flex rounded-xl bg-white/5 p-1 border border-white/5">
          <button
            onClick={() => setMode('login')}
            className={cn(
              'flex-1 rounded-lg py-2.5 text-sm font-bold transition-all duration-300',
              mode === 'login' ? 'bg-gradient-to-r from-accent-primary to-accent-secondary text-white shadow-md' : 'text-white/50 hover:bg-white/5 hover:text-white'
            )}
          >
            登录
          </button>
          <button
            onClick={() => setMode('register')}
            className={cn(
              'flex-1 rounded-lg py-2.5 text-sm font-bold transition-all duration-300',
              mode === 'register' ? 'bg-gradient-to-r from-accent-primary to-accent-secondary text-white shadow-md' : 'text-white/50 hover:bg-white/5 hover:text-white'
            )}
          >
            注册
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-bold text-white/60 uppercase tracking-widest">账号</label>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3.5 text-sm font-bold text-white placeholder-white/30 outline-none transition-all focus:border-accent-primary focus:bg-black/60 focus:ring-2 focus:ring-accent-primary/20 shadow-inner"
                placeholder="你的独占 ID"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-bold text-white/60 uppercase tracking-widest">密钥</label>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3.5 text-sm font-bold text-white placeholder-white/30 outline-none transition-all focus:border-accent-primary focus:bg-black/60 focus:ring-2 focus:ring-accent-primary/20 shadow-inner"
                placeholder="至少 8 个字符"
              />
            </div>
          </div>
          
          {message && (
            <div className={cn('rounded-xl border px-4 py-3 text-xs font-bold animate-in fade-in slide-in-from-top-2', tone === 'error' ? 'border-danger/30 bg-danger/20 text-danger shadow-sm' : 'border-accent-cyan/30 bg-accent-cyan/20 text-accent-cyan shadow-sm')}>
              {message}
            </div>
          )}
          
          <button
            type="submit"
            disabled={busy || !username.trim() || !password.trim()}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent-cyan to-accent-primary py-3.5 text-sm font-bold text-white shadow-lg transition-all hover:scale-[1.02] hover:shadow-accent-primary/40 disabled:opacity-50 disabled:hover:scale-100 disabled:cursor-not-allowed mt-2"
          >
            {busy ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : mode === 'login' ? (
              <LogIn className="h-5 w-5" />
            ) : (
              <UserPlus className="h-5 w-5" />
            )}
            {mode === 'login' ? '开启同步' : '注册并启用'}
          </button>
        </form>
      </div>
    </div>
  )
}
