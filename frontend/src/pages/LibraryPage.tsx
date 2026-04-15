import { useEffect, useState } from 'react'
import { AlertCircle, BookOpen, Heart, Loader2, Search, Sparkles, Star } from 'lucide-react'
import { addFavorite, getCoverUrl, getFavorites, importLegacyFavorites, removeFavorite, searchMetadata, updateFavorite } from '@/api'
import { AuthPanel } from '@/components/auth/AuthPanel'
import { useAuth } from '@/contexts/useAuth'
import { cn } from '@/lib/utils'
import type { AnimeMetadata, FavoriteItem } from '@/types'

type ViewTab = 'search' | 'favorites'

const statusLabels: Record<string, string> = {
  watching: '在追',
  completed: '看完',
  dropped: '弃番',
  planned: '想看',
}

const statusColors: Record<string, string> = {
  watching: 'bg-accent-cyan/10 text-accent-cyan',
  completed: 'bg-success/10 text-success',
  dropped: 'bg-danger/10 text-danger',
  planned: 'bg-accent-gold/10 text-accent-gold',
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return '操作失败，请稍后重试'
}

export default function LibraryPage() {
  const { user, isAuthenticated, loading: authLoading } = useAuth()
  const [tab, setTab] = useState<ViewTab>('favorites')
  const [query, setQuery] = useState('')
  const [animes, setAnimes] = useState<AnimeMetadata[]>([])
  const [favorites, setFavorites] = useState<FavoriteItem[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedAnime, setSelectedAnime] = useState<AnimeMetadata | null>(null)
  const [favSet, setFavSet] = useState<Set<number>>(new Set())
  const [message, setMessage] = useState('')
  const [messageTone, setMessageTone] = useState<'info' | 'error'>('info')
  const [importing, setImporting] = useState(false)

  const loadFavorites = async () => {
    if (!isAuthenticated) {
      setFavorites([])
      setFavSet(new Set())
      return
    }
    try {
      const favs = await getFavorites()
      setFavorites(favs)
      setFavSet(new Set(favs.map((item) => item.bangumi_id)))
    } catch (error) {
      setMessageTone('error')
      setMessage(extractErrorMessage(error))
    }
  }

  useEffect(() => {
    let active = true

    if (!isAuthenticated) {
      setFavorites([])
      setFavSet(new Set())
      return
    }

    const run = async () => {
      try {
        const favs = await getFavorites()
        if (!active) return
        setFavorites(favs)
        setFavSet(new Set(favs.map((item) => item.bangumi_id)))
      } catch (error) {
        if (!active) return
        setMessageTone('error')
        setMessage(extractErrorMessage(error))
      }
    }

    void run()

    return () => {
      active = false
    }
  }, [isAuthenticated])

  const doSearch = async (value: string) => {
    if (!value.trim()) return
    setLoading(true)
    try {
      const results = await searchMetadata(value)
      setAnimes(results)
    } catch (error) {
      setMessageTone('error')
      setMessage(extractErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    setTab('search')
    void doSearch(query)
  }

  const toggleFavorite = async (anime: AnimeMetadata) => {
    if (!isAuthenticated) {
      setTab('favorites')
      setMessageTone('error')
      setMessage('登录后才能收藏，收藏也会自动按账号隔离。')
      setSelectedAnime(null)
      return
    }
    if (favSet.has(anime.id)) {
      await removeFavorite(anime.id)
    } else {
      await addFavorite({
        bangumi_id: anime.id,
        name_cn: anime.name_cn,
        name: anime.name,
        cover_url: anime.cover_url,
        score: anime.score,
      })
    }
    await loadFavorites()
  }

  const handleStatusChange = async (bangumiId: number, status: string) => {
    await updateFavorite(bangumiId, { status })
    await loadFavorites()
  }

  const handleImportLegacy = async () => {
    setImporting(true)
    try {
      const result = await importLegacyFavorites()
      setMessageTone('info')
      setMessage(`旧共享收藏导入完成：新增 ${result.imported} 条，跳过 ${result.skipped} 条。`)
      await loadFavorites()
    } catch (error) {
      setMessageTone('error')
      setMessage(extractErrorMessage(error))
    } finally {
      setImporting(false)
    }
  }

  const tabs: { key: ViewTab; label: string }[] = [
    { key: 'favorites', label: isAuthenticated ? '我的收藏' : '个人收藏' },
    { key: 'search', label: '搜索番剧' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2 rounded-xl bg-accent-cyan/10 px-4 py-3 text-sm text-accent-cyan">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          {isAuthenticated && user ? (
            <>
              <p className="font-medium">当前账号：{user.username}</p>
              <p className="mt-1">现在开始，收藏已经按账号隔离。你可以继续把旧的共享收藏导入到自己的账号里。</p>
            </>
          ) : (
            <>
              <p className="font-medium">个人收藏已经上线</p>
              <p className="mt-1">登录后，收藏会绑定到你的账号，不再和其他访问者共享。旧的共享收藏也可以一键导入。</p>
            </>
          )}
        </div>
      </div>

      {message && (
        <div className={cn('rounded-xl px-4 py-3 text-sm', messageTone === 'error' ? 'bg-danger/8 text-danger' : 'bg-accent-cyan/10 text-accent-cyan')}>
          {message}
        </div>
      )}

      <div className="flex items-center gap-6">
        <div className="flex gap-4 border-b border-border">
          {tabs.map((item) => (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={cn(
                'border-b-2 pb-2 text-sm font-medium transition-colors',
                tab === item.key
                  ? 'border-accent-primary text-accent-primary'
                  : 'border-transparent text-text-muted hover:text-text-secondary'
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <form onSubmit={handleSubmit} className="flex max-w-md flex-1 gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索 Bangumi..."
              className={cn(
                'w-full rounded-xl border border-border bg-bg-card py-2 pl-10 pr-4 text-sm',
                'focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary/50'
              )}
            />
          </div>
          <button type="submit" className="rounded-xl bg-accent-secondary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-secondary/90">
            搜索
          </button>
        </form>
      </div>

      {selectedAnime && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setSelectedAnime(null)}>
          <div className="relative max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-border bg-bg-secondary p-6" onClick={(event) => event.stopPropagation()}>
            <div className="flex gap-6">
              <img
                src={getCoverUrl(selectedAnime.id)}
                alt={selectedAnime.name_cn || selectedAnime.name}
                className="h-64 w-44 shrink-0 rounded-xl object-cover"
                onError={(event) => {
                  (event.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 176 256"><rect fill="%231a1a2e" width="176" height="256"/><text x="88" y="128" text-anchor="middle" fill="%2364748b" font-size="14">No Cover</text></svg>'
                }}
              />
              <div className="flex-1 space-y-3">
                <h2 className="text-xl font-bold">{selectedAnime.name_cn || selectedAnime.name}</h2>
                {selectedAnime.name_cn && <p className="text-sm text-text-secondary">{selectedAnime.name}</p>}
                {selectedAnime.score > 0 && (
                  <div className="flex items-center gap-1.5">
                    <Star className="h-4 w-4 fill-accent-gold text-accent-gold" />
                    <span className="text-sm font-medium">{selectedAnime.score}</span>
                  </div>
                )}
                <p className="text-sm leading-relaxed text-text-secondary">{selectedAnime.summary || '暂无简介'}</p>
                <button
                  onClick={() => void toggleFavorite(selectedAnime)}
                  className={cn(
                    'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                    favSet.has(selectedAnime.id) ? 'bg-danger/10 text-danger' : 'bg-accent-primary/10 text-accent-primary'
                  )}
                >
                  <Heart className={cn('h-4 w-4', favSet.has(selectedAnime.id) && 'fill-current')} />
                  {!isAuthenticated ? '登录后收藏' : favSet.has(selectedAnime.id) ? '取消收藏' : '加入收藏'}
                </button>
              </div>
            </div>
            <button onClick={() => setSelectedAnime(null)} className="absolute right-4 top-4 rounded-lg p-1 text-text-muted hover:text-text-primary">✕</button>
          </div>
        </div>
      )}

      {tab === 'favorites' ? (
        authLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
          </div>
        ) : !isAuthenticated ? (
          <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
            <AuthPanel />
            <div className="rounded-2xl border border-border bg-bg-card p-6">
              <div className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-accent-gold" />
                <h2 className="text-lg font-semibold">登录后会得到什么</h2>
              </div>
              <div className="mt-4 space-y-3 text-sm text-text-secondary">
                <p>收藏将只属于当前账号，不再和其他访问者混在一起。</p>
                <p>旧的共享收藏可以一键导入，不需要重新手动逐个点一遍。</p>
                <p>后续如果继续推进，我们也可以把观看记录、订阅和下载偏好一起挂到账号上。</p>
              </div>
            </div>
          </div>
        ) : favorites.length === 0 ? (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-bg-card p-5">
              <div>
                <p className="text-sm font-medium text-text-primary">旧共享收藏还在</p>
                <p className="mt-1 text-sm text-text-secondary">如果你之前已经积累了一批共享收藏，可以把它们导入到当前账号。</p>
              </div>
              <button
                onClick={() => void handleImportLegacy()}
                disabled={importing}
                className="rounded-lg bg-accent-primary px-3 py-2 text-sm font-medium text-white hover:bg-accent-primary/90 disabled:opacity-60"
              >
                {importing ? '导入中...' : '导入旧共享收藏'}
              </button>
            </div>

            <div className="py-20 text-center text-text-muted">
              <BookOpen className="mx-auto mb-3 h-12 w-12 opacity-30" />
              <p>这个账号还没有收藏番剧</p>
              <p className="mt-1 text-xs">切换到「搜索番剧」添加一部，或者先导入旧共享收藏。</p>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-bg-card p-5">
              <div>
                <p className="text-sm font-medium text-text-primary">当前账号：{user?.username}</p>
                <p className="mt-1 text-sm text-text-secondary">下面这些收藏现在只对你自己可见。</p>
              </div>
              <button
                onClick={() => void handleImportLegacy()}
                disabled={importing}
                className="rounded-lg bg-bg-secondary px-3 py-2 text-sm text-text-secondary hover:text-text-primary disabled:opacity-60"
              >
                {importing ? '导入中...' : '导入旧共享收藏'}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {favorites.map((fav) => (
                <div
                  key={fav.bangumi_id}
                  className="group cursor-pointer"
                  onClick={() => {
                    setSelectedAnime({ id: fav.bangumi_id, name_cn: fav.name_cn, name: fav.name, cover_url: fav.cover_url, score: fav.score, summary: '', cover_local: '' })
                  }}
                >
                  <div className="poster-card card-hover relative border border-border">
                    <img
                      src={getCoverUrl(fav.bangumi_id)}
                      alt={fav.name_cn || fav.name}
                      loading="lazy"
                      onError={(event) => {
                        (event.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect fill="%231a1a2e" width="200" height="300"/><text x="100" y="150" text-anchor="middle" fill="%2364748b" font-size="14">No Cover</text></svg>'
                      }}
                    />
                    <div className="absolute left-2 top-2">
                      <select
                        value={fav.status}
                        onChange={(event) => {
                          event.stopPropagation()
                          void handleStatusChange(fav.bangumi_id, event.target.value)
                        }}
                        onClick={(event) => event.stopPropagation()}
                        className={cn('cursor-pointer rounded-md border-0 px-1.5 py-0.5 text-[10px] font-medium backdrop-blur-sm', statusColors[fav.status] || 'bg-bg-card/80 text-text-muted')}
                      >
                        {Object.entries(statusLabels).map(([key, label]) => (
                          <option key={key} value={key}>{label}</option>
                        ))}
                      </select>
                    </div>
                    {fav.score > 0 && (
                      <div className="absolute right-2 top-2 flex items-center gap-0.5 rounded-md bg-black/60 px-1.5 py-0.5 text-xs font-medium text-accent-gold backdrop-blur-sm">
                        <Star className="h-3 w-3 fill-accent-gold" />
                        {fav.score}
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <p className="mt-2 truncate text-xs font-medium text-text-secondary transition-colors group-hover:text-text-primary">
                    {fav.name_cn || fav.name}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )
      ) : (
        loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
          </div>
        ) : animes.length > 0 ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {animes.map((anime) => (
              <div key={anime.id} className="group cursor-pointer" onClick={() => setSelectedAnime(anime)}>
                <div className="poster-card card-hover relative border border-border">
                  <img
                    src={getCoverUrl(anime.id)}
                    alt={anime.name_cn || anime.name}
                    loading="lazy"
                    onError={(event) => {
                      (event.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect fill="%231a1a2e" width="200" height="300"/><text x="100" y="150" text-anchor="middle" fill="%2364748b" font-size="14">No Cover</text></svg>'
                    }}
                  />
                  {favSet.has(anime.id) && (
                    <div className="absolute left-2 top-2">
                      <Heart className="h-4 w-4 fill-accent-primary text-accent-primary drop-shadow" />
                    </div>
                  )}
                  {anime.score > 0 && (
                    <div className="absolute right-2 top-2 flex items-center gap-0.5 rounded-md bg-black/60 px-1.5 py-0.5 text-xs font-medium text-accent-gold backdrop-blur-sm">
                      <Star className="h-3 w-3 fill-accent-gold" />
                      {anime.score}
                    </div>
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
                  <div className="absolute bottom-0 left-0 right-0 p-3 opacity-0 transition-opacity group-hover:opacity-100">
                    <p className="line-clamp-2 text-xs font-medium text-white">{anime.name_cn || anime.name}</p>
                  </div>
                </div>
                <p className="mt-2 truncate text-xs font-medium text-text-secondary transition-colors group-hover:text-text-primary">
                  {anime.name_cn || anime.name}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-20 text-center text-text-muted">
            <p>搜索番剧以浏览海报墙</p>
          </div>
        )
      )}
    </div>
  )
}
