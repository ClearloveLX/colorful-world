import { useEffect, useRef, useState } from 'react'
import { validatePassword, fetchCurrentPassword } from './api'
import Filters from './components/Filters'
import MediaGrid from './components/MediaGrid'

export default function App() {
  const [modelIds, setModelIds] = useState<string[]>([])
  const [tagIds, setTagIds] = useState<string[]>([])
  const [excludeTagIds, setExcludeTagIds] = useState<string[]>([])
  const [strict, setStrict] = useState<boolean>(true)
  const [minHeat, setMinHeat] = useState<number | undefined>()
  const [maxHeat, setMaxHeat] = useState<number | undefined>()
  const [order, setOrder] = useState<'random' | 'duration' | 'duration_asc' | 'recent' | 'recent_asc' | 'heat' | 'heat_asc'>('random')
  const [nameSearch, setNameSearch] = useState<string>('')
  const [locked, setLocked] = useState<boolean>(true)
  const [code, setCode] = useState<string>('')
  const [error, setError] = useState<string>('')
  const seedInit = (() => {
    const d = new Date()
    const y = d.getFullYear()
    const m = d.getMonth() + 1
    const day = d.getDate()
    return y * 10000 + m * 100 + day
  })()
  const [seed, setSeed] = useState<number>(seedInit)
  const [showTop, setShowTop] = useState(false)
  const idleTimerRef = useRef<number | null>(null)
  useEffect(() => {
    const onScroll = () => {
      setShowTop(window.scrollY > 600)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    if (locked) {
      if (idleTimerRef.current) {
        window.clearTimeout(idleTimerRef.current)
        idleTimerRef.current = null
      }
      return
    }
    const resetIdle = () => {
      if (idleTimerRef.current) window.clearTimeout(idleTimerRef.current)
      idleTimerRef.current = window.setTimeout(() => {
        setLocked(true)
        setCode('')
        setError('')
      }, 10 * 60 * 1000)
    }
    const onActivity = () => resetIdle()
    const events: Array<keyof WindowEventMap> = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel']
    events.forEach(evt => window.addEventListener(evt, onActivity, { passive: true }))
    resetIdle()
    return () => {
      if (idleTimerRef.current) {
        window.clearTimeout(idleTimerRef.current)
        idleTimerRef.current = null
      }
      events.forEach(evt => window.removeEventListener(evt, onActivity))
    }
  }, [locked])
  const onSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    setError('')
    const s = code.trim()
    if (!s) { setError(''); return }
    try {
      const r = await validatePassword(s)
      if (r.ok) { setLocked(false); setCode(''); return }
      setError('密码错误或已过期')
    } catch {
      setError('请求失败，请稍后重试')
    }
  }
  const onFillFromLocal = () => {
    try {
      const v = window.localStorage.getItem('cw_access_code') || ''
      if (v) {
        setCode(v)
        try { navigator.clipboard.writeText(v) } catch {}
      }
    } catch {}
  }
  useEffect(() => {
    if (!locked) return
    ;(async () => {
      try {
        const r = await fetchCurrentPassword()
        const v = String(r.code || '')
        try {
          window.localStorage.setItem('cw_access_code', v)
        } catch {}
      } catch {}
    })()
  }, [locked])
  return (
    <div className={`app-layout${locked ? ' bg-anim' : ''}`}>
      {locked && (
        <div className="lock-overlay">
          <form className="lock-card" onSubmit={onSubmit}>
            <div className="lock-title">访问密码</div>
            <input
              className="lock-input"
              type="password"
              autoFocus
              value={code}
              onChange={e => setCode(e.target.value)}
              placeholder="请输入访问密码"
            />
            <button className="lock-btn" type="submit">进入</button>
            {error && <div className="lock-error">密码错误</div>}
          </form>
        </div>
      )}
      {!locked && (
        <>
          <Filters
            selectedModels={modelIds}
            selectedTags={tagIds}
            excludedTags={excludeTagIds}
            strict={strict}
            minHeat={minHeat}
            maxHeat={maxHeat}
            order={order}
            nameSearch={nameSearch}
            onRandomizeSeed={() => setSeed(Date.now() + Math.floor(Math.random()*1e9))}
            onChange={(m, t, ex, s) => {
              setModelIds(m)
              setTagIds(t)
              setExcludeTagIds(ex)
              setStrict(s)
            }}
            onHeatChange={(min, max) => {
              setMinHeat(min)
              setMaxHeat(max)
            }}
            onOrderChange={(o) => setOrder(o)}
            onNameSearchChange={(q) => setNameSearch(q)}
          />
          <MediaGrid
            modelIds={modelIds}
            tagIds={tagIds}
            excludeTagIds={excludeTagIds}
            strict={strict}
            minHeat={minHeat}
            maxHeat={maxHeat}
            order={order}
            nameSearch={nameSearch}
            seed={seed}
            onTagClick={(id) => {
          setTagIds(prev => {
            const s = new Set(prev)
            s.add(id)
            return Array.from(s)
          })
            }}
            onModelClick={(id) => {
              setModelIds([id])
            }}
          />
          <button
            className={`back-to-top${showTop ? ' show' : ''}`}
            aria-label="回到顶部"
            title="回到顶部"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 5l-7 7h4v7h6v-7h4l-7-7z" fill="currentColor"/>
            </svg>
          </button>
        </>
      )}
    </div>
  )
}
