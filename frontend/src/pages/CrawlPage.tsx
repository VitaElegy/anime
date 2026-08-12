import { useState, useRef, useEffect } from 'react'
import { Play, Square, Trash2, Radio, History, Info, ChevronUp, TerminalSquare } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getCrawlHistory } from '@/api'
import type { CrawlLogEntry } from '@/types'

type CrawlSource = 'subsplease' | 'nyaa' | 'bangumi'

interface SourceConfig {
  key: CrawlSource
  label: string
  description: string
  capabilities: string[]
  pageSize: number
  maxPages: number
}

const sources: SourceConfig[] = [
  {
    key: 'subsplease', label: 'SubsPlease', description: 'RSS 当季新番',
    capabilities: ['当季全部新番 RSS', '支持 1080p/720p/480p', '含磁力链接', '无分页限制，一次拉取全部'],
    pageSize: 0, maxPages: 1,
  },
  {
    key: 'nyaa', label: 'Nyaa.land', description: 'BT 种子索引',
    capabilities: ['HTML 搜索 + RSS 回退', '每页 75 条结果', '支持分页连续抓取', '含种子数/下载数/文件大小', '分类: 动画/英字/非英字/生肉'],
    pageSize: 75, maxPages: 10,
  },
  {
    key: 'bangumi', label: 'Bangumi', description: '番剧元数据',
    capabilities: ['中文番剧搜索', '评分/简介/封面', '每次最多 25 条', '自动缓存元数据', '封面自动下载到本地'],
    pageSize: 25, maxPages: 1,
  },
]

function levelColor(level: CrawlLogEntry['level']): string {
  switch (level) {
    case 'info': return 'text-accent-cyan'
    case 'warn': return 'text-warning'
    case 'error': return 'text-danger'
    case 'success': return 'text-success'
  }
}

function levelTag(level: CrawlLogEntry['level']): string {
  switch (level) {
    case 'info': return 'INFO'
    case 'warn': return 'WARN'
    case 'error': return 'FAIL'
    case 'success': return ' OK '
  }
}

export default function CrawlPage() {
  const [logs, setLogs] = useState<CrawlLogEntry[]>([])
  const [running, setRunning] = useState<Set<CrawlSource>>(new Set())
  const [keyword, setKeyword] = useState('')
  const [history, setHistory] = useState<Record<string, unknown>[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [expandedInfo, setExpandedInfo] = useState<CrawlSource | null>(null)
  const [nyaaPage, setNyaaPage] = useState(1)
  const [nyaaMaxPage, setNyaaMaxPage] = useState(3)
  const logEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<Map<CrawlSource, AbortController>>(new Map())
  const breakpointRef = useRef<Map<string, number>>(new Map())

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const addLog = (entry: CrawlLogEntry) => {
    setLogs((prev) => [...prev, entry])
  }

  const now = () => new Date().toLocaleTimeString('zh-CN', { hour12: false })

  const startCrawlSSE = async (source: CrawlSource) => {
    if (running.has(source)) return

    const controller = new AbortController()
    abortRef.current.set(source, controller)
    setRunning((prev) => new Set(prev).add(source))

    const bpKey = `${source}:${keyword}`
    const lastPage = breakpointRef.current.get(bpKey) || 0

    if (source === 'nyaa' && lastPage > 0) {
      addLog({ timestamp: now(), level: 'info', source, message: `断点续抓：从第 ${lastPage + 1} 页继续` })
    }

    const startPage = source === 'nyaa' ? Math.max(lastPage + 1, nyaaPage) : 1
    const endPage = source === 'nyaa' ? nyaaMaxPage : 1

    addLog({ timestamp: now(), level: 'info', source, message: `启动抓取 [${source}] 关键词="${keyword || '(全部)'}" 页=${startPage}-${endPage}` })

    let totalResults = 0

    try {
      for (let page = startPage; page <= endPage; page++) {
        if (controller.signal.aborted) break

        if (endPage > 1) {
          addLog({ timestamp: now(), level: 'info', source, message: `━━━ 第 ${page}/${endPage} 页 ━━━` })
        }

        const params = new URLSearchParams({ source, keyword: keyword || '', quality: '1080', page: String(page) })

        const resp = await fetch(`/api/crawl/stream?${params}`, { signal: controller.signal })
        if (!resp.ok) {
          addLog({ timestamp: now(), level: 'error', source, message: `SSE 连接失败: HTTP ${resp.status}` })
          break
        }

        const reader = resp.body?.getReader()
        const decoder = new TextDecoder()
        if (!reader) break

        let buffer = ''
        let pageResults = 0
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const payload = line.slice(6).trim()
              if (payload === '[DONE]') break
              try {
                const data = JSON.parse(payload)
                const countMatch = data.msg?.match(/共 (\d+) 条/)
                if (countMatch) pageResults = parseInt(countMatch[1])

                addLog({
                  timestamp: data.ts || now(),
                  level: data.level || 'info',
                  source: data.source || source,
                  message: data.msg || '',
                })
              } catch { /* ignore */ }
            }
          }
        }

        totalResults += pageResults
        breakpointRef.current.set(bpKey, page)

        if (source === 'nyaa' && pageResults === 0 && page > 1) {
          addLog({ timestamp: now(), level: 'warn', source, message: `第 ${page} 页无结果，提前终止` })
          break
        }

        if (page < endPage && !controller.signal.aborted) {
          addLog({ timestamp: now(), level: 'info', source, message: '等待 1 秒避免限流...' })
          await new Promise(r => setTimeout(r, 1000))
        }
      }

      if (!controller.signal.aborted) {
        addLog({ timestamp: now(), level: 'success', source, message: `全部完成！累计获取 ${totalResults} 条数据` })
        breakpointRef.current.delete(bpKey)
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        addLog({ timestamp: now(), level: 'warn', source, message: `已暂停 (已保存断点，可续抓)` })
      } else {
        addLog({ timestamp: now(), level: 'error', source, message: `出错: ${(e as Error).message}` })
      }
    } finally {
      setRunning((prev) => { const next = new Set(prev); next.delete(source); return next })
      abortRef.current.delete(source)
    }
  }

  const stopCrawl = (source: CrawlSource) => {
    abortRef.current.get(source)?.abort()
  }

  const startAll = () => {
    for (const src of sources) {
      if (!running.has(src.key)) startCrawlSSE(src.key)
    }
  }

  const clearLogs = () => { setLogs([]); breakpointRef.current.clear() }

  const loadHistory = async () => {
    try { const data = await getCrawlHistory(30); setHistory(data); setShowHistory(true) } catch { /* */ }
  }

  const hasBreakpoint = (source: CrawlSource) => {
    const bpKey = `${source}:${keyword}`
    return breakpointRef.current.has(bpKey)
  }

  return (
    <div className="space-y-8 max-w-[1400px] mx-auto animate-in fade-in duration-500">
      
      {/* Header Banner */}
      <div className="relative overflow-hidden rounded-[2rem] border border-white/10 bg-black/40 p-8 shadow-2xl backdrop-blur-xl">
        <div className="absolute inset-0 bg-gradient-to-br from-accent-gold/15 via-transparent to-accent-primary/10" />
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-center gap-4">
             <div className="rounded-xl bg-accent-gold/20 p-3 border border-accent-gold/30 shadow-inner">
               <TerminalSquare className="h-6 w-6 text-accent-gold" />
             </div>
             <div>
               <h1 className="text-3xl font-black text-white tracking-wide">抓取控制台</h1>
               <p className="text-sm font-medium text-white/60 mt-1">从多个数据源获取番剧和种子信息</p>
             </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <button onClick={loadHistory} className="group flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-6 py-3 text-sm font-bold text-white shadow-lg transition-all hover:bg-white/10 hover:shadow-xl hover:scale-105">
              <History className="h-4 w-4 transition-transform duration-500 group-hover:-rotate-45" /> 抓取历史
            </button>
            <button onClick={startAll} disabled={running.size === sources.length}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent-primary to-accent-secondary px-6 py-3 text-sm font-bold text-white shadow-lg shadow-accent-primary/20 transition-all hover:scale-105 disabled:opacity-50 disabled:hover:scale-100">
              <Play className="h-4 w-4" /> 全部抓取
            </button>
          </div>
        </div>
      </div>

      {/* Configs */}
      <div className="rounded-2xl border border-white/5 bg-black/20 p-6 shadow-xl backdrop-blur-md">
         <div className="flex flex-wrap gap-4 items-end">
           <div className="flex-1 min-w-[200px]">
             <label className="text-xs font-bold text-white/60 mb-2 block">目标关键词</label>
             <input type="text" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="留空则拉取全部（例如 SubsPlease 当季新番）"
               className="w-full rounded-xl border border-white/10 bg-white/5 py-3 px-4 text-sm font-bold text-white outline-none focus:border-accent-primary focus:bg-white/10 transition-all" />
           </div>
           <div className="w-32">
             <label className="text-xs font-bold text-white/60 mb-2 block">Nyaa 起始页</label>
             <input type="number" min={1} max={100} value={nyaaPage} onChange={(e) => setNyaaPage(Math.max(1, parseInt(e.target.value) || 1))}
               className="w-full rounded-xl border border-white/10 bg-white/5 py-3 px-4 text-sm font-bold text-white outline-none focus:border-accent-primary focus:bg-white/10 transition-all" />
           </div>
           <div className="w-32">
             <label className="text-xs font-bold text-white/60 mb-2 block">Nyaa 总页数</label>
             <input type="number" min={1} max={20} value={nyaaMaxPage} onChange={(e) => setNyaaMaxPage(Math.max(1, parseInt(e.target.value) || 1))}
               className="w-full rounded-xl border border-white/10 bg-white/5 py-3 px-4 text-sm font-bold text-white outline-none focus:border-accent-primary focus:bg-white/10 transition-all" />
           </div>
         </div>
      </div>

      {/* Sources */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {sources.map((src) => {
          const isRunning = running.has(src.key)
          const isExpanded = expandedInfo === src.key
          const bp = hasBreakpoint(src.key)
          return (
            <div key={src.key} className={cn("relative overflow-hidden rounded-2xl border p-6 shadow-xl backdrop-blur-md transition-all duration-500 hover:-translate-y-1 hover:shadow-2xl", isRunning ? 'border-accent-cyan/30 bg-accent-cyan/5' : 'border-white/5 bg-black/20 hover:border-white/20')}>
              {isRunning && <div className="absolute inset-0 bg-gradient-to-t from-accent-cyan/0 via-accent-cyan/5 to-accent-cyan/0 opacity-50 animate-pulse" />}
              
              <div className="relative z-10 space-y-5">
                 <div className="flex items-start justify-between gap-4">
                   <div>
                     <div className="flex items-center gap-3 mb-1">
                       <h3 className="text-lg font-bold text-white">{src.label}</h3>
                       {bp && <span className="rounded bg-warning/20 border border-warning/30 px-1.5 py-0.5 text-[10px] font-bold text-warning shadow-sm">断点存在</span>}
                     </div>
                     <p className="text-sm font-medium text-white/50">{src.description}</p>
                   </div>
                   <div className="flex items-center gap-2">
                     {isRunning && <Radio className="h-5 w-5 text-accent-cyan animate-pulse" />}
                     <button onClick={() => setExpandedInfo(isExpanded ? null : src.key)} className="rounded-lg bg-white/5 p-2 text-white/60 hover:bg-white/10 hover:text-white transition-all shadow-sm border border-white/5">
                       {isExpanded ? <ChevronUp className="h-4 w-4" /> : <Info className="h-4 w-4" />}
                     </button>
                   </div>
                 </div>

                 {/* Capability info panel */}
                 {isExpanded && (
                   <div className="rounded-xl bg-white/5 border border-white/5 p-4 space-y-2 animate-in slide-in-from-top-2 fade-in">
                     <p className="text-[10px] font-black text-accent-secondary uppercase tracking-widest">支持特性</p>
                     <div className="space-y-1.5">
                        {src.capabilities.map((cap, j) => (
                          <div key={j} className="flex items-start gap-2 text-xs font-medium text-white/70">
                            <span className="text-accent-cyan mt-0.5">•</span>
                            <span>{cap}</span>
                          </div>
                        ))}
                     </div>
                     <div className="border-t border-white/10 pt-2 mt-2 text-[10px] font-bold text-white/40">
                       {src.pageSize > 0 ? `每页 ${src.pageSize} 条 · 可连续抓取 ${src.maxPages} 页` : '一次拉取全部数据'}
                     </div>
                   </div>
                 )}

                 <button onClick={() => isRunning ? stopCrawl(src.key) : startCrawlSSE(src.key)}
                   className={cn('w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-bold shadow-lg transition-all hover:scale-[1.02]',
                     isRunning ? 'bg-danger/20 text-danger border border-danger/30 hover:bg-danger/30' : 
                     bp ? 'bg-warning/20 text-warning border border-warning/30 hover:bg-warning/30' : 
                     'bg-white/10 text-white border border-white/10 hover:bg-white/20'
                   )}>
                   {isRunning ? <><Square className="h-4 w-4" /> 暂停抓取</> : bp ? <><Play className="h-4 w-4" /> 续抓</> : <><Play className="h-4 w-4" /> 开始抓取</>}
                 </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Log console */}
      <div className="rounded-2xl border border-white/5 bg-black overflow-hidden shadow-2xl ring-1 ring-white/10">
        <div className="flex items-center justify-between border-b border-white/10 bg-white/[0.02] px-6 py-4">
          <span className="text-sm font-bold text-white/80 flex items-center gap-2">
             <TerminalSquare className="h-4 w-4" /> 运行日志 {logs.length > 0 && `(${logs.length})`}
          </span>
          <button onClick={clearLogs} className="flex items-center gap-1.5 text-xs font-bold text-text-muted hover:text-white transition-colors bg-white/5 px-3 py-1.5 rounded-lg">
            <Trash2 className="h-3.5 w-3.5" /> 清空终端
          </button>
        </div>
        <div className="h-[400px] overflow-y-auto p-6 font-mono text-sm space-y-1.5 custom-scrollbar">
          {logs.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center text-white/30 space-y-4">
               <TerminalSquare className="h-12 w-12 opacity-20" />
               <div className="space-y-2">
                 <p>点击上方的「开始抓取」启动数据流（SSE）</p>
                 <p>日志将实时显示在这里</p>
               </div>
            </div>
          ) : logs.map((entry, i) => (
            <div key={i} className="flex gap-3 hover:bg-white/[0.02] px-2 py-0.5 rounded transition-colors">
              <span className="text-white/40 shrink-0 select-none">{entry.timestamp}</span>
              <span className={cn('shrink-0 font-bold w-12 select-none', levelColor(entry.level))}>[{levelTag(entry.level)}]</span>
              <span className="text-accent-secondary shrink-0 font-bold select-none w-24">[{entry.source}]</span>
              <span className="text-white/80 break-all">{entry.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>

      {/* History modal */}
      {showHistory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in" onClick={() => setShowHistory(false)}>
          <div className="relative max-h-[80vh] w-full max-w-4xl overflow-hidden rounded-3xl border border-white/10 bg-bg-primary/95 shadow-2xl flex flex-col animate-in zoom-in-95" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-white/10 p-6 bg-white/[0.02]">
               <h2 className="text-xl font-bold text-white flex items-center gap-2"><History className="h-5 w-5" /> 抓取历史记录</h2>
               <button onClick={() => setShowHistory(false)} className="rounded-full bg-white/5 p-2 text-white/50 hover:bg-white/10 hover:text-white transition-colors">✕</button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 bg-black/20">
               {history.length === 0 ? (
                 <div className="py-20 text-center text-white/40 font-medium">暂无历史记录</div>
               ) : (
                 <div className="space-y-3">
                   {history.map((h, i) => (
                     <div key={i} className="flex flex-col sm:flex-row sm:items-center gap-4 rounded-xl border border-white/5 bg-white/[0.02] p-4 shadow-sm hover:bg-white/5 transition-colors">
                       <div className="flex items-center gap-4 min-w-0 flex-1">
                          <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-bold shadow-inner border", h.status === 'success' ? 'bg-success/10 text-success border-success/20' : 'bg-danger/10 text-danger border-danger/20')}>
                             {h.status === 'success' ? '✓' : '✗'}
                          </div>
                          <div className="min-w-0">
                             <div className="flex items-center gap-2">
                               <span className="font-bold text-white text-sm">[{String(h.source)}]</span>
                               <span className="truncate text-sm font-medium text-white/70">{String(h.keyword) || '全部抓取'}</span>
                             </div>
                             <p className="text-xs text-white/50 mt-1">共抓取 <span className="text-white font-bold">{String(h.result_count)}</span> 条数据</p>
                          </div>
                       </div>
                       <div className="flex sm:flex-col items-center sm:items-end justify-between gap-2 shrink-0">
                          <span className="text-xs font-bold text-white/60 bg-white/5 px-2 py-1 rounded-md">{String(h.duration_ms)} ms</span>
                          <span className="text-[10px] font-medium text-white/40">{String(h.created_at)}</span>
                       </div>
                     </div>
                   ))}
                 </div>
               )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
