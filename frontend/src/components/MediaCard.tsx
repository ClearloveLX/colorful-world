import { useEffect, useMemo, useRef, useState } from 'react'
import type { MediaItem } from '../types'

type Props = { item: MediaItem; onOpen: () => void; onOpenSystem?: () => void; onTagClick?: (id: string) => void; onModelClick?: (id: string) => void }

export default function MediaCard({ item, onOpen, onOpenSystem, onTagClick, onModelClick }: Props) {
  const isVideo = item.file_type && ['mp4','avi','mov','mkv','webm','mpeg','mpg','m4v'].includes(item.file_type.toLowerCase())
  const cover = item.thumbnail_path || item.file_path
  const cardRef = useRef<HTMLDivElement | null>(null)
  const [tilt, setTilt] = useState<string>('')
  const [ripple, setRipple] = useState<{x:number;y:number;key:number}|null>(null)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [inView, setInView] = useState(false)
  const [imgSrc, setImgSrc] = useState<string>(cover)
  const [triedFallback, setTriedFallback] = useState<boolean>(false)
  const [imgFailed, setImgFailed] = useState<boolean>(false)
  const [beam, setBeam] = useState<string>('')
  const [sizeOverride, setSizeOverride] = useState<number | null>(null)
  const clickTimerRef = useRef<number | null>(null)
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
  const onMove = (e: React.MouseEvent) => {
    const el = cardRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const x = e.clientX - r.left
    const y = e.clientY - r.top
    const rx = ((y / r.height) - 0.5) * -6
    const ry = ((x / r.width) - 0.5) * 6
    setTilt(`perspective(600px) rotateX(${rx}deg) rotateY(${ry}deg) translateZ(0)`) 
    const tx = Math.max(0, Math.min(r.width, x)) - r.width * 0.2
    setBeam(`translate(${tx}px, -10%) rotate(-12deg)`) 
  }
  const onLeave = () => { setTilt(''); setBeam('') }
  const onClick = (e: React.MouseEvent) => {
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
    return () => { io.disconnect() }
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
  return (
    <div className="card tilt" ref={cardRef} style={{ transform: tilt }} onMouseMove={onMove} onMouseLeave={onLeave}>
      <div className={`card-cover${imgLoaded ? ' loaded' : ''}`} onClick={onClick} onDoubleClick={onDoubleClick} style={{ cursor:'pointer', background:'#f5f8ff', aspectRatio: aspect }}>
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
        <div className="shine" />
        <div className="hover-beam" style={{ transform: beam }} />

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
        <div className="meta" style={{ marginTop: 4 }}>
          {(() => {
            const size = fmtSize(sizeOverride ?? item.file_size)
            const dur = isVideo ? fmtDurZh(item.duration_ms) : null
            const text = isVideo ? [size, dur].filter(Boolean).join(' · ') : size
            return text ? (<span className="card-tag">{text}</span>) : null
          })()}
        </div>
        {item.tags.length > 0 && (
          <div className="meta" style={{ marginTop: 4 }}>
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
