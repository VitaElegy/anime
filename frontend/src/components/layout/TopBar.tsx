import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Bell } from 'lucide-react'
import { cn } from '@/lib/utils'

interface TopBarProps {
  sidebarCollapsed: boolean
}

export function TopBar({ sidebarCollapsed: _sidebarCollapsed }: TopBarProps) {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
    }
  }

  return (
    <header className="flex h-14 items-center gap-4 border-b border-border bg-bg-secondary/80 px-4 backdrop-blur-sm">
      {/* Global search */}
      <form onSubmit={handleSearch} className="flex flex-1 items-center max-w-xl">
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

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <button className="relative rounded-lg p-2 text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors">
          <Bell className="h-5 w-5" />
          <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-accent-primary pulse-dot" />
        </button>
      </div>
    </header>
  )
}
