import { useEffect, useRef, useState } from 'react'
import { validatePassword, fetchCurrentPassword, fetchTrueRandomCacheSettings, updateTrueRandomCacheSettings, clearTrueRandomCache } from './api'
import Filters from './components/Filters'
import MediaGrid from './components/MediaGrid'
import FluidBackground from './effects/FluidBackground'
import ParticleField from './effects/ParticleField'

export default function App() {
  const [modelIds, setModelIds] = useState<string[]>([])
  const [tagIds, setTagIds] = useState<string[]>([])
  const [excludeTagIds, setExcludeTagIds] = useState<string[]>([])
  const [strict, setStrict] = useState<boolean>(true)
  const [minHeat, setMinHeat] = useState<number | undefined>()
  const [maxHeat, setMaxHeat] = useState<number | undefined>()
  const [order, setOrder] = useState<'random' | 'duration' | 'duration_asc' | 'recent' | 'recent_asc' | 'heat' | 'heat_asc'>('random')
  const [randomMode, setRandomMode] = useState<'random' | 'true_random'>('random')
  const [nameSearch, setNameSearch] = useState<string>('')
  const [locked, setLocked] = useState<boolean>(true)
  const [code, setCode] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [trueRandomCacheEnabled, setTrueRandomCacheEnabled] = useState(true)
  const [trueRandomCacheCount, setTrueRandomCacheCount] = useState(0)
  const [settingsBusy, setSettingsBusy] = useState(false)
  const [settingsHint, setSettingsHint] = useState('')
  const [editMode, setEditMode] = useState(false)
  const [seed, setSeed] = useState<number>(() => {
    const d = new Date()
    const y = d.getFullYear()
    const m = d.getMonth() + 1
    const day = d.getDate()
    return y * 10000 + m * 100 + day
  })
  const [showTop, setShowTop] = useState(false)
  const [reduceMotion, setReduceMotion] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [pageProgress, setPageProgress] = useState({ width: 0, done: false })
  const idleTimerRef = useRef<number | null>(null)
  const settingsHintTimerRef = useRef<number | null>(null)
  const loadTrueRandomSettings = async () => {
    try {
      const r = await fetchTrueRandomCacheSettings()
      setTrueRandomCacheEnabled(r.enabled)
      setTrueRandomCacheCount(r.cached_count)
    } catch {}
  }
  const flashSettingsHint = (text: string) => {
    setSettingsHint(text)
    if (settingsHintTimerRef.current) window.clearTimeout(settingsHintTimerRef.current)
    settingsHintTimerRef.current = window.setTimeout(() => setSettingsHint(''), 1800)
  }
  useEffect(() => {
    const onScroll = () => {
      setShowTop(window.scrollY > 600)
      // Sidebar color shift with scroll
      const sidebar = document.querySelector('.app-sidebar-shell') as HTMLElement | null
      if (sidebar) {
        const progress = Math.min(window.scrollY / 800, 1)
        sidebar.style.background = `rgba(255,255,255,${0.72 + progress * 0.12})`
      }
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
  useEffect(() => {
    const applyFromUrl = () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const mode = (params.get('mode') || '').toLowerCase()
        setEditMode(mode === 'edit')
      } catch {
        setEditMode(false)
      }
    }
    applyFromUrl()
    const onPop = () => applyFromUrl()
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  useEffect(() => {
    if (!editMode) return
    void loadTrueRandomSettings()
    const timer = window.setInterval(() => {
      void loadTrueRandomSettings()
    }, 15000)
    const onFocus = () => { void loadTrueRandomSettings() }
    window.addEventListener('focus', onFocus)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      if (settingsHintTimerRef.current) {
        window.clearTimeout(settingsHintTimerRef.current)
        settingsHintTimerRef.current = null
      }
    }
  }, [editMode])
  const onToggleTrueRandomCache = async (enabled: boolean) => {
    if (settingsBusy) return
    setSettingsBusy(true)
    try {
      const r = await updateTrueRandomCacheSettings(enabled)
      setTrueRandomCacheEnabled(r.enabled)
      setTrueRandomCacheCount(r.cached_count)
      flashSettingsHint(r.enabled ? '真随机缓存已开启' : '真随机缓存已关闭')
    } catch {
      flashSettingsHint('设置保存失败')
    } finally {
      setSettingsBusy(false)
    }
  }
  const onClearTrueRandomCache = async () => {
    if (settingsBusy) return
    setSettingsBusy(true)
    try {
      const r = await clearTrueRandomCache()
      setTrueRandomCacheCount(r.cached_count)
      flashSettingsHint(`已清理 ${r.deleted} 条随机缓存`)
    } catch {
      flashSettingsHint('清理缓存失败')
    } finally {
      setSettingsBusy(false)
    }
  }
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

  // Page load progress simulation
  useEffect(() => {
    if (locked) return
    let w = 0
    const timer = setInterval(() => {
      w += (100 - w) * 0.25
      if (w > 99) { w = 100; clearInterval(timer); setPageProgress({ width: 100, done: true }) }
      else setPageProgress({ width: w, done: false })
    }, 100)
    return () => clearInterval(timer)
  }, [locked])

  // Mobile detection
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  // Prefers reduced motion detection
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduceMotion(mq.matches)
    const onChange = (e: MediaQueryListEvent) => setReduceMotion(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  return (
    <div className={`app-layout${locked ? ' bg-anim' : ''}`}>
      {!locked && <div className={`page-progress${pageProgress.done ? ' done' : ''}`} style={{ width: `${pageProgress.width}%` }} />}
      {!isMobile && !reduceMotion && <FluidBackground />}
      {!isMobile && !reduceMotion && <ParticleField />}
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
            <div className="lock-actions">
              <button className="lock-btn" type="submit">进入</button>
            </div>
            {error && <div className="lock-error">{error}</div>}
          </form>
        </div>
      )}
      {!locked && (
        <>
          <aside className="app-sidebar-shell">
            <Filters
              selectedModels={modelIds}
              selectedTags={tagIds}
              excludedTags={excludeTagIds}
              strict={strict}
              minHeat={minHeat}
              maxHeat={maxHeat}
              order={order}
              editMode={editMode}
              randomMode={randomMode}
              nameSearch={nameSearch}
              onRandomizeSeed={() => setSeed(Date.now() + Math.floor(Math.random()*1e9))}
              onRandomModeChange={(mode) => setRandomMode(mode)}
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
              trueRandomCacheEnabled={trueRandomCacheEnabled}
              trueRandomCacheCount={trueRandomCacheCount}
              settingsBusy={settingsBusy}
              settingsHint={settingsHint}
              onToggleTrueRandomCache={onToggleTrueRandomCache}
              onClearTrueRandomCache={onClearTrueRandomCache}
            />
          </aside>
          <main className="app-main-shell">
            <MediaGrid
              modelIds={modelIds}
              tagIds={tagIds}
              excludeTagIds={excludeTagIds}
              strict={strict}
              minHeat={minHeat}
              maxHeat={maxHeat}
              order={order}
              randomMode={randomMode}
              trueRandomCacheEnabled={trueRandomCacheEnabled}
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
          </main>
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
