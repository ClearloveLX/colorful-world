import { useEffect, useRef, useCallback } from 'react'

export function useAnimationFrame(callback: (deltaTime: number, elapsed: number) => void, active: boolean = true) {
  const rafRef = useRef<number | null>(null)
  const prevRef = useRef<number>(0)
  const startRef = useRef<number>(0)
  const cbRef = useRef(callback)
  cbRef.current = callback

  const loop = useCallback((timestamp: number) => {
    if (!startRef.current) startRef.current = timestamp
    const delta = timestamp - prevRef.current
    const elapsed = timestamp - startRef.current
    prevRef.current = timestamp
    cbRef.current(Math.min(delta, 100), elapsed)
    rafRef.current = requestAnimationFrame(loop)
  }, [])

  useEffect(() => {
    if (!active) return
    prevRef.current = performance.now()
    startRef.current = 0
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [active, loop])
}
