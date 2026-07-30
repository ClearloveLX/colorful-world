import { useEffect, useMemo, useState } from 'react'
import { fetchModels, fetchTags } from '../api'
import type { Model, Tag } from '../types'
import { toggleGroupOpen } from '../utils/toggleGroupOpen'

type Props = {
  selectedModels: string[]
  selectedTags: string[]
  excludedTags: string[]
  strict: boolean
  minHeat?: number
  maxHeat?: number
  order: 'random' | 'duration' | 'duration_asc' | 'recent' | 'recent_asc' | 'heat' | 'heat_asc'
  editMode: boolean
  randomMode: 'random' | 'true_random'
  onChange: (models: string[], tags: string[], excludedTags: string[], strict: boolean) => void
  onHeatChange?: (min?: number, max?: number) => void
  onOrderChange: (order: 'random' | 'duration' | 'duration_asc' | 'recent' | 'recent_asc' | 'heat' | 'heat_asc') => void
  nameSearch: string
  onNameSearchChange: (q: string) => void
  onRandomizeSeed?: () => void
  onRandomModeChange: (mode: 'random' | 'true_random') => void
  trueRandomCacheEnabled: boolean
  trueRandomCacheCount: number
  settingsBusy: boolean
  settingsHint: string
  onToggleTrueRandomCache: (enabled: boolean) => void
  onClearTrueRandomCache: () => void
}

export default function Filters({
  selectedModels,
  selectedTags,
  excludedTags,
  strict,
  minHeat,
  maxHeat,
  order,
  editMode,
  randomMode,
  onChange,
  onHeatChange,
  onOrderChange,
  nameSearch,
  onNameSearchChange,
  onRandomizeSeed,
  onRandomModeChange,
  trueRandomCacheEnabled,
  trueRandomCacheCount,
  settingsBusy,
  settingsHint,
  onToggleTrueRandomCache,
  onClearTrueRandomCache,
}: Props) {
  const [models, setModels] = useState<Model[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [modelSearch, setModelSearch] = useState('')
  const [tagSearch, setTagSearch] = useState('')

  const [modelOpenGroups, setModelOpenGroups] = useState<Record<string, boolean>>({})
  const [tagOpenGroups, setTagOpenGroups] = useState<Record<string, boolean>>({})
  const [sectionOpen, setSectionOpen] = useState<{ filter: boolean; order: boolean; system: boolean; selected: boolean; models: boolean; tags: boolean }>({ filter: true, order: true, system: false, selected: true, models: true, tags: true })

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
  const [btnBurst, setBtnBurst] = useState<{ id: string; type: 'in' | 'ex'; key: number } | null>(null)
  const fireBurst = (id: string, type: 'in' | 'ex') => {
    setBtnBurst({ id, type, key: Date.now() })
    window.setTimeout(() => {
      setBtnBurst(cur => (cur && cur.id === id && cur.type === type ? null : cur))
    }, 460)
  }
  const applyInclude = (id: string) => {
    const nextInclude = toggle(selectedTags, id)
    const nextExclude = excludedTags.filter(t => t !== id)
    fireBurst(id, 'in')
    onChange(selectedModels, nextInclude, nextExclude, strict)
  }
  const applyExclude = (id: string) => {
    const nextExclude = toggle(excludedTags, id)
    const nextInclude = selectedTags.filter(t => t !== id)
    fireBurst(id, 'ex')
    onChange(selectedModels, nextInclude, nextExclude, strict)
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
  const onToggleKey = (e: React.KeyboardEvent, fn: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      fn()
    }
  }
  return (
    <div className="sidebar">
      <div className="sidebar-curation-head">
        <div className="sidebar-title">筛选</div>
      </div>
      {(() => {
        const modelMeta = new Map(models.map(m => [m.id, m]))
        const tagMeta = new Map(tags.map(t => [t.id, t]))
        const total = selectedModels.length + selectedTags.length + excludedTags.length
        if (total === 0) return null
        return (
          <section className="filter-section-card filter-section-card-emphasis" style={{ marginBottom: 12 }}>
            <div
              className="section-header"
              role="button"
              tabIndex={0}
              aria-expanded={sectionOpen.selected}
              onClick={() => setSectionOpen(s => ({ ...s, selected: !s.selected }))}
              onKeyDown={(e) => onToggleKey(e, () => setSectionOpen(s => ({ ...s, selected: !s.selected })))}
            >
              <span className="section-name">已选</span>
              <span style={{ display:'flex', alignItems:'center', gap:8 }}>
                <span className={`caret${sectionOpen.selected ? ' open' : ''}`} />
                <span className="badge-count">{total}</span>
              </span>
            </div>
            {sectionOpen.selected && (
              <div style={{ display:'grid', gap:8, marginTop:8 }}>
                {selectedModels.length > 0 && (
                  <div>
                    <div className="section-title" style={{ margin: '0 0 6px' }}>模特</div>
                    <div className="chips">
                      {selectedModels.map(id => {
                        const m = modelMeta.get(id)
                        return (
                          <button
                            key={`sel-m-${id}`}
                            className="chip selected"
                            onClick={() => onChange(selectedModels.filter(x => x !== id), selectedTags, excludedTags, strict)}
                            title="移除该模特"
                          >
                            {m?.preview_image_path ? (
                              <img src={m.preview_image_path} alt={m?.name || id} width={20} height={20} style={{ borderRadius: '50%', objectFit: 'cover' }} />
                            ) : (
                              <div style={{ width: 20, height: 20, borderRadius: '50%', background: '#161617', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 12 }}>{(m?.name || id)[0]}</div>
                            )}
                            <span>{m?.name || id}</span>
                            <span aria-hidden="true">×</span>
                          </button>
                        )
                      })}
                      <button className="tool-btn" onClick={() => onChange([], selectedTags, excludedTags, strict)}>清空模特</button>
                    </div>
                  </div>
                )}
                {selectedTags.length > 0 && (
                  <div>
                    <div className="section-title" style={{ margin: '0 0 6px' }}>包含标签</div>
                    <div className="chips">
                      {selectedTags.map(id => {
                        const t = tagMeta.get(id)
                        return (
                          <button
                            key={`sel-t-${id}`}
                            className="tag-chip selected"
                            onClick={() => onChange(selectedModels, selectedTags.filter(x => x !== id), excludedTags, strict)}
                            title="移除该标签"
                          >
                            <span>{t?.name || id}</span>
                            <span aria-hidden="true">×</span>
                          </button>
                        )
                      })}
                      <button className="tool-btn" onClick={() => onChange(selectedModels, [], excludedTags, strict)}>清空包含</button>
                    </div>
                  </div>
                )}
                {excludedTags.length > 0 && (
                  <div>
                    <div className="section-title" style={{ margin: '0 0 6px' }}>排除标签</div>
                    <div className="chips">
                      {excludedTags.map(id => {
                        const t = tagMeta.get(id)
                        return (
                          <button
                            key={`sel-et-${id}`}
                            className="tag-chip exclude"
                            onClick={() => onChange(selectedModels, selectedTags, excludedTags.filter(x => x !== id), strict)}
                            title="移除该排除"
                          >
                            <span>{t?.name || id}</span>
                            <span aria-hidden="true">×</span>
                          </button>
                        )
                      })}
                      <button className="tool-btn" onClick={() => onChange(selectedModels, selectedTags, [], strict)}>清空排除</button>
                    </div>
                  </div>
                )}
                <div>
                  <button className="tool-btn" onClick={() => onChange([], [], [], strict)}>清空全部</button>
                </div>
              </div>
            )}
          </section>
        )
      })()}
      <section className="filter-section-card filter-section-card-emphasis" style={{ marginBottom: 12 }}>
        <div
          className="section-header"
          role="button"
          tabIndex={0}
          aria-expanded={sectionOpen.filter}
          onClick={() => setSectionOpen(s => ({ ...s, filter: !s.filter }))}
          onKeyDown={(e) => onToggleKey(e, () => setSectionOpen(s => ({ ...s, filter: !s.filter })))}
        >
          <span className="section-name">筛选</span>
          <span className={`caret${sectionOpen.filter ? ' open' : ''}`} />
        </div>
        {sectionOpen.filter && (
          <div className="filter-section-body" style={{ margin: '12px 0' }}>
            <label className="chip" style={{ display: 'inline-flex', marginBottom: 8 }}>
              <input type="checkbox" checked={strict} onChange={e => onChange(selectedModels, selectedTags, excludedTags, e.target.checked)} />
              <span>强关联</span>
            </label>
            <div className="filter-heat-stack">
              <div className="filter-heat-label">热度</div>
              <div className="filter-heat-row">
                <input
                  type="number"
                  inputMode="numeric"
                  className="search-input filter-heat-input"
                  placeholder="最小"
                  value={minHeat ?? ''}
                  onChange={e => {
                    const val = e.target.value ? parseInt(e.target.value, 10) : undefined
                    onHeatChange && onHeatChange(val, maxHeat)
                  }}
                />
                <span className="filter-heat-separator" aria-hidden="true">-</span>
                <input
                  type="number"
                  inputMode="numeric"
                  className="search-input filter-heat-input"
                  placeholder="最大"
                  value={maxHeat ?? ''}
                  onChange={e => {
                    const val = e.target.value ? parseInt(e.target.value, 10) : undefined
                    onHeatChange && onHeatChange(minHeat, val)
                  }}
                />
              </div>
            </div>
            <input
              className="search-input"
              style={{ marginTop: 10 }}
              value={nameSearch}
              onChange={e => onNameSearchChange(e.target.value)}
              placeholder="按名称模糊搜索"
            />
          </div>
        )}
      </section>
      <section className="filter-section-card filter-section-card-emphasis" style={{ marginBottom: 12 }}>
        <div
          className="section-header"
          role="button"
          tabIndex={0}
          aria-expanded={sectionOpen.order}
          onClick={() => setSectionOpen(s => ({ ...s, order: !s.order }))}
          onKeyDown={(e) => onToggleKey(e, () => setSectionOpen(s => ({ ...s, order: !s.order })))}
        >
          <span className="section-name">排序</span>
          <span className={`caret${sectionOpen.order ? ' open' : ''}`} />
        </div>
        {sectionOpen.order && (
          <div className="sort-segmented" style={{ marginTop: 8 }}>
            <button
              className={`sort-seg${order==='random' && randomMode==='random' ? ' active' : ''}`}
              onClick={() => { onRandomModeChange('random'); onOrderChange('random') }}
              title="随机排序"
            >
              随机
            </button>
            <button
              className={`sort-seg${order==='random' && randomMode==='true_random' ? ' active' : ''}`}
              onClick={() => { onRandomModeChange('true_random'); onOrderChange('random'); onRandomizeSeed && onRandomizeSeed() }}
              title="真随机，每次不同"
            >
              真随机
            </button>
            <button
              className={`sort-seg${order.startsWith('duration') ? ' active' : ''}`}
              onClick={() => onOrderChange(order === 'duration' ? 'duration_asc' : 'duration')}
              title={order === 'duration_asc' ? "按时长升序，点击切换降序" : "按时长降序，点击切换升序"}
            >
              时长<span className="sort-arrow">{order === 'duration_asc' ? '↑' : '↓'}</span>
            </button>
            <button
              className={`sort-seg${order.startsWith('recent') ? ' active' : ''}`}
              onClick={() => onOrderChange(order === 'recent' ? 'recent_asc' : 'recent')}
              title={order === 'recent_asc' ? "按时间升序(旧->新)，点击切换降序" : "按时间降序(新->旧)，点击切换升序"}
            >
              最新<span className="sort-arrow">{order === 'recent_asc' ? '↑' : '↓'}</span>
            </button>
            <button
              className={`sort-seg${order.startsWith('heat') ? ' active' : ''}`}
              onClick={() => onOrderChange(order === 'heat' ? 'heat_asc' : 'heat')}
              title={order === 'heat_asc' ? "按热度升序(冷->热)，点击切换降序" : "按热度降序(热->冷)，点击切换升序"}
            >
              热度<span className="sort-arrow">{order === 'heat_asc' ? '↑' : '↓'}</span>
            </button>
          </div>
        )}
      </section>
      <section className="filter-section-card" style={{ marginBottom: 12 }}>
        <div
          className="section-header"
          role="button"
          tabIndex={0}
          aria-expanded={sectionOpen.models}
          onClick={() => setSectionOpen(s => ({ ...s, models: !s.models }))}
          onKeyDown={(e) => onToggleKey(e, () => setSectionOpen(s => ({ ...s, models: !s.models })))}
        >
          <span className="section-name">模特</span>
          <span style={{ display:'flex', alignItems:'center', gap:8 }}>
            <span className={`caret${sectionOpen.models ? ' open' : ''}`} />
            <span className="badge-count">{models.length}</span>
          </span>
        </div>
        {sectionOpen.models && (
          <>
            <input className="search-input" value={modelSearch} onChange={e => setModelSearch(e.target.value)} placeholder="搜索模特或类型" />
            <div style={{ display: 'grid', gap: 8 }}>
              {filteredModelsByGroup.map(([group, list]) => (
                <div key={`model-group-${group}`}>
                  <div
                    className="group-header"
                    role="button"
                    tabIndex={0}
                    onClick={() => setModelOpenGroups(s => ({ ...s, [group]: toggleGroupOpen(s[group]) }))}
                    onKeyDown={(e) => onToggleKey(e, () => setModelOpenGroups(s => ({ ...s, [group]: toggleGroupOpen(s[group]) })))}
                  >
                    <span className="group-name">{group}</span>
                    <span style={{ display:'flex', alignItems:'center', gap:8 }}>
                      <span className={`caret${(modelOpenGroups[group] !== false) ? ' open' : ''}`} />
                      <span className="badge-count">{list.length}</span>
                    </span>
                  </div>
                  {modelOpenGroups[group] !== false && (
                    <div className="chips" style={{ marginTop: 6 }}>
                      {list.map(m => (
                        <button
                          key={m.id}
                          className={`chip${selectedModels.includes(m.id) ? ' selected' : ''}`}
                          onClick={() => onChange(toggle(selectedModels, m.id), selectedTags, excludedTags, strict)}
                          title={`按模特筛选：${m.name}`}
                        >
                          {m.preview_image_path ? (
                            <img src={m.preview_image_path} alt={m.name} width={20} height={20} style={{ borderRadius: '50%', objectFit: 'cover' }} />
                          ) : (
                            <div style={{ width: 20, height: 20, borderRadius: '50%', background: '#161617', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 12 }}>{m.name[0]}</div>
                          )}
                          <span>{m.name} <span className="file-count">({m.file_count ?? 0})</span></span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </section>
      <section className="filter-section-card" style={{ marginBottom: 12 }}>
        <div
          className="section-header"
          role="button"
          tabIndex={0}
          aria-expanded={sectionOpen.tags}
          onClick={() => setSectionOpen(s => ({ ...s, tags: !s.tags }))}
          onKeyDown={(e) => onToggleKey(e, () => setSectionOpen(s => ({ ...s, tags: !s.tags })))}
        >
          <span className="section-name">标签</span>
          <span style={{ display:'flex', alignItems:'center', gap:8 }}>
            <span className={`caret${sectionOpen.tags ? ' open' : ''}`} />
            <span className="badge-count">{tags.length}</span>
          </span>
        </div>
        {sectionOpen.tags && (
          <>
            <input className="search-input" value={tagSearch} onChange={e => setTagSearch(e.target.value)} placeholder="搜索标签" />
            <div style={{ display:'flex', gap:8, flexWrap:'wrap', margin: '8px 0 4px' }}>
              <span className="muted">包含 {selectedTags.length} · 排除 {excludedTags.length}</span>
            </div>
            <div style={{ display: 'grid', gap: 8 }}>
              {filteredTagsByGroup.map(([group, list]) => (
                <div key={group}>
                  <div
                    className="group-header"
                    role="button"
                    tabIndex={0}
                    onClick={() => setTagOpenGroups(s => ({ ...s, [group]: toggleGroupOpen(s[group]) }))}
                    onKeyDown={(e) => onToggleKey(e, () => setTagOpenGroups(s => ({ ...s, [group]: toggleGroupOpen(s[group]) })))}
                  >
                    <span className="group-name">{group}</span>
                    <span style={{ display:'flex', alignItems:'center', gap:8 }}>
                      <span className={`caret${(tagOpenGroups[group] !== false) ? ' open' : ''}`} />
                      <span className="badge-count">{list.length}</span>
                    </span>
                  </div>
                  {tagOpenGroups[group] !== false && (
                    <div className="chips" style={{ marginTop: 6 }}>
                      {list.map(t => (
                        <span key={t.id} className={`tag-chip${selectedTags.includes(t.id) ? ' selected' : ''}${excludedTags.includes(t.id) ? ' exclude' : ''}`}>
                          <button
                            className={`tag-action-btn include-btn${selectedTags.includes(t.id) ? ' active' : ''}${btnBurst?.id === t.id && btnBurst.type === 'in' ? ' burst' : ''}`}
                            onClick={(e) => { e.stopPropagation(); e.currentTarget.blur(); applyInclude(t.id); }}
                            title="包含"
                          ><span className="tag-action-glyph">+</span></button>
                          <span>{t.name} <span className="file-count">({t.file_count ?? 0})</span></span>
                          <button
                            className={`tag-action-btn exclude-btn${excludedTags.includes(t.id) ? ' active' : ''}${btnBurst?.id === t.id && btnBurst.type === 'ex' ? ' burst' : ''}`}
                            onClick={(e) => { e.stopPropagation(); e.currentTarget.blur(); applyExclude(t.id); }}
                            title="排除"
                          ><span className="tag-action-glyph">−</span></button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      {editMode && (
        <section className="filter-section-card" style={{ marginBottom: 12 }}>
          <div
            className="section-header"
            role="button"
            tabIndex={0}
            aria-expanded={sectionOpen.system}
            onClick={() => setSectionOpen(s => ({ ...s, system: !s.system }))}
            onKeyDown={(e) => onToggleKey(e, () => setSectionOpen(s => ({ ...s, system: !s.system })))}
          >
            <span className="section-name">系统设置</span>
            <span style={{ display:'flex', alignItems:'center', gap:8 }}>
              <span className={`caret${sectionOpen.system ? ' open' : ''}`} />
              <span className="badge-count">{trueRandomCacheCount}</span>
            </span>
          </div>
          {sectionOpen.system && (
            <div className="system-settings-panel">
              <div className="system-setting-row">
                <div>
                  <div className="system-setting-title">真随机缓存</div>
                  <div className="muted">仅编辑模式下的真随机会自动排除历史缓存数据</div>
                </div>
                <label className={`switch${trueRandomCacheEnabled ? ' on' : ''}${settingsBusy ? ' disabled' : ''}`}>
                  <input
                    type="checkbox"
                    checked={trueRandomCacheEnabled}
                    disabled={settingsBusy}
                    onChange={e => onToggleTrueRandomCache(e.target.checked)}
                  />
                  <span className="switch-track"><span className="switch-thumb" /></span>
                </label>
              </div>
              <div className="system-setting-meta">
                <span className={`cache-state-pill${trueRandomCacheEnabled ? ' active' : ''}`}>
                  {trueRandomCacheEnabled ? '缓存过滤已启用' : '缓存过滤已停用'}
                </span>
                <span className="cache-state-pill">已缓存 {trueRandomCacheCount} 条</span>
              </div>
              <div className="system-setting-actions">
                <button className="tool-btn" disabled={settingsBusy} onClick={onClearTrueRandomCache}>清理全部缓存</button>
                {settingsHint && <span className="system-setting-hint">{settingsHint}</span>}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
