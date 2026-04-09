import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Download, ExternalLink, Loader2, CheckCircle2, XCircle, Star, Globe, Zap, Filter, ArrowUpDown, ArrowDown, ArrowUp, Heart } from 'lucide-react'
import { cn } from '@/lib/utils'
import { onCoverError } from '@/lib/utils'
import { searchNyaa, searchSubsPlease, searchDmhy, searchMikan, searchAnimeTosho, searchAnimeGarden, searchComicat, addDownload, anilistSearch, proxyImageUrl, batchResolveCovers, addFavorite, removeFavorite, getFavorites } from '@/api'
import type { TorrentItem, SearchResult } from '@/types'
import type { AniListAnime } from '@/api'

type SearchMode = 'anilist' | 'torrent'
type SortKey = 'default' | 'seeders' | 'size' | 'date'
type SortDir = 'desc' | 'asc'

const SOURCE_CONFIG: Record<string, { label: string; cls: string }> = {
  nyaa: { label: 'Nyaa', cls: 'bg-accent-cyan/10 text-accent-cyan' },
  subsplease: { label: 'SubsPlease', cls: 'bg-accent-secondary/10 text-accent-secondary' },
  dmhy: { label: '动漫花园', cls: 'bg-accent-primary/10 text-accent-primary' },
  mikan: { label: '蜜柑计划', cls: 'bg-accent-gold/10 text-accent-gold' },
  animetosho: { label: 'AnimeTosho', cls: 'bg-success/10 text-success' },
  animegarden: { label: 'AnimeGarden', cls: 'bg-purple-500/10 text-purple-400' },
  comicat: { label: '漫猫', cls: 'bg-pink-500/10 text-pink-400' },
}

function parseSizeToBytes(size: string): number {
  if (!size) return 0
  const match = size.match(/([\d.]+)\s*(GiB|GB|MiB|MB|KiB|KB|TiB|TB)/i)
  if (!match) return 0
  const val = parseFloat(match[1])
  const unit = match[2].toLowerCase()
  if (unit.startsWith('t')) return val * 1024 * 1024 * 1024 * 1024
  if (unit.startsWith('g')) return val * 1024 * 1024 * 1024
  if (unit.startsWith('m')) return val * 1024 * 1024
  return val * 1024
}

interface CoverInfo { cover_url: string; name_cn: string }

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [mode, setMode] = useState<SearchMode>('anilist')
  const [torrentResults, setTorrentResults] = useState<TorrentItem[]>([])
  const [anilistResults, setAnilistResults] = useState<AniListAnime[]>([])
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState<Set<number>>(new Set())
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)
  const lastSearchedQ = useRef('')
  const searchVersionRef = useRef(0)

  // Filter & sort state
  const [sourceFilter, setSourceFilter] = useState<Set<string>>(new Set())
  const [sortKey, setSortKey] = useState<SortKey>('default')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // Cover map for torrent results
  const [coverMap, setCoverMap] = useState<Record<string, CoverInfo>>({})

  // Favorites tracking
  const [favSet, setFavSet] = useState<Set<number>>(new Set())

  // Load favorites on mount
  useEffect(() => {
    getFavorites().then(favs => {
      setFavSet(new Set((favs as { bangumi_id: number }[]).map(f => f.bangumi_id)))
    }).catch(() => {})
  }, [])

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2500)
  }

  const doSearch = useCallback(async (q: string, m: SearchMode) => {
    if (!q.trim()) return
    const version = ++searchVersionRef.current
    setLoading(true)
    setTorrentResults([])
    setAnilistResults([])
    setCoverMap({})
    setSourceFilter(new Set())
    setSortKey('default')
    try {
      if (m === 'anilist') {
        const result = await anilistSearch(q, 1, 24)
        if (searchVersionRef.current === version) setAnilistResults(result.items)
      } else {
        const [nyaa, sp, dmhyR, mikanR, toshoR, gardenR, comicatR] = await Promise.allSettled([
          searchNyaa(q), searchSubsPlease(q), searchDmhy(q), searchMikan(q), searchAnimeTosho(q), searchAnimeGarden(q), searchComicat(q)
        ])
        if (searchVersionRef.current !== version) return
        const items: TorrentItem[] = []
        if (nyaa.status === 'fulfilled') items.push(...nyaa.value.items)
        if (sp.status === 'fulfilled') items.push(...sp.value.items)
        if (dmhyR.status === 'fulfilled') items.push(...dmhyR.value.items)
        if (mikanR.status === 'fulfilled') items.push(...mikanR.value.items)
        if (toshoR.status === 'fulfilled') items.push(...toshoR.value.items)
        if (gardenR.status === 'fulfilled') items.push(...gardenR.value.items)
        if (comicatR.status === 'fulfilled') items.push(...comicatR.value.items)
        setTorrentResults(items)

        // Resolve covers in background (best effort, deduplicated)
        if (items.length > 0) {
          const uniqueTitles = [...new Set(items.map(i => i.title))].slice(0, 30)
          try {
            const covers = await batchResolveCovers(uniqueTitles)
            if (searchVersionRef.current === version) {
              const map: Record<string, CoverInfo> = {}
              for (const c of covers) {
                if (c.cover_url || c.name_cn) {
                  map[c.title] = { cover_url: c.cover_url || '', name_cn: c.name_cn || '' }
                }
              }
              setCoverMap(map)
            }
          } catch { /* best effort */ }
        }
      }
    } catch { /* silent */ } finally {
      if (searchVersionRef.current === version) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const q = searchParams.get('q')
    if (q && q !== lastSearchedQ.current) {
      lastSearchedQ.current = q
      setQuery(q)
      doSearch(q, mode)
    }
  }, [searchParams, mode, doSearch])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      lastSearchedQ.current = query.trim()
      setSearchParams({ q: query.trim() })
      doSearch(query.trim(), mode)
    }
  }

  const handleModeSwitch = (m: SearchMode) => {
    setMode(m)
    if (query.trim()) doSearch(query.trim(), m)
  }

  const handleDownload = async (item: TorrentItem, index: number) => {
    setDownloading((prev) => new Set(prev).add(index))
    try {
      const res = await addDownload({ magnet: item.magnet, torrent_url: item.torrent_url })
      if (res.status === 'ok') {
        showToast('已添加到下载队列', 'ok')
      } else {
        showToast(`添加下载异常: ${res.detail || '未知'}`, 'err')
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err as Error)?.message
        || '未知错误'
      console.error('Download failed:', err)
      showToast(`添加下载失败: ${detail}`, 'err')
    } finally {
      setDownloading((prev) => { const n = new Set(prev); n.delete(index); return n })
    }
  }

  const handleAnilistClick = (anime: AniListAnime) => {
    const searchTerm = anime.title_romaji || anime.title_english || anime.title_preferred
    setQuery(searchTerm)
    setMode('torrent')
    lastSearchedQ.current = searchTerm
    setSearchParams({ q: searchTerm })
    doSearch(searchTerm, 'torrent')
  }

  const toggleFavorite = async (anime: AniListAnime, e: React.MouseEvent) => {
    e.stopPropagation()
    const bangumiId = anime.id // AniList ID as proxy (will be matched via search)
    try {
      if (favSet.has(bangumiId)) {
        await removeFavorite(bangumiId)
        setFavSet(prev => { const n = new Set(prev); n.delete(bangumiId); return n })
        showToast('已取消收藏', 'ok')
      } else {
        await addFavorite({
          bangumi_id: bangumiId,
          name_cn: anime.title_native || anime.title_preferred || '',
          name: anime.title_romaji || anime.title_english || '',
          cover_url: anime.cover_large || anime.cover_medium || '',
          score: anime.score || 0,
        })
        setFavSet(prev => new Set(prev).add(bangumiId))
        showToast('已收藏', 'ok')
      }
    } catch {
      showToast('操作失败', 'err')
    }
  }

  const getAnilistTitle = (a: AniListAnime): string => {
    return a.title_native || a.title_preferred || a.title_romaji || a.title_english || ''
  }

  // Source counts for filter chips
  const sourceCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of torrentResults) {
      counts[item.source] = (counts[item.source] || 0) + 1
    }
    return counts
  }, [torrentResults])

  // Filtered + sorted results
  const filteredResults = useMemo(() => {
    let items = torrentResults
    if (sourceFilter.size > 0) {
      items = items.filter(i => sourceFilter.has(i.source))
    }
    if (sortKey !== 'default') {
      items = [...items].sort((a, b) => {
        let diff = 0
        if (sortKey === 'seeders') diff = (a.seeders || 0) - (b.seeders || 0)
        else if (sortKey === 'size') diff = parseSizeToBytes(a.size) - parseSizeToBytes(b.size)
        else if (sortKey === 'date') diff = a.date.localeCompare(b.date)
        return sortDir === 'desc' ? -diff : diff
      })
    }
    return items
  }, [torrentResults, sourceFilter, sortKey, sortDir])

  const toggleSource = (src: string) => {
    setSourceFilter(prev => {
      const next = new Set(prev)
      if (next.has(src)) next.delete(src)
      else next.add(src)
      return next
    })
  }

  const cycleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(prev => prev === 'desc' ? 'asc' : 'desc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  return (
    <div className="max-w-5xl space-y-6">
      {/* Search bar */}
      <form onSubmit={handleSubmit} className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={mode === 'anilist' ? '搜索番剧（支持中文、日文、英文）...' : '搜索种子资源...'}
            className={cn('w-full rounded-xl border border-border bg-bg-card py-3 pl-10 pr-4 text-sm',
              'text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary/50')} />
        </div>
        <button type="submit" className="rounded-xl bg-accent-primary px-6 py-3 text-sm font-medium text-white hover:bg-accent-primary/90 transition-colors">
          搜索
        </button>
      </form>

      {/* Mode switch */}
      <div className="flex items-center gap-4 border-b border-border pb-2">
        <div className="flex rounded-lg border border-border overflow-hidden">
          <button onClick={() => handleModeSwitch('anilist')}
            className={cn('flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors',
              mode === 'anilist' ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-muted hover:text-text-secondary')}>
            <Globe className="h-3.5 w-3.5" /> AniList 番剧搜索
          </button>
          <button onClick={() => handleModeSwitch('torrent')}
            className={cn('flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors',
              mode === 'torrent' ? 'bg-accent-primary text-white' : 'bg-bg-card text-text-muted hover:text-text-secondary')}>
            <Zap className="h-3.5 w-3.5" /> 种子搜索 (7源聚合)
          </button>
        </div>
        {mode === 'anilist' && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent-secondary/10 text-accent-secondary font-medium">AniList GraphQL · 原生中文搜索</span>
        )}
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
        </div>
      ) : mode === 'anilist' ? (
        /* ===== AniList Results — Poster Grid ===== */
        anilistResults.length > 0 ? (
          <div>
            <p className="text-xs text-text-muted mb-3">点击番剧卡片跳转到种子搜索，点击 ❤ 收藏</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
              {anilistResults.map((anime) => (
                <div key={anime.id} className="group cursor-pointer" onClick={() => handleAnilistClick(anime)}>
                  <div className="poster-card card-hover border border-border relative bg-bg-card">
                    <img src={proxyImageUrl(anime.cover_large || anime.cover_medium)} alt={getAnilistTitle(anime)}
                      loading="lazy" className="w-full h-full object-cover" onError={onCoverError} />
                    {/* Favorite button */}
                    <button
                      onClick={(e) => toggleFavorite(anime, e)}
                      className={cn('absolute top-1.5 left-1.5 rounded-full p-1 backdrop-blur-sm transition-all z-10',
                        favSet.has(anime.id)
                          ? 'bg-pink-500/80 text-white'
                          : 'bg-black/40 text-white/60 opacity-0 group-hover:opacity-100 hover:bg-pink-500/60 hover:text-white'
                      )}
                      title={favSet.has(anime.id) ? '取消收藏' : '收藏'}
                    >
                      <Heart className={cn('h-3 w-3', favSet.has(anime.id) && 'fill-current')} />
                    </button>
                    {anime.score > 0 && (
                      <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-accent-gold backdrop-blur-sm">
                        <Star className="h-2.5 w-2.5 fill-accent-gold" />{anime.score.toFixed(1)}
                      </div>
                    )}
                    {anime.format && (
                      <div className="absolute top-7 left-1.5 rounded-md bg-accent-primary/80 px-1.5 py-0.5 text-[9px] font-medium text-white backdrop-blur-sm">
                        {anime.format}
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent" />
                    <div className="absolute bottom-0 left-0 right-0 p-2">
                      <p className="text-[11px] font-medium text-white line-clamp-2 leading-tight">{getAnilistTitle(anime)}</p>
                      {anime.title_romaji && anime.title_native && (
                        <p className="text-[9px] text-white/50 mt-0.5 truncate">{anime.title_romaji}</p>
                      )}
                      <div className="flex items-center gap-1.5 mt-1 text-[9px] text-white/40">
                        {anime.season_year > 0 && <span>{anime.season_year}</span>}
                        {anime.episodes > 0 && <span>{anime.episodes}话</span>}
                        {anime.genres.length > 0 && <span>{anime.genres[0]}</span>}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : query ? (
          <div className="text-center py-20 text-text-muted">
            <Search className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>没有找到相关番剧</p>
          </div>
        ) : null
      ) : (
        /* ===== Torrent Results ===== */
        torrentResults.length > 0 ? (
          <div className="space-y-4">
            {/* Filter toolbar */}
            <div className="space-y-3">
              {/* Source filter chips */}
              <div className="flex items-center gap-2 flex-wrap">
                <Filter className="h-3.5 w-3.5 text-text-muted shrink-0" />
                <button onClick={() => setSourceFilter(new Set())}
                  className={cn('rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors border',
                    sourceFilter.size === 0 ? 'border-accent-primary bg-accent-primary/10 text-accent-primary' : 'border-border text-text-muted hover:text-text-secondary')}>
                  全部 ({torrentResults.length})
                </button>
                {Object.entries(sourceCounts).map(([src, count]) => {
                  const cfg = SOURCE_CONFIG[src] || { label: src, cls: 'bg-bg-card text-text-muted' }
                  const active = sourceFilter.has(src)
                  return (
                    <button key={src} onClick={() => toggleSource(src)}
                      className={cn('rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors border',
                        active ? `border-transparent ${cfg.cls}` : 'border-border text-text-muted hover:text-text-secondary')}>
                      {cfg.label} ({count})
                    </button>
                  )
                })}
              </div>

              {/* Sort buttons */}
              <div className="flex items-center gap-2">
                <ArrowUpDown className="h-3.5 w-3.5 text-text-muted shrink-0" />
                {([['default', '默认'], ['seeders', '做种数'], ['size', '大小'], ['date', '日期']] as const).map(([key, label]) => (
                  <button key={key} onClick={() => cycleSort(key)}
                    className={cn('flex items-center gap-1 rounded-lg px-2.5 py-1 text-[11px] font-medium transition-colors',
                      sortKey === key ? 'bg-accent-primary/10 text-accent-primary' : 'text-text-muted hover:text-text-secondary')}>
                    {label}
                    {sortKey === key && key !== 'default' && (sortDir === 'desc' ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
                  </button>
                ))}
                <span className="text-[10px] text-text-muted ml-auto">
                  显示 {filteredResults.length} / {torrentResults.length} 条
                </span>
              </div>
            </div>

            {/* Results list */}
            <div className="space-y-2">
              {filteredResults.map((item, i) => {
                const cover = coverMap[item.title]
                const cfg = SOURCE_CONFIG[item.source] || { label: item.source, cls: 'bg-bg-card text-text-muted' }
                return (
                  <div key={i} className="group flex items-start gap-3 rounded-xl bg-bg-card border border-border p-3 card-hover">
                    {/* Thumbnail */}
                    {cover?.cover_url ? (
                      <img src={proxyImageUrl(cover.cover_url)} alt="" loading="lazy"
                        className="h-16 w-12 rounded-lg object-cover shrink-0 bg-bg-secondary"
                        onError={onCoverError} />
                    ) : (
                      <div className="h-16 w-12 rounded-lg bg-bg-secondary flex items-center justify-center shrink-0">
                        <span className="text-[10px] text-border font-bold">{(cover?.name_cn || item.title).charAt(0)}</span>
                      </div>
                    )}

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium leading-snug mb-1 line-clamp-2">
                        {cover?.name_cn && <span className="text-accent-primary mr-1.5">{cover.name_cn}</span>}
                        <span className={cover?.name_cn ? 'text-text-secondary text-xs' : ''}>{item.title}</span>
                      </p>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
                        <span className={cn('rounded px-1.5 py-0.5 font-medium', cfg.cls)}>{cfg.label}</span>
                        {item.size && <span>{item.size}</span>}
                        {item.seeders > 0 && <span className="text-success">S:{item.seeders}</span>}
                        {item.leechers > 0 && <span className="text-danger">L:{item.leechers}</span>}
                        {item.date && <span>{item.date}</span>}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 gap-1">
                      {item.magnet && (
                        <a href={item.magnet} className="rounded-lg p-2 text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors" title="磁力链接">
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      )}
                      <button onClick={() => handleDownload(item, i)} disabled={downloading.has(i)}
                        className={cn('rounded-lg p-2 transition-colors',
                          downloading.has(i) ? 'text-text-muted cursor-not-allowed' : 'text-accent-primary hover:bg-accent-primary/10')}
                        title="添加下载">
                        {downloading.has(i) ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ) : query && !loading ? (
          <div className="text-center py-20 text-text-muted">
            <Search className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>没有找到相关种子</p>
            <button onClick={() => handleModeSwitch('anilist')} className="mt-2 text-xs text-accent-primary hover:underline">
              切换到 AniList 番剧搜索试试？
            </button>
          </div>
        ) : null
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-xl bg-bg-card border border-border px-4 py-3 shadow-lg">
          {toast.type === 'ok' ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-danger" />}
          <span className="text-sm">{toast.msg}</span>
        </div>
      )}
    </div>
  )
}
