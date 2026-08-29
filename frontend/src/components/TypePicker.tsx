import { useEffect } from 'react'
import type { MediaKind } from '../types'
import { MEDIA_KIND_LABELS } from '../utils/format'

type Props = {
  open: boolean
  onClose: () => void
  onApply: (kind: MediaKind) => void
}

const KINDS: MediaKind[] = ['image', 'video', 'audio', 'unknown']

export default function TypePicker({ open, onClose, onApply }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="lightbox-backdrop" onClick={onClose}>
      <div
        className="lightbox-body anim-in dialog-panel type-picker-panel"
        role="dialog"
        aria-modal="true"
        aria-label="手动设置类型"
        onClick={e => e.stopPropagation()}
      >
        <div className="dialog-header tag-picker-header">
          <div className="dialog-title">设置媒体类型</div>
          <div className="dialog-actions">
            <button className="tool-btn" onClick={onClose}>关闭</button>
          </div>
        </div>
        <div className="type-picker-grid">
          {KINDS.map(kind => (
            <button
              key={kind}
              type="button"
              className={`type-picker-btn${kind === 'unknown' ? ' other' : ''}`}
              onClick={() => onApply(kind)}
            >
              <span className={`media-kind-badge kind-${kind}`}>{MEDIA_KIND_LABELS[kind]}</span>
              <span>{kind === 'unknown' ? '标记为其他/未识别' : `标记为${MEDIA_KIND_LABELS[kind]}`}</span>
            </button>
          ))}
        </div>
        <p className="muted" style={{ margin: '8px 4px 0' }}>将批量应用到当前选中的文件。</p>
      </div>
    </div>
  )
}
