import { useState, useEffect } from 'react'
import { Search, Star, Heart, Loader2, BookOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { onCoverError } from '@/lib/utils'
import { searchMetadata, getCoverUrl, getFavorites, addFavorite, removeFavorite, updateFavorite } from '@/api'
import type { AnimeMetadata } from '@/types'

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

interface Favorite {
  bangumi_id: number
  name_cn: string
  name: string
  cover_url: string
  score: number
  status: string
  episode_progress: number
  total_episodes: number
}

export default function LibraryPage() {
  const [tab, setTab] = useState<ViewTab>('favorites')
  const [query, setQuery] = useState('')
  const [animes, setAnimes] = useState<AnimeMetadata[]>([])
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedAnime, setSelectedAnime] = useState<AnimeMetadata | null>(null)
  const [favSet, setFavSet] = useState<Set<number>>(new Set())

  const loadFavorites = async () => {
    try {
      const data = await getFavorites()
      const favs = data as unknown as Favorite[]
      setFavorites(favs)
      setFavSet(new Set(favs.map((f) => f.bangumi_id)))
    } catch {
      // silent
    }
  }

  useEffect(() => {
    loadFavorites()
  }, [])

  const doSearch = async (q: string) => {
    if (!q.trim()) return
    setLoading(true)
    try {
      const results = await searchMetadata(q)
      setAnimes(results)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setTab('search')
    doSearch(query)
  }

  const toggleFavorite = async (anime: AnimeMetadata) => {
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
    loadFavorites()
  }

  const handleStatusChange = async (bangumiId: number, status: string) => {
    await updateFavorite(bangumiId, { status })
    loadFavorites()
  }

  const tabs: { key: ViewTab; label: string }[] = [
    { key: 'favorites', label: '我的收藏' },
    { key: 'search', label: '搜索番剧' },
  ]

  return (
    <div className="space-y-6">
      {/* Top bar */}
      <div className="flex items-center gap-6">
        <div className="flex gap-4 border-b border-border">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                'pb-2 text-sm font-medium border-b-2 transition-colors',
                tab === t.key
                  ? 'border-accent-primary text-accent-primary'
                  : 'border-transparent text-text-muted hover:text-text-secondary'
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <form onSubmit={handleSubmit} className="flex flex-1 gap-3 max-w-md">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索 Bangumi..."
              className={cn(
                'w-full rounded-xl border border-border bg-bg-card py-2 pl-10 pr-4 text-sm',
                'focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary/50'
              )}
            />
          </div>
          <button type="submit" className="rounded-xl bg-accent-secondary px-4 py-2 text-sm font-medium text-white hover:bg-accent-secondary/90 transition-colors">
            搜索
          </button>
        </form>
      </div>

      {/* Detail modal */}
      {selectedAnime && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setSelectedAnime(null)}>
          <div className="relative max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-bg-secondary border border-border p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex gap-6">
              <img src={getCoverUrl(selectedAnime.id)} alt={selectedAnime.name_cn || selectedAnime.name} className="h-64 w-44 shrink-0 rounded-xl object-cover"
                onError={onCoverError} />
              <div className="flex-1 space-y-3">
                <h2 className="text-xl font-bold">{selectedAnime.name_cn || selectedAnime.name}</h2>
                {selectedAnime.name_cn && <p className="text-sm text-text-secondary">{selectedAnime.name}</p>}
                {selectedAnime.score > 0 && (
                  <div className="flex items-center gap-1.5">
                    <Star className="h-4 w-4 text-accent-gold fill-accent-gold" />
                    <span className="text-sm font-medium">{selectedAnime.score}</span>
                  </div>
                )}
                <p className="text-sm text-text-secondary leading-relaxed">{selectedAnime.summary || '暂无简介'}</p>
                <button
                  onClick={() => toggleFavorite(selectedAnime)}
                  className={cn('flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                    favSet.has(selectedAnime.id) ? 'bg-danger/10 text-danger' : 'bg-accent-primary/10 text-accent-primary'
                  )}
                >
                  <Heart className={cn('h-4 w-4', favSet.has(selectedAnime.id) && 'fill-current')} />
                  {favSet.has(selectedAnime.id) ? '取消收藏' : '加入收藏'}
                </button>
              </div>
            </div>
            <button onClick={() => setSelectedAnime(null)} className="absolute right-4 top-4 rounded-lg p-1 text-text-muted hover:text-text-primary">✕</button>
          </div>
        </div>
      )}

      {tab === 'favorites' ? (
        /* ===== Favorites ===== */
        favorites.length === 0 ? (
          <div className="text-center py-20 text-text-muted">
            <BookOpen className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p>还没有收藏番剧</p>
            <p className="text-xs mt-1">切换到「搜索番剧」添加收藏吧</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {favorites.map((fav) => (
              <div key={fav.bangumi_id} className="group cursor-pointer" onClick={() => {
                setSelectedAnime({ id: fav.bangumi_id, name_cn: fav.name_cn, name: fav.name, cover_url: fav.cover_url, score: fav.score, summary: '', cover_local: '' })
              }}>
                <div className="poster-card card-hover border border-border relative">
                  <img src={getCoverUrl(fav.bangumi_id)} alt={fav.name_cn || fav.name} loading="lazy"
                    onError={onCoverError} />
                  <div className="absolute top-2 left-2">
                    <select
                      value={fav.status}
                      onChange={(e) => { e.stopPropagation(); handleStatusChange(fav.bangumi_id, e.target.value) }}
                      onClick={(e) => e.stopPropagation()}
                      className={cn('rounded-md px-1.5 py-0.5 text-[10px] font-medium backdrop-blur-sm border-0 cursor-pointer', statusColors[fav.status] || 'bg-bg-card/80 text-text-muted')}
                    >
                      {Object.entries(statusLabels).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </div>
                  {fav.score > 0 && (
                    <div className="absolute top-2 right-2 flex items-center gap-0.5 rounded-md bg-black/60 px-1.5 py-0.5 text-xs font-medium text-accent-gold backdrop-blur-sm">
                      <Star className="h-3 w-3 fill-accent-gold" />{fav.score}
                    </div>
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <p className="mt-2 text-xs font-medium truncate text-text-secondary group-hover:text-text-primary transition-colors">
                  {fav.name_cn || fav.name}
                </p>
              </div>
            ))}
          </div>
        )
      ) : (
        /* ===== Search ===== */
        loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
          </div>
        ) : animes.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {animes.map((anime) => (
              <div key={anime.id} className="group cursor-pointer" onClick={() => setSelectedAnime(anime)}>
                <div className="poster-card card-hover border border-border relative">
                  <img src={getCoverUrl(anime.id)} alt={anime.name_cn || anime.name} loading="lazy"
                    onError={onCoverError} />
                  {favSet.has(anime.id) && (
                    <div className="absolute top-2 left-2">
                      <Heart className="h-4 w-4 text-accent-primary fill-accent-primary drop-shadow" />
                    </div>
                  )}
                  {anime.score > 0 && (
                    <div className="absolute top-2 right-2 flex items-center gap-0.5 rounded-md bg-black/60 px-1.5 py-0.5 text-xs font-medium text-accent-gold backdrop-blur-sm">
                      <Star className="h-3 w-3 fill-accent-gold" />{anime.score}
                    </div>
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                  <div className="absolute bottom-0 left-0 right-0 p-3 opacity-0 group-hover:opacity-100 transition-opacity">
                    <p className="text-xs font-medium text-white line-clamp-2">{anime.name_cn || anime.name}</p>
                  </div>
                </div>
                <p className="mt-2 text-xs font-medium truncate text-text-secondary group-hover:text-text-primary transition-colors">
                  {anime.name_cn || anime.name}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-20 text-text-muted"><p>搜索番剧以浏览海报墙</p></div>
        )
      )}
    </div>
  )
}
