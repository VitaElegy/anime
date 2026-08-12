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

  useEffect(() => {
    // Deferred so the effect body stays side-effect-free (react-hooks/set-state-in-effect).
    void Promise.resolve().then(() => { void load() })
  }, [])

  const today = new Date().getDay()
  const todayIdx = today === 0 ? 6 : today - 1

  const week = calendarData?.week || {}
  const timeline = calendarData?.timeline || []

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="relative">
          <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
          <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/5 bg-white/[0.02] p-6 shadow-lg backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-black tracking-tight text-white drop-shadow-md">新番日历</h1>
          <span className="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-3 py-1 text-xs font-medium text-accent-secondary backdrop-blur-sm">SubsPlease RSS</span>
          <span className="rounded-full border border-accent-cyan/20 bg-accent-cyan/10 px-3 py-1 text-xs font-medium text-accent-cyan backdrop-blur-sm">Bangumi 封面</span>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => load(true)} className="group flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white transition-all hover:bg-white/10 hover:shadow-lg backdrop-blur-md">
            <RefreshCw className="h-4 w-4 transition-transform duration-500 group-hover:rotate-180" /> 刷新
          </button>
          <div className="flex overflow-hidden rounded-xl border border-white/10 bg-white/5 backdrop-blur-md">
            <button onClick={() => setViewMode('week')} className={cn('flex items-center gap-2 px-4 py-2 text-sm font-medium transition-all', viewMode === 'week' ? 'bg-accent-primary text-white shadow-[0_0_15px_rgba(233,69,96,0.5)]' : 'text-text-muted hover:bg-white/10 hover:text-white')}>
              <CalendarDays className="h-4 w-4" /> 周历
            </button>
            <button onClick={() => setViewMode('timeline')} className={cn('flex items-center gap-2 px-4 py-2 text-sm font-medium transition-all', viewMode === 'timeline' ? 'bg-accent-primary text-white shadow-[0_0_15px_rgba(233,69,96,0.5)]' : 'text-text-muted hover:bg-white/10 hover:text-white')}>
              <List className="h-4 w-4" /> 时间线
            </button>
          </div>
        </div>
      </div>

      {viewMode === 'week' ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-7 lg:gap-3">
          {WEEKDAYS.map((dayName, i) => {
            const entries = week[dayName] || []
            const isToday = i === todayIdx
            return (
              <div key={i} className={cn("space-y-3 rounded-2xl border p-3 transition-colors duration-300", isToday ? "border-accent-primary/30 bg-accent-primary/5 shadow-[0_0_30px_rgba(233,69,96,0.1)] backdrop-blur-sm" : "border-white/5 bg-white/[0.01]")}>
                <div className={cn('flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-bold shadow-sm backdrop-blur-md transition-all', isToday ? 'bg-gradient-to-r from-accent-primary to-accent-secondary text-white shadow-[0_0_15px_rgba(233,69,96,0.4)]' : 'bg-white/5 text-text-secondary')}>
                  {dayName}{isToday && <span className="rounded-full bg-white/20 px-2 py-0.5 text-[10px] uppercase tracking-wider text-white">今日</span>}
                </div>
                <div className="space-y-3 min-h-[200px]">
                  {entries.length > 0 ? entries.map((entry, j) => (
                    <Link
                      key={j}
                      to={buildAnimeHref(entry)}
                      className="group block overflow-hidden rounded-xl border border-white/5 bg-white/[0.02] shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-white/20 hover:bg-white/5 hover:shadow-xl hover:shadow-white/5"
                      title={entry.raw_title || entry.title}
                    >
                      {entry.cover_url ? (
                        <div className="relative aspect-[3/2] overflow-hidden bg-bg-secondary">
                          <img
                            src={proxyImageUrl(entry.cover_url)}
                            alt={entry.title}
                            loading="lazy"
                            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-110"
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-bg-primary via-bg-primary/40 to-transparent opacity-80" />
                          <p className="absolute bottom-2 left-2 right-2 text-xs font-semibold text-white line-clamp-2 leading-tight drop-shadow-md">{entry.title}</p>
                        </div>
                      ) : (
                        <div className="p-3">
                          <p className="text-xs font-semibold text-white truncate leading-snug">{entry.title}</p>
                          {(entry.time || entry.size) && <p className="text-text-muted text-[10px] mt-1 font-medium tracking-wide truncate">{entry.time || entry.size}</p>}
                        </div>
                      )}
                    </Link>
                  )) : (
                    <div className="flex h-24 items-center justify-center rounded-xl border border-dashed border-white/10 bg-white/[0.01]">
                      <span className="text-xs font-medium text-text-muted/50">暂无更新</span>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mx-auto max-w-4xl space-y-2">
          {timeline.length === 0 ? (
            <div className="rounded-2xl border border-white/5 bg-white/[0.02] py-20 text-center backdrop-blur-sm">
              <p className="text-lg font-medium text-text-muted">暂无数据</p>
            </div>
          ) : timeline.map((item, i) => {
            const showDate = i === 0 || timeline[i - 1].date.slice(0, 10) !== item.date.slice(0, 10)
            return (
              <div key={i} className="animate-in slide-in-from-bottom-2 fade-in" style={{ animationDelay: `${i * 30}ms`, animationFillMode: 'both' }}>
                {showDate && (
                  <div className="flex items-center gap-4 py-6">
                    <div className="h-px flex-1 bg-gradient-to-r from-transparent to-accent-primary/30" />
                    <span className="rounded-full border border-accent-primary/20 bg-accent-primary/10 px-4 py-1.5 text-sm font-bold text-accent-primary backdrop-blur-sm shadow-[0_0_15px_rgba(233,69,96,0.15)]">{item.date.slice(0, 10) || '未知日期'}</span>
                    <div className="h-px flex-1 bg-gradient-to-l from-transparent to-accent-primary/30" />
                  </div>
                )}
                <Link to={buildAnimeHref(item)} className="group flex items-center gap-4 rounded-2xl border border-white/5 bg-white/[0.02] p-3 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-white/10 hover:bg-white/[0.04] hover:shadow-lg backdrop-blur-sm">
                  {item.cover_url ? (
                    <div className="relative h-16 w-12 shrink-0 overflow-hidden rounded-xl border border-white/10">
                      <img src={proxyImageUrl(item.cover_url)} alt={item.title} loading="lazy" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-110" />
                    </div>
                  ) : (
                    <div className="flex h-16 w-12 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/5 shadow-inner">
                      <span className="text-lg font-black text-white/30">{item.title.charAt(0)}</span>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-base font-bold text-white truncate transition-colors group-hover:text-accent-primary">{item.title}</p>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-medium text-text-secondary">{item.source}</span>
                      <span className="text-xs font-medium text-text-muted">{item.size}</span>
                    </div>
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
