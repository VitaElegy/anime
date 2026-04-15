import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { CalendarDays, List, Loader2, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getCalendarOverview, proxyImageUrl } from '@/api'
import type { CalendarOverview } from '@/api'
import { buildAnimeHref } from '@/lib/animeLinks'

type ViewMode = 'week' | 'timeline'
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default function CalendarPage() {
  const [calendarData, setCalendarData] = useState<CalendarOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [viewMode, setViewMode] = useState<ViewMode>('week')

  const load = async (forceRefresh = false) => {
    setLoading(true)
    try {
      const data = await getCalendarOverview(forceRefresh)
      setCalendarData(data)
    } catch { /* silent */ } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const today = new Date().getDay()
  const todayIdx = today === 0 ? 6 : today - 1

  const week = calendarData?.week || {}
  const timeline = calendarData?.timeline || []

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
          <button onClick={() => load(true)} className="flex items-center gap-1.5 rounded-lg bg-bg-card border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors">
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
            const entries = week[dayName] || []
            return (
              <div key={i} className="space-y-2">
                <div className={cn('rounded-lg py-2 text-center text-xs font-semibold', i === todayIdx ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-secondary border border-border')}>
                  {dayName}{i === todayIdx && <span className="ml-1 text-[10px] opacity-80">今日</span>}
                </div>
                <div className="space-y-2 min-h-[200px]">
                  {entries.length > 0 ? entries.map((entry, j) => (
                    <Link
                      key={j}
                      to={buildAnimeHref(entry)}
                      className="block rounded-lg bg-bg-card border border-border overflow-hidden card-hover cursor-pointer"
                      title={entry.raw_title || entry.title}
                    >
                      {entry.cover_url ? (
                        <div className="relative aspect-[3/2] overflow-hidden bg-bg-secondary">
                          <img
                            src={proxyImageUrl(entry.cover_url)}
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
                          {(entry.time || entry.size) && <p className="text-text-muted text-[10px] mt-0.5 truncate">{entry.time || entry.size}</p>}
                        </div>
                      )}
                    </Link>
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
            return (
              <div key={i}>
                {showDate && (
                  <div className="flex items-center gap-3 py-3">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-xs font-medium text-accent-primary">{item.date.slice(0, 10) || '未知日期'}</span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                )}
                <Link to={buildAnimeHref(item)} className="flex items-center gap-3 rounded-lg bg-bg-card border border-border p-2 card-hover">
                  {item.cover_url ? (
                    <img src={proxyImageUrl(item.cover_url)} alt={item.title} loading="lazy" className="h-12 w-9 rounded object-cover shrink-0 bg-bg-secondary" />
                  ) : (
                    <div className="h-12 w-9 rounded bg-bg-secondary flex items-center justify-center shrink-0">
                      <span className="text-xs text-border font-bold">{item.title.charAt(0)}</span>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{item.title}</p>
                    <p className="text-[10px] text-text-muted mt-0.5">{item.source} · {item.size}</p>
                  </div>
                </Link>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
