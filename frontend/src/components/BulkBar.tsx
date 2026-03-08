type Props = {
  selectedCount: number
  onAddTags: () => void
  onRemoveTags: () => void
  onClear: () => void
  onExit: () => void
  onSelectAll: () => void
}

export default function BulkBar({ selectedCount, onAddTags, onRemoveTags, onClear, onExit, onSelectAll }: Props) {
  return (
    <div className="bulk-bar">
      <span className="muted">已选：{selectedCount}</span>
      <button className="tool-btn primary" onClick={onAddTags}>添加标签</button>
      <button className="tool-btn primary" onClick={onRemoveTags}>移除标签</button>
      <button className="tool-btn" onClick={onSelectAll}>全选已加载</button>
      <button className="tool-btn" onClick={onClear}>清空选择</button>
      <div style={{ flex:1 }} />
      <button className="tool-btn" onClick={onExit}>退出选择模式</button>
    </div>
  )
}
