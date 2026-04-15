import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, LogOut, Search, UserCircle2, X } from 'lucide-react'
import { AuthPanel } from '@/components/auth/AuthPanel'
import { useAuth } from '@/contexts/useAuth'
import { cn } from '@/lib/utils'

export function TopBar() {
  const [query, setQuery] = useState('')
  const [authOpen, setAuthOpen] = useState(false)
  const navigate = useNavigate()
  const { user, isAuthenticated, logout } = useAuth()

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
    }
  }

  return (
    <>
      <header className="flex h-14 items-center gap-4 border-b border-border bg-bg-secondary/80 px-4 backdrop-blur-sm">
        <form onSubmit={handleSearch} className="flex max-w-xl flex-1 items-center">
          <div className="relative w-full">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索番剧、种子..."
              className={cn(
                'w-full rounded-lg border border-border bg-bg-primary py-2 pl-10 pr-4 text-sm',
                'text-text-primary placeholder:text-text-muted',
                'focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary/50',
                'transition-colors'
              )}
            />
          </div>
        </form>

        <div className="flex items-center gap-2">
          <button className="relative rounded-lg p-2 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary">
            <Bell className="h-5 w-5" />
            <span className="pulse-dot absolute right-1 top-1 h-2 w-2 rounded-full bg-accent-primary" />
          </button>

          {isAuthenticated && user ? (
            <div className="flex items-center gap-2 rounded-xl border border-border bg-bg-card px-3 py-1.5">
              <UserCircle2 className="h-4 w-4 text-accent-cyan" />
              <div className="text-right">
                <p className="text-xs font-medium text-text-primary">{user.username}</p>
                <p className="text-[11px] text-text-muted">个人收藏已启用</p>
              </div>
              <button
                onClick={() => void logout()}
                className="rounded-lg p-1 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
                title="退出登录"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setAuthOpen(true)}
              className="inline-flex items-center gap-2 rounded-xl bg-accent-primary px-3 py-2 text-sm font-medium text-white hover:bg-accent-primary/90"
            >
              <UserCircle2 className="h-4 w-4" />
              登录 / 注册
            </button>
          )}
        </div>
      </header>

      {authOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm" onClick={() => setAuthOpen(false)}>
          <div className="relative w-full max-w-md" onClick={(event) => event.stopPropagation()}>
            <button
              onClick={() => setAuthOpen(false)}
              className="absolute right-3 top-3 z-10 rounded-lg p-1 text-text-muted hover:text-text-primary"
            >
              <X className="h-4 w-4" />
            </button>
            <AuthPanel
              title="创建你的账号"
              description="登录后收藏会按用户隔离，后续也能继续扩展到观看记录和个人偏好。"
              onSuccess={() => setAuthOpen(false)}
            />
          </div>
        </div>
      )}
    </>
  )
}
