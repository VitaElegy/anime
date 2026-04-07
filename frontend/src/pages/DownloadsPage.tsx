import { useEffect, useState, useRef } from 'react'
import { Pause, Play, Trash2, RefreshCw, Loader2 } from 'lucide-react'
import { cn, formatBytes, formatEta } from '@/lib/utils'
import { getDownloadProgress, pauseTorrent, resumeTorrent, deleteTorrent } from '@/api'
import type { DownloadTask } from '@/types'

const stateLabels: Record<string, string> = {
  downloading: '下载中',
  stalledDL: '等待连接',
  uploading: '做种中',
  stalledUP: '已完成',
  pausedDL: '已暂停',
  pausedUP: '已暂停',
  queuedDL: '排队中',
  queuedUP: '排队中',
  checking: '校验中',
  error: '错误',
  missingFiles: '文件丢失',
}

function stateColor(state: string): string {
  if (state.includes('download') || state === 'stalledDL') return 'text-accent-cyan'
  if (state.includes('paused')) return 'text-warning'
  if (state.includes('upload') || state === 'stalledUP') return 'text-success'
  if (state === 'error' || state === 'missingFiles') return 'text-danger'
  return 'text-text-muted'
}

export default function DownloadsPage() {
  const [tasks, setTasks] = useState<DownloadTask[]>([])
  const [loading, setLoading] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = async () => {
    try {
      const data = await getDownloadProgress()
      setTasks(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, 3000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  const handlePause = async (hash: string) => {
    await pauseTorrent(hash)
    refresh()
  }

  const handleResume = async (hash: string) => {
    await resumeTorrent(hash)
    refresh()
  }

  const handleDelete = async (hash: string) => {
    if (!confirm('确定删除此任务？')) return
    await deleteTorrent(hash, false)
    refresh()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-accent-primary" />
      </div>
    )
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">下载管理</h1>
        <button
          onClick={refresh}
          className="flex items-center gap-1.5 rounded-lg bg-bg-card border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {tasks.length === 0 ? (
        <div className="text-center py-20 text-text-muted">
          <Play className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>暂无下载任务</p>
          <p className="text-xs mt-1">去搜索页添加一些下载吧</p>
        </div>
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => {
            const isPaused = task.state.includes('paused')
            const pct = (task.progress * 100).toFixed(1)

            return (
              <div key={task.hash} className="rounded-xl bg-bg-card border border-border p-4 space-y-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{task.name || task.hash}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-text-muted">
                      <span className={stateColor(task.state)}>
                        {stateLabels[task.state] || task.state}
                      </span>
                      <span>{formatBytes(task.size)}</span>
                      {task.speed > 0 && <span>{formatBytes(task.speed)}/s</span>}
                      {task.eta > 0 && <span>剩余 {formatEta(task.eta)}</span>}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {isPaused ? (
                      <button
                        onClick={() => handleResume(task.hash)}
                        className="rounded-lg p-2 text-success hover:bg-success/10 transition-colors"
                        title="恢复"
                      >
                        <Play className="h-4 w-4" />
                      </button>
                    ) : (
                      <button
                        onClick={() => handlePause(task.hash)}
                        className="rounded-lg p-2 text-warning hover:bg-warning/10 transition-colors"
                        title="暂停"
                      >
                        <Pause className="h-4 w-4" />
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(task.hash)}
                      className="rounded-lg p-2 text-danger hover:bg-danger/10 transition-colors"
                      title="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="space-y-1">
                  <div className="h-2 rounded-full bg-bg-primary overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all duration-500',
                        isPaused
                          ? 'bg-warning'
                          : 'bg-gradient-to-r from-accent-cyan to-accent-primary'
                      )}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <p className="text-right text-xs text-text-muted">{pct}%</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
