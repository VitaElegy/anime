import { useEffect, useState, type SyntheticEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, Heart, Loader2, Search, Sparkles, Star } from 'lucide-react'
import { addFavorite, anilistSearch, getCoverUrl, getFavorites, getMetadata, normalizeExternalImageUrl, proxyImageUrl, removeFavorite, searchMetadata } from '@/api'
import type { AniListAnime } from '@/api'
import { useAuth } from '@/contexts/useAuth'
import { cn } from '@/lib/utils'
import type { AnimeMetadata } from '@/types'

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
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/calendar" className="inline-flex items-center gap-2 rounded-lg border border-border bg-bg-card px-3 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary">
          <ArrowLeft className="h-4 w-4" /> 返回新番日历
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to={`/search?q=${encodeURIComponent(searchQuery)}`}
            className="inline-flex items-center gap-2 rounded-lg bg-accent-primary px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-primary/90"
          >
            <Search className="h-4 w-4" /> 搜索下载资源
          </Link>
          {pageParam && (
            <a
              href={pageParam}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-bg-card px-3 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              <ExternalLink className="h-4 w-4" /> 源站页面
            </a>
          )}
          {metadata?.id ? (
            <a
              href={`https://bgm.tv/subject/${metadata.id}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-bg-card px-3 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              <ExternalLink className="h-4 w-4" /> Bangumi
            </a>
          ) : null}
        </div>
      </div>

      {message && (
        <div className={cn('rounded-xl px-4 py-3 text-sm', messageTone === 'error' ? 'bg-danger/8 text-danger' : 'bg-accent-cyan/10 text-accent-cyan')}>
          {message}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
          <div className="overflow-hidden rounded-2xl border border-border bg-bg-card">
            {coverUrl ? (
              <img
                key={coverUrl}
                src={coverUrl}
                alt={displayTitle}
                className="aspect-[3/4] w-full object-cover"
                onError={handleCoverError}
              />
            ) : (
              <div className="flex aspect-[3/4] items-center justify-center bg-bg-card">
                <span className="text-5xl font-bold text-border">{displayTitle.charAt(0)}</span>
              </div>
            )}
          </div>

          <div className="space-y-5 rounded-2xl border border-border bg-bg-card p-6">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-accent-secondary/10 px-2.5 py-1 text-[11px] font-medium text-accent-secondary">番剧详情</span>
                {!metadata?.id && (
                  <span className="rounded-full bg-accent-gold/10 px-2.5 py-1 text-[11px] font-medium text-accent-gold">临时匹配</span>
                )}
              </div>
              <h1 className="text-3xl font-bold leading-tight">{displayTitle}</h1>
              {secondaryTitle && secondaryTitle !== displayTitle && (
                <p className="text-sm text-text-secondary">{secondaryTitle}</p>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
              {score > 0 && (
                <div className="inline-flex items-center gap-1.5 rounded-full bg-accent-gold/10 px-3 py-1 text-accent-gold">
                  <Star className="h-4 w-4 fill-current" />
                  <span className="font-medium">{score.toFixed(1)}</span>
                </div>
              )}
              {anilistItem?.format && <span className="rounded-full bg-bg-secondary px-3 py-1">{anilistItem.format}</span>}
              {episodes > 0 && <span className="rounded-full bg-bg-secondary px-3 py-1">{episodes} 话</span>}
              {anilistItem?.season_year ? <span className="rounded-full bg-bg-secondary px-3 py-1">{anilistItem.season_year}</span> : null}
            </div>

            <div className="rounded-2xl bg-bg-secondary/70 p-4">
              <p className="text-sm leading-7 text-text-secondary">
                {summary || '这条番剧目前还没有同步到完整简介，但你已经可以从这里直接跳去搜索资源或查看源站页面。'}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => void handleFavoriteToggle()}
                disabled={favoriteBusy}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                  canFavorite
                    ? isFavorite
                      ? 'bg-danger/10 text-danger hover:bg-danger/15'
                      : 'bg-accent-primary/10 text-accent-primary hover:bg-accent-primary/15'
                    : 'cursor-not-allowed bg-bg-secondary text-text-muted'
                )}
              >
                {favoriteBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Heart className={cn('h-4 w-4', isFavorite && 'fill-current')} />}
                {!canFavorite ? '等待条目完善' : !isAuthenticated ? '登录后收藏' : isFavorite ? '已在收藏中' : '加入收藏'}
              </button>

              <div className="inline-flex items-center gap-2 rounded-lg bg-accent-cyan/10 px-3 py-2 text-sm text-accent-cyan">
                <Sparkles className="h-4 w-4" />
                <span>{metadata?.id ? '已关联 Bangumi 详情' : '当前使用搜索结果兜底展示'}</span>
              </div>
            </div>

            {rawTitleParam && rawTitleParam !== displayTitle && (
              <div className="rounded-xl border border-border bg-bg-secondary/40 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-text-muted">原始标题</p>
                <p className="mt-2 text-sm text-text-secondary break-words">{rawTitleParam}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
