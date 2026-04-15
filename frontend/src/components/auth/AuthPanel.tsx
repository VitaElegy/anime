import { useState } from 'react'
import { Loader2, LogIn, UserPlus } from 'lucide-react'
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
  title = '登录后启用个人收藏',
  description = '收藏会按账号隔离，后续也可以继续扩展到观看记录和偏好设置。',
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
    <div className="space-y-4 rounded-2xl border border-border bg-bg-card p-4">
      <div className="space-y-1">
        <h3 className={cn('font-semibold text-text-primary', compact ? 'text-sm' : 'text-lg')}>{title}</h3>
        <p className={cn('text-text-secondary', compact ? 'text-xs' : 'text-sm')}>{description}</p>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => setMode('login')}
          className={cn(
            'rounded-lg px-3 py-2 text-xs font-medium transition-colors',
            mode === 'login' ? 'bg-accent-primary text-white' : 'bg-bg-secondary text-text-secondary hover:text-text-primary'
          )}
        >
          登录
        </button>
        <button
          onClick={() => setMode('register')}
          className={cn(
            'rounded-lg px-3 py-2 text-xs font-medium transition-colors',
            mode === 'register' ? 'bg-accent-primary text-white' : 'bg-bg-secondary text-text-secondary hover:text-text-primary'
          )}
        >
          注册
        </button>
      </div>

      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="mb-1 block text-xs text-text-muted">用户名</label>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
            placeholder="例如 elegy"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-muted">密码</label>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
            placeholder="至少 8 位"
          />
        </div>
        {message && (
          <div className={cn('rounded-lg px-3 py-2 text-xs', tone === 'error' ? 'bg-danger/8 text-danger' : 'bg-accent-cyan/10 text-accent-cyan')}>
            {message}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-accent-cyan px-3 py-2 text-sm font-medium text-white hover:bg-accent-cyan/90 disabled:opacity-60"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : mode === 'login' ? (
            <LogIn className="h-4 w-4" />
          ) : (
            <UserPlus className="h-4 w-4" />
          )}
          {mode === 'login' ? '登录' : '注册并登录'}
        </button>
      </form>
    </div>
  )
}
