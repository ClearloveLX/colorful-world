import { useCallback, useEffect, useRef, useState } from 'react'
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
  flipKey?: string | number | null
}

export default function Lightbox({ open, onClose, onPrev, onNext, canPrev = true, canNext = true, children, footer, leftAside, rightAside, flipKey }: Props) {
  const [closing, setClosing] = useState(false)
  const [flipDir, setFlipDir] = useState<'in' | 'out' | null>(null)
  const prevFlipKey = useRef(flipKey)

  useEffect(() => {
    if (flipKey !== undefined && flipKey !== null && prevFlipKey.current !== undefined && prevFlipKey.current !== null && flipKey !== prevFlipKey.current) {
      setFlipDir('out')
      const timer = setTimeout(() => setFlipDir('in'), 250)
      return () => clearTimeout(timer)
    }
    prevFlipKey.current = flipKey
  }, [flipKey])

  const handleClose = useCallback(() => {
    setClosing(true)
    setTimeout(() => {
      setClosing(false)
      onClose()
    }, 310)
  }, [onClose])

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
      if (e.key === 'Escape') handleClose()
      else if (e.key === 'ArrowLeft' && onPrev) onPrev()
      else if (e.key === 'ArrowRight' && onNext) onNext()
    }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose, onPrev, onNext])

  if (!open) return null
  return createPortal(
    <div className={`lightbox-backdrop${closing ? ' closing' : ''}`} onClick={handleClose} role="dialog" aria-modal="true" aria-label="媒体预览">
      <button
        className={`lightbox-close`}
        onClick={e => { e.stopPropagation(); handleClose() }}
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
      <div className="lightbox-body anim-in" onClick={e => { if (e.target === e.currentTarget) handleClose(); e.stopPropagation() }}>
        {leftAside}
        <div className={`lightbox-media${flipDir === 'in' ? ' flip-in' : ''}${flipDir === 'out' ? ' flip-out' : ''}`}>{children}</div>
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
