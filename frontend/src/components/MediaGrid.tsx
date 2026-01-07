import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchMedia } from '../api'
import type { MediaItem } from '../types'
import MediaCard from './MediaCard'
import Lightbox from './Lightbox'
import VideoPlayer from './VideoPlayer'

type Props = {
  modelIds: string[]
  tagIds: string[]
  strict: boolean
  order: 'random' | 'duration' | 'recent'
  seed: number
  onTagClick?: (id: string) => void
  onModelClick?: (id: string) => void
}

export default function MediaGrid({ modelIds, tagIds, strict, order, seed, onTagClick, onModelClick }: Props) {
  const [items, setItems] = useState<MediaItem[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const [vMeta, setVMeta] = useState<{ w: number; h: number; d: number | null } | null>(null)
  const [vSize, setVSize] = useState<number | null>(null)
  const sentinel = useRef<HTMLDivElement | null>(null)
  const fetchedKeysRef = useRef<Set<string>>(new Set())
  const [reloadHint, setReloadHint] = useState(false)
  const initialLoadedRef = useRef<boolean>(false)
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const gridRef = useRef<HTMLDivElement | null>(null)
  const [colCount, setColCount] = useState<number>(4)
  const [colWidth, setColWidth] = useState<number>(300)
  const filterKeyRef = useRef<string>('')
  const prefetchedRef = useRef<Set<string>>(new Set())

  useEffect(() => { setVMeta(null) }, [selectedIndex])
  useEffect(() => {
    setVSize(null)
    if (selectedIndex === null) return
    const it = items[selectedIndex]
    if (!it) return
    const bytes = it.file_size || 0
    if (bytes > 0) { setVSize(bytes); return }
    const url = it.file_path
    if (!url) return
    try {
      ;(async () => {
        try {
          const r2 = await fetch(url, { method: 'GET', headers: { Range: 'bytes=0-0' } })
          const cr = r2.headers.get('content-range')
          if (cr) {
            const m = cr.match(/bytes\s+\d+-\d+\/(\d+)/i)
            if (m && m[1]) {
              const n = Number(m[1])
              if (isFinite(n) && n > 0) { setVSize(n); return }
            }
          }
        } catch {}
        try {
          const r = await fetch(url, { method: 'HEAD' })
          const cl = r.headers.get('content-length')
          if (cl) {
            const n = Number(cl)
            if (isFinite(n) && n > 0) { setVSize(n); return }
          }
        } catch {}
      })().catch(() => {})
    } catch {}
  }, [selectedIndex, items])

  useEffect(() => {
    const el = gridRef.current
    if (!el) return
    const GAP = 16
    const MIN_COL = 260
    const TARGET_COL = 300
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      const ideal = Math.max(1, Math.floor((w + GAP) / (TARGET_COL + GAP)))
      const cols = Math.max(1, ideal)
      const cw = Math.floor((w - GAP * (cols - 1)) / cols)
      const bounded = Math.max(MIN_COL, cw)
      setColCount(cols)
      setColWidth(bounded)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const columns = useMemo(() => {
    const cc = Math.max(1, colCount)
    const cols: Array<Array<{ item: MediaItem; idx: number }>> = Array.from({ length: cc }, () => [])
    const heights = Array.from({ length: cc }, () => 0)
    const w = colWidth || 300
    const gap = 16
    const base = 88
    for (let i = 0; i < items.length; i++) {
      const it = items[i]
      const iw = Number(it.image_width || it.video_width || 0)
      const ih = Number(it.image_height || it.video_height || 0)
      const ratio = iw > 0 && ih > 0 ? ih / iw : 3 / 4
      const coverH = w * ratio
      let minCol = 0
      for (let c = 1; c < cc; c++) { if (heights[c] < heights[minCol]) minCol = c }
      cols[minCol].push({ item: it, idx: i })
      heights[minCol] += coverH + base + gap
    }
    return cols
  }, [items, colCount, colWidth])

  useEffect(() => {
    setItems([])
    setPage(1)
    setHasMore(true)
    fetchedKeysRef.current.clear()
    setReloadHint(true)
    initialLoadedRef.current = false
    filterKeyRef.current = `${modelIds.join(',')}|${tagIds.join(',')}|${strict}|${order}|${seed}`
    const t = setTimeout(() => setReloadHint(false), 1200)
    return () => clearTimeout(t)
  }, [modelIds.join(','), tagIds.join(','), strict, order])

  useEffect(() => {
    const run = async () => {
      if (!hasMore || loading) return
      const key = `${page}|${modelIds.join(',')}|${tagIds.join(',')}|${strict}|${order}`
      if (fetchedKeysRef.current.has(key)) return
      fetchedKeysRef.current.add(key)
      setLoading(true)
      const noFilters = modelIds.length === 0 && tagIds.length === 0
      if (noFilters) {
        const res = await fetchMedia({ model_ids: modelIds, tag_ids: tagIds, page, page_size: 30, strict, order, seed })
        if (filterKeyRef.current !== `${modelIds.join(',')}|${tagIds.join(',')}|${strict}|${order}|${seed}`) { setLoading(false); return }
        setItems(prev => {
          const seen = new Set(prev.map(i => i.id))
          const merged = [...prev]
          for (const it of res.items) {
            if (!seen.has(it.id)) {
              seen.add(it.id)
              merged.push(it)
            }
          }
          return merged
        })
        setHasMore(res.hasMore)
        setLoading(false)
        if (page === 1) initialLoadedRef.current = true
        return
      }
      const res = await fetchMedia({ model_ids: modelIds, tag_ids: tagIds, page, page_size: 30, strict, order, seed })
      if (filterKeyRef.current !== `${modelIds.join(',')}|${tagIds.join(',')}|${strict}|${order}|${seed}`) { setLoading(false); return }
      setItems(prev => {
        const seen = new Set(prev.map(i => i.id))
        const merged = [...prev]
        for (const it of res.items) {
          if (!seen.has(it.id)) {
            seen.add(it.id)
            merged.push(it)
          }
        }
        return merged
      })
      setHasMore(res.hasMore)
      setLoading(false)
      if (page === 1) initialLoadedRef.current = true
    }
    run()
  }, [page, modelIds.join(','), tagIds.join(','), strict, order, loading, hasMore])

  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting && !loading && hasMore && initialLoadedRef.current && items.length > 0) {
          setPage(p => p + 1)
        }
      })
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [sentinel.current, loading, hasMore, items.length])

  useEffect(() => {
    if (selectedIndex === null) return
    const set = prefetchedRef.current
    const ids = [selectedIndex - 1, selectedIndex + 1]
    const isVideo = (ft?: string | null) => {
      const s = (ft || '').toLowerCase()
      return ['mp4','avi','mov','mkv','webm','mpeg','mpg','m4v'].includes(s)
    }
    ids.forEach(idx => {
      if (idx < 0 || idx >= items.length) return
      const it = items[idx]
      const key = it.file_path || ''
      if (!key || set.has(key)) return
      if (!isVideo(it.file_type)) return
      set.add(key)
      try {
        ;(async () => {
          try {
            await fetch(key, { method: 'GET', headers: { Range: 'bytes=0-65535' } })
          } catch {}
        })().catch(() => {})
      } catch {}
    })
  }, [selectedIndex, items])

  return (
    <div className="container">
      {reloadHint && (
        <div className="toast"><div className="bubble">{strict ? '强关联已开启，重新加载…' : '强关联已关闭，重新加载…'}</div></div>
      )}
      <div className="masonry" ref={gridRef} style={{ ['--col-w' as any]: `${colWidth}px` }}>
        {items.length > 0 && columns.map((col, ci) => (
          <div className="col" key={`col-${ci}`}>
            {col.map(({ item, idx }) => (
              <MediaCard key={item.id} item={item} onOpen={() => setSelectedIndex(idx)} onTagClick={onTagClick} onModelClick={onModelClick} />
            ))}
          </div>
        ))}
        {loading && items.length === 0 && (
          Array.from({ length: 10 }).map((_, i) => (
            <div key={`sk-${i}`} className="skeleton">
              <div className="block" />
              <div className="line" />
              <div className="line" />
            </div>
          ))
        )}
      </div>
      {!loading && items.length === 0 && (<div className="muted" style={{ textAlign:'center', padding:24 }}>暂无内容，试试关闭强关联或减少筛选条件</div>)}
      <div ref={sentinel} />
      {loading && items.length > 0 && (
        <div style={{ textAlign:'center', padding:16 }}>
          <div className="spinner" />
        </div>
      )}
      {!hasMore && <div className="muted" style={{ textAlign:'center', padding:16 }}>没有更多了</div>}
      <Lightbox
        open={selectedIndex !== null && items[selectedIndex] !== undefined}
        onClose={() => setSelectedIndex(null)}
        onPrev={() => setSelectedIndex(i => (i === null ? i : Math.max(0, i - 1)))}
        onNext={() => setSelectedIndex(i => (i === null ? i : Math.min(items.length - 1, i + 1)))}
        canPrev={selectedIndex !== null && selectedIndex > 0}
        canNext={selectedIndex !== null && selectedIndex < items.length - 1}
        leftAside={(() => {
          if (selectedIndex === null) return null
          const it = items[selectedIndex]
          if (!it) return null
          const isVideo = it.file_type && ['mp4','avi','mov','mkv','webm','mpeg','mpg','m4v'].includes(it.file_type.toLowerCase())
          const wh = isVideo ? `${(vMeta?.w ?? it.video_width) ?? ''}×${(vMeta?.h ?? it.video_height) ?? ''}` : `${it.image_width ?? ''}×${it.image_height ?? ''}`
          const fmtSize = (bytes?: number | null): string | null => {
            if (!bytes || bytes <= 0) return null
            const kb = bytes / 1024
            const mb = kb / 1024
            const gb = mb / 1024
            if (gb >= 1) return `${gb.toFixed(2)}G`
            if (mb >= 1) return `${Math.round(mb)}M`
            return `${Math.max(1, Math.ceil(kb))}k`
          }
          const fmtDurZh = (ms?: number | null): string | null => {
            if (!ms || ms <= 0) return null
            const total = Math.round(ms / 1000)
            const h = Math.floor(total / 3600)
            const m = Math.floor((total % 3600) / 60)
            const s = total % 60
            const pad = (n: number) => String(n).padStart(2, '0')
            if (h > 0) return `${h}时${pad(m)}分${pad(s)}秒`
            return `${m}分${pad(s)}秒`
          }
          const size = fmtSize(it.file_size)
          const sizeResolved = fmtSize((vSize ?? it.file_size) ?? null)
          const durZh = fmtDurZh((vMeta?.d ? vMeta.d * 1000 : it.duration_ms) ?? null)
          const fmt = (s?: string | null): string | null => {
            if (!s) return null
            const d = new Date(s)
            if (isNaN(d.getTime())) return s
            const y = d.getFullYear()
            const m = String(d.getMonth() + 1).padStart(2, '0')
            const day = String(d.getDate()).padStart(2, '0')
            const hh = String(d.getHours()).padStart(2, '0')
            const mm = String(d.getMinutes()).padStart(2, '0')
            return `${y}-${m}-${day} ${hh}:${mm}`
          }
          const ts = fmt(it.created_at)
          return (
            <div className="lightbox-meta lightbox-left">
              <div className="lightbox-title">详情</div>
              <div className="lightbox-row"><span className="muted">类型：</span><span className="pill">{it.file_type || '未知'}</span></div>
              <div className="lightbox-row"><span className="muted">尺寸：</span><span className="pill">{wh}</span></div>
              {sizeResolved && <div className="lightbox-row"><span className="muted">大小：</span><span className="pill">{sizeResolved}</span></div>}
              {isVideo && durZh && <div className="lightbox-row"><span className="muted">时长：</span><span className="pill">{durZh}</span></div>}
              {ts && (
                <div className="lightbox-row"><span className="muted">时间：</span><span className="pill">{ts}</span></div>
              )}
            </div>
          )
        })()}
        rightAside={(() => {
          if (selectedIndex === null) return null
          const it = items[selectedIndex]
          if (!it) return null
          const onOpenInSystem = async () => {
            try {
              const u = new URL(it.file_path || '', window.location.origin)
              if (u.pathname.startsWith('/api/file')) {
                const b64 = u.searchParams.get('path')
                if (b64) {
                  await fetch(`/api/open?path=${encodeURIComponent(b64)}`, { method: 'POST' })
                  return
                }
              }
            } catch {}
            const url = it.file_path || ''
            if (url) window.open(url, '_blank')
          }
          const displayTitle = (() => {
            const t = it.title || ''
            const m = t.match(/^(.*?)(\.(jpg|jpeg|png|gif|webp|bmp|tiff|svg|mp4|avi|mov|mkv|webm|mpeg|mpg|m4v))$/i)
            return m ? m[1] : t
          })()
          return (
            <div className="lightbox-meta lightbox-right">
              <div className="lightbox-title">{displayTitle}</div>
              <div className="lightbox-row">
                <button className="pill pill-dark clickable" onClick={(e) => { e.stopPropagation(); onOpenInSystem() }}>
                  用系统工具打开
                </button>
                <a className="pill pill-dark clickable" style={{ marginLeft: 8 }} href={it.file_path} target="_blank" rel="noreferrer">
                  在浏览器打开原文件
                </a>
              </div>
              <div className="lightbox-row"><span className="muted">模特：</span>{it.models.length === 0 ? (<span className="muted">无</span>) : it.models.map(m => (
                <button key={m.id} className="pill pill-dark clickable" onClick={() => { onModelClick && onModelClick(m.id); setSelectedIndex(null) }} title={`按模特筛选：${m.name}`}>
                  {m.name}{m.type ? ` · ${m.type}` : ''}
                </button>
              ))}</div>
              <div className="lightbox-row"><span className="muted">标签：</span>{it.tags.length === 0 ? (<span className="muted">无</span>) : it.tags.map(t => (
                <button key={t.id} className="pill pill-dark clickable" onClick={() => { onTagClick && onTagClick(t.id); setSelectedIndex(null) }} title={`按标签筛选：${t.name}`}>
                  {t.name}
                </button>
              ))}</div>
            </div>
          )
        })()}
      >
        {selectedIndex !== null && items[selectedIndex] && (
          (() => {
            const it = items[selectedIndex]
            const isVideo = it.file_type && ['mp4','avi','mov','mkv','webm','mpeg','mpg','m4v'].includes(it.file_type.toLowerCase())
            const src = it.file_path || ''
            const onMeta = (e: React.SyntheticEvent<HTMLVideoElement>) => {
              const el = e.currentTarget
              const w = el.videoWidth || 0
              const h = el.videoHeight || 0
              const d = isFinite(el.duration) && el.duration > 0 ? Math.round(el.duration) : null
              if ((w > 0 && h > 0) || (d && d > 0)) setVMeta({ w, h, d })
            }
            return isVideo ? (
              <VideoPlayer src={src} onLoadedMetadata={onMeta} autoplay initialVolume={0.08} style={{ maxWidth:'calc(90vw - 580px)', maxHeight:'90vh' }} />
            ) : (
              <img src={it.file_path} style={{ maxWidth:'calc(90vw - 580px)', maxHeight:'90vh', objectFit:'contain' }} />
            )
          })()
        )}
      </Lightbox>
    </div>
  )
}
