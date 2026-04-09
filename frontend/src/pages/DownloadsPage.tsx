import { useEffect, useState, useRef } from 'react'
import { Pause, Play, Trash2, RefreshCw, Loader2, Folder, FolderOpen, File, ChevronRight, Settings, ArrowLeft, HardDrive, Check } from 'lucide-react'
import { cn, formatBytes, formatEta } from '@/lib/utils'
import { getDownloadProgress, pauseTorrent, resumeTorrent, deleteTorrent, getDownloadSettings, updateDownloadSettings, listDownloadedFiles, deleteDownloadedFile } from '@/api'
import type { DownloadTask } from '@/types'
import type { FileItem } from '@/api'

type Tab = 'active' | 'files' | 'settings'

const ENGINE_LABELS: Record<string, { label: string; cls: string }> = {
  qbittorrent: { label: 'qBittorrent', cls: 'bg-accent-cyan/10 text-accent-cyan' },
  aria2: { label: 'aria2 (内置)', cls: 'bg-accent-secondary/10 text-accent-secondary' },
}

const stateLabels: Record<string, string> = {
  downloading: '下载中', stalledDL: '搜索节点', uploading: '做种中', stalledUP: '已完成',
  pausedDL: '已暂停', pausedUP: '已暂停', queuedDL: '排队中', queuedUP: '排队中',
  checking: '校验中', error: '错误', missingFiles: '文件丢失',
}

function stateColor(state: string): string {
  if (state.includes('download') || state === 'stalledDL') return 'text-accent-cyan'
  if (state.includes('paused')) return 'text-warning'
  if (state.includes('upload') || state === 'stalledUP') return 'text-success'
  if (state === 'error' || state === 'missingFiles') return 'text-danger'
  return 'text-text-muted'
}

function formatDate(ts: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const CATEGORY_ICONS: Record<string, string> = {
  video: '🎬',
  audio: '🎵',
  subtitle: '📝',
  archive: '📦',
  image: '🖼️',
  other: '📄',
}

export default function DownloadsPage() {
  const [tab, setTab] = useState<Tab>('active')
  const [tasks, setTasks] = useState<DownloadTask[]>([])
  const [loading, setLoading] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tasksRef = useRef<DownloadTask[]>([])
  const [engineName, setEngineName] = useState('')

  // Files tab
  const [files, setFiles] = useState<FileItem[]>([])
  const [currentDir, setCurrentDir] = useState('')
  const [parentDir, setParentDir] = useState('')
  const [currentPath, setCurrentPath] = useState('')
  const [filesLoading, setFilesLoading] = useState(false)

  // Settings tab
  const [downloadDir, setDownloadDir] = useState('')
  const [dirInput, setDirInput] = useState('')
  const [freeSpace, setFreeSpace] = useState(0)
  const [settingsSaved, setSettingsSaved] = useState(false)

  // ── Active downloads ──
  const refresh = async () => {
    try {
      const data = await getDownloadProgress()
      setTasks(data)
      tasksRef.current = data
    } catch (err) {
      console.error('[Downloads] refresh error:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    setTimeout(() => {
      fetch('/api/download/engine').then(r => r.json()).then(d => setEngineName(d.engine || '')).catch(() => {})
    }, 500)

    const startPolling = () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      const hasActive = tasksRef.current.some(t =>
        t.state.includes('download') || t.state === 'stalledDL' || t.state.includes('queued') || t.state === 'checking'
      )
      intervalRef.current = setInterval(refresh, hasActive ? 3000 : 10000)
    }
    startPolling()
    const adjustInterval = setInterval(() => startPolling(), 5000)

    const onVisibility = () => {
      if (document.hidden) {
        if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
      } else { refresh(); startPolling() }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      clearInterval(adjustInterval)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  const handlePause = async (hash: string) => { try { await pauseTorrent(hash) } catch {} refresh() }
  const handleResume = async (hash: string) => { try { await resumeTorrent(hash) } catch {} refresh() }
  const handleDelete = async (hash: string) => {
    if (!confirm('确定删除此任务？')) return
    try { await deleteTorrent(hash, false) } catch {} refresh()
  }

  // ── Files tab ──
  const loadFiles = async (subdir = '') => {
    setFilesLoading(true)
    try {
      const data = await listDownloadedFiles(subdir)
      setFiles(data.items)
      setCurrentDir(data.relative)
      setParentDir(data.parent)
      setCurrentPath(data.path)
    } catch { /* silent */ }
    finally { setFilesLoading(false) }
  }

  const handleDeleteFile = async (path: string, name: string) => {
    if (!confirm(`确定删除「${name}」？`)) return
    try { await deleteDownloadedFile(path); loadFiles(currentDir) } catch {}
  }

  useEffect(() => { if (tab === 'files') loadFiles(currentDir) }, [tab])

  // ── Settings tab ──
  const loadSettings = async () => {
    try {
      const data = await getDownloadSettings()
      setDownloadDir(data.download_dir)
      setDirInput(data.download_dir)
      setFreeSpace(data.free_space)
    } catch {}
  }

  const saveSettings = async () => {
    try {
      const data = await updateDownloadSettings(dirInput)
      setDownloadDir(data.download_dir)
      setFreeSpace(data.free_space)
      setSettingsSaved(true)
      setTimeout(() => setSettingsSaved(false), 2000)
    } catch {}
  }

  useEffect(() => { if (tab === 'settings') loadSettings() }, [tab])

  if (loading && tab === 'active') {
    return <div className="flex items-center justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-accent-primary" /></div>
  }

  const activeTasks = tasks.filter(t => !['stalledUP'].includes(t.state))
  const completedTasks = tasks.filter(t => t.state === 'stalledUP')

  return (
    <div className="max-w-5xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-bold">下载管理</h1>
          {engineName && (() => {
            const cfg = ENGINE_LABELS[engineName] || { label: engineName, cls: 'bg-bg-card text-text-muted' }
            return <span className={cn('text-[10px] px-2 py-0.5 rounded-full font-medium', cfg.cls)}>{cfg.label}</span>
          })()}
        </div>
        <button onClick={tab === 'files' ? () => loadFiles(currentDir) : refresh}
          className="flex items-center gap-1.5 rounded-lg bg-bg-card border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors">
          <RefreshCw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {([
          ['active', `下载中 (${activeTasks.length})`, undefined],
          ['files', '已下载文件', undefined],
          ['settings', '设置', undefined],
        ] as const).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key as Tab)}
            className={cn('px-4 py-2 text-sm font-medium border-b-2 transition-colors',
              tab === key ? 'border-accent-primary text-accent-primary' : 'border-transparent text-text-muted hover:text-text-secondary')}>
            {label}
          </button>
        ))}
      </div>

      {/* ═══ Active Downloads Tab ═══ */}
      {tab === 'active' && (
        <div className="space-y-4">
          {activeTasks.length === 0 && completedTasks.length === 0 ? (
            <div className="text-center py-16 text-text-muted">
              <Play className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>暂无下载任务</p>
              <p className="text-xs mt-1">去搜索页添加一些下载吧</p>
            </div>
          ) : (
            <>
              {activeTasks.length > 0 && (
                <div className="space-y-3">
                  {activeTasks.map((task) => {
                    const isPaused = task.state.includes('paused')
                    const pct = (task.progress * 100).toFixed(1)
                    return (
                      <div key={task.hash} className="rounded-xl bg-bg-card border border-border p-4 space-y-3">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium truncate">{task.name || task.hash}</p>
                            <div className="flex items-center gap-3 mt-1 text-xs text-text-muted">
                              <span className={stateColor(task.state)}>{stateLabels[task.state] || task.state}</span>
                              <span>{formatBytes(task.size)}</span>
                              {task.speed > 0 && <span>{formatBytes(task.speed)}/s</span>}
                              {task.eta > 0 && <span>剩余 {formatEta(task.eta)}</span>}
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-1">
                            {isPaused ? (
                              <button onClick={() => handleResume(task.hash)} className="rounded-lg p-2 text-success hover:bg-success/10 transition-colors" title="恢复"><Play className="h-4 w-4" /></button>
                            ) : (
                              <button onClick={() => handlePause(task.hash)} className="rounded-lg p-2 text-warning hover:bg-warning/10 transition-colors" title="暂停"><Pause className="h-4 w-4" /></button>
                            )}
                            <button onClick={() => handleDelete(task.hash)} className="rounded-lg p-2 text-danger hover:bg-danger/10 transition-colors" title="删除"><Trash2 className="h-4 w-4" /></button>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <div className="h-2 rounded-full bg-bg-primary overflow-hidden">
                            <div className={cn('h-full rounded-full transition-all duration-500', isPaused ? 'bg-warning' : 'bg-gradient-to-r from-accent-cyan to-accent-primary')} style={{ width: `${pct}%` }} />
                          </div>
                          <p className="text-right text-xs text-text-muted">{pct}%</p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              {completedTasks.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-text-muted">已完成 ({completedTasks.length})</p>
                  {completedTasks.map((task) => (
                    <div key={task.hash} className="flex items-center gap-3 rounded-xl bg-bg-card border border-border p-3">
                      <div className="h-8 w-8 rounded-lg bg-success/10 flex items-center justify-center shrink-0"><Check className="h-4 w-4 text-success" /></div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">{task.name}</p>
                        <p className="text-xs text-text-muted">{formatBytes(task.size)}</p>
                      </div>
                      <button onClick={() => handleDelete(task.hash)} className="rounded-lg p-2 text-danger/50 hover:text-danger hover:bg-danger/10 transition-colors" title="删除任务"><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ═══ Files Tab ═══ */}
      {tab === 'files' && (
        <div className="space-y-3">
          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 text-xs text-text-muted">
            <button onClick={() => loadFiles('')} className="hover:text-accent-primary transition-colors flex items-center gap-1">
              <HardDrive className="h-3.5 w-3.5" /> 下载目录
            </button>
            {currentDir && currentDir.split('/').filter(Boolean).map((part, i, arr) => {
              const subPath = arr.slice(0, i + 1).join('/')
              return (
                <span key={i} className="flex items-center gap-1.5">
                  <ChevronRight className="h-3 w-3" />
                  <button onClick={() => loadFiles(subPath)} className="hover:text-accent-primary transition-colors">{part}</button>
                </span>
              )
            })}
          </div>

          {/* Back button */}
          {currentDir && (
            <button onClick={() => loadFiles(parentDir)} className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors">
              <ArrowLeft className="h-3.5 w-3.5" /> 返回上级
            </button>
          )}

          {filesLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-accent-primary" /></div>
          ) : files.length === 0 ? (
            <div className="text-center py-16 text-text-muted">
              <Folder className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>目录为空</p>
              <p className="text-xs mt-1">下载目录: {currentPath}</p>
            </div>
          ) : (
            <div className="space-y-1">
              {files.map((item) => (
                <div key={item.path} className="flex items-center gap-3 rounded-lg bg-bg-card border border-border p-3 hover:border-border-hover transition-colors group">
                  {item.type === 'dir' ? (
                    <button onClick={() => loadFiles(item.path)} className="flex items-center gap-3 flex-1 min-w-0 text-left">
                      <FolderOpen className="h-5 w-5 text-accent-gold shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">{item.name}</p>
                        <p className="text-xs text-text-muted">
                          {item.video_count ? `${item.video_count} 个视频` : `${item.file_count} 个文件`} · {formatBytes(item.size)}
                        </p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-text-muted shrink-0" />
                    </button>
                  ) : (
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <span className="text-lg shrink-0">{CATEGORY_ICONS[item.category || 'other'] || '📄'}</span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm truncate">{item.name}</p>
                        <p className="text-xs text-text-muted">{formatBytes(item.size)} · {formatDate(item.modified)}</p>
                      </div>
                    </div>
                  )}
                  <button onClick={() => handleDeleteFile(item.path, item.name)}
                    className="rounded-lg p-1.5 text-text-muted opacity-0 group-hover:opacity-100 hover:text-danger hover:bg-danger/10 transition-all" title="删除">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ═══ Settings Tab ═══ */}
      {tab === 'settings' && (
        <div className="space-y-6 max-w-2xl">
          <div className="rounded-xl bg-bg-card border border-border p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Settings className="h-5 w-5 text-text-secondary" />
              <h2 className="text-sm font-semibold">下载目录</h2>
            </div>
            <div className="space-y-3">
              <div className="flex gap-2">
                <input type="text" value={dirInput} onChange={(e) => setDirInput(e.target.value)}
                  placeholder="输入下载目录路径..."
                  className={cn('flex-1 rounded-lg border border-border bg-bg-primary py-2 px-3 text-sm',
                    'focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary/50')} />
                <button onClick={saveSettings}
                  disabled={dirInput === downloadDir}
                  className={cn('rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                    dirInput === downloadDir
                      ? 'bg-bg-hover text-text-muted cursor-not-allowed'
                      : 'bg-accent-primary text-white hover:bg-accent-primary/90')}>
                  {settingsSaved ? '已保存 ✓' : '保存'}
                </button>
              </div>
              <div className="flex items-center gap-4 text-xs text-text-muted">
                <span>当前: <code className="bg-bg-primary px-1.5 py-0.5 rounded">{downloadDir}</code></span>
                {freeSpace > 0 && <span>可用空间: <strong className="text-text-secondary">{formatBytes(freeSpace)}</strong></span>}
              </div>
            </div>
          </div>

          <div className="rounded-xl bg-bg-card border border-border p-5 space-y-3">
            <h2 className="text-sm font-semibold">下载引擎</h2>
            <div className="text-xs text-text-muted space-y-1.5">
              <p>当前引擎: <strong className="text-text-secondary">{engineName || '未知'}</strong></p>
              <p>• <strong>aria2 (内置)</strong> — 零配置，自动下载安装，支持 BT/磁力链接</p>
              <p>• <strong>qBittorrent</strong> — 功能更全，需自行安装并开启 WebUI</p>
              <p className="text-text-muted/60">系统自动选择可用引擎，优先使用 qBittorrent</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
