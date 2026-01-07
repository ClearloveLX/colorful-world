import { useEffect, useMemo, useState } from 'react'
import { fetchModels, fetchTags } from '../api'
import type { Model, Tag } from '../types'

type Props = {
  selectedModels: string[]
  selectedTags: string[]
  strict: boolean
  order: 'random' | 'duration' | 'recent'
  onChange: (models: string[], tags: string[], strict: boolean) => void
  onOrderChange: (order: 'random' | 'duration' | 'recent') => void
}

export default function Filters({ selectedModels, selectedTags, strict, order, onChange, onOrderChange }: Props) {
  const [models, setModels] = useState<Model[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [modelSearch, setModelSearch] = useState('')
  const [tagSearch, setTagSearch] = useState('')
  const [modelOpenGroups, setModelOpenGroups] = useState<Record<string, boolean>>({})
  const [tagOpenGroups, setTagOpenGroups] = useState<Record<string, boolean>>({})

  useEffect(() => {
    fetchModels().then(setModels)
    fetchTags().then(setTags)
  }, [])

  const modelGroups = useMemo(() => {
    const groups: Record<string, Model[]> = {}
    models.forEach(m => {
      const key = m.type || '未分类'
      if (!groups[key]) groups[key] = []
      groups[key].push(m)
    })
    return groups
  }, [models])

  const tagGroups = useMemo(() => {
    const groups: Record<string, Tag[]> = {}
    tags.forEach(t => {
      const key = t.category_name || '未分类'
      if (!groups[key]) groups[key] = []
      groups[key].push(t)
    })
    return groups
  }, [tags])

  const toggle = (arr: string[], id: string) => {
    const s = new Set(arr)
    if (s.has(id)) s.delete(id)
    else s.add(id)
    return Array.from(s)
  }

  const filteredModelsByGroup = useMemo(() => {
    const q = modelSearch.trim().toLowerCase()
    const entries = Object.entries(modelGroups)
    if (!q) return entries
    return entries.map(([g, list]) => [g, list.filter(m => `${m.name}${m.type ?? ''}`.toLowerCase().includes(q))] as [string, Model[]])
  }, [modelGroups, modelSearch])

  const filteredTagsByGroup = useMemo(() => {
    const q = tagSearch.trim().toLowerCase()
    const entries = Object.entries(tagGroups)
    if (!q) return entries
    return entries.map(([g, list]) => [g, list.filter(t => `${t.name}${t.category_name ?? ''}`.toLowerCase().includes(q))] as [string, Tag[]])
  }, [tagGroups, tagSearch])

  return (
    <div className="sidebar">
      <div className="section-title">筛选</div>
      <label className="chip" style={{ marginBottom: 12 }}>
        <input type="checkbox" checked={strict} onChange={e => onChange(selectedModels, selectedTags, e.target.checked)} />
        <span>强关联</span>
      </label>
      <div style={{ marginBottom: 12 }}>
        <div className="section-title">排序</div>
        <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
          <button className={`sort-btn${order==='random' ? ' active' : ''}`} onClick={() => onOrderChange('random')} title="随机排序">随机</button>
          <button className={`sort-btn${order==='duration' ? ' active' : ''}`} onClick={() => onOrderChange('duration')} title="按时长排序">时长</button>
        </div>
      </div>
      <div style={{ marginBottom: 12 }}>
        <div className="section-title">模特</div>
        <input className="search-input" value={modelSearch} onChange={e => setModelSearch(e.target.value)} placeholder="搜索模特或类型" />
        <div style={{ display: 'grid', gap: 8 }}>
          {filteredModelsByGroup.map(([group, list]) => (
            <div key={`model-group-${group}`}>
              <div className="group-header" onClick={() => setModelOpenGroups(s => ({ ...s, [group]: (s[group] === undefined ? false : !s[group]) }))}>
                <span className="group-name">{group}</span>
                <span style={{ display:'flex', alignItems:'center', gap:8 }}>
                  <span className={`caret${(modelOpenGroups[group] !== false) ? ' open' : ''}`} />
                  <span className="badge-count">{list.length}</span>
                </span>
              </div>
              {modelOpenGroups[group] !== false && (
                <div className="chips" style={{ marginTop: 6 }}>
                  {list.map(m => (
                    <label key={m.id} className={`chip ${selectedModels.includes(m.id) ? 'selected' : ''}`}>
                      <input type="checkbox" checked={selectedModels.includes(m.id)} onChange={() => onChange(toggle(selectedModels, m.id), selectedTags, strict)} />
                      {m.preview_image_path ? (
                        <img src={m.preview_image_path} alt={m.name} width={20} height={20} style={{ borderRadius: '50%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{ width: 20, height: 20, borderRadius: '50%', background: '#999', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 12 }}>{m.name[0]}</div>
                      )}
                      <span>{m.name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="section-title">标签</div>
        <input className="search-input" value={tagSearch} onChange={e => setTagSearch(e.target.value)} placeholder="搜索标签" />
        <div style={{ display: 'grid', gap: 8 }}>
          {filteredTagsByGroup.map(([group, list]) => (
            <div key={group}>
              <div className="group-header" onClick={() => setTagOpenGroups(s => ({ ...s, [group]: (s[group] === undefined ? false : !s[group]) }))}>
                <span className="group-name">{group}</span>
                <span style={{ display:'flex', alignItems:'center', gap:8 }}>
                  <span className={`caret${(tagOpenGroups[group] !== false) ? ' open' : ''}`} />
                  <span className="badge-count">{list.length}</span>
                </span>
              </div>
              {tagOpenGroups[group] !== false && (
                <div className="chips" style={{ marginTop: 6 }}>
                  {list.map(t => (
                    <label key={t.id} className={`tag-chip ${selectedTags.includes(t.id) ? 'selected' : ''}`}>
                      <input type="checkbox" checked={selectedTags.includes(t.id)} onChange={() => onChange(selectedModels, toggle(selectedTags, t.id), strict)} />
                      <span>{t.name}</span>
                      {t.category_name && <span className="muted">（{t.category_name}）</span>}
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
