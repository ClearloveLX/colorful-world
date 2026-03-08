import { useEffect, useMemo, useState } from 'react'
import { fetchTags } from '../api'
import type { Tag } from '../types'

type Props = {
  open: boolean
  onClose: () => void
  onApply: (tagIds: string[]) => void
  title?: string
}

export default function TagPicker({ open, onClose, onApply, title }: Props) {
  const [tags, setTags] = useState<Tag[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (!open) return
    fetchTags().then(setTags).catch(() => setTags([]))
    setSelected(new Set())
    setSearch('')
  }, [open])
  const groups = useMemo(() => {
    const g: Record<string, Tag[]> = {}
    const q = search.trim().toLowerCase()
    tags.forEach(t => {
      const k = t.category_name || '未分类'
      if (!g[k]) g[k] = []
      if (!q || `${t.name}${t.category_name ?? ''}`.toLowerCase().includes(q)) g[k].push(t)
    })
    return g
  }, [tags, search])
  if (!open) return null
  return (
    <div className="lightbox-backdrop" onClick={onClose}>
      <div className="lightbox-body anim-in dialog-panel" onClick={e => e.stopPropagation()} style={{ display: 'flex', flexDirection: 'column', height: '85vh', width: '600px', maxWidth: '95vw' }}>
        <div className="dialog-header">
          <div className="dialog-title">{title || '选择标签'}</div>
          <div className="dialog-actions">
            <button className="tool-btn primary" onClick={() => onApply(Array.from(selected))}>应用</button>
            <button className="tool-btn" onClick={onClose}>关闭</button>
          </div>
        </div>
        <input className="search-input" placeholder="搜索标签" value={search} onChange={e => setSearch(e.target.value)} />
        <div style={{ display:'flex', flexDirection: 'column', gap:8, marginTop:8, flex: 1, overflow:'auto' }}>
          {Object.entries(groups).map(([k, list]) => (
            <div key={k}>
              <div className="section-title">{k}（{list.length}）</div>
              <div style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
                {list.map(t => {
                  const isSel = selected.has(t.id)
                  const toggle = () => {
                    const s = new Set(selected)
                    if (s.has(t.id)) s.delete(t.id); else s.add(t.id)
                    setSelected(s)
                  }
                  return (
                    <button
                      key={t.id}
                      type="button"
                      className={`tag-chip${isSel ? ' selected' : ''}`}
                      onClick={toggle}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}
                      aria-pressed={isSel}
                    >
                      <span>{t.name}</span>
                      {isSel && <span style={{ marginLeft:8 }}>✓</span>}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
