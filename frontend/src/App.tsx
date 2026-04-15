import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

const HomePage = lazy(() => import('./pages/HomePage'))
const SearchPage = lazy(() => import('./pages/SearchPage'))
const DownloadsPage = lazy(() => import('./pages/DownloadsPage'))
const LibraryPage = lazy(() => import('./pages/LibraryPage'))
const CalendarPage = lazy(() => import('./pages/CalendarPage'))
const AnimeDetailPage = lazy(() => import('./pages/AnimeDetailPage'))
const CrawlPage = lazy(() => import('./pages/CrawlPage'))
const WatchPartyPage = lazy(() => import('./pages/WatchPartyPage'))
const WatchRoomPage = lazy(() => import('./pages/WatchRoomPage'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
    </div>
  )
}

function withPageSuspense(node: ReactNode) {
  return <Suspense fallback={<PageLoader />}>{node}</Suspense>
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={withPageSuspense(<HomePage />)} />
        <Route path="/search" element={withPageSuspense(<SearchPage />)} />
        <Route path="/downloads" element={withPageSuspense(<DownloadsPage />)} />
        <Route path="/library" element={withPageSuspense(<LibraryPage />)} />
        <Route path="/calendar" element={withPageSuspense(<CalendarPage />)} />
        <Route path="/anime/:subjectId" element={withPageSuspense(<AnimeDetailPage />)} />
        <Route path="/crawl" element={withPageSuspense(<CrawlPage />)} />
        <Route path="/watch" element={withPageSuspense(<WatchPartyPage />)} />
        <Route path="/watch/:roomId" element={withPageSuspense(<WatchRoomPage />)} />
      </Route>
    </Routes>
  )
}
