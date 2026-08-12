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
  watching: 'bg-accent-cyan/20 text-accent-cyan ring-accent-cyan/30',
  completed: 'bg-success/20 text-success ring-success/30',
  dropped: 'bg-danger/20 text-danger ring-danger/30',
  planned: 'bg-accent-gold/20 text-accent-gold ring-accent-gold/30',
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
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex items-start gap-4 rounded-2xl border border-accent-cyan/20 bg-accent-cyan/10 px-6 py-5 text-sm text-accent-cyan shadow-lg backdrop-blur-md">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
        <div className="space-y-1.5">
          {isAuthenticated && user ? (
            <>
              <p className="text-base font-bold text-white tracking-wide">当前账号：{user.username}</p>
              <p className="text-accent-cyan/80 leading-relaxed">现在开始，收藏已经按账号隔离。你可以继续把旧的共享收藏导入到自己的账号里。</p>
            </>
          ) : (
            <>
              <p className="text-base font-bold text-white tracking-wide">个人收藏已经上线</p>
              <p className="text-accent-cyan/80 leading-relaxed">登录后，收藏会绑定到你的账号，不再和其他访问者共享。旧的共享收藏也可以一键导入。</p>
            </>
          )}
        </div>
      </div>

      {message && (
        <div className={cn('rounded-2xl border px-6 py-4 text-sm font-medium shadow-lg backdrop-blur-md animate-in slide-in-from-top-2', messageTone === 'error' ? 'border-danger/20 bg-danger/10 text-danger shadow-danger/10' : 'border-accent-cyan/20 bg-accent-cyan/10 text-accent-cyan shadow-accent-cyan/10')}>
          {message}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-6 rounded-2xl border border-white/5 bg-white/[0.02] p-4 shadow-sm backdrop-blur-sm">
        <div className="flex gap-2 p-1 rounded-xl bg-black/20">
          {tabs.map((item) => (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={cn(
                'rounded-lg px-6 py-2.5 text-sm font-bold transition-all duration-300',
                tab === item.key
                  ? 'bg-gradient-to-r from-accent-primary to-accent-secondary text-white shadow-md shadow-accent-primary/20'
                  : 'text-text-muted hover:text-white hover:bg-white/5'
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        <form onSubmit={handleSubmit} className="flex w-full max-w-md gap-3 sm:w-auto">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索 Bangumi..."
              className={cn(
                'w-full rounded-xl border border-white/10 bg-black/20 py-2.5 pl-11 pr-4 text-sm font-medium text-white transition-all',
                'focus:border-accent-primary focus:bg-white/5 focus:outline-none focus:ring-2 focus:ring-accent-primary/30 placeholder-text-muted/50'
              )}
            />
          </div>
          <button type="submit" className="rounded-xl bg-white/10 px-6 py-2.5 text-sm font-bold text-white transition-all hover:bg-white/20 hover:shadow-lg border border-white/5">
            搜索
          </button>
        </form>
      </div>

      {selectedAnime && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xl animate-in fade-in duration-300" onClick={() => setSelectedAnime(null)}>
          <div className="relative max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-white/10 bg-bg-primary/90 p-8 shadow-2xl animate-in zoom-in-95" onClick={(event) => event.stopPropagation()}>
            <div className="flex flex-col gap-8 md:flex-row">
              <div className="shrink-0 group overflow-hidden rounded-2xl border border-white/10 shadow-2xl">
                <img
                  src={getCoverUrl(selectedAnime.id)}
                  alt={selectedAnime.name_cn || selectedAnime.name}
                  className="h-[360px] w-60 object-cover transition-transform duration-700 group-hover:scale-105"
                  onError={(event) => {
                    (event.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect fill="%231a1a2e" width="200" height="300"/><text x="100" y="150" text-anchor="middle" fill="%2364748b" font-size="14">No Cover</text></svg>'
                  }}
                />
              </div>
              <div className="flex-1 space-y-6">
                <div className="space-y-2">
                  <h2 className="text-3xl font-black text-white drop-shadow-sm">{selectedAnime.name_cn || selectedAnime.name}</h2>
                  {selectedAnime.name_cn && <p className="text-base font-medium text-text-secondary">{selectedAnime.name}</p>}
                </div>
                
                {selectedAnime.score > 0 && (
                  <div className="inline-flex items-center gap-2 rounded-full border border-accent-gold/20 bg-accent-gold/10 px-4 py-1.5 backdrop-blur-md">
                    <Star className="h-5 w-5 fill-accent-gold text-accent-gold drop-shadow-[0_0_8px_rgba(255,215,0,0.5)]" />
                    <span className="text-base font-bold text-accent-gold">{selectedAnime.score.toFixed(1)}</span>
                  </div>
                )}
                
                <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-5 shadow-inner">
                  <p className="text-sm leading-loose text-text-secondary">{selectedAnime.summary || '暂无简介'}</p>
                </div>
                
                <button
                  onClick={() => void toggleFavorite(selectedAnime)}
                  className={cn(
                    'flex items-center gap-3 rounded-xl px-8 py-3.5 text-base font-bold transition-all duration-300 shadow-lg',
                    favSet.has(selectedAnime.id) 
                      ? 'border border-danger/30 bg-danger/20 text-danger hover:bg-danger/30 hover:scale-105' 
                      : 'bg-gradient-to-r from-accent-primary to-accent-secondary text-white hover:scale-105 hover:shadow-accent-primary/20'
                  )}
                >
                  <Heart className={cn('h-5 w-5 transition-transform duration-300', favSet.has(selectedAnime.id) && 'scale-110 fill-current')} />
                  {!isAuthenticated ? '登录后收藏' : favSet.has(selectedAnime.id) ? '取消收藏' : '加入收藏'}
                </button>
              </div>
            </div>
            <button onClick={() => setSelectedAnime(null)} className="absolute right-6 top-6 rounded-full bg-white/5 p-2 text-text-muted transition-colors hover:bg-white/10 hover:text-white">✕</button>
          </div>
        </div>
      )}

      {tab === 'favorites' ? (
        authLoading ? (
          <div className="flex items-center justify-center py-32">
            <div className="relative">
              <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
              <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
            </div>
          </div>
        ) : !isAuthenticated ? (
          <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
            <AuthPanel />
            <div className="flex flex-col justify-center rounded-3xl border border-white/5 bg-gradient-to-br from-white/[0.05] to-transparent p-10 shadow-2xl backdrop-blur-sm">
              <div className="flex items-center gap-3">
                <div className="rounded-xl bg-accent-gold/20 p-2.5 border border-accent-gold/30">
                  <Sparkles className="h-6 w-6 text-accent-gold drop-shadow-[0_0_8px_rgba(255,215,0,0.8)]" />
                </div>
                <h2 className="text-2xl font-bold text-white tracking-wide">登录后会得到什么</h2>
              </div>
              <div className="mt-8 space-y-5 text-base text-text-secondary">
                <p className="flex items-center gap-3"><span className="h-2 w-2 rounded-full bg-accent-primary shrink-0 shadow-[0_0_8px_rgba(233,69,96,0.8)]" /> 收藏将只属于当前账号，不再和其他访问者混在一起。</p>
                <p className="flex items-center gap-3"><span className="h-2 w-2 rounded-full bg-accent-secondary shrink-0 shadow-[0_0_8px_rgba(15,52,96,0.8)]" /> 旧的共享收藏可以一键导入，不需要重新手动逐个点一遍。</p>
                <p className="flex items-center gap-3"><span className="h-2 w-2 rounded-full bg-accent-cyan shrink-0 shadow-[0_0_8px_rgba(0,255,255,0.8)]" /> 后续如果继续推进，我们也可以把观看记录、订阅和下载偏好一起挂到账号上。</p>
              </div>
            </div>
          </div>
        ) : favorites.length === 0 ? (
          <div className="space-y-8">
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-accent-primary/20 bg-accent-primary/5 p-6 shadow-lg backdrop-blur-sm">
              <div>
                <p className="text-lg font-bold text-white tracking-wide">旧共享收藏还在</p>
                <p className="mt-1 text-sm font-medium text-text-secondary">如果你之前已经积累了一批共享收藏，可以把它们导入到当前账号。</p>
              </div>
              <button
                onClick={() => void handleImportLegacy()}
                disabled={importing}
                className="rounded-xl bg-gradient-to-r from-accent-primary to-accent-secondary px-6 py-3 text-sm font-bold text-white shadow-lg transition-all hover:scale-105 hover:shadow-accent-primary/30 disabled:opacity-50 disabled:hover:scale-100"
              >
                {importing ? '导入中...' : '导入旧共享收藏'}
              </button>
            </div>

            <div className="rounded-3xl border border-white/5 bg-white/[0.01] py-32 text-center shadow-inner">
              <BookOpen className="mx-auto mb-6 h-16 w-16 text-text-muted opacity-20" />
              <p className="text-xl font-bold text-white tracking-wide">这个账号还没有收藏番剧</p>
              <p className="mt-3 text-sm font-medium text-text-muted">切换到「搜索番剧」添加一部，或者先导入旧共享收藏。</p>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/5 bg-white/[0.02] p-6 shadow-sm backdrop-blur-sm">
              <div>
                <p className="text-lg font-bold text-white tracking-wide">我的收藏库</p>
                <p className="mt-1 text-sm font-medium text-text-secondary">下面这些收藏现在只对你自己可见。</p>
              </div>
              <button
                onClick={() => void handleImportLegacy()}
                disabled={importing}
                className="rounded-xl border border-white/10 bg-white/5 px-6 py-3 text-sm font-bold text-white transition-all hover:bg-white/10 hover:shadow-md disabled:opacity-50"
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
                  <div className="relative aspect-[3/4] overflow-hidden rounded-2xl border border-white/10 bg-bg-secondary shadow-lg transition-all duration-500 group-hover:-translate-y-2 group-hover:border-white/20 group-hover:shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
                    <img
                      src={getCoverUrl(fav.bangumi_id)}
                      alt={fav.name_cn || fav.name}
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110"
                      onError={(event) => {
                        (event.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect fill="%231a1a2e" width="200" height="300"/><text x="100" y="150" text-anchor="middle" fill="%2364748b" font-size="14">No Cover</text></svg>'
                      }}
                    />
                    <div className="absolute left-2 top-2 z-10">
                      <select
                        value={fav.status}
                        onChange={(event) => {
                          event.stopPropagation()
                          void handleStatusChange(fav.bangumi_id, event.target.value)
                        }}
                        onClick={(event) => event.stopPropagation()}
                        className={cn('cursor-pointer rounded-lg border-0 px-2.5 py-1 text-xs font-bold ring-1 backdrop-blur-md transition-all hover:brightness-110 focus:ring-2', statusColors[fav.status] || 'bg-black/60 text-white ring-white/20')}
                      >
                        {Object.entries(statusLabels).map(([key, label]) => (
                          <option key={key} value={key} className="bg-bg-primary text-white">{label}</option>
                        ))}
                      </select>
                    </div>
                    {fav.score > 0 && (
                      <div className="absolute right-2 top-2 z-10 flex items-center gap-1 rounded-lg border border-accent-gold/20 bg-black/60 px-2 py-1 text-xs font-bold text-accent-gold shadow-sm backdrop-blur-md">
                        <Star className="h-3.5 w-3.5 fill-accent-gold drop-shadow-[0_0_5px_rgba(255,215,0,0.8)]" />
                        {fav.score.toFixed(1)}
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black via-black/20 to-transparent opacity-60 transition-opacity duration-300 group-hover:opacity-80" />
                    <div className="absolute bottom-0 left-0 right-0 p-3 opacity-0 transition-all duration-300 group-hover:opacity-100 group-hover:translate-y-0 translate-y-2">
                       <p className="text-center text-xs font-bold text-white bg-white/10 backdrop-blur-md border border-white/20 rounded-lg py-1.5 shadow-lg">查看详情</p>
                    </div>
                  </div>
                  <p className="mt-3 truncate text-sm font-bold text-white transition-colors group-hover:text-accent-primary px-1">
                    {fav.name_cn || fav.name}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )
      ) : (
        loading ? (
          <div className="flex items-center justify-center py-32">
            <div className="relative">
              <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
              <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
            </div>
          </div>
        ) : animes.length > 0 ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {animes.map((anime) => (
              <div key={anime.id} className="group cursor-pointer" onClick={() => setSelectedAnime(anime)}>
                <div className="relative aspect-[3/4] overflow-hidden rounded-2xl border border-white/10 bg-bg-secondary shadow-lg transition-all duration-500 group-hover:-translate-y-2 group-hover:border-white/20 group-hover:shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
                  <img
                    src={getCoverUrl(anime.id)}
                    alt={anime.name_cn || anime.name}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110"
                    onError={(event) => {
                      (event.target as HTMLImageElement).src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300"><rect fill="%231a1a2e" width="200" height="300"/><text x="100" y="150" text-anchor="middle" fill="%2364748b" font-size="14">No Cover</text></svg>'
                    }}
                  />
                  {favSet.has(anime.id) && (
                    <div className="absolute left-2 top-2 z-10 rounded-full bg-black/40 p-1.5 backdrop-blur-md">
                      <Heart className="h-4 w-4 fill-accent-primary text-accent-primary drop-shadow-[0_0_8px_rgba(233,69,96,0.8)]" />
                    </div>
                  )}
                  {anime.score > 0 && (
                    <div className="absolute right-2 top-2 z-10 flex items-center gap-1 rounded-lg border border-accent-gold/20 bg-black/60 px-2 py-1 text-xs font-bold text-accent-gold shadow-sm backdrop-blur-md">
                      <Star className="h-3.5 w-3.5 fill-accent-gold drop-shadow-[0_0_5px_rgba(255,215,0,0.8)]" />
                      {anime.score.toFixed(1)}
                    </div>
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-black via-black/20 to-transparent opacity-60 transition-opacity duration-300 group-hover:opacity-80" />
                  <div className="absolute bottom-0 left-0 right-0 p-4 translate-y-4 opacity-0 transition-all duration-300 group-hover:translate-y-0 group-hover:opacity-100">
                    <p className="line-clamp-2 text-sm font-bold leading-snug text-white drop-shadow-md">{anime.name_cn || anime.name}</p>
                  </div>
                </div>
                <p className="mt-3 truncate text-sm font-bold text-white transition-colors group-hover:text-accent-primary px-1">
                  {anime.name_cn || anime.name}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-3xl border border-white/5 bg-white/[0.01] py-32 text-center shadow-inner">
            <Search className="mx-auto mb-6 h-16 w-16 text-text-muted opacity-20" />
            <p className="text-xl font-bold text-white tracking-wide">搜索番剧以浏览海报墙</p>
            <p className="mt-3 text-sm font-medium text-text-muted">输入 Bangumi 链接或关键词进行搜索</p>
          </div>
        )
      )}
    </div>
  )
}
