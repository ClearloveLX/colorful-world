import { useEffect, useMemo, useRef, useState } from 'react'
import type { MediaItem } from '../types'
import { likeMedia, dislikeMedia } from '../api'

type Props = { item: MediaItem; onOpen: () => void; onOpenSystem?: () => void; onLocate?: () => void; highlighted?: boolean; onTagClick?: (id: string) => void; onModelClick?: (id: string) => void }
type ExtraProps = { selectable?: boolean; selected?: boolean; onSelectToggle?: () => void; dragging?: boolean }

export default function MediaCard({ item, onOpen, onOpenSystem, onLocate, highlighted, onTagClick, onModelClick, selectable, selected, onSelectToggle, dragging }: Props & ExtraProps) {
  const isVideo = item.file_type && ['mp4','avi','mov','mkv','webm','mpeg','mpg','m4v','mp3','m4a'].includes(item.file_type.toLowerCase())
  const cover = item.thumbnail_path || item.file_path
  const cardRef = useRef<HTMLDivElement | null>(null)
  const [ripple, setRipple] = useState<{x:number;y:number;key:number}|null>(null)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [inView, setInView] = useState(false)
  const [imgSrc, setImgSrc] = useState<string>(cover)
  const [triedFallback, setTriedFallback] = useState<boolean>(false)
  const [imgFailed, setImgFailed] = useState<boolean>(false)
  const [sizeOverride, setSizeOverride] = useState<number | null>(null)
  const clickTimerRef = useRef<number | null>(null)
  const [heat, setHeat] = useState<number>(Number(item.heat_value ?? 0))
  const [liking, setLiking] = useState<boolean>(false)
  const [disliking, setDisliking] = useState<boolean>(false)
  const mutationInFlightRef = useRef<boolean>(false)
  const lastClickRef = useRef<number>(0)
  const lastClickDownRef = useRef<number>(0)
  const [flyKey, setFlyKey] = useState<number | null>(null)
  const [flyDownKey, setFlyDownKey] = useState<number | null>(null)
  const [dispHeat, setDispHeat] = useState<number>(Number(item.heat_value ?? 0))
  const heatAnimRef = useRef<number | null>(null)
  const [heatBumpKey, setHeatBumpKey] = useState<number | null>(null)
  const busy = liking || disliking
  const aspect = useMemo(() => {
    const w = item.image_width || 0
    const h = item.image_height || 0
    if (w > 0 && h > 0) return `${w}/${h}`
    return undefined
  }, [item.image_width, item.image_height])
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
  const onClick = (e: React.MouseEvent) => {
    if (selectable) {
      e.preventDefault()
      e.stopPropagation()
      onSelectToggle && onSelectToggle()
      return
    }
    const el = cardRef.current
    if (!el) { onOpen(); return }
    const r = el.getBoundingClientRect()
    const x = e.clientX - r.left
    const y = e.clientY - r.top
    const key = Date.now()
    setRipple({ x, y, key })
    setTimeout(() => setRipple(null), 600)
    if (clickTimerRef.current) { window.clearTimeout(clickTimerRef.current); clickTimerRef.current = null }
    clickTimerRef.current = window.setTimeout(() => {
      onOpen()
      clickTimerRef.current = null
    }, 260)
  }
  const onDoubleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (clickTimerRef.current) { window.clearTimeout(clickTimerRef.current); clickTimerRef.current = null }
    onOpenSystem && onOpenSystem()
  }
  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => { if (e.isIntersecting) setInView(true) })
    }, { rootMargin: '80px' })
    io.observe(el)
    return () => {
      io.disconnect()
      if (clickTimerRef.current) {
        window.clearTimeout(clickTimerRef.current)
        clickTimerRef.current = null
      }
    }
  }, [])
  useEffect(() => {
    setSizeOverride(null)
    const bytes = item.file_size || 0
    if (bytes > 0) return
    const url = item.file_path
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
              if (isFinite(n) && n > 0) { setSizeOverride(n); return }
            }
          }
        } catch {}
        try {
          const r = await fetch(url, { method: 'HEAD' })
          const cl = r.headers.get('content-length')
          if (cl) {
            const n = Number(cl)
            if (isFinite(n) && n > 0) { setSizeOverride(n); return }
          }
        } catch {}
      })().catch(() => {})
    } catch {}
  }, [item.id, item.file_path, item.file_size])
  useEffect(() => {
    if (!mutationInFlightRef.current) {
      setHeat(Number(item.heat_value ?? 0))
    }
  }, [item.id, item.heat_value])
  const onLike = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const now = Date.now()
    if (busy || (now - lastClickRef.current) < 420) return
    lastClickRef.current = now
    mutationInFlightRef.current = true
    setHeat(h => (Number.isFinite(h) ? h + 1 : 1))
    setFlyKey(now)
    setLiking(true)
    try {
      const res = await likeMedia(item.id)
      if (typeof res?.heat_value === 'number') setHeat(res.heat_value)
    } catch {
      // 保持乐观更新，不回滚
    } finally {
      setLiking(false)
      mutationInFlightRef.current = false
    }
  }
  const fmtHeat = (n?: number | null): string => {
    const v = Number(n || 0)
    if (!isFinite(v)) return '0'
    if (v >= 1_000_000) return `${(v/1_000_000).toFixed(2)}M`
    if (v >= 10_000) return `${(v/1000).toFixed(1)}k`
    return String(v)
  }
  useEffect(() => {
    const from = dispHeat
    const to = heat
    const d = 280
    if (heatAnimRef.current) {
      try { cancelAnimationFrame(heatAnimRef.current) } catch {}
      heatAnimRef.current = null
    }
    const start = performance.now()
    const step = (ts: number) => {
      const p = Math.min((ts - start) / d, 1)
      const eased = p < 0 ? 0 : (p * (2 - p))
      const val = Math.round(from + (to - from) * eased)
      setDispHeat(val)
      if (p < 1) {
        heatAnimRef.current = requestAnimationFrame(step)
      } else {
        heatAnimRef.current = null
      }
    }
    setHeatBumpKey(Date.now())
    heatAnimRef.current = requestAnimationFrame(step)
    return () => {
      if (heatAnimRef.current) {
        try { cancelAnimationFrame(heatAnimRef.current) } catch {}
        heatAnimRef.current = null
      }
    }
  }, [heat])
  return (
    <div className={`card${selected ? ' card-selected' : ''}${highlighted ? ' highlight-pulse' : ''}`} ref={cardRef} data-media-id={item.id}>
      <div className={`card-cover${imgLoaded ? ' loaded' : ''}`} onClick={onClick} onDoubleClick={onDoubleClick} style={{ aspectRatio: aspect }}>
        {selectable && (
          <label className="card-select-toggle" onClick={(e) => { e.stopPropagation(); onSelectToggle && onSelectToggle() }}>
            <input type="checkbox" checked={!!selected} readOnly className="card-select-checkbox" />
            <span className="muted">选择</span>
          </label>
        )}
        {onLocate && (
          <button
            className="card-locate-btn"
            onClick={(e) => { e.stopPropagation(); onLocate() }}
            title="定位到最新排序"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/></svg>
            <span>定位</span>
          </button>
        )}
        {(!imgLoaded || imgFailed) && <div className="img-placeholder" />}
        <img
          src={imgSrc}
          alt={item.title}
          loading="lazy"
          decoding="async"
          className={imgLoaded && inView ? 'img-loaded img-fade' : 'img-loading'}
          style={{ height: aspect ? '100%' as const : 'auto' }}
          onLoad={() => { setImgFailed(false); setImgLoaded(true) }}
          onError={() => {
            if (!triedFallback && cover !== item.file_path) {
              setTriedFallback(true)
              setImgSrc(item.file_path)
            } else {
              setImgFailed(true)
            }
          }}
        />

        {ripple && <span className="ripple" style={{ left: ripple.x, top: ripple.y, width: 120, height: 120 }} />}
        {isVideo && (
          <div className="video-corner">
            <span className="video-corner-icon">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M9 6l10 6-10 6V6z" fill="currentColor" />
              </svg>
            </span>
          </div>
        )}
        {isVideo && (
          <div className="play-badge"><div className="dot">▶</div></div>
        )}
        {isVideo && typeof item.duration_ms === 'number' && item.duration_ms > 0 && (
          <div className="duration">{fmtDurZh(item.duration_ms)}</div>
        )}
      </div>
      <div className="card-content">
        <div className="title">{item.title}</div>
        <div className="meta">
          {item.models.map(m => (
            <button
              key={m.id}
              className="card-tag model"
              onClick={(e) => { e.stopPropagation(); onModelClick && onModelClick(m.id) }}
              title={`按模特筛选：${m.name}`}
            >
              {m.name}
            </button>
          ))}
        </div>
        <div className="meta card-meta-row">
          {(() => {
            const size = fmtSize(sizeOverride ?? item.file_size)
            const dur = isVideo ? fmtDurZh(item.duration_ms) : null
            const text = isVideo ? [size, dur].filter(Boolean).join(' · ') : size
            return text ? (<span className="card-tag">{text}</span>) : null
          })()}
        </div>
        <div className="meta card-actions-row">
          <span className="card-tag heat-pill" title={`好感度：${heat}`}>
            <span className="heat-icon" aria-hidden>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="#ef4444" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 21s-6.716-4.09-9.192-6.566C1.332 13.956 1 12.872 1 11.727 1 9.1 3.1 7 5.727 7c1.516 0 2.897.643 3.846 1.669L12 11.136l2.427-2.467C15.376 7.643 16.757 7 18.273 7 20.9 7 23 9.1 23 11.727c0 1.145-.332 2.229-1.808 2.707C18.716 16.91 12 21 12 21z"/>
              </svg>
            </span>
            <span className={`heat-count${heatBumpKey ? ' bump' : ''}`} key={heatBumpKey || undefined}>{fmtHeat(dispHeat)}</span>
          </span>
          <button
            className={`pill pill-dark clickable like-btn${liking ? ' disabled' : ''}`}
            onClick={onLike}
            title="好感度+1"
            aria-label="点赞"
            disabled={liking}
          >
            <span style={{ display:'inline-flex', alignItems:'center', justifyContent:'center', width:18, height:18 }}>👍</span>
          </button>
          {flyKey && (
            <>
              <span key={`fp0-${flyKey}`} className="like-particle p0" />
              <span key={`fp1-${flyKey}`} className="like-particle p1" />
              <span key={`fp2-${flyKey}`} className="like-particle p2" />
              <span key={`fp3-${flyKey}`} className="like-particle p3" />
              <span key={`fp4-${flyKey}`} className="like-particle p4" />
              <span key={`fp5-${flyKey}`} className="like-particle p5" />
              <span key={`fp6-${flyKey}`} className="like-particle p6" />
            </>
          )}
          <button
            className={`pill pill-dark clickable dislike-btn${disliking ? ' disabled' : ''}`}
            onClick={(e) => {
              e.stopPropagation()
              const now = Date.now()
              if (busy || (now - lastClickDownRef.current) < 420) return
              lastClickDownRef.current = now
              mutationInFlightRef.current = true
              setHeat(h => (Number.isFinite(h) ? h - 1 : -1))
              setFlyDownKey(now)
              setDisliking(true)
              ;(async () => {
                try {
                  const res = await dislikeMedia(item.id)
                  if (typeof res?.heat_value === 'number') setHeat(res.heat_value)
                } finally {
                  setDisliking(false)
                  mutationInFlightRef.current = false
                }
              })()
            }}
            title="好感度-1"
            aria-label="点踩"
            disabled={busy}
          >
            <span style={{ display:'inline-flex', alignItems:'center', justifyContent:'center', width:18, height:18 }}>👎</span>
          </button>
          {flyDownKey && (
            <span key={`d-${flyDownKey}`} className="dislike-fly">-1</span>
          )}
        </div>
        {item.tags.length > 0 && (
          <div className="meta card-meta-row">
            {item.tags.map(t => (
              <button
                key={t.id}
                className="card-tag"
                onClick={(e) => { e.stopPropagation(); onTagClick && onTagClick(t.id) }}
                title={`按标签筛选：${t.name}`}
              >
                {t.name}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
