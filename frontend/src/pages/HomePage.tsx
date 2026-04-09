import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TrendingUp, Download, Search, Calendar, Terminal, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { onCoverError } from '@/lib/utils'
import { searchSubsPlease, getDownloadProgress, batchResolveCovers, proxyImageUrl } from '@/api'
import type { TorrentItem, DownloadTask } from '@/types'
import { formatBytes } from '@/lib/utils'

const quickLinks = [
  { to: '/search', icon: Search, label: '搜索资源', color: 'bg-accent-primary' },
  { to: '/calendar', icon: Calendar, label: '新番日历', color: 'bg-accent-secondary' },
  { to: '/downloads', icon: Download, label: '下载管理', color: 'bg-accent-cyan' },
  { to: '/crawl', icon: Terminal, label: '抓取控制台', color: 'bg-accent-gold' },
]

interface CoverInfo {
  cover_url: string
  name_cn: string
  name: string
}

export default function HomePage() {
  const [recentItems, setRecentItems] = useState<TorrentItem[]>([])
  const [downloads, setDownloads] = useState<DownloadTask[]>([])
  const [coverMap, setCoverMap] = useState<Record<string, CoverInfo>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const [spResult, dlTasks] = await Promise.allSettled([
          searchSubsPlease('', 1080),
          getDownloadProgress(),
        ])
        let items: TorrentItem[] = []
        if (spResult.status === 'fulfilled') {
          items = spResult.value.items.slice(0, 12)
          setRecentItems(items)
        }
        if (dlTasks.status === 'fulfilled') setDownloads(dlTasks.value.slice(0, 5))

        // Resolve covers — deduplicate by cleaned name to reduce API calls
        if (items.length > 0) {
          try {
            const covers = await batchResolveCovers(items.map(i => i.title))
            const map: Record<string, CoverInfo> = {}
            for (const c of covers) {
              map[c.title] = { cover_url: c.cover_url || '', name_cn: c.name_cn || '', name: c.name || '' }
            }
            setCoverMap(map)
          } catch { /* best effort */ }
        }
      } catch { /* silent */ } finally { setLoading(false) }
    }
    load()
  }, [])

  const getDisplayName = (item: TorrentItem): string => {
    const info = coverMap[item.title]
    if (info?.name_cn) return info.name_cn
    if (info?.name) return info.name
    return item.title.replace(/\[.*?\]/g, '').replace(/\(.*?\)/g, '').replace(/- \d+.*/, '').trim()
  }

  return (
    <div className="space-y-8 max-w-6xl">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-accent-primary/20 via-bg-secondary to-accent-secondary/20 p-8 border border-border">
        <div className="relative z-10">
          <h1 className="text-3xl font-bold gradient-text mb-2">NicoTracker</h1>
          <p className="text-text-secondary text-sm max-w-md">你的个人番剧资源管理中心。搜索、下载、追番，一站搞定。</p>
        </div>
        <div className="absolute -right-8 -top-8 h-40 w-40 rounded-full bg-accent-primary/10 blur-3xl" />
        <div className="absolute -bottom-4 right-20 h-32 w-32 rounded-full bg-accent-secondary/10 blur-3xl" />
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {quickLinks.map((link) => (
          <Link key={link.to} to={link.to} className="card-hover flex items-center gap-3 rounded-xl bg-bg-card border border-border p-4 group">
            <div className={cn('rounded-lg p-2.5 text-white', link.color)}><link.icon className="h-5 w-5" /></div>
            <span className="text-sm font-medium text-text-secondary group-hover:text-text-primary transition-colors">{link.label}</span>
          </Link>
        ))}
      </div>

      {/* Recent releases with covers + Chinese names */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp className="h-5 w-5 text-accent-primary" />
          <h2 className="text-lg font-semibold">最新发布</h2>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-secondary/10 text-accent-secondary font-medium">
            数据源: SubsPlease RSS
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan font-medium">
            封面/中文名: Bangumi API
          </span>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-accent-primary" /></div>
        ) : recentItems.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {recentItems.map((item, i) => {
              const info = coverMap[item.title]
              const displayName = getDisplayName(item)
              return (
                <Link to={`/search?q=${encodeURIComponent(displayName.slice(0, 20))}`} key={i} className="group">
                  <div className="poster-card card-hover border border-border relative bg-bg-card">
                    {info?.cover_url ? (
                      <img src={proxyImageUrl(info.cover_url)} alt={displayName} loading="lazy" className="w-full h-full object-cover"
                        onError={onCoverError} />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-bg-card to-bg-secondary">
                        <span className="text-3xl font-bold text-border">{displayName.charAt(0)}</span>
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent" />
                    <div className="absolute bottom-0 left-0 right-0 p-2.5">
                      <p className="text-[11px] font-medium text-white line-clamp-2 leading-tight">{displayName}</p>
                      <div className="flex items-center gap-2 mt-1 text-[10px] text-white/60">
                        <span>{item.source}</span>
                        {item.size && <span>{item.size}</span>}
                      </div>
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>
        ) : (
          <p className="text-sm text-text-muted">暂无数据，请先抓取资源</p>
        )}
      </section>

      {/* Active downloads */}
      {downloads.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Download className="h-5 w-5 text-accent-cyan" />
            <h2 className="text-lg font-semibold">下载中</h2>
          </div>
          <div className="space-y-2">
            {downloads.map((task) => (
              <div key={task.hash} className="rounded-xl bg-bg-card border border-border p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium truncate max-w-md">{task.name}</p>
                  <div className="flex items-center gap-3 text-xs text-text-muted shrink-0">
                    {task.speed > 0 && <span>{formatBytes(task.speed)}/s</span>}
                    <span className="text-accent-cyan font-medium">{(task.progress * 100).toFixed(1)}%</span>
                  </div>
                </div>
                <div className="h-1.5 rounded-full bg-bg-primary overflow-hidden">
                  <div className="h-full rounded-full bg-gradient-to-r from-accent-cyan to-accent-primary transition-all duration-500" style={{ width: `${task.progress * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
