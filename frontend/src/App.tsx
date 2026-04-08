import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { lazy, Suspense } from 'react'
import { Loader2 } from 'lucide-react'

const HomePage = lazy(() => import('./pages/HomePage'))
const SearchPage = lazy(() => import('./pages/SearchPage'))
const DownloadsPage = lazy(() => import('./pages/DownloadsPage'))
const LibraryPage = lazy(() => import('./pages/LibraryPage'))
const CalendarPage = lazy(() => import('./pages/CalendarPage'))
const CrawlPage = lazy(() => import('./pages/CrawlPage'))
const WatchPartyPage = lazy(() => import('./pages/WatchPartyPage'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/downloads" element={<DownloadsPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/crawl" element={<CrawlPage />} />
          <Route path="/watchparty" element={<WatchPartyPage />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
