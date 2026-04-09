import { useState, useEffect } from 'react'
import { CalendarDays, List, Loader2, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { searchSubsPlease, getWeeklySchedule, batchResolveCovers, proxyImageUrl } from '@/api'
import type { TorrentItem } from '@/types'

type ViewMode = 'week' | 'timeline'
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function getDayOfWeek(dateStr: string): number {
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return -1
    const day = d.getDay()
    return day === 0 ? 6 : day - 1
  } catch { return -1 }
}

interface CoverInfo { cover_url: string; name_cn: string; name: string; cleaned_title?: string }

// Clean title for dedup — extract anime name from torrent title
function cleanTitle(t: string): string {
  let c = t.replace(/\[.*?\]/g, '').replace(/\(.*?\)/g, '')
  c = c.replace(/\.\w{3}$/, '')
  c = c.replace(/\s*[-–]\s*\d+.*$/, '')
  c = c.replace(/\s+S\d+\s*$/i, '')
  return c.replace(/\s+/g, ' ').trim()
}

export default function CalendarPage() {
  const [items, setItems] = useState<TorrentItem[]>([])
  const [scheduleData, setScheduleData] = useState<Record<string, { title: string; page: string; day: string }[]>>({})
  const [coverMap, setCoverMap] = useState<Record<string, CoverInfo>>({})
  const [loading, setLoading] = useState(true)
  const [viewMode, setViewMode] = useState<ViewMode>('week')

  const load = async () => {
    setLoading(true)
    try {
      const [rss, sched] = await Promise.allSettled([
        searchSubsPlease('', 1080),
        getWeeklySchedule(),
      ])
      let rssItems: TorrentItem[] = []
      if (rss.status === 'fulfilled') { rssItems = rss.value.items; setItems(rssItems) }
      if (sched.status === 'fulfilled') setScheduleData(sched.value)

      // Deduplicate
      const seen = new Set<string>()
      const uniqueTitles: string[] = []
      for (const item of rssItems) {
        const name = cleanTitle(item.title)
        if (!seen.has(name)) {
          seen.add(name)
          uniqueTitles.push(item.title)
        }
      }

      // Resolve ALL unique titles in batches of 25
      const allCovers: Record<string, CoverInfo> = {}
      for (let i = 0; i < uniqueTitles.length; i += 25) {
        try {
          const batch = uniqueTitles.slice(i, i + 25)
          const results = await batchResolveCovers(batch)
          for (const c of results) {
            allCovers[c.title] = {
              cover_url: c.cover_url || '',
              name_cn: c.name_cn || '',
              name: c.name || '',
              cleaned_title: (c as Record<string, unknown>).cleaned_title as string || '',
            }
          }
        } catch { /* continue with next batch */ }
      }

      // Propagate covers to all RSS items sharing the same cleaned name
      for (const item of rssItems) {
        if (allCovers[item.title]) continue
        const name = cleanTitle(item.title)
        for (const [resolved, info] of Object.entries(allCovers)) {
          if (cleanTitle(resolved) === name) {
            allCovers[item.title] = info
            break
          }
        }
      }

      setCoverMap(allCovers)
    } catch { /* silent */ } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const today = new Date().getDay()
  const todayIdx = today === 0 ? 6 : today - 1

  const rssGrouped: Record<number, TorrentItem[]> = {}
  for (let i = 0; i < 7; i++) rssGrouped[i] = []
  for (const item of items) {
    const day = getDayOfWeek(item.date)
    if (day >= 0 && day < 7) rssGrouped[day].push(item)
  }

  const getDisplay = (title: string): { name: string; cover?: string } => {
    const info = coverMap[title]
    return {
      name: info?.name_cn || info?.name || cleanTitle(title),
      cover: info?.cover_url,
    }
  }

  interface CalEntry { title: string; rawTitle?: string; sub?: string; coverUrl?: string }

  const buildEntries = (dayIdx: number, dayName: string): CalEntry[] => {
    const schedShows = scheduleData[dayName] || []
    const rssItems = rssGrouped[dayIdx] || []
    const seen = new Set<string>()
    const entries: CalEntry[] = []

    for (const s of schedShows) {
      if (!seen.has(s.title)) { seen.add(s.title); entries.push({ title: s.title }) }
    }
    for (const r of rssItems) {
      const { name, cover } = getDisplay(r.title)
      if (!seen.has(name)) {
        seen.add(name)
        entries.push({ title: name, rawTitle: r.title, sub: r.size, coverUrl: cover })
      }
    }
    return entries
  }

  const timeline = [...items].sort((a, b) => b.date.localeCompare(a.date))

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-accent-primary" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-xl font-bold">新番日历</h1>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-secondary/10 text-accent-secondary font-medium">SubsPlease RSS</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan font-medium">Bangumi 封面</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className="flex items-center gap-1.5 rounded-lg bg-bg-card border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors">
            <RefreshCw className="h-3.5 w-3.5" /> 刷新
          </button>
          <div className="flex rounded-lg border border-border overflow-hidden">
            <button onClick={() => setViewMode('week')} className={cn('flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors', viewMode === 'week' ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-muted hover:text-text-secondary')}>
              <CalendarDays className="h-3.5 w-3.5" /> 周历
            </button>
            <button onClick={() => setViewMode('timeline')} className={cn('flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors', viewMode === 'timeline' ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-muted hover:text-text-secondary')}>
              <List className="h-3.5 w-3.5" /> 时间线
            </button>
          </div>
        </div>
      </div>

      {viewMode === 'week' ? (
        <div className="grid grid-cols-7 gap-3">
          {WEEKDAYS.map((dayName, i) => {
            const entries = buildEntries(i, dayName)
            return (
              <div key={i} className="space-y-2">
                <div className={cn('rounded-lg py-2 text-center text-xs font-semibold', i === todayIdx ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-secondary border border-border')}>
                  {dayName}{i === todayIdx && <span className="ml-1 text-[10px] opacity-80">今日</span>}
                </div>
                <div className="space-y-2 min-h-[200px]">
                  {entries.length > 0 ? entries.map((entry, j) => (
                    <div key={j} className="rounded-lg bg-bg-card border border-border overflow-hidden card-hover cursor-default" title={entry.rawTitle || entry.title}>
                      {entry.coverUrl ? (
                        <div className="relative aspect-[3/2] overflow-hidden bg-bg-secondary">
                          <img
                            src={proxyImageUrl(entry.coverUrl)}
                            alt={entry.title}
                            loading="lazy"
                            className="w-full h-full object-cover"
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent" />
                          <p className="absolute bottom-1 left-1.5 right-1 text-[10px] font-medium text-white line-clamp-2 leading-tight">{entry.title}</p>
                        </div>
                      ) : (
                        <div className="p-2">
                          <p className="text-xs font-medium truncate leading-snug">{entry.title}</p>
                          {entry.sub && <p className="text-text-muted text-[10px] mt-0.5 truncate">{entry.sub}</p>}
                        </div>
                      )}
                    </div>
                  )) : (
                    <div className="flex items-center justify-center h-20 text-text-muted text-[10px]">暂无</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="max-w-3xl space-y-1">
          {timeline.length === 0 ? (
            <p className="text-center text-text-muted py-10">暂无数据</p>
          ) : timeline.map((item, i) => {
            const showDate = i === 0 || timeline[i - 1].date.slice(0, 10) !== item.date.slice(0, 10)
            const { name, cover } = getDisplay(item.title)
            return (
              <div key={i}>
                {showDate && (
                  <div className="flex items-center gap-3 py-3">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-xs font-medium text-accent-primary">{item.date.slice(0, 10) || '未知日期'}</span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                )}
                <div className="flex items-center gap-3 rounded-lg bg-bg-card border border-border p-2 card-hover">
                  {cover ? (
                    <img src={proxyImageUrl(cover)} alt={name} loading="lazy" className="h-12 w-9 rounded object-cover shrink-0 bg-bg-secondary" />
                  ) : (
                    <div className="h-12 w-9 rounded bg-bg-secondary flex items-center justify-center shrink-0">
                      <span className="text-xs text-border font-bold">{name.charAt(0)}</span>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{name}</p>
                    <p className="text-[10px] text-text-muted mt-0.5">{item.source} · {item.size}</p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
