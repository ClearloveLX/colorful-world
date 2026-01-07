import { useEffect, useRef, useState } from 'react'
import Filters from './components/Filters'
import MediaGrid from './components/MediaGrid'

export default function App() {
  const [modelIds, setModelIds] = useState<string[]>([])
  const [tagIds, setTagIds] = useState<string[]>([])
  const [strict, setStrict] = useState<boolean>(false)
  const [order, setOrder] = useState<'random' | 'duration' | 'recent'>('random')
  const seedRef = useRef<number>((() => {
    const d = new Date()
    const y = d.getFullYear()
    const m = d.getMonth() + 1
    const day = d.getDate()
    return y * 10000 + m * 100 + day
  })())
  const [showTop, setShowTop] = useState(false)
  useEffect(() => {
    const onScroll = () => {
      setShowTop(window.scrollY > 600)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  return (
    <div className="app-layout">
      <Filters
        selectedModels={modelIds}
        selectedTags={tagIds}
        strict={strict}
        order={order}
        onChange={(m, t, s) => {
          setModelIds(m)
          setTagIds(t)
          setStrict(s)
        }}
        onOrderChange={(o) => setOrder(o)}
      />
      <MediaGrid
        modelIds={modelIds}
        tagIds={tagIds}
        strict={strict}
        order={order}
        seed={seedRef.current}
        onTagClick={(id) => {
          setTagIds([id])
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
    </div>
  )
}
