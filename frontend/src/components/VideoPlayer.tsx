import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  src: string
  onLoadedMetadata?: (e: React.SyntheticEvent<HTMLVideoElement>) => void
  autoplay?: boolean
  initialVolume?: number
  style?: React.CSSProperties
}

export default function VideoPlayer({ src, onLoadedMetadata, autoplay = true, initialVolume = 0.08, style }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [playing, setPlaying] = useState<boolean>(false)
  const playingRef = useRef(playing)
  playingRef.current = playing
  const [muted, setMuted] = useState<boolean>(false)
  const [vol, setVol] = useState<number>(initialVolume)
  const [cur, setCur] = useState<number>(0)
  const [dur, setDur] = useState<number>(0)
  const [rate, setRate] = useState<number>(1)
  const [rateOpen, setRateOpen] = useState<boolean>(false)
  const rateWrapRef = useRef<HTMLDivElement | null>(null)
  const rateBtnRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null)
  const [fs, setFs] = useState<boolean>(false)
  const [srcToken, setSrcToken] = useState<number>(0)
  const retryLockRef = useRef<number>(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.volume = Math.max(0, Math.min(1, vol))
  }, [vol])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.muted = muted
  }, [muted])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.playbackRate = rate
  }, [rate])

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      const w = rateWrapRef.current
      const m = menuRef.current
      if (!w && !m) return
      if (e.target instanceof Node) {
        const insideBtn = w ? w.contains(e.target) : false
        const insideMenu = m ? m.contains(e.target) : false
        if (!insideBtn && !insideMenu) {
          setRateOpen(false)
        }
      }
    }
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [])

  useEffect(() => {
    if (!rateOpen) return
    const btn = rateBtnRef.current
    const menu = menuRef.current
    if (!btn || !menu) return
    const update = () => {
      const br = btn.getBoundingClientRect()
      const mr = menu.getBoundingClientRect()
      const margin = 8
      let top = br.bottom + 6
      let left = br.left
      if (top + mr.height > window.innerHeight - margin) {
        top = Math.max(margin, br.top - mr.height - 6)
      }
      if (left + mr.width > window.innerWidth - margin) {
        left = Math.max(margin, window.innerWidth - mr.width - margin)
      }
      setMenuPos({ top: Math.round(top), left: Math.round(left) })
    }
    update()
    const ro = new ResizeObserver(() => update())
    ro.observe(menu)
    return () => ro.disconnect()
  }, [rateOpen])

  useEffect(() => {
    const onFs = () => { setFs(!!document.fullscreenElement) }
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  const onMeta = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const el = e.currentTarget
    setDur(el.duration || 0)
    el.volume = Math.max(0, Math.min(1, initialVolume))
    if (autoplay) {
      el.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
    }
    onLoadedMetadata && onLoadedMetadata(e)
  }

  const onTime = () => {
    const el = ref.current
    if (!el) return
    setCur(el.currentTime || 0)
  }

  const togglePlay = () => {
    const el = ref.current
    if (!el) return
    if (playing) {
      el.pause()
      setPlaying(false)
    } else {
      el.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
    }
  }

  const toggleFs = () => {
    if (fs) {
      document.exitFullscreen().catch(() => {})
      return
    }
    const w = wrapRef.current
    if (w) { w.requestFullscreen().catch(() => {}) }
  }

  const onSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const el = ref.current
    if (!el) return
    const v = Number(e.target.value)
    el.currentTime = v
  }
  const retryPlayback = () => {
    const now = Date.now()
    if (now - (retryLockRef.current || 0) < 5000) return
    retryLockRef.current = now
    const el = ref.current
    if (!el) return
    const prevTime = el.currentTime || 0
    const prevMuted = muted
    const prevVol = vol
    setSrcToken(t => t + 1)
    setTimeout(() => {
      const v = ref.current
      if (!v) return
      try {
        v.load()
        v.currentTime = Math.min(prevTime, dur || prevTime)
      } catch {}
      v.muted = prevMuted
      v.volume = Math.max(0, Math.min(1, prevVol))
      if (autoplay || playing) {
        v.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
      }
    }, 20)
  }
  useEffect(() => {
    const id = window.setInterval(() => {
      const el = ref.current
      if (!el) return
      const rs = el.readyState
      if (playingRef.current && rs < 3) {
        retryPlayback()
      }
    }, 3000)
    return () => window.clearInterval(id)
  }, [src])

  const fmt = (s: number) => {
    const m = Math.floor(s / 60)
    const r = Math.floor(s % 60)
    return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}`
  }

  const controlsReservedPx = 104
  const videoMaxH = (() => {
    const mh = style?.maxHeight
    const base = typeof mh === 'string' ? mh : (typeof mh === 'number' ? `${mh}px` : '90vh')
    return `calc(${base} - ${controlsReservedPx}px)`
  })()
  const videoStyle: React.CSSProperties = {
    maxWidth: style?.maxWidth,
    maxHeight: videoMaxH,
    objectFit: 'contain',
    width: '100%',
  }
  const rateLabel = (v: number) => {
    if (Number.isInteger(v)) return `${v.toFixed(1).replace(/\.0$/, '')}x`
    const vs = String(v)
    return `${vs.endsWith('0') ? vs.replace(/0$/, '') : vs}x`
  }
  const wrapStyle: React.CSSProperties = fs
    ? {
        display: 'grid',
        gap: 8,
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        background: '#000',
        overflow: 'hidden',
        justifyItems: 'center',
        alignItems: 'center',
      }
    : {
        display: 'grid',
        gap: 8,
        overflow: 'visible',
        maxWidth: style?.maxWidth,
        maxHeight: style?.maxHeight,
      }
  const videoStyleFs: React.CSSProperties = {
    maxWidth: '100vw',
    maxHeight: `calc(100vh - ${controlsReservedPx}px)`,
    objectFit: 'contain',
    width: '100%',
    height: `calc(100vh - ${controlsReservedPx}px)`,
    background: '#000',
  }
  const srcUrl = `${src}${src.includes('?') ? '&' : '?'}t=${srcToken}`

  return (
    <div ref={wrapRef} style={wrapStyle} className={`video-player-wrap${fs ? ' is-fullscreen' : ''}`}>
      <video
        ref={ref}
        src={srcUrl}
        controls={false}
        aria-label="视频播放器"
        onLoadedMetadata={onMeta}
        onTimeUpdate={onTime}
        onError={retryPlayback}
        onStalled={retryPlayback}
        onWaiting={() => { if (playing) retryPlayback() }}
        onEmptied={retryPlayback}
        playsInline
        style={fs ? videoStyleFs : videoStyle}
        preload="metadata"
        loop
      />
      <div className="video-controls-row">
        <button className="video-btn" onClick={togglePlay}>{playing ? '暂停' : '播放'}</button>
        <button className="video-btn" onClick={toggleFs}>{fs ? '退出全屏' : '全屏'}</button>
        <span className="muted">{fmt(cur)} / {fmt(dur)}</span>
        <input className="video-range" type="range" min={0} max={dur || 0} step={0.1} value={Math.min(cur, dur || 0)} onChange={onSeek} style={{ flex:1 }} aria-label="播放进度" />
      </div>
      <div className="video-controls-row">
        <button className="video-btn" onClick={() => setMuted(m => !m)}>{muted ? '取消静音' : '静音'}</button>
        <input className="video-range" type="range" min={0} max={1} step={0.01} value={muted ? 0 : vol} onChange={e => setVol(Number(e.target.value))} style={{ width:160 }} aria-label="音量" />
        <div ref={rateWrapRef} style={{ position:'relative' }}>
          <button
            className="video-btn"
            ref={rateBtnRef}
            onClick={() => {
              setRateOpen(o => {
                const next = !o
                if (next) {
                  const el = rateBtnRef.current
                  if (el) {
                    const r = el.getBoundingClientRect()
                    setMenuPos({ top: Math.round(r.bottom + 6), left: Math.round(r.left) })
                  }
                }
                return next
              })
            }}
            style={{ minWidth:90, fontSize:14 }}
            title="倍速"
          >
            倍速：{rateLabel(rate)} ▾
          </button>
          {rateOpen && menuPos && createPortal(
            <div
              ref={menuRef}
              className="video-rate-menu"
              style={{
                position:'fixed',
                top: menuPos.top,
                left: menuPos.left,
                padding:8,
                minWidth:160,
                maxHeight:'50vh',
                overflowY:'auto',
                zIndex:10000
              }}
            >
              {[0.5,0.75,1,1.25,1.5,2].map(v => (
                <button
                  key={`rate-${v}`}
                  onClick={() => { setRate(v); setRateOpen(false) }}
                  className={`video-rate-item${v === rate ? ' active' : ''}`}
                  style={{
                    display:'block',
                    width:'100%',
                    textAlign:'left',
                    padding:'10px 12px',
                    margin:'2px 0',
                    fontSize:16
                  }}
                >
                  {rateLabel(v)}
                </button>
              ))}
            </div>,
            document.body
          )}
        </div>
      </div>
    </div>
  )
}
