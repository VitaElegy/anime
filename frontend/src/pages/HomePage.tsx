import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TrendingUp, Download, Search, Calendar, Terminal, Loader2, Tv } from 'lucide-react'
import { cn } from '@/lib/utils'
import { searchSubsPlease, getDownloadProgress, batchResolveCovers, proxyImageUrl } from '@/api'
import { buildAnimeHref } from '@/lib/animeLinks'
import type { TorrentItem, DownloadTask } from '@/types'
import { formatBytes } from '@/lib/utils'

const quickLinks = [
  { to: '/search', icon: Search, label: '搜索资源', color: 'from-[#FF6B6B] to-[#FF8E53]', shadow: 'shadow-[#FF6B6B]/20' },
  { to: '/calendar', icon: Calendar, label: '新番日历', color: 'from-[#4D96FF] to-[#6BCB77]', shadow: 'shadow-[#4D96FF]/20' },
  { to: '/downloads', icon: Download, label: '下载管理', color: 'from-[#FFD93D] to-[#FF8E53]', shadow: 'shadow-[#FFD93D]/20' },
  { to: '/watch', icon: Tv, label: '一起看', color: 'from-[#9B5DE5] to-[#F15BB5]', shadow: 'shadow-[#9B5DE5]/20' },
  { to: '/crawl', icon: Terminal, label: '抓取控制台', color: 'from-[#00F5D4] to-[#00BBF9]', shadow: 'shadow-[#00F5D4]/20' },
]

interface CoverInfo {
  cover_url: string
  bangumi_id: number
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
              if (c.cover_url) {
                map[c.title] = { cover_url: c.cover_url, bangumi_id: c.bangumi_id, name_cn: c.name_cn, name: c.name }
              }
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
    <div className="space-y-10 animate-in fade-in duration-500 max-w-[1400px] mx-auto">
      {/* Hero Banner */}
      <div className="relative overflow-hidden rounded-[2rem] border border-white/10 bg-black/40 p-8 sm:p-12 shadow-2xl backdrop-blur-xl">
        <div className="absolute inset-0 bg-gradient-to-br from-accent-primary/20 via-transparent to-accent-secondary/20" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-8">
          <div className="space-y-4">
            <h1 className="text-4xl sm:text-5xl md:text-6xl font-black tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-white/70 drop-shadow-sm">
              NicoTracker
            </h1>
            <p className="text-base sm:text-lg text-white/70 font-medium max-w-xl leading-relaxed">
              你的个人番剧资源管理中心。集搜索、下载、追番与同看于一体，尽享纯粹的观影体验。
            </p>
          </div>
          <div className="flex -space-x-4">
             {/* Decorative Elements */}
             <div className="h-20 w-20 rounded-full border border-white/10 bg-gradient-to-tr from-accent-primary to-accent-secondary opacity-80 mix-blend-screen blur-md animate-pulse"></div>
             <div className="h-24 w-24 rounded-full border border-white/10 bg-gradient-to-tr from-accent-cyan to-accent-secondary opacity-60 mix-blend-screen blur-lg animate-pulse delay-150"></div>
          </div>
        </div>
        
        {/* Glow Effects */}
        <div className="absolute -left-20 -top-20 h-64 w-64 rounded-full bg-accent-primary/20 blur-[100px] pointer-events-none" />
        <div className="absolute -right-20 -bottom-20 h-64 w-64 rounded-full bg-accent-secondary/20 blur-[100px] pointer-events-none" />
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {quickLinks.map((link) => (
          <Link 
            key={link.to} 
            to={link.to} 
            className="group relative flex items-center gap-4 rounded-2xl border border-white/5 bg-white/[0.02] p-5 transition-all duration-500 hover:-translate-y-1 hover:border-white/10 hover:bg-white/[0.05] hover:shadow-xl backdrop-blur-md overflow-hidden"
          >
            <div className={cn('relative z-10 rounded-xl p-3 text-white bg-gradient-to-br shadow-lg transition-transform duration-500 group-hover:scale-110 group-hover:rotate-3', link.color, link.shadow)}>
              <link.icon className="h-6 w-6" />
            </div>
            <span className="relative z-10 text-base font-bold text-text-secondary transition-colors group-hover:text-white">{link.label}</span>
            <div className="absolute right-0 top-0 h-full w-1/2 bg-gradient-to-l from-white/5 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
          </Link>
        ))}
      </div>

      {/* Active downloads */}
      {downloads.length > 0 && (
        <section className="space-y-6">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-accent-cyan/20 p-2 border border-accent-cyan/30">
              <Download className="h-5 w-5 text-accent-cyan" />
            </div>
            <h2 className="text-2xl font-bold text-white tracking-wide">下载进行中</h2>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {downloads.map((task) => (
              <div key={task.hash} className="group relative overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-sm backdrop-blur-sm transition-all hover:border-accent-cyan/30 hover:shadow-lg hover:shadow-accent-cyan/10">
                <div className="absolute inset-0 bg-gradient-to-r from-accent-cyan/0 via-accent-cyan/5 to-accent-cyan/0 opacity-0 transition-opacity duration-500 group-hover:opacity-100 translate-x-[-100%] group-hover:translate-x-[100%]" />
                <div className="relative z-10">
                  <div className="flex items-center justify-between mb-4 gap-4">
                    <p className="text-sm font-bold text-white truncate">{task.name}</p>
                    <div className="flex items-center gap-3 shrink-0">
                      {task.speed > 0 && <span className="rounded bg-white/10 px-2 py-1 text-[10px] font-bold text-white/80">{formatBytes(task.speed)}/s</span>}
                      <span className="text-sm font-black text-accent-cyan drop-shadow-sm">{(task.progress * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                  <div className="h-2 rounded-full bg-black/40 overflow-hidden shadow-inner">
                    <div className="h-full rounded-full bg-gradient-to-r from-accent-cyan to-[#00f2fe] transition-all duration-500 relative" style={{ width: `${task.progress * 100}%` }}>
                       <div className="absolute inset-0 bg-white/20 w-full h-full animate-pulse" />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent releases */}
      <section className="space-y-6">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-accent-primary/20 p-2 border border-accent-primary/30">
              <TrendingUp className="h-5 w-5 text-accent-primary" />
            </div>
            <h2 className="text-2xl font-bold text-white tracking-wide">最新发布</h2>
          </div>
          <div className="flex gap-2">
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-text-secondary backdrop-blur-md">
              数据源: SubsPlease RSS
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-text-secondary backdrop-blur-md">
              封面: Bangumi
            </span>
          </div>
        </div>
        
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="relative">
              <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
              <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
            </div>
          </div>
        ) : recentItems.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 gap-5">
            {recentItems.map((item, i) => {
              const info = coverMap[item.title]
              const displayName = getDisplayName(item)
              return (
                <Link
                  to={buildAnimeHref({
                    bangumi_id: info?.bangumi_id || 0,
                    title: displayName,
                    raw_title: item.title,
                    cover_url: info?.cover_url || '',
                  })}
                  key={i}
                  className="group relative"
                >
                  <div className="relative aspect-[3/4] overflow-hidden rounded-2xl border border-white/10 bg-bg-secondary shadow-lg transition-all duration-500 group-hover:-translate-y-2 group-hover:border-white/30 group-hover:shadow-[0_15px_30px_rgba(0,0,0,0.6)]">
                    {info?.cover_url ? (
                      <img src={proxyImageUrl(info.cover_url)} alt={displayName} loading="lazy" className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-black/60 to-bg-secondary">
                        <span className="text-5xl font-black text-white/20">{displayName.charAt(0)}</span>
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black via-black/20 to-transparent opacity-80 transition-opacity duration-300 group-hover:opacity-90" />
                    <div className="absolute bottom-0 left-0 right-0 p-4 transition-transform duration-300 group-hover:-translate-y-1">
                      <p className="text-sm font-bold text-white line-clamp-2 leading-snug drop-shadow-md">{displayName}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="rounded border border-white/20 bg-white/10 px-1.5 py-0.5 text-[10px] font-bold text-white backdrop-blur-sm">{item.source}</span>
                        {item.size && <span className="text-[10px] font-medium text-white/70">{item.size}</span>}
                      </div>
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>
        ) : (
          <div className="rounded-3xl border border-white/5 bg-white/[0.01] py-32 text-center shadow-inner backdrop-blur-sm">
            <Terminal className="mx-auto mb-6 h-16 w-16 text-text-muted opacity-20" />
            <p className="text-xl font-bold text-white tracking-wide">暂无数据</p>
            <p className="mt-3 text-sm font-medium text-text-muted">请前往「抓取控制台」执行数据抓取</p>
          </div>
        )}
      </section>
    </div>
  )
}
