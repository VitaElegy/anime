import { useEffect, useState, type SyntheticEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, Heart, Loader2, Play, Search, Sparkles, Star, Tv2, Users } from 'lucide-react'
import { addFavorite, anilistSearch, getCoverUrl, getFavorites, getMetadata, getMetadataFull, getStreamingLinks, normalizeExternalImageUrl, proxyImageUrl, removeFavorite, searchMetadata } from '@/api'
import type { AniListAnime } from '@/api'
import { useAuth } from '@/contexts/useAuth'
import { cn } from '@/lib/utils'
import type { AnimeMetadata, AnimeMetadataFull, StreamingLink } from '@/types'

const COVER_PLACEHOLDER =
  'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400"><rect fill="%23161b2b" width="300" height="400"/><text x="150" y="200" text-anchor="middle" fill="%2364748b" font-size="16">No Cover</text></svg>'

function cleanTitle(value: string): string {
  let cleaned = value.replace(/\[.*?\]/g, '').replace(/\(.*?\)/g, '')
  cleaned = cleaned.replace(/\.\w{3,4}$/i, '')
  cleaned = cleaned.replace(/\s*[-–]\s*\d+.*$/, '')
  cleaned = cleaned.replace(/\s+S\d+\s*$/i, '')
  return cleaned.replace(/\s+/g, ' ').trim()
}

function normalizeTitle(value: string): string {
  return cleanTitle(value).toLowerCase()
}

function uniqueCandidates(title: string, rawTitle: string): string[] {
  const seen = new Set<string>()
  const values = [title, rawTitle, cleanTitle(title), cleanTitle(rawTitle)]
  return values.filter((value) => {
    const next = value.trim()
    if (!next || seen.has(next)) return false
    seen.add(next)
    return true
  })
}

function pickMetadata(results: AnimeMetadata[], title: string, rawTitle: string): AnimeMetadata | null {
  if (results.length === 0) return null
  const targets = new Set(uniqueCandidates(title, rawTitle).map(normalizeTitle))
  return results.find((item) => targets.has(normalizeTitle(item.name_cn)) || targets.has(normalizeTitle(item.name))) || results[0]
}

function pickAniList(results: AniListAnime[], title: string, rawTitle: string): AniListAnime | null {
  if (results.length === 0) return null
  const targets = new Set(uniqueCandidates(title, rawTitle).map(normalizeTitle))
  return results.find((item) => {
    return [item.title_native, item.title_preferred, item.title_romaji, item.title_english].some((candidate) => targets.has(normalizeTitle(candidate || '')))
  }) || results[0]
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return '操作失败，请稍后重试'
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []

  for (const value of values) {
    const next = (value || '').trim()
    if (!next || seen.has(next)) continue
    seen.add(next)
    result.push(next)
  }

  return result
}

export default function AnimeDetailPage() {
  const { subjectId: subjectIdParam = '0' } = useParams()
  const [searchParams] = useSearchParams()
  const { isAuthenticated } = useAuth()
  const [metadata, setMetadata] = useState<AnimeMetadata | null>(null)
  const [metadataFull, setMetadataFull] = useState<AnimeMetadataFull | null>(null)
  const [streamingLinks, setStreamingLinks] = useState<StreamingLink[]>([])
  const [anilistItem, setAnilistItem] = useState<AniListAnime | null>(null)
  const [loading, setLoading] = useState(true)
  const [favoriteIds, setFavoriteIds] = useState<Set<number>>(new Set())
  const [favoriteBusy, setFavoriteBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [messageTone, setMessageTone] = useState<'info' | 'error'>('info')
  const [coverIndex, setCoverIndex] = useState(0)

  const subjectId = Number(subjectIdParam || '0') || 0
  const titleParam = searchParams.get('title') || ''
  const rawTitleParam = searchParams.get('rawTitle') || ''
  const coverParam = searchParams.get('cover') || ''
  const pageParam = searchParams.get('page') || ''

  useEffect(() => {
    const loadFavorites = async () => {
      if (!isAuthenticated) {
        setFavoriteIds(new Set())
        return
      }
      try {
        const favorites = await getFavorites()
        setFavoriteIds(new Set(favorites.map((item) => item.bangumi_id)))
      } catch {
        /* best effort */
      }
    }

    void loadFavorites()
  }, [isAuthenticated])

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setMessage('')
      setMetadata(null)
      setMetadataFull(null)
      setStreamingLinks([])
      setAnilistItem(null)

      try {
        if (subjectId > 0) {
          try {
            const detail = await getMetadata(subjectId)
            setMetadata(detail)
            return
          } catch {
            /* fall through to lookup */
          }
        }

        const candidates = uniqueCandidates(titleParam, rawTitleParam)
        for (const candidate of candidates) {
          const results = await searchMetadata(candidate, 6)
          const picked = pickMetadata(results, titleParam, rawTitleParam)
          if (picked) {
            setMetadata(picked)
            return
          }
        }

        for (const candidate of candidates) {
          const results = await anilistSearch(candidate, 1, 6)
          const picked = pickAniList(results.items, titleParam, rawTitleParam)
          if (picked) {
            setAnilistItem(picked)
            return
          }
        }
      } catch (error) {
        setMessageTone('error')
        setMessage(extractErrorMessage(error))
      } finally {
        setLoading(false)
      }
    }

    void load()
  }, [rawTitleParam, subjectId, titleParam])

  // When a Bangumi metadata lands, fire off full-metadata + streaming concurrently.
  useEffect(() => {
    const bgmId = metadata?.id
    if (!bgmId || bgmId <= 0) return

    void (async () => {
      const [fullResult, streamingResult] = await Promise.allSettled([
        getMetadataFull(bgmId),
        getStreamingLinks(bgmId),
      ])
      if (fullResult.status === 'fulfilled') {
        setMetadataFull(fullResult.value)
      }
      if (streamingResult.status === 'fulfilled') {
        setStreamingLinks(streamingResult.value)
      }
    })()
  }, [metadata?.id])

  const displayTitle =
    metadata?.name_cn ||
    metadata?.name ||
    anilistItem?.title_native ||
    anilistItem?.title_preferred ||
    titleParam ||
    cleanTitle(rawTitleParam) ||
    '番剧详情'

  const secondaryTitle =
    (metadata?.name_cn && metadata.name) ||
    anilistItem?.title_romaji ||
    anilistItem?.title_english ||
    rawTitleParam

  const summary = metadata?.summary || anilistItem?.description || ''
  const score = metadata?.score || anilistItem?.score || 0
  const episodes = anilistItem?.episodes || 0
  const coverCandidates = uniqueStrings([
    metadata?.id ? getCoverUrl(metadata.id) : '',
    coverParam ? proxyImageUrl(coverParam) : '',
    metadata?.cover_url ? proxyImageUrl(metadata.cover_url) : '',
    coverParam ? normalizeExternalImageUrl(coverParam) : '',
    metadata?.cover_url ? normalizeExternalImageUrl(metadata.cover_url) : '',
    anilistItem?.cover_large ? proxyImageUrl(anilistItem.cover_large) : '',
    anilistItem?.cover_medium ? proxyImageUrl(anilistItem.cover_medium) : '',
    anilistItem?.cover_large ? normalizeExternalImageUrl(anilistItem.cover_large) : '',
    anilistItem?.cover_medium ? normalizeExternalImageUrl(anilistItem.cover_medium) : '',
  ])
  const coverUrl = coverCandidates[coverIndex] || ''

  useEffect(() => {
    setCoverIndex(0)
  }, [subjectId, coverParam, metadata?.id, metadata?.cover_url, anilistItem?.cover_large, anilistItem?.cover_medium])

  const searchQuery =
    metadata?.name ||
    metadata?.name_cn ||
    anilistItem?.title_romaji ||
    anilistItem?.title_preferred ||
    cleanTitle(rawTitleParam) ||
    titleParam

  const canFavorite = Boolean(metadata?.id)
  const isFavorite = canFavorite ? favoriteIds.has(metadata!.id) : false

  const handleCoverError = (event: SyntheticEvent<HTMLImageElement>) => {
    const nextIndex = coverIndex + 1
    if (nextIndex < coverCandidates.length) {
      setCoverIndex(nextIndex)
      return
    }

    event.currentTarget.onerror = null
    event.currentTarget.src = COVER_PLACEHOLDER
  }

  const handleFavoriteToggle = async () => {
    if (!metadata?.id) {
      setMessageTone('error')
      setMessage('当前条目还没有稳定的 Bangumi 条目，暂时不能收藏。')
      return
    }
    if (!isAuthenticated) {
      setMessageTone('error')
      setMessage('登录后就可以把这部番加入收藏。')
      return
    }

    setFavoriteBusy(true)
    try {
      if (favoriteIds.has(metadata.id)) {
        await removeFavorite(metadata.id)
      } else {
        await addFavorite({
          bangumi_id: metadata.id,
          name_cn: metadata.name_cn,
          name: metadata.name,
          cover_url: metadata.cover_url,
          score: metadata.score,
        })
      }
      const favorites = await getFavorites()
      setFavoriteIds(new Set(favorites.map((item) => item.bangumi_id)))
      setMessageTone('info')
      setMessage(favoriteIds.has(metadata.id) ? '已取消收藏' : '已加入收藏')
    } catch (error) {
      setMessageTone('error')
      setMessage(extractErrorMessage(error))
    } finally {
      setFavoriteBusy(false)
    }
  }

  return (
    <div className="-mx-6 -mt-6 min-h-full">
      {/* Background Banner */}
      <div className="relative h-[320px] w-full overflow-hidden sm:h-[400px]">
        <div
          className="absolute inset-0 scale-110 transform bg-cover bg-center bg-no-repeat opacity-40 blur-2xl transition-all duration-1000"
          style={{ backgroundImage: `url('${coverUrl || COVER_PLACEHOLDER}')` }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-bg-primary via-bg-primary/80 to-transparent" />
        
        {/* Top Navigation Overlay */}
        <div className="absolute left-0 right-0 top-0 z-20 flex flex-wrap items-center justify-between gap-4 p-6">
          <Link to="/calendar" className="inline-flex items-center gap-2 rounded-xl bg-black/40 px-4 py-2 text-sm font-medium text-text-primary ring-1 ring-white/10 backdrop-blur-md transition-all hover:bg-white/10 hover:shadow-lg">
            <ArrowLeft className="h-4 w-4" /> 返回新番日历
          </Link>
          
          <div className="flex flex-wrap items-center gap-3">
            {pageParam && (
              <a
                href={pageParam}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-xl bg-black/40 px-4 py-2 text-sm font-medium text-text-primary ring-1 ring-white/10 backdrop-blur-md transition-all hover:bg-white/10"
              >
                <ExternalLink className="h-4 w-4" /> 源站页面
              </a>
            )}
            {metadata?.id ? (
              <a
                href={`https://bgm.tv/subject/${metadata.id}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-xl bg-[#f09199]/20 px-4 py-2 text-sm font-medium text-[#f09199] ring-1 ring-[#f09199]/30 backdrop-blur-md transition-all hover:bg-[#f09199]/30"
              >
                <ExternalLink className="h-4 w-4" /> Bangumi
              </a>
            ) : null}
          </div>
        </div>
      </div>

      <div className="relative z-10 mx-auto max-w-6xl px-6 pb-12">
        {message && (
          <div className={cn('mb-6 rounded-xl border px-4 py-3 text-sm backdrop-blur-md animate-in fade-in slide-in-from-top-2', 
            messageTone === 'error' ? 'border-danger/20 bg-danger/10 text-danger' : 'border-accent-cyan/20 bg-accent-cyan/10 text-accent-cyan'
          )}>
            {message}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="relative">
              <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
              <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
            </div>
          </div>
        ) : (
          <div className="relative -mt-32 flex flex-col gap-8 sm:-mt-48 md:flex-row md:items-end">
            {/* Poster Card */}
            <div className="z-10 mx-auto w-48 shrink-0 sm:w-64 md:mx-0 xl:w-72">
              <div className="group overflow-hidden rounded-2xl border border-white/10 bg-bg-card shadow-2xl ring-1 ring-black/50 transition-all duration-500 hover:scale-[1.03] hover:shadow-[0_0_40px_rgba(233,69,96,0.4)] glow-accent">
                {coverUrl ? (
                  <img
                    key={coverUrl}
                    src={coverUrl}
                    alt={displayTitle}
                    className="aspect-[3/4] w-full object-cover transition-transform duration-700 group-hover:scale-105"
                    onError={handleCoverError}
                  />
                ) : (
                  <div className="flex aspect-[3/4] items-center justify-center bg-bg-secondary">
                    <span className="text-6xl font-black text-text-muted opacity-30">{displayTitle.charAt(0)}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Content Details */}
            <div className="z-10 flex-1 space-y-6 pb-2 pt-4 text-center sm:pt-10 md:text-left">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-center gap-2 md:justify-start">
                  <span className="rounded-full border border-white/5 bg-white/10 px-3 py-1 text-xs font-medium text-text-primary shadow-sm backdrop-blur-md">
                    番剧详情
                  </span>
                  {!metadata?.id && (
                    <span className="rounded-full border border-accent-gold/10 bg-accent-gold/20 px-3 py-1 text-xs font-medium text-accent-gold shadow-sm backdrop-blur-md">
                      临时匹配
                    </span>
                  )}
                  {score > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-accent-gold/10 bg-accent-gold/20 px-3 py-1 text-xs font-medium text-accent-gold shadow-sm backdrop-blur-md">
                      <Star className="h-3.5 w-3.5 fill-current" />
                      {score.toFixed(1)}
                    </span>
                  )}
                  {anilistItem?.format && <span className="rounded-full border border-white/5 bg-white/10 px-3 py-1 text-xs font-medium text-text-primary shadow-sm backdrop-blur-md">{anilistItem.format}</span>}
                  {episodes > 0 && <span className="rounded-full border border-white/5 bg-white/10 px-3 py-1 text-xs font-medium text-text-primary shadow-sm backdrop-blur-md">{episodes} 话</span>}
                  {anilistItem?.season_year ? <span className="rounded-full border border-white/5 bg-white/10 px-3 py-1 text-xs font-medium text-text-primary shadow-sm backdrop-blur-md">{anilistItem.season_year}</span> : null}
                </div>
                
                <h1 className="text-4xl font-black tracking-tight text-white drop-shadow-lg sm:text-5xl lg:text-6xl">
                  {displayTitle}
                </h1>
                
                {secondaryTitle && secondaryTitle !== displayTitle && (
                  <p className="text-lg font-medium tracking-wide text-text-secondary">
                    {secondaryTitle}
                  </p>
                )}
              </div>

              <div className="flex flex-wrap items-center justify-center gap-4 pt-2 md:justify-start">
                <Link
                  to={`/search?q=${encodeURIComponent(searchQuery)}`}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent-primary to-accent-secondary px-6 py-3 text-base font-bold text-white shadow-lg transition-all hover:scale-105 hover:shadow-[0_0_20px_rgba(233,69,96,0.4)]"
                >
                  <Search className="h-5 w-5" /> 搜索下载资源
                </Link>

                {streamingLinks.filter(l => l.platform === 'bilibili').slice(0, 1).map(link => (
                  <a
                    key={link.season_id}
                    href={link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="group relative inline-flex items-center gap-2 overflow-hidden rounded-xl bg-gradient-to-r from-[#00aeec] to-[#fb7299] px-6 py-3 text-base font-bold text-white shadow-lg transition-all hover:scale-105 hover:shadow-[0_0_25px_rgba(251,114,153,0.5)]"
                  >
                    <div className="absolute inset-0 bg-white/20 opacity-0 transition-opacity group-hover:opacity-100" />
                    <Play className="relative h-5 w-5 fill-current" />
                    <span className="relative">B 站正版</span>
                    {link.is_paid && (
                      <span className="relative rounded-md bg-white/20 px-1.5 py-0.5 text-[10px] font-black tracking-wider">VIP</span>
                    )}
                  </a>
                ))}
                
                <button
                  onClick={() => void handleFavoriteToggle()}
                  disabled={favoriteBusy || !canFavorite}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-xl px-6 py-3 text-base font-bold shadow-lg transition-all',
                    canFavorite
                      ? isFavorite
                        ? 'border border-danger/30 bg-danger/20 text-danger hover:scale-105 hover:bg-danger/30'
                        : 'border border-white/10 bg-white/10 text-white backdrop-blur-md hover:scale-105 hover:bg-white/20'
                      : 'cursor-not-allowed border border-border/50 bg-bg-secondary/50 text-text-muted'
                  )}
                >
                  {favoriteBusy ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Heart className={cn('h-5 w-5 transition-transform duration-300', isFavorite && 'scale-110 fill-current')} />
                  )}
                  {!canFavorite ? '等待条目完善' : !isAuthenticated ? '登录后收藏' : isFavorite ? '已收藏' : '加入收藏'}
                </button>
              </div>
            </div>
          </div>
        )}
        
        {/* Main Content Sections */}
        {!loading && (
          <div className="mt-12 grid gap-8 lg:grid-cols-3">
            <div className="space-y-8 lg:col-span-2">
              <section className="space-y-4">
                <div className="flex items-center gap-2 text-xl font-bold text-white">
                  <div className="h-6 w-1.5 rounded-full bg-accent-cyan"></div>
                  <h2>剧情简介</h2>
                </div>
                <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-6 shadow-inner backdrop-blur-sm">
                  <p className="whitespace-pre-wrap text-base leading-relaxed text-text-secondary">
                    {(metadataFull?.summary || summary) || '这条番剧目前还没有同步到完整简介，但你已经可以从这里直接跳去搜索资源或查看源站页面。'}
                  </p>
                </div>
              </section>

              {metadataFull && metadataFull.tags.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-center gap-2 text-xl font-bold text-white">
                    <div className="h-6 w-1.5 rounded-full bg-accent-gold"></div>
                    <h2>标签 · 风格</h2>
                  </div>
                  <div className="flex flex-wrap gap-2 rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-inner backdrop-blur-sm">
                    {metadataFull.meta_tags.map(t => (
                      <span key={`m-${t}`} className="rounded-full border border-accent-primary/30 bg-accent-primary/10 px-3 py-1 text-xs font-bold text-accent-primary backdrop-blur-sm">
                        {t}
                      </span>
                    ))}
                    {metadataFull.tags.slice(0, 16).map(t => (
                      <span key={t} className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-white/80 transition-colors hover:bg-white/10">
                        {t}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {metadataFull && metadataFull.staff.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-center gap-2 text-xl font-bold text-white">
                    <div className="h-6 w-1.5 rounded-full bg-accent-primary"></div>
                    <h2 className="flex items-center gap-2"><Users className="h-5 w-5" /> 制作团队</h2>
                  </div>
                  <div className="grid grid-cols-1 gap-3 rounded-2xl border border-white/5 bg-white/[0.02] p-6 shadow-inner backdrop-blur-sm sm:grid-cols-2">
                    {metadataFull.staff.map((s, idx) => (
                      <div key={`${s.role}-${idx}`} className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06]">
                        <span className="shrink-0 rounded-lg bg-accent-primary/20 px-2.5 py-1 text-[11px] font-black text-accent-primary">{s.role}</span>
                        <span className="flex-1 truncate text-right text-sm font-bold text-white/90">{s.name}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {metadataFull && metadataFull.theme_songs.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-center gap-2 text-xl font-bold text-white">
                    <div className="h-6 w-1.5 rounded-full bg-accent-secondary"></div>
                    <h2>主题曲</h2>
                  </div>
                  <div className="grid grid-cols-1 gap-3 rounded-2xl border border-white/5 bg-white/[0.02] p-6 shadow-inner backdrop-blur-sm md:grid-cols-2">
                    {metadataFull.theme_songs.map((song, idx) => (
                      <div key={`${song.kind}-${idx}`} className="flex items-center gap-4 rounded-xl border border-white/5 bg-gradient-to-r from-white/[0.03] to-transparent p-4 transition-all hover:border-accent-secondary/30 hover:from-accent-secondary/10">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-secondary/20 text-xs font-black text-accent-secondary">
                          {song.kind.slice(0, 4)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-base font-bold text-white">{song.title}</p>
                          {song.artist && <p className="truncate text-xs font-medium text-white/50">{song.artist}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
            
            <div className="space-y-6">
              {streamingLinks.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-center gap-2 text-lg font-bold text-white">
                    <div className="h-5 w-1.5 rounded-full bg-gradient-to-b from-[#00aeec] to-[#fb7299]"></div>
                    <h3 className="flex items-center gap-2"><Tv2 className="h-5 w-5" /> 正版观看入口</h3>
                  </div>
                  <div className="space-y-3">
                    {streamingLinks.map(link => (
                      <a
                        key={`${link.platform}-${link.season_id}`}
                        href={link.url}
                        target="_blank"
                        rel="noreferrer"
                        className="group block overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-[#00aeec]/10 via-white/[0.02] to-[#fb7299]/10 shadow-lg backdrop-blur-sm transition-all hover:scale-[1.02] hover:border-[#fb7299]/40 hover:shadow-[0_0_25px_rgba(251,114,153,0.2)]"
                      >
                        <div className="flex gap-4 p-4">
                          {link.cover_url && (
                            <img
                              src={proxyImageUrl(link.cover_url)}
                              alt={link.title}
                              className="h-20 w-14 shrink-0 rounded-lg object-cover shadow-md"
                              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                            />
                          )}
                          <div className="min-w-0 flex-1 space-y-1.5">
                            <div className="flex items-center gap-2">
                              <span className="rounded-md bg-gradient-to-r from-[#00aeec] to-[#fb7299] px-2 py-0.5 text-[10px] font-black text-white">
                                {link.platform === 'bilibili' ? 'B 站' : link.platform}
                              </span>
                              {link.is_finished && (
                                <span className="rounded-md border border-success/30 bg-success/10 px-1.5 py-0.5 text-[10px] font-bold text-success">已完结</span>
                              )}
                              {link.is_paid && (
                                <span className="rounded-md border border-accent-gold/30 bg-accent-gold/10 px-1.5 py-0.5 text-[10px] font-bold text-accent-gold">VIP</span>
                              )}
                            </div>
                            <p className="truncate text-sm font-bold text-white group-hover:text-white">{link.title}</p>
                            <div className="flex items-center gap-3 text-[11px] font-medium text-white/60">
                              {link.score > 0 && (
                                <span className="inline-flex items-center gap-1 text-accent-gold">
                                  <Star className="h-3 w-3 fill-current" />{link.score.toFixed(1)}
                                </span>
                              )}
                              {link.total_episodes > 0 && <span>全 {link.total_episodes} 话</span>}
                            </div>
                          </div>
                          <Play className="my-auto h-5 w-5 shrink-0 text-white/40 transition-transform group-hover:translate-x-1 group-hover:text-white" />
                        </div>
                      </a>
                    ))}
                  </div>
                </section>
              )}

              <section className="space-y-4">
                <div className="flex items-center gap-2 text-lg font-bold text-white">
                  <div className="h-5 w-1.5 rounded-full bg-accent-secondary"></div>
                  <h3>元数据信息</h3>
                </div>
                <div className="space-y-4 rounded-2xl border border-white/5 bg-white/[0.02] p-5 backdrop-blur-sm">
                  <div className="flex items-center justify-between border-b border-white/5 pb-3">
                    <span className="text-sm text-text-muted">匹配状态</span>
                    <div className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-cyan">
                      <Sparkles className="h-4 w-4" />
                      <span>{metadata?.id ? 'Bangumi 精确匹配' : '搜索兜底'}</span>
                    </div>
                  </div>

                  {metadataFull?.air_date && (
                    <div className="flex items-center justify-between border-b border-white/5 pb-3">
                      <span className="text-sm text-text-muted">放送时间</span>
                      <span className="text-sm font-bold text-white">
                        {metadataFull.air_date}
                        {metadataFull.air_weekday && <span className="ml-2 text-accent-cyan">· {metadataFull.air_weekday}</span>}
                      </span>
                    </div>
                  )}

                  {metadataFull?.rank && metadataFull.rank > 0 ? (
                    <div className="flex items-center justify-between border-b border-white/5 pb-3">
                      <span className="text-sm text-text-muted">Bangumi 排名</span>
                      <span className="text-sm font-bold text-accent-gold">#{metadataFull.rank}</span>
                    </div>
                  ) : null}

                  {metadataFull?.total_episodes && metadataFull.total_episodes > 0 ? (
                    <div className="flex items-center justify-between border-b border-white/5 pb-3">
                      <span className="text-sm text-text-muted">总集数</span>
                      <span className="text-sm font-bold text-white">{metadataFull.total_episodes}</span>
                    </div>
                  ) : null}

                  {metadataFull?.official_site && (
                    <div className="flex flex-col gap-2 border-b border-white/5 pb-3">
                      <span className="text-sm text-text-muted">官方网站</span>
                      <a href={metadataFull.official_site} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 break-all text-sm font-bold text-accent-cyan transition-colors hover:text-white">
                        <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">{metadataFull.official_site}</span>
                      </a>
                    </div>
                  )}

                  {rawTitleParam && rawTitleParam !== displayTitle && (
                    <div className="space-y-1.5">
                      <span className="text-xs uppercase tracking-wider text-text-muted">识别原标题</span>
                      <p className="break-words rounded-lg bg-black/20 p-2 font-mono text-sm text-text-secondary">{rawTitleParam}</p>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <span className="text-xs uppercase tracking-wider text-text-muted">搜索关键字</span>
                    <p className="break-words rounded-lg bg-black/20 p-2 font-mono text-sm text-text-secondary">{searchQuery}</p>
                  </div>
                </div>
              </section>

              {metadataFull?.aliases && metadataFull.aliases.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-center gap-2 text-lg font-bold text-white">
                    <div className="h-5 w-1.5 rounded-full bg-white/40"></div>
                    <h3>别名</h3>
                  </div>
                  <div className="flex flex-wrap gap-2 rounded-2xl border border-white/5 bg-white/[0.02] p-4 backdrop-blur-sm">
                    {metadataFull.aliases.slice(0, 10).map(a => (
                      <span key={a} className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs font-medium text-white/70">
                        {a}
                      </span>
                    ))}
                  </div>
                </section>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
