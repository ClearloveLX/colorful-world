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
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
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
      <div className="lightbox-body anim-in dialog-panel tag-picker-panel" onClick={e => e.stopPropagation()}>
        <div className="dialog-header tag-picker-header">
          <div className="dialog-title">{title || '选择标签'}</div>
          <div className="dialog-actions">
            <button className="tool-btn primary" onClick={() => onApply(Array.from(selected))} disabled={selected.size === 0}>应用</button>
            <button className="tool-btn" onClick={onClose}>关闭</button>
          </div>
        </div>
        <input className="search-input" placeholder="搜索标签" value={search} onChange={e => setSearch(e.target.value)} />
        <div className="tag-picker-body">
          {Object.entries(groups).map(([k, list]) => (
            <div key={k}>
              <div className="section-title">{k}（{list.length}）</div>
              <div className="tag-picker-tags">
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
                      {isSel && <span className="tag-picker-check">✓</span>}
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
