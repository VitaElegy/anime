interface AnimeLinkInput {
  bangumi_id?: number
  title?: string
  raw_title?: string
  cover_url?: string
  page?: string
}

export function buildAnimeHref(entry: AnimeLinkInput): string {
  const params = new URLSearchParams()
  if (entry.title) params.set('title', entry.title)
  if (entry.raw_title) params.set('rawTitle', entry.raw_title)
  if (entry.cover_url) params.set('cover', entry.cover_url)
  if (entry.page) params.set('page', entry.page)

  const subjectId = entry.bangumi_id || 0
  const query = params.toString()
  return query ? `/anime/${subjectId}?${query}` : `/anime/${subjectId}`
}
