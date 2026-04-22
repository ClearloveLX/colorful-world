type Props = {
  selectedCount: number
  onAddTags: () => void
  onRemoveTags: () => void
  onIncreaseHeat: () => void
  onDecreaseHeat: () => void
  onRefresh: () => void
  onClear: () => void
  onExit: () => void
  onSelectAll: () => void
  heatBusy?: boolean
}

export default function BulkBar({ selectedCount, onAddTags, onRemoveTags, onIncreaseHeat, onDecreaseHeat, onRefresh, onClear, onExit, onSelectAll, heatBusy = false }: Props) {
  const noSelection = selectedCount <= 0
  return (
    <div className="bulk-bar" role="region" aria-label="批量操作栏">
      <span className="muted" aria-live="polite">已选：{selectedCount}</span>
      <button className="tool-btn primary" onClick={onAddTags} disabled={noSelection}>添加标签</button>
      <button className="tool-btn primary" onClick={onRemoveTags} disabled={noSelection}>移除标签</button>
      <div className={`heat-group${heatBusy ? ' disabled' : ''}`} aria-label="批量好感度操作">
        <span className="heat-group-label">好感度</span>
        <button
          className="heat-chip heat-up"
          onClick={onIncreaseHeat}
          disabled={heatBusy || noSelection}
          title="批量提高好感度"
          aria-label="批量提高好感度"
        >
          <span className="heat-icon-shell" aria-hidden="true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 21s-6.716-4.09-9.192-6.566C1.332 13.956 1 12.872 1 11.727 1 9.1 3.1 7 5.727 7c1.516 0 2.897.643 3.846 1.669L12 11.136l2.427-2.467C15.376 7.643 16.757 7 18.273 7 20.9 7 23 9.1 23 11.727c0 1.145-.332 2.229-1.808 2.707C18.716 16.91 12 21 12 21z" fill="currentColor"/>
              <path d="M12 8.2v5.6M9.2 11h5.6" stroke="#fff" strokeWidth="1.8" strokeLinecap="round"/>
            </svg>
          </span>
          <span className="heat-chip-text">提升</span>
        </button>
        <button
          className="heat-chip heat-down"
          onClick={onDecreaseHeat}
          disabled={heatBusy || noSelection}
          title="批量减少好感度"
          aria-label="批量减少好感度"
        >
          <span className="heat-icon-shell" aria-hidden="true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 21s-6.716-4.09-9.192-6.566C1.332 13.956 1 12.872 1 11.727 1 9.1 3.1 7 5.727 7c1.516 0 2.897.643 3.846 1.669L12 11.136l2.427-2.467C15.376 7.643 16.757 7 18.273 7 20.9 7 23 9.1 23 11.727c0 1.145-.332 2.229-1.808 2.707C18.716 16.91 12 21 12 21z" fill="currentColor"/>
              <path d="M9.2 11h5.6" stroke="#fff" strokeWidth="1.8" strokeLinecap="round"/>
            </svg>
          </span>
          <span className="heat-chip-text">降低</span>
        </button>
      </div>
      <button className="tool-btn" onClick={onRefresh}>刷新数据</button>
      <button className="tool-btn" onClick={onSelectAll}>全选已加载</button>
      <button className="tool-btn" onClick={onClear} disabled={noSelection}>清空选择</button>
      <div style={{ flex:1 }} />
      <button className="tool-btn" onClick={onExit}>退出选择模式</button>
    </div>
  )
}
