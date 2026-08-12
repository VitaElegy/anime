import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Search,
  Download,
  ExternalLink,
  Loader2,
  Film,
  HardDrive,
  AlertCircle,
  Star,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  searchAnimeNew,
  searchTorrentsNew,
  addDownload,
  proxyImageUrl,
  type SimpleAnimeHit,
  type SimpleTorrentHit,
} from '@/api'

type SearchScope = 'anime' | 'torrent'

const SOURCE_STYLE: Record<string, string> = {
  Mikan: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  AnimeGarden: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  Nyaa: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
  SubsPlease: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  Bangumi: 'bg-sky-500/10 text-sky-300 border-sky-500/20',
}

function SourcePill({ name }: { name: string }) {
  return (
    <span
      className={cn(
        'text-[10px] px-1.5 py-0.5 rounded border font-medium tracking-wide',
        SOURCE_STYLE[name] || 'bg-white/5 text-white/60 border-white/10'
      )}
    >
      {name}
    </span>
  )
}

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [scope, setScope] = useState<SearchScope>(
    (searchParams.get('scope') as SearchScope) === 'torrent' ? 'torrent' : 'anime'
  )

  const [animeResults, setAnimeResults] = useState<SimpleAnimeHit[]>([])
  const [torrentResults, setTorrentResults] = useState<SimpleTorrentHit[]>([])

  const [animeLoading, setAnimeLoading] = useState(false)
  const [torrentLoading, setTorrentLoading] = useState(false)
  const [animeError, setAnimeError] = useState<string | null>(null)
  const [torrentError, setTorrentError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<Set<number>>(new Set())
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)

  const lastKeyRef = useRef('')

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2500)
  }

  /**
   * 同时触发两类搜索，关键词保持原文。
   * 切换「番剧/种子」只影响展示，不再触发重复请求。
   */
  const doSearch = useCallback(async (q: string) => {
    const kw = q.trim()
    if (!kw) return
    if (kw === lastKeyRef.current) return
    lastKeyRef.current = kw

    setAnimeError(null)
    setTorrentError(null)
    setAnimeLoading(true)
    setTorrentLoading(true)
    setAnimeResults([])
    setTorrentResults([])

    // 两边独立并发，互不阻塞
    searchAnimeNew(kw, 12)
      .then((list) => setAnimeResults(list))
      .catch((err) => {
        console.warn('anime search error', err)
        setAnimeError('番剧检索失败，请稍后重试')
      })
      .finally(() => setAnimeLoading(false))

    searchTorrentsNew(kw, 100)
      .then((list) => setTorrentResults(list))
      .catch((err) => {
        console.warn('torrent search error', err)
        setTorrentError('种子检索失败，请检查网络或后端状态')
      })
      .finally(() => setTorrentLoading(false))
  }, [])

  useEffect(() => {
    const q = searchParams.get('q') || ''
    const s = (searchParams.get('scope') as SearchScope) === 'torrent' ? 'torrent' : 'anime'
    if (q) {
      setQuery(q)
      setScope(s)
      doSearch(q)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const kw = query.trim()
    if (!kw) return
    const next = new URLSearchParams()
    next.set('q', kw)
    next.set('scope', scope)
    setSearchParams(next)
  }

  const handleScopeSwitch = (s: SearchScope) => {
    setScope(s)
    if (searchParams.get('q')) {
      const next = new URLSearchParams(searchParams)
      next.set('scope', s)
      setSearchParams(next, { replace: true })
    }
  }

  const handleOpenAnime = (a: SimpleAnimeHit) => {
    // 直接打开 Bangumi 详情页（使用 subject_id）
    const params = new URLSearchParams()
    if (a.title) params.set('title', a.title)
    if (a.titleOriginal) params.set('rawTitle', a.titleOriginal)
    if (a.coverImage) params.set('cover', a.coverImage)
    navigate(`/anime/${a.id}?${params.toString()}`)
  }

  const handleDownload = async (item: SimpleTorrentHit, idx: number) => {
    if (!item.link) {
      showToast('该资源暂无磁力链接', 'err')
      return
    }
    const next = new Set(downloading)
    next.add(idx)
    setDownloading(next)
    try {
      await addDownload({
        magnet: item.link,
        category: '',
        save_path: '',
      })
      showToast('已加入下载队列', 'ok')
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showToast(detail || '添加下载失败', 'err')
    } finally {
      setDownloading((prev) => {
        const s = new Set(prev)
        s.delete(idx)
        return s
      })
    }
  }

  const hasSearched = !!searchParams.get('q')
  const currentError = scope === 'anime' ? animeError : torrentError

  const stats = useMemo(
    () => ({
      anime: animeResults.length,
      torrent: torrentResults.length,
    }),
    [animeResults.length, torrentResults.length]
  )

  return (
    <div className="min-h-screen relative text-white">
      {/* 背景光晕 */}
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-40 -left-40 w-[500px] h-[500px] bg-sky-500/10 rounded-full blur-3xl" />
        <div className="absolute top-1/2 -right-40 w-[500px] h-[500px] bg-purple-500/10 rounded-full blur-3xl" />
      </div>

      <div className="max-w-6xl mx-auto px-6 pb-16">
        {/* ============== 顶部：搜索框 + 模式切换 ============== */}
        <header className={cn('transition-all duration-500', hasSearched ? 'pt-10 pb-6' : 'pt-24 pb-10')}>
          {!hasSearched && (
            <div className="text-center mb-10 space-y-3">
              <h1 className="text-5xl md:text-6xl font-black tracking-tight bg-gradient-to-br from-sky-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
                一搜到底
              </h1>
              <p className="text-white/50 text-lg">中文、日文、罗马音通通可以 · 番剧与种子一次并发</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
            <div className="relative group">
              <div className="absolute inset-0 bg-gradient-to-r from-sky-500 to-purple-500 rounded-2xl blur opacity-20 group-hover:opacity-35 group-focus-within:opacity-50 transition duration-500" />
              <div className="relative flex items-center bg-black/40 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden shadow-2xl focus-within:border-sky-400/60 transition-all">
                <Search className="w-5 h-5 text-white/40 ml-6 shrink-0" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="输入番剧名称，例如「葬送的芙莉莲」"
                  className="flex-1 px-4 py-5 bg-transparent text-lg placeholder-white/30 focus:outline-none"
                  autoFocus
                />
                <button
                  type="submit"
                  disabled={!query.trim() || animeLoading || torrentLoading}
                  className="mr-2 px-7 py-3 bg-white text-black hover:bg-white/90 rounded-xl font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {(animeLoading || torrentLoading) && <Loader2 className="w-4 h-4 animate-spin" />}
                  搜索
                </button>
              </div>
            </div>

            {hasSearched && (
              <div className="flex items-center justify-center gap-2 mt-6">
                <ModeTab
                  active={scope === 'anime'}
                  onClick={() => handleScopeSwitch('anime')}
                  icon={<Film className="w-4 h-4" />}
                  label="番剧"
                  count={stats.anime}
                  loading={animeLoading}
                />
                <ModeTab
                  active={scope === 'torrent'}
                  onClick={() => handleScopeSwitch('torrent')}
                  icon={<HardDrive className="w-4 h-4" />}
                  label="种子"
                  count={stats.torrent}
                  loading={torrentLoading}
                />
              </div>
            )}
          </form>
        </header>

        {/* ============== 主内容 ============== */}
        <main>
          {!hasSearched && <WelcomeHints />}

          {hasSearched && (
            <div className="space-y-6">
              {currentError && (
                <div className="flex items-center gap-2 text-red-400 bg-red-500/5 px-4 py-3 rounded-xl border border-red-500/20">
                  <AlertCircle className="w-5 h-5 shrink-0" />
                  <span>{currentError}</span>
                </div>
              )}

              {scope === 'anime' && (
                <AnimeSection
                  loading={animeLoading}
                  list={animeResults}
                  keyword={query}
                  onOpen={handleOpenAnime}
                  onSwitchToTorrents={() => handleScopeSwitch('torrent')}
                />
              )}

              {scope === 'torrent' && (
                <TorrentSection
                  loading={torrentLoading}
                  list={torrentResults}
                  keyword={query}
                  downloading={downloading}
                  onDownload={handleDownload}
                  onSwitchToAnime={() => handleScopeSwitch('anime')}
                />
              )}
            </div>
          )}
        </main>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-bottom-2">
          <div
            className={cn(
              'px-4 py-2.5 rounded-xl border backdrop-blur-xl text-sm shadow-xl',
              toast.type === 'ok'
                ? 'bg-emerald-500/10 border-emerald-400/30 text-emerald-300'
                : 'bg-red-500/10 border-red-400/30 text-red-300'
            )}
          >
            {toast.msg}
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------
 * Sub-components
 * ---------------------------------------------------------------- */

function ModeTab({
  active,
  onClick,
  icon,
  label,
  count,
  loading,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  count: number
  loading: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all border',
        active
          ? 'bg-white text-black border-white shadow-lg shadow-white/10'
          : 'bg-black/30 text-white/70 border-white/10 hover:border-white/30 hover:text-white'
      )}
    >
      {icon}
      <span>{label}</span>
      <span
        className={cn(
          'ml-1 text-[11px] font-bold px-1.5 py-0.5 rounded',
          active ? 'bg-black/10 text-black' : 'bg-white/5 text-white/50'
        )}
      >
        {loading ? '...' : count}
      </span>
    </button>
  )
}

function AnimeSection({
  loading,
  list,
  keyword,
  onOpen,
  onSwitchToTorrents,
}: {
  loading: boolean
  list: SimpleAnimeHit[]
  keyword: string
  onOpen: (a: SimpleAnimeHit) => void
  onSwitchToTorrents: () => void
}) {
  if (loading && list.length === 0) return <SkeletonList count={4} />

  if (!loading && list.length === 0) {
    return (
      <EmptyState
        title={`没有找到关于「${keyword}」的番剧`}
        hint="也许换个写法，或直接切到「种子」模式？"
        actionLabel="去查种子"
        onAction={onSwitchToTorrents}
      />
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {list.map((a) => (
        <button
          key={`${a.source}-${a.id}`}
          onClick={() => onOpen(a)}
          className="group flex items-stretch text-left bg-black/30 hover:bg-white/5 border border-white/10 hover:border-sky-400/50 rounded-2xl overflow-hidden transition-all duration-300"
        >
          <div className="w-28 shrink-0 overflow-hidden bg-black/60">
            <img
              src={a.coverImage ? proxyImageUrl(a.coverImage) : ''}
              alt={a.title}
              loading="lazy"
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
              onError={(e) => {
                ;(e.currentTarget as HTMLImageElement).style.display = 'none'
              }}
            />
          </div>
          <div className="flex-1 p-4 min-w-0 flex flex-col">
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-bold text-base leading-snug line-clamp-2 group-hover:text-sky-300 transition-colors">
                {a.title}
              </h3>
              <SourcePill name={a.source} />
            </div>
            {a.titleOriginal && a.titleOriginal !== a.title && (
              <p className="text-xs text-white/40 mt-0.5 truncate">{a.titleOriginal}</p>
            )}
            <div className="flex items-center gap-3 mt-1 text-xs text-white/50">
              {a.year && <span>{a.year}</span>}
              {a.score ? (
                <span className="flex items-center gap-1 text-amber-300">
                  <Star className="w-3 h-3 fill-current" />
                  {a.score.toFixed(1)}
                </span>
              ) : null}
            </div>
            <p className="text-xs text-white/50 mt-2 line-clamp-3 leading-relaxed">
              {a.description || '暂无简介'}
            </p>
          </div>
        </button>
      ))}
    </div>
  )
}

function TorrentSection({
  loading,
  list,
  keyword,
  downloading,
  onDownload,
  onSwitchToAnime,
}: {
  loading: boolean
  list: SimpleTorrentHit[]
  keyword: string
  downloading: Set<number>
  onDownload: (item: SimpleTorrentHit, idx: number) => void
  onSwitchToAnime: () => void
}) {
  if (loading && list.length === 0) return <SkeletonList count={6} />

  if (!loading && list.length === 0) {
    return (
      <EmptyState
        title={`没有找到关于「${keyword}」的种子资源`}
        hint="回去先确认一下番剧标题？"
        actionLabel="查找番剧"
        onAction={onSwitchToAnime}
      />
    )
  }

  return (
    <div className="bg-black/30 rounded-2xl border border-white/10 overflow-hidden backdrop-blur-xl">
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-white/10 bg-white/5 text-xs uppercase tracking-wider text-white/50">
              <th className="p-4 font-semibold">资源</th>
              <th className="p-4 font-semibold w-28">大小</th>
              <th className="p-4 font-semibold w-20 text-center">热度</th>
              <th className="p-4 font-semibold w-32">来源</th>
              <th className="p-4 font-semibold w-28 text-center">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-sm">
            {list.map((t, idx) => (
              <tr key={t.info_hash || `${t.source}-${idx}`} className="hover:bg-white/5 transition-colors">
                <td className="p-4">
                  <div className="flex flex-col gap-1.5">
                    <span className="font-medium text-white/90 leading-snug line-clamp-2 break-all">
                      {t.title}
                    </span>
                    <div className="flex items-center gap-2 flex-wrap">
                      {t.fansub && (
                        <span className="text-[11px] px-2 py-0.5 bg-indigo-500/10 text-indigo-300 rounded border border-indigo-500/20">
                          {t.fansub}
                        </span>
                      )}
                      {t.pubDate && (
                        <span className="text-[11px] text-white/40">{t.pubDate.slice(0, 10)}</span>
                      )}
                    </div>
                  </div>
                </td>
                <td className="p-4 text-white/60 font-mono text-xs">{t.size || '-'}</td>
                <td className="p-4 text-center">
                  <span
                    className={cn(
                      'inline-flex items-center justify-center min-w-[2rem] px-2 py-0.5 rounded text-xs font-bold',
                      t.seeders > 50
                        ? 'bg-emerald-500/10 text-emerald-300'
                        : t.seeders > 10
                        ? 'bg-amber-500/10 text-amber-300'
                        : 'bg-white/5 text-white/40'
                    )}
                  >
                    {t.seeders}
                  </span>
                </td>
                <td className="p-4">
                  <SourcePill name={t.source} />
                </td>
                <td className="p-4">
                  <div className="flex items-center justify-center gap-1">
                    <button
                      type="button"
                      onClick={() => onDownload(t, idx)}
                      disabled={downloading.has(idx) || !t.link}
                      className="inline-flex items-center justify-center p-2 bg-white/5 hover:bg-sky-500 text-white/70 hover:text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      title="加入 qBittorrent 下载"
                    >
                      {downloading.has(idx) ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                    </button>
                    {t.link && (
                      <a
                        href={t.link}
                        className="inline-flex items-center justify-center p-2 bg-white/5 hover:bg-white/10 text-white/70 hover:text-white rounded-lg transition-all"
                        title="打开磁力链接"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SkeletonList({ count }: { count: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="h-20 bg-white/5 border border-white/10 rounded-2xl animate-pulse"
        />
      ))}
    </div>
  )
}

function EmptyState({
  title,
  hint,
  actionLabel,
  onAction,
}: {
  title: string
  hint: string
  actionLabel: string
  onAction: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-full bg-white/5 border border-white/10 flex items-center justify-center mb-4">
        <Search className="w-6 h-6 text-white/30" />
      </div>
      <p className="text-white/80 font-medium">{title}</p>
      <p className="text-white/40 text-sm mt-1">{hint}</p>
      <button
        type="button"
        onClick={onAction}
        className="mt-5 px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 border border-white/10 text-sm transition-colors"
      >
        {actionLabel}
      </button>
    </div>
  )
}

function WelcomeHints() {
  return (
    <div className="grid md:grid-cols-2 gap-5 max-w-3xl mx-auto">
      <div className="bg-black/30 border border-white/10 rounded-2xl p-5 backdrop-blur-xl">
        <div className="flex items-center gap-2 mb-2">
          <Film className="w-5 h-5 text-sky-300" />
          <h3 className="font-semibold">番剧模式</h3>
        </div>
        <p className="text-sm text-white/60 leading-relaxed">
          基于 Bangumi 中文百科实时检索，支持"葬送的芙莉莲""孤独摇滚"这类中文原名。点击卡片直接进入详情页查看简介、评分、制作团队与播放入口。
        </p>
      </div>
      <div className="bg-black/30 border border-white/10 rounded-2xl p-5 backdrop-blur-xl">
        <div className="flex items-center gap-2 mb-2">
          <HardDrive className="w-5 h-5 text-purple-300" />
          <h3 className="font-semibold">种子模式</h3>
        </div>
        <p className="text-sm text-white/60 leading-relaxed">
          同一关键词聚合 Mikan、动漫花园、Nyaa、SubsPlease 多源资源，中文字幕组自动加权。点击下载按钮即可推送到 qBittorrent。
        </p>
      </div>
    </div>
  )
}
