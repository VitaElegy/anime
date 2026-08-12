import { useEffect, useState, useRef } from 'react'
import { Pause, Play, Trash2, RefreshCw, Loader2, Download as DownloadIcon } from 'lucide-react'
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
      <div className="flex items-center justify-center py-32">
        <div className="relative">
          <Loader2 className="h-12 w-12 animate-spin text-accent-primary" />
          <div className="absolute inset-0 animate-pulse rounded-full bg-accent-primary opacity-50 blur-xl"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-8 animate-in fade-in duration-500">
      
      <div className="relative overflow-hidden rounded-[2rem] border border-white/10 bg-black/40 p-8 shadow-2xl backdrop-blur-xl">
        <div className="absolute inset-0 bg-gradient-to-br from-accent-primary/10 via-transparent to-accent-cyan/10" />
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-center gap-4">
             <div className="rounded-xl bg-accent-primary/20 p-3 border border-accent-primary/30 shadow-inner">
               <DownloadIcon className="h-6 w-6 text-accent-primary" />
             </div>
             <div>
               <h1 className="text-3xl font-black text-white tracking-wide">下载管理</h1>
               <p className="text-sm font-medium text-white/60 mt-1">管理你的离线缓存进度</p>
             </div>
          </div>
          <button
            onClick={refresh}
            className="group flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-6 py-3 text-sm font-bold text-white shadow-lg transition-all hover:bg-white/10 hover:shadow-xl hover:scale-105"
          >
            <RefreshCw className="h-4 w-4 transition-transform duration-500 group-hover:rotate-180" /> 刷新
          </button>
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="rounded-3xl border border-white/5 bg-white/[0.01] py-32 text-center shadow-inner backdrop-blur-sm">
          <Play className="mx-auto mb-6 h-16 w-16 text-text-muted opacity-20" />
          <p className="text-xl font-bold text-white tracking-wide">暂无下载任务</p>
          <p className="mt-3 text-sm font-medium text-text-muted">去搜索页添加一些下载吧</p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {tasks.map((task) => {
            const isPaused = task.state.includes('paused')
            const pct = (task.progress * 100).toFixed(1)

            return (
              <div key={task.hash} className="group relative overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] p-6 shadow-lg backdrop-blur-md transition-all hover:border-white/10 hover:bg-white/[0.04]">
                <div className="absolute inset-0 bg-gradient-to-r from-accent-cyan/0 via-accent-cyan/5 to-accent-cyan/0 opacity-0 transition-opacity duration-500 group-hover:opacity-100 translate-x-[-100%] group-hover:translate-x-[100%]" />
                
                <div className="relative z-10 flex flex-col gap-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1 space-y-2">
                      <p className="text-lg font-bold text-white leading-snug break-all">{task.name || task.hash}</p>
                      <div className="flex flex-wrap items-center gap-3 text-xs font-bold text-white/60">
                        <span className={cn('rounded-md px-2 py-1 border shadow-sm backdrop-blur-sm', 
                            stateColor(task.state).includes('success') ? 'bg-success/20 text-success border-success/30' :
                            stateColor(task.state).includes('danger') ? 'bg-danger/20 text-danger border-danger/30' :
                            stateColor(task.state).includes('warning') ? 'bg-warning/20 text-warning border-warning/30' :
                            'bg-accent-cyan/20 text-accent-cyan border-accent-cyan/30'
                        )}>
                          {stateLabels[task.state] || task.state}
                        </span>
                        <span className="rounded-md bg-white/10 px-2 py-1">{formatBytes(task.size)}</span>
                        {task.speed > 0 && <span className="rounded-md bg-white/10 px-2 py-1">{formatBytes(task.speed)}/s</span>}
                        {task.eta > 0 && <span className="rounded-md bg-white/10 px-2 py-1">剩余 {formatEta(task.eta)}</span>}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      {isPaused ? (
                        <button
                          onClick={() => handleResume(task.hash)}
                          className="rounded-xl border border-success/30 bg-success/20 p-2.5 text-success transition-all hover:scale-105 hover:bg-success/30 shadow-md"
                          title="恢复"
                        >
                          <Play className="h-5 w-5" />
                        </button>
                      ) : (
                        <button
                          onClick={() => handlePause(task.hash)}
                          className="rounded-xl border border-warning/30 bg-warning/20 p-2.5 text-warning transition-all hover:scale-105 hover:bg-warning/30 shadow-md"
                          title="暂停"
                        >
                          <Pause className="h-5 w-5" />
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(task.hash)}
                        className="rounded-xl border border-danger/30 bg-danger/20 p-2.5 text-danger transition-all hover:scale-105 hover:bg-danger/30 shadow-md"
                        title="删除"
                      >
                        <Trash2 className="h-5 w-5" />
                      </button>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="space-y-2 mt-2">
                    <div className="flex justify-end">
                       <span className="text-sm font-black text-white/90 drop-shadow-sm">{pct}%</span>
                    </div>
                    <div className="h-2.5 rounded-full bg-black/40 overflow-hidden shadow-inner">
                      <div
                        className={cn(
                          'h-full rounded-full transition-all duration-500 relative',
                          isPaused
                            ? 'bg-warning shadow-[0_0_10px_rgba(250,204,21,0.5)]'
                            : 'bg-gradient-to-r from-accent-cyan to-[#00f2fe] shadow-[0_0_10px_rgba(0,242,254,0.5)]'
                        )}
                        style={{ width: `${pct}%` }}
                      >
                         {!isPaused && <div className="absolute inset-0 bg-white/20 w-full h-full animate-pulse" />}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
