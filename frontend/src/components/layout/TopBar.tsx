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
      <header className="sticky top-0 z-30 flex h-20 items-center gap-6 border-b border-white/5 bg-black/40 px-8 backdrop-blur-xl">
        <form onSubmit={handleSearch} className="flex max-w-xl flex-1 items-center group">
          <div className="relative w-full transition-all duration-300 transform group-focus-within:scale-[1.02]">
            <div className="absolute inset-0 bg-gradient-to-r from-accent-primary to-accent-secondary rounded-2xl blur opacity-20 transition-opacity duration-300 group-focus-within:opacity-50" />
            <div className="relative">
               <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40 transition-colors group-focus-within:text-accent-primary" />
               <input
                 type="text"
                 value={query}
                 onChange={(e) => setQuery(e.target.value)}
                 placeholder="搜索番剧、种子..."
                 className={cn(
                   'w-full rounded-xl border border-white/10 bg-white/5 py-2.5 pl-12 pr-4 text-sm font-bold text-white shadow-inner',
                   'placeholder:text-white/30',
                   'focus:border-accent-primary/50 focus:bg-black/60 focus:outline-none focus:ring-2 focus:ring-accent-primary/20',
                   'transition-all duration-300'
                 )}
               />
            </div>
          </div>
        </form>

        <div className="flex items-center gap-4">
          <button className="relative rounded-xl p-2.5 text-white/50 transition-all hover:bg-white/10 hover:text-white hover:scale-105 border border-transparent hover:border-white/5 shadow-sm">
            <Bell className="h-5 w-5" />
            <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-accent-primary shadow-[0_0_8px_rgba(233,69,96,0.8)] animate-pulse" />
          </button>

          {isAuthenticated && user ? (
            <div className="group relative flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-2 shadow-sm backdrop-blur-md transition-all hover:bg-white/10 hover:border-accent-cyan/30">
              <div className="rounded-full bg-gradient-to-br from-accent-cyan to-accent-primary p-0.5">
                 <UserCircle2 className="h-7 w-7 text-white" />
              </div>
              <div className="text-right">
                <p className="text-sm font-black text-white leading-none tracking-wide">{user.username}</p>
                <p className="text-[10px] font-bold text-accent-cyan/80 mt-1">个人空间已开启</p>
              </div>
              <button
                onClick={() => void logout()}
                className="ml-2 rounded-xl p-2 text-white/40 transition-all hover:bg-danger/20 hover:text-danger hover:scale-105 border border-transparent hover:border-danger/30"
                title="退出登录"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setAuthOpen(true)}
              className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-accent-primary to-accent-secondary px-6 py-2.5 text-sm font-bold text-white shadow-lg transition-all hover:scale-105 hover:shadow-accent-primary/30"
            >
              <UserCircle2 className="h-5 w-5" />
              登录 / 注册
            </button>
          )}
        </div>
      </header>

      {authOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 px-4 backdrop-blur-xl animate-in fade-in duration-300" onClick={() => setAuthOpen(false)}>
          <div className="relative w-full max-w-md animate-in zoom-in-95 duration-300" onClick={(event) => event.stopPropagation()}>
            <button
              onClick={() => setAuthOpen(false)}
              className="absolute -right-4 -top-4 z-10 rounded-full bg-white/10 p-2 text-white/60 transition-all hover:bg-white/20 hover:text-white hover:scale-110 shadow-lg border border-white/5"
            >
              <X className="h-5 w-5" />
            </button>
            <AuthPanel
              title="连接你的个人空间"
              description="登录后解锁个人收藏库，实现观看进度自动云同步、多端无缝切换与专属番剧推荐体验。"
              onSuccess={() => setAuthOpen(false)}
            />
          </div>
        </div>
      )}
    </>
  )
}
