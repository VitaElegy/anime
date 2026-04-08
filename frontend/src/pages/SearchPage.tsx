import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, Download, ExternalLink, Loader2, ArrowUpDown, CheckCircle2, XCircle, Star, Globe, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import { searchNyaa, searchSubsPlease, searchDmhy, searchMikan, searchAnimeTosho, addDownload, anilistSearch, proxyImageUrl } from '@/api'
import type { TorrentItem, SearchResult } from '@/types'
import type { AniListAnime } from '@/api'

type SearchMode = 'anilist' | 'torrent'

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

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2500)
  }

  const doSearch = useCallback(async (q: string, m: SearchMode) => {
    if (!q.trim()) return
    setLoading(true)
    setTorrentResults([])
    setAnilistResults([])
    try {
      if (m === 'anilist') {
        const result = await anilistSearch(q, 1, 24)
        setAnilistResults(result.items)
      } else {
        const [nyaa, sp, dmhyR, mikanR, toshoR] = await Promise.allSettled([
          searchNyaa(q), searchSubsPlease(q), searchDmhy(q), searchMikan(q), searchAnimeTosho(q)
        ])
        const items: TorrentItem[] = []
        if (nyaa.status === 'fulfilled') items.push(...nyaa.value.items)
        if (sp.status === 'fulfilled') items.push(...sp.value.items)
        if (dmhyR.status === 'fulfilled') items.push(...dmhyR.value.items)
        if (mikanR.status === 'fulfilled') items.push(...mikanR.value.items)
        if (toshoR.status === 'fulfilled') items.push(...toshoR.value.items)
        setTorrentResults(items)
      }
    } catch { /* silent */ } finally { setLoading(false) }
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
      await addDownload({ magnet: item.magnet, torrent_url: item.torrent_url })
      showToast('已添加到下载队列', 'ok')
    } catch {
      showToast('添加下载失败', 'err')
    } finally {
      setDownloading((prev) => { const n = new Set(prev); n.delete(index); return n })
    }
  }

  // Click AniList card -> switch to torrent mode and search by romaji name
  const handleAnilistClick = (anime: AniListAnime) => {
    const searchTerm = anime.title_romaji || anime.title_english || anime.title_preferred
    setQuery(searchTerm)
    setMode('torrent')
    lastSearchedQ.current = searchTerm
    setSearchParams({ q: searchTerm })
    doSearch(searchTerm, 'torrent')
  }

  const getAnilistTitle = (a: AniListAnime): string => {
    return a.title_native || a.title_preferred || a.title_romaji || a.title_english || ''
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
            <Zap className="h-3.5 w-3.5" /> 种子搜索 (5源聚合)
          </button>
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          {mode === 'anilist' ? (
            <span className="px-2 py-0.5 rounded-full bg-accent-secondary/10 text-accent-secondary font-medium">AniList GraphQL · 原生中文搜索</span>
          ) : (
            <>
              <span className="px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan font-medium">Nyaa</span>
              <span className="px-2 py-0.5 rounded-full bg-accent-secondary/10 text-accent-secondary font-medium">SubsPlease</span>
              <span className="px-2 py-0.5 rounded-full bg-accent-primary/10 text-accent-primary font-medium">动漫花园</span>
              <span className="px-2 py-0.5 rounded-full bg-accent-gold/10 text-accent-gold font-medium">蜜柑计划</span>
              <span className="px-2 py-0.5 rounded-full bg-success/10 text-success font-medium">AnimeTosho</span>
            </>
          )}
        </div>
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
            <p className="text-xs text-text-muted mb-3">点击番剧卡片跳转到种子搜索</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
              {anilistResults.map((anime) => (
                <div key={anime.id} className="group cursor-pointer" onClick={() => handleAnilistClick(anime)}>
                  <div className="poster-card card-hover border border-border relative bg-bg-card">
                    <img src={proxyImageUrl(anime.cover_large || anime.cover_medium)} alt={getAnilistTitle(anime)}
                      loading="lazy" className="w-full h-full object-cover" />
                    {anime.score > 0 && (
                      <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-accent-gold backdrop-blur-sm">
                        <Star className="h-2.5 w-2.5 fill-accent-gold" />{anime.score.toFixed(1)}
                      </div>
                    )}
                    {anime.format && (
                      <div className="absolute top-1.5 left-1.5 rounded-md bg-accent-primary/80 px-1.5 py-0.5 text-[9px] font-medium text-white backdrop-blur-sm">
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
        /* ===== Torrent Results — List ===== */
        torrentResults.length > 0 ? (
          <div className="space-y-2">
            {torrentResults.map((item, i) => (
              <div key={i} className="group flex items-start gap-4 rounded-xl bg-bg-card border border-border p-4 card-hover">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium leading-snug mb-1.5">{item.title}</p>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-text-muted">
                    <span className={cn('rounded px-1.5 py-0.5 font-medium',
                      item.source === 'nyaa' ? 'bg-accent-cyan/10 text-accent-cyan'
                        : item.source === 'subsplease' ? 'bg-accent-secondary/10 text-accent-secondary'
                        : item.source === 'dmhy' ? 'bg-accent-primary/10 text-accent-primary'
                        : item.source === 'mikan' ? 'bg-accent-gold/10 text-accent-gold'
                        : item.source === 'animetosho' ? 'bg-success/10 text-success'
                        : 'bg-bg-card text-text-muted')}>
                      {item.source}
                    </span>
                    {item.size && <span>{item.size}</span>}
                    {item.seeders > 0 && <span className="text-success">S: {item.seeders}</span>}
                    {item.leechers > 0 && <span className="text-danger">L: {item.leechers}</span>}
                    {item.date && <span>{item.date}</span>}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
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
            ))}
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
