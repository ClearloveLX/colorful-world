import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchMedia, bulkAddTags, bulkRemoveTags, bulkUpdateHeat, fetchTags } from '../api'
import type { MediaItem } from '../types'
import MediaCard from './MediaCard'
import Lightbox from './Lightbox'
import VideoPlayer from './VideoPlayer'
import TagPicker from './TagPicker'
import BulkBar from './BulkBar'

type Props = {
  modelIds: string[]
  tagIds: string[]
  excludeTagIds: string[]
  strict: boolean
  minHeat?: number
  maxHeat?: number
  order: 'random' | 'duration' | 'duration_asc' | 'recent' | 'recent_asc' | 'heat' | 'heat_asc'
  randomMode: 'random' | 'true_random'
  trueRandomCacheEnabled: boolean
  seed: number
  nameSearch?: string
  onTagClick?: (id: string) => void
  onModelClick?: (id: string) => void
}

export default function MediaGrid({ modelIds, tagIds, excludeTagIds, strict, minHeat, maxHeat, order, randomMode, trueRandomCacheEnabled, seed, nameSearch = '', onTagClick, onModelClick }: Props) {
  const [items, setItems] = useState<MediaItem[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [loading, setLoading] = useState(false)
  const loadingRef = useRef(loading)
  loadingRef.current = loading
  const hasMoreRef = useRef(hasMore)
  hasMoreRef.current = hasMore
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
  const [selectMode, setSelectMode] = useState<boolean>(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [pickerOpen, setPickerOpen] = useState<{ type:'add'|'remove'|null }>({ type: null })
  const [tagMeta, setTagMeta] = useState<Map<string, { name: string; category_name?: string | null }>>(new Map())
  const [refreshKey, setRefreshKey] = useState(0)
  const [heatBusy, setHeatBusy] = useState<boolean>(false)
  const dragStartRef = useRef<{ x: number; y: number } | null>(null)
  const dragSelectingRef = useRef<boolean>(false)
  const blockClickRef = useRef<boolean>(false)
  const blockTimerRef = useRef<number | null>(null)
  const dragRafRef = useRef<number | null>(null)
  const scrollRafRef = useRef<number | null>(null)
  const pendingRectRef = useRef<{ left: number; top: number; width: number; height: number } | null>(null)
  const origUserSelectRef = useRef<string>('')
  const retryTimerRef = useRef<number | null>(null)
  const retryCountsRef = useRef<Map<string, number>>(new Map())
  const abortControllerRef = useRef<AbortController | null>(null)
  const [dragSelecting, setDragSelecting] = useState<boolean>(false)
  const [selectRect, setSelectRect] = useState<{ left: number; top: number; width: number; height: number } | null>(null)
  const [requestRetryTick, setRequestRetryTick] = useState(0)
  const manualLoadMore = selectMode && order === 'random' && randomMode === 'true_random' && trueRandomCacheEnabled
  useEffect(() => {
    ;(async () => {
      try {
        const rows = await fetchTags()
        const m = new Map<string, { name: string; category_name?: string | null }>()
        rows.forEach(t => m.set(t.id, { name: t.name, category_name: t.category_name ?? null }))
        setTagMeta(m)
      } catch {}
    })()
  }, [])
  useEffect(() => {
    const applyFromUrl = () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const m = (params.get('mode') || '').toLowerCase()
        setSelectMode(m === 'edit')
      } catch {}
    }
    applyFromUrl()
    const onPop = () => applyFromUrl()
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  useEffect(() => {
    return () => {
      if (blockTimerRef.current) {
        window.clearTimeout(blockTimerRef.current)
        blockTimerRef.current = null
      }
      if (retryTimerRef.current) {
        window.clearTimeout(retryTimerRef.current)
        retryTimerRef.current = null
      }
    }
  }, [])
  useEffect(() => {
    if (selectMode) return
    dragStartRef.current = null
    dragSelectingRef.current = false
    blockClickRef.current = false
    setDragSelecting(false)
    setSelectRect(null)
  }, [selectMode])
  const resetToFirstPage = () => {
    setItems([])
    setPage(1)
    setHasMore(true)
    setLoading(false)
    fetchedKeysRef.current.clear()
    retryCountsRef.current.clear()
    if (retryTimerRef.current) {
      window.clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    initialLoadedRef.current = false
  }
  const triggerRefresh = () => {
    resetToFirstPage()
    setSelectedIds(new Set())
    setRefreshKey(k => k + 1)
  }
  const applyBulkHeat = async (delta: number) => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0 || heatBusy) return
    setHeatBusy(true)
    try {
      await bulkUpdateHeat(ids, delta)
      const step = delta >= 0 ? 1 : -1
      setItems(prev => prev.map(it => (
        selectedIds.has(it.id)
          ? { ...it, heat_value: Number(it.heat_value ?? 0) + step }
          : it
      )))
    } catch {
      // 失败时保持原状
    } finally {
      setHeatBusy(false)
    }
  }
  useEffect(() => {
    if (!selectMode) return
    resetToFirstPage()
  }, [selectMode])
  useEffect(() => {
    if (!selectMode) return
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase() || ''
      const editable = tag === 'input' || tag === 'textarea' || target?.isContentEditable
      if (editable) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
        e.preventDefault()
        setSelectedIds(new Set(items.map(i => i.id)))
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSelectedIds(new Set())
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectMode, items])

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

  const onMasonryMouseDown = (e: React.MouseEvent) => {
    if (!selectMode || e.button !== 0) return
    e.preventDefault()
    const DRAG_THRESHOLD = 8
    const MIN_RECT = 8
    origUserSelectRef.current = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    const start = { x: e.clientX, y: e.clientY }
    dragStartRef.current = start
    dragSelectingRef.current = false
    setDragSelecting(false)
    setSelectRect(null)
    let lastClientY = e.clientY
    const stopAutoScroll = () => {
      if (scrollRafRef.current) {
        cancelAnimationFrame(scrollRafRef.current)
        scrollRafRef.current = null
      }
    }
    const startAutoScroll = () => {
      const EDGE = 80
      const SPEED = 8
      const loop = () => {
        const h = window.innerHeight
        if (lastClientY < EDGE) {
          window.scrollBy(0, -SPEED * (EDGE - lastClientY) / EDGE)
        } else if (lastClientY > h - EDGE) {
          window.scrollBy(0, SPEED * (lastClientY - (h - EDGE)) / EDGE)
        } else {
          scrollRafRef.current = null
          return
        }
        scrollRafRef.current = requestAnimationFrame(loop)
      }
      stopAutoScroll()
      scrollRafRef.current = requestAnimationFrame(loop)
    }
    const onMove = (ev: MouseEvent) => {
      const s = dragStartRef.current
      if (!s) return
      lastClientY = ev.clientY
      const dx = ev.clientX - s.x
      const dy = ev.clientY - s.y
      if (!dragSelectingRef.current && Math.hypot(dx, dy) > DRAG_THRESHOLD) {
        dragSelectingRef.current = true
        setDragSelecting(true)
      }
      if (!dragSelectingRef.current) return
      const left = Math.min(s.x, ev.clientX)
      const top = Math.min(s.y, ev.clientY)
      const width = Math.abs(dx)
      const height = Math.abs(dy)
      pendingRectRef.current = { left, top, width, height }
      if (!dragRafRef.current) {
        dragRafRef.current = requestAnimationFrame(() => {
          dragRafRef.current = null
          if (pendingRectRef.current) {
            setSelectRect(pendingRectRef.current)
          }
          const h = window.innerHeight
          if (lastClientY < 80 || lastClientY > h - 80) startAutoScroll()
          else stopAutoScroll()
        })
      }
    }
    const onUp = (ev: MouseEvent) => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      if (dragRafRef.current) { cancelAnimationFrame(dragRafRef.current); dragRafRef.current = null }
      stopAutoScroll()
      document.body.style.userSelect = origUserSelectRef.current
      const s = dragStartRef.current
      if (s && dragSelectingRef.current) {
        const left = Math.min(s.x, ev.clientX)
        const right = Math.max(s.x, ev.clientX)
        const top = Math.min(s.y, ev.clientY)
        const bottom = Math.max(s.y, ev.clientY)
        const rectW = right - left
        const rectH = bottom - top
        if (rectW >= MIN_RECT && rectH >= MIN_RECT) {
          const grid = gridRef.current
          if (grid) {
            const nodes = grid.querySelectorAll<HTMLElement>('[data-media-id]')
            const picked: string[] = []
            nodes.forEach(el => {
              const r = el.getBoundingClientRect()
              const hit = !(r.right < left || r.left > right || r.bottom < top || r.top > bottom)
              if (hit) {
                const id = el.dataset.mediaId
                if (id) picked.push(id)
              }
            })
            if (picked.length > 0) {
              setSelectedIds(prev => {
                const next = new Set(prev)
                picked.forEach(id => next.add(id))
                return next
              })
            }
          }
          if (blockTimerRef.current) {
            window.clearTimeout(blockTimerRef.current)
          }
          blockClickRef.current = true
          blockTimerRef.current = window.setTimeout(() => { blockClickRef.current = false }, 80)
        }
      }
      dragStartRef.current = null
      dragSelectingRef.current = false
      setDragSelecting(false)
      setSelectRect(null)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

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
    resetToFirstPage()
    setReloadHint(true)
    const sName = nameSearch.trim().toLowerCase()
    filterKeyRef.current = `${modelIds.join(',')}|${tagIds.join(',')}|${excludeTagIds.join(',')}|${strict}|${minHeat ?? ''}|${maxHeat ?? ''}|${order}|${randomMode}|${trueRandomCacheEnabled}|${seed}|${sName}|${refreshKey}`
    const t = setTimeout(() => setReloadHint(false), 1200)
    return () => clearTimeout(t)
  }, [modelIds.join(','), tagIds.join(','), excludeTagIds.join(','), strict, minHeat, maxHeat, order, randomMode, trueRandomCacheEnabled, nameSearch, seed, refreshKey])

  useEffect(() => {
    const run = async () => {
      if (!hasMoreRef.current || loadingRef.current) return
      const filterSig = `${modelIds.join(',')}|${tagIds.join(',')}|${excludeTagIds.join(',')}|${strict}|${minHeat ?? ''}|${maxHeat ?? ''}|${order}|${randomMode}|${trueRandomCacheEnabled}|${seed}|${nameSearch.trim().toLowerCase()}|${refreshKey}`
      const key = `${page}|${filterSig}`
      if (fetchedKeysRef.current.has(key)) return
      const controller = new AbortController()
      abortControllerRef.current?.abort()
      abortControllerRef.current = controller
      setLoading(true)
      const applyPerModelLimit = (arr: MediaItem[], limitPerModel = 2, targetCount = 30): MediaItem[] => {
        const counts = new Map<string, number>()
        const chosen: MediaItem[] = []
        const skipped: MediaItem[] = []
        const uniq = (ids: string[]) => Array.from(new Set(ids))
        for (let i = 0; i < arr.length; i++) {
          const it = arr[i]
          const ids = uniq(it.models.map(m => m.id))
          if (ids.length === 0) {
            chosen.push(it)
          } else {
            let ok = true
            for (const id of ids) {
              const c = counts.get(id) || 0
              if (c >= limitPerModel) { ok = false; break }
            }
            if (ok) {
              chosen.push(it)
              for (const id of ids) counts.set(id, (counts.get(id) || 0) + 1)
            } else {
              skipped.push(it)
            }
          }
          if (chosen.length >= targetCount) break
        }
        if (chosen.length < targetCount) {
          for (const it of skipped) {
            chosen.push(it)
            if (chosen.length >= targetCount) break
          }
        }
        return chosen
      }
      try {
        const res = await fetchMedia({
          model_ids: modelIds,
          tag_ids: tagIds,
          exclude_tag_ids: excludeTagIds,
          page,
          page_size: 30,
          strict,
          min_heat: minHeat,
          max_heat: maxHeat,
          order,
          seed,
          name: nameSearch,
          edit_mode: selectMode,
          true_random: order === 'random' && randomMode === 'true_random',
        }, controller.signal)
        if (filterKeyRef.current !== filterSig) return
        fetchedKeysRef.current.add(key)
        retryCountsRef.current.delete(key)
        const hasFilters = modelIds.length > 0 || tagIds.length > 0 || excludeTagIds.length > 0 || nameSearch.trim() !== '' || minHeat !== undefined || maxHeat !== undefined
        setItems(prev => {
          const seen = new Set(prev.map(i => i.id))
          const merged = [...prev]
          const diversified = (order === 'random' && !hasFilters) ? applyPerModelLimit(res.items, 2, 30) : res.items
          for (const it of diversified) {
            if (!seen.has(it.id)) {
              seen.add(it.id)
              merged.push(it)
            }
          }
          return merged
        })
        setHasMore(res.items.length > 0 ? res.hasMore : false)
        if (page === 1) initialLoadedRef.current = true
      } catch {
        if (filterKeyRef.current !== filterSig) return
        const nextRetryCount = (retryCountsRef.current.get(key) ?? 0) + 1
        retryCountsRef.current.set(key, nextRetryCount)
        if (nextRetryCount <= 1) {
          fetchedKeysRef.current.add(key)
          if (retryTimerRef.current) window.clearTimeout(retryTimerRef.current)
          retryTimerRef.current = window.setTimeout(() => {
            fetchedKeysRef.current.delete(key)
            setRequestRetryTick(t => t + 1)
          }, 600)
        } else {
          fetchedKeysRef.current.add(key)
        }
      } finally {
        if (filterKeyRef.current === filterSig) {
          setLoading(false)
        }
      }
    }
    run()
    return () => {
      abortControllerRef.current?.abort()
      if (retryTimerRef.current) {
        window.clearTimeout(retryTimerRef.current)
        retryTimerRef.current = null
      }
    }
  }, [page, modelIds.join(','), tagIds.join(','), excludeTagIds.join(','), strict, minHeat, maxHeat, order, randomMode, seed, nameSearch, refreshKey, selectMode, requestRetryTick])

  useEffect(() => {
    if (manualLoadMore) return
    const el = sentinel.current
    if (!el) return
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting && !loadingRef.current && hasMoreRef.current && initialLoadedRef.current) {
          setPage(p => p + 1)
        }
      })
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [sentinel.current, manualLoadMore])

  useEffect(() => {
    if (selectedIndex === null) return
    const set = prefetchedRef.current
    const ids = [selectedIndex - 1, selectedIndex + 1]
    const isVideo = (ft?: string | null) => {
      const s = (ft || '').toLowerCase()
      return ['mp4','avi','mov','mkv','webm','mpeg','mpg','m4v','mp3','m4a'].includes(s)
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
      {selectMode && (
        <BulkBar
          selectedCount={selectedIds.size}
          onAddTags={() => setPickerOpen({ type:'add' })}
          onRemoveTags={() => setPickerOpen({ type:'remove' })}
          onIncreaseHeat={() => { void applyBulkHeat(1) }}
          onDecreaseHeat={() => { void applyBulkHeat(-1) }}
          onRefresh={() => triggerRefresh()}
          onSelectAll={() => {
            try {
              const all = new Set(items.map(i => i.id))
              setSelectedIds(all)
            } catch {
              setSelectedIds(new Set(items.map(i => i.id)))
            }
          }}
          onClear={() => setSelectedIds(new Set())}
          onExit={() => {
            setSelectMode(false)
            setSelectedIds(new Set())
            try {
              const url = new URL(window.location.href)
              url.searchParams.delete('mode')
              window.history.replaceState({}, '', url.toString())
            } catch {}
          }}
          heatBusy={heatBusy}
        />
      )}
      {reloadHint && (
        <div className="toast"><div className="bubble">{strict ? '强关联已开启，重新加载…' : '强关联已关闭，重新加载…'}</div></div>
      )}
      {selectMode && order === 'random' && randomMode === 'true_random' && (
        <div className="toast"><div className="bubble">{trueRandomCacheEnabled ? '真随机缓存过滤已启用' : '真随机缓存过滤已关闭'}</div></div>
      )}
      <div
        className={`masonry${dragSelecting ? ' selecting' : ''}`}
        ref={gridRef}
        style={{ ['--col-w' as any]: `${colWidth}px` }}
        onMouseDown={onMasonryMouseDown}
        onClickCapture={(e) => {
          if (blockClickRef.current) {
            e.preventDefault()
            e.stopPropagation()
          }
        }}
      >
        {items.length > 0 && columns.map((col, ci) => (
          <div className="col" key={`col-${ci}`} style={{ ['--col-index' as any]: ci }}>
            {col.map(({ item, idx }, ri) => (
              <div key={item.id} style={{ ['--row-index' as any]: ri }}>
              <MediaCard
                key={item.id}
                item={item}
                onOpen={() => setSelectedIndex(idx)}
                onOpenSystem={async () => {
                  const s = item.file_path || ''
                  if (!s) return
                  try {
                    const u = new URL(s, window.location.origin)
                    if (u.pathname.startsWith('/api/file')) {
                      const b64 = u.searchParams.get('path')
                      if (b64) {
                        const tryPost = async (endpoint: string): Promise<boolean> => {
                          const ac = new AbortController()
                          const timer = setTimeout(() => ac.abort(), 1200)
                          try {
                            const r = await fetch(endpoint, { method: 'POST', signal: ac.signal })
                            return r.ok
                          } catch {
                            return false
                          } finally {
                            clearTimeout(timer)
                          }
                        }
                        const helperOk = await tryPost(`http://127.0.0.1:8001/open?path=${encodeURIComponent(b64)}`)
                        if (helperOk) return
                        const apiOk = await tryPost(`/api/open?path=${encodeURIComponent(b64)}`)
                        if (apiOk) return
                      }
                    }
                  } catch {}
                }}
                onTagClick={onTagClick}
                onModelClick={onModelClick}
                selectable={selectMode}
                selected={selectedIds.has(item.id)}
                dragging={dragSelecting}
                onSelectToggle={() => {
                  setSelectedIds(prev => {
                    const s = new Set(prev)
                    if (s.has(item.id)) s.delete(item.id); else s.add(item.id)
                    return s
                  })
                }}
              />
              </div>
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
      {selectRect && (
        <div
          className="selection-rect"
          style={{ left: selectRect.left, top: selectRect.top, width: selectRect.width, height: selectRect.height }}
        />
      )}
      {!loading && items.length === 0 && (
        <div className="empty-state-panel">
          <div className="empty-state-title">暂无内容</div>
        </div>
      )}
      <div ref={sentinel} />
      {loading && items.length > 0 && (
        <div className="loadmore-panel">
          <div className="spinner" />
        </div>
      )}
      {!loading && hasMore && items.length > 0 && manualLoadMore && (
        <div className="loadmore-panel">
          <button className="tool-btn primary" onClick={() => setPage(p => p + 1)}>加载下一页</button>
          <div className="loadmore-text muted">真随机缓存模式下改为手动分页</div>
        </div>
      )}
      {!hasMore && <div className="muted end-of-list">没有更多了</div>}
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
            if (mb >= 1) return `${mb.toFixed(2)}M`
            const k = Number(kb.toFixed(2))
            return `${(k <= 0 ? 0.01 : k).toFixed(2)}k`
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
          const onOpenInSystem = () => { (window as any).__openInSystem(it.file_path) }
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
      <TagPicker
        open={pickerOpen.type !== null}
        title={pickerOpen.type === 'add' ? '批量添加标签' : '批量移除标签'}
        onClose={() => setPickerOpen({ type:null })}
        onApply={async (tagIdsSel: string[]) => {
          const ids = Array.from(selectedIds)
          if (ids.length === 0 || tagIdsSel.length === 0) { setPickerOpen({ type:null }); return }
          try {
            if (pickerOpen.type === 'add') {
              await bulkAddTags(ids, tagIdsSel)
              setItems(prev => prev.map(it => {
                if (!selectedIds.has(it.id)) return it
                const exist = new Set(it.tags.map(t => t.id))
                const newTags = [...it.tags]
                tagIdsSel.forEach(tid => {
                  if (!exist.has(tid)) {
                    const meta = tagMeta.get(tid)
                    newTags.push({ id: tid, name: meta?.name || tid, category_name: meta?.category_name })
                  }
                })
                return { ...it, tags: newTags }
              }))
            } else {
              await bulkRemoveTags(ids, tagIdsSel)
              setItems(prev => prev.map(it => {
                if (!selectedIds.has(it.id)) return it
                const tset = new Set(tagIdsSel)
                return { ...it, tags: it.tags.filter(t => !tset.has(t.id)) }
              }))
            }
          } catch {}
          setPickerOpen({ type:null })
        }}
      />
    </div>
  )
}
