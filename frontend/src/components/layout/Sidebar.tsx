import { NavLink } from 'react-router-dom'
import {
  Home,
  Search,
  Download,
  Library,
  Calendar,
  Terminal,
  Tv,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', icon: Home, label: '首页' },
  { to: '/search', icon: Search, label: '搜索资源' },
  { to: '/downloads', icon: Download, label: '下载管理' },
  { to: '/library', icon: Library, label: '番剧库' },
  { to: '/calendar', icon: Calendar, label: '新番日历' },
  { to: '/watch', icon: Tv, label: '一起看' },
  { to: '/crawl', icon: Terminal, label: '抓取控制台' },
]

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-white/5 bg-black/40 backdrop-blur-2xl transition-all duration-300 z-40',
        collapsed ? 'w-20' : 'w-64'
      )}
    >
      <div className="absolute inset-0 bg-gradient-to-b from-white/[0.02] to-transparent pointer-events-none" />
      
      {/* Brand */}
      <div className="relative flex h-16 items-center gap-3 border-b border-white/5 px-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-primary to-accent-secondary text-white font-black text-lg shadow-lg shadow-accent-primary/20 transition-transform hover:scale-105 hover:rotate-3">
          N
        </div>
        {!collapsed && (
          <span className="text-xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-white/70 whitespace-nowrap drop-shadow-sm">
            NicoTracker
          </span>
        )}
      </div>

      {/* Nav */}
      <nav className="relative flex-1 space-y-2 p-3 mt-4 overflow-y-auto custom-scrollbar">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-bold transition-all duration-300',
                isActive
                  ? 'bg-white/10 text-white shadow-sm ring-1 ring-white/10'
                  : 'text-text-muted hover:bg-white/5 hover:text-white'
              )
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className={cn('h-5 w-5 shrink-0 transition-transform duration-300', isActive ? 'text-accent-primary scale-110 drop-shadow-[0_0_8px_rgba(233,69,96,0.6)]' : 'group-hover:scale-110 group-hover:text-white')} />
                {!collapsed && <span className="whitespace-nowrap">{item.label}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="relative p-3 border-t border-white/5">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-center rounded-xl py-3 text-text-muted transition-all hover:bg-white/5 hover:text-white"
        >
          {collapsed ? <ChevronRight className="h-5 w-5" /> : <ChevronLeft className="h-5 w-5" />}
        </button>
      </div>
    </aside>
  )
}
