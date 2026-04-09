import { useState, useRef, useEffect } from 'react'
import { Play, Square, Trash2, Radio, History, Info, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getCrawlHistory } from '@/api'
import type { CrawlLogEntry } from '@/types'

type CrawlSource = 'subsplease' | 'nyaa' | 'bangumi' | 'dmhy' | 'mikan' | 'animetosho' | 'animegarden' | 'comicat'

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
    key: 'dmhy', label: '动漫花园', description: '中文字幕组 BT 资源',
    capabilities: ['原生中文关键词搜索', 'HTML 爬取 + RSS 回退', '含字幕组标签', '支持分页抓取', '分类: 动画/完结/漫画/音乐'],
    pageSize: 80, maxPages: 10,
  },
  {
    key: 'mikan', label: '蜜柑计划', description: 'RSS 订阅追番',
    capabilities: ['中文 RSS 订阅', '字幕组聚合', '当季新番列表', '支持中文搜索', '自动追番推荐'],
    pageSize: 0, maxPages: 1,
  },
  {
    key: 'animetosho', label: 'AnimeTosho', description: '种子聚合 JSON API',
    capabilities: ['聚合 Nyaa/TokyoTosho/AniDex 等多源', '干净 JSON API', '含做种/下载数', '支持分页', '英文关键词搜索（自动翻译中文）'],
    pageSize: 50, maxPages: 5,
  },
  {
    key: 'animegarden', label: 'AnimeGarden', description: '开放 API 资源聚合',
    capabilities: ['聚合 DMHY+Moe+ANi 等数据源', '开放 JSON API（无需认证）', '原生中文搜索', '含字幕组+发布者信息', '支持类型/关键词过滤', '关联 Bangumi 条目 ID'],
    pageSize: 50, maxPages: 5,
  },
  {
    key: 'comicat', label: '漫猫动漫', description: '中文字幕组 BT 资源',
    capabilities: ['RSS 最新资源', 'HTML 关键词搜索', '中文字幕组覆盖', '活跃更新'],
    pageSize: 0, maxPages: 1,
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
  // Breakpoint state: tracks last successfully completed page per source
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

    // Check breakpoint for resume
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
                // Extract result count from success messages
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
        // Save breakpoint
        breakpointRef.current.set(bpKey, page)

        if (source === 'nyaa' && pageResults === 0 && page > 1) {
          addLog({ timestamp: now(), level: 'warn', source, message: `第 ${page} 页无结果，提前终止` })
          break
        }

        // Small delay between pages
        if (page < endPage && !controller.signal.aborted) {
          addLog({ timestamp: now(), level: 'info', source, message: '等待 1 秒避免限流...' })
          await new Promise(r => setTimeout(r, 1000))
        }
      }

      if (!controller.signal.aborted) {
        addLog({ timestamp: now(), level: 'success', source, message: `全部完成！累计获取 ${totalResults} 条数据` })
        // Clear breakpoint on full completion
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
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">抓取控制台</h1>
        <div className="flex gap-2">
          <button onClick={loadHistory} className="flex items-center gap-1.5 rounded-lg bg-bg-card border border-border px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors">
            <History className="h-3.5 w-3.5" /> 历史
          </button>
          <button onClick={startAll} disabled={running.size === sources.length}
            className="flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-primary/90 transition-colors disabled:opacity-50">
            <Play className="h-3.5 w-3.5" /> 全部抓取
          </button>
        </div>
      </div>

      {/* Keyword + Nyaa pagination config */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-text-muted mb-1 block">关键词</label>
          <input type="text" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="抓取关键词（可选）"
            className={cn('w-full rounded-lg border border-border bg-bg-card py-2 px-3 text-sm', 'focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary/50')} />
        </div>
        <div className="w-28">
          <label className="text-xs text-text-muted mb-1 block">Nyaa 起始页</label>
          <input type="number" min={1} max={100} value={nyaaPage} onChange={(e) => setNyaaPage(Math.max(1, parseInt(e.target.value) || 1))}
            className="w-full rounded-lg border border-border bg-bg-card py-2 px-3 text-sm focus:border-accent-primary focus:outline-none" />
        </div>
        <div className="w-28">
          <label className="text-xs text-text-muted mb-1 block">Nyaa 总页数</label>
          <input type="number" min={1} max={20} value={nyaaMaxPage} onChange={(e) => setNyaaMaxPage(Math.max(1, parseInt(e.target.value) || 1))}
            className="w-full rounded-lg border border-border bg-bg-card py-2 px-3 text-sm focus:border-accent-primary focus:outline-none" />
        </div>
      </div>

      {/* Source cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {sources.map((src) => {
          const isRunning = running.has(src.key)
          const isExpanded = expandedInfo === src.key
          const bp = hasBreakpoint(src.key)
          return (
            <div key={src.key} className="rounded-xl bg-bg-card border border-border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{src.label}</p>
                    {bp && <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning/10 text-warning">有断点</span>}
                  </div>
                  <p className="text-xs text-text-muted">{src.description}</p>
                </div>
                <div className="flex items-center gap-1">
                  {isRunning && <Radio className="h-4 w-4 text-accent-cyan pulse-dot" />}
                  <button onClick={() => setExpandedInfo(isExpanded ? null : src.key)} className="rounded p-1 text-text-muted hover:text-text-primary">
                    {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <Info className="h-3.5 w-3.5" />}
                  </button>
                </div>
              </div>

              {/* Capability info panel */}
              {isExpanded && (
                <div className="rounded-lg bg-bg-primary/50 p-3 space-y-1.5">
                  <p className="text-[10px] font-semibold text-accent-secondary uppercase tracking-wider">可抓取能力</p>
                  {src.capabilities.map((cap, j) => (
                    <div key={j} className="flex items-start gap-1.5 text-xs text-text-secondary">
                      <span className="text-accent-cyan mt-0.5">•</span>
                      <span>{cap}</span>
                    </div>
                  ))}
                  <div className="border-t border-border/50 pt-1.5 mt-1.5 text-[10px] text-text-muted">
                    {src.pageSize > 0 ? `每页 ${src.pageSize} 条 · 可连续抓取 ${src.maxPages} 页` : '一次拉取全部数据'}
                  </div>
                </div>
              )}

              <button onClick={() => isRunning ? stopCrawl(src.key) : startCrawlSSE(src.key)}
                className={cn('w-full flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-medium transition-colors',
                  isRunning ? 'bg-danger/10 text-danger hover:bg-danger/20' : bp ? 'bg-warning/10 text-warning hover:bg-warning/20' : 'bg-accent-primary/10 text-accent-primary hover:bg-accent-primary/20'
                )}>
                {isRunning ? <><Square className="h-3.5 w-3.5" /> 暂停</> : bp ? <><Play className="h-3.5 w-3.5" /> 续抓</> : <><Play className="h-3.5 w-3.5" /> 抓取</>}
              </button>
            </div>
          )
        })}
      </div>

      {/* Log console */}
      <div className="rounded-xl bg-bg-card border border-border overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="text-xs font-medium text-text-secondary">日志输出 {logs.length > 0 && `(${logs.length} 条)`}</span>
          <button onClick={clearLogs} className="flex items-center gap-1 text-xs text-text-muted hover:text-text-secondary transition-colors">
            <Trash2 className="h-3 w-3" /> 清空
          </button>
        </div>
        <div className="h-80 overflow-y-auto p-4 font-mono text-xs space-y-0.5">
          {logs.length === 0 ? (
            <div className="text-text-muted space-y-1">
              <p>点击上方「抓取」按钮开始（支持 SSE 实时流）</p>
              <p>点击 <Info className="h-3 w-3 inline" /> 查看每个数据源可抓取的详细能力</p>
              <p>中途暂停后可「续抓」，从断点位置继续</p>
            </div>
          ) : logs.map((entry, i) => (
            <div key={i} className="log-entry flex gap-2">
              <span className="text-text-muted shrink-0">{entry.timestamp}</span>
              <span className={cn('shrink-0 font-bold', levelColor(entry.level))}>[{levelTag(entry.level)}]</span>
              <span className="text-accent-secondary shrink-0">[{entry.source}]</span>
              <span className="text-text-primary">{entry.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>

      {/* History modal */}
      {showHistory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowHistory(false)}>
          <div className="relative max-h-[70vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-bg-secondary border border-border p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">抓取历史</h2>
            {history.length === 0 ? <p className="text-text-muted text-sm">暂无记录</p> : (
              <div className="space-y-2">
                {history.map((h, i) => (
                  <div key={i} className="flex items-center gap-3 rounded-lg bg-bg-card border border-border p-3 text-xs">
                    <span className={cn('font-medium', h.status === 'success' ? 'text-success' : 'text-danger')}>{h.status === 'success' ? '✓' : '✗'}</span>
                    <span className="text-accent-secondary">[{String(h.source)}]</span>
                    <span className="flex-1">{String(h.keyword) || '(全部)'} — {String(h.result_count)} 条</span>
                    <span className="text-text-muted">{String(h.duration_ms)}ms</span>
                    <span className="text-text-muted">{String(h.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
            <button onClick={() => setShowHistory(false)} className="absolute right-4 top-4 rounded-lg p-1 text-text-muted hover:text-text-primary">✕</button>
          </div>
        </div>
      )}
    </div>
  )
}
