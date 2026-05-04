import { useEffect } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  open: boolean
  onClose: () => void
  onPrev?: () => void
  onNext?: () => void
  canPrev?: boolean
  canNext?: boolean
  children: React.ReactNode
  footer?: React.ReactNode
  leftAside?: React.ReactNode
  rightAside?: React.ReactNode
}

export default function Lightbox({ open, onClose, onPrev, onNext, canPrev = true, canNext = true, children, footer, leftAside, rightAside }: Props) {
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft' && onPrev) onPrev()
      else if (e.key === 'ArrowRight' && onNext) onNext()
    }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return createPortal(
    <div className="lightbox-backdrop blur" onClick={onClose} role="dialog" aria-modal="true" aria-label="媒体预览">
      <button
        className="lightbox-close"
        onClick={e => { e.stopPropagation(); onClose() }}
        aria-label="关闭预览"
        title="关闭"
      >
        ×
      </button>
      <button
        className={`lightbox-nav prev${canPrev ? '' : ' disabled'}`}
        onClick={e => { e.stopPropagation(); if (canPrev && onPrev) onPrev() }}
        aria-label="上一项"
      >◀</button>
      <div className="lightbox-body anim-in" onClick={e => { if (e.target === e.currentTarget) onClose(); e.stopPropagation() }}>
        {leftAside}
        <div className="lightbox-media">{children}</div>
        {rightAside}
        {footer}
      </div>
      <button
        className={`lightbox-nav next${canNext ? '' : ' disabled'}`}
        onClick={e => { e.stopPropagation(); if (canNext && onNext) onNext() }}
        aria-label="下一项"
      >▶</button>
    </div>,
    document.body
  )
}
