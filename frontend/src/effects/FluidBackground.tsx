import { useEffect, useRef } from 'react'

interface Blob {
  x: number
  y: number
  baseX: number
  baseY: number
  radius: number
  color: string
  phase: number
  speed: number
  amplitude: number
}

const BLOB_COLORS = [
  'rgba(139,92,246,0.18)',   // purple
  'rgba(59,130,246,0.16)',   // blue
  'rgba(6,182,212,0.14)',    // cyan
  'rgba(236,72,153,0.12)',   // pink
  'rgba(99,102,241,0.10)',   // indigo
]

export default function FluidBackground() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const blobsRef = useRef<Blob[]>([])
  const mouseRef = useRef({ x: -1000, y: -1000 })
  const rafRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const resize = () => {
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
    }
    resize()
    window.addEventListener('resize', resize)

    // Initialize blobs
    const initBlobs = () => {
      blobsRef.current = BLOB_COLORS.map((color, i) => {
        const angle = (i / BLOB_COLORS.length) * Math.PI * 2
        const cx = window.innerWidth * (0.3 + Math.cos(angle) * 0.25)
        const cy = window.innerHeight * (0.4 + Math.sin(angle) * 0.25)
        return {
          x: cx,
          y: cy,
          baseX: cx,
          baseY: cy,
          radius: Math.min(window.innerWidth, window.innerHeight) * (0.28 + i * 0.04),
          color,
          phase: i * 1.3,
          speed: 0.0003 + i * 0.00008,
          amplitude: 80 + i * 40,
        }
      })
    }
    initBlobs()

    const onMouse = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY }
    }
    window.addEventListener('mousemove', onMouse, { passive: true })

    let prevTime = 0
    const draw = (timestamp: number) => {
      if (!ctx || !canvas) return

      // Throttle to ~30fps for performance (skip if less than 32ms elapsed)
      if (timestamp - prevTime < 32) {
        rafRef.current = requestAnimationFrame(draw)
        return
      }
      prevTime = timestamp

      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const mx = mouseRef.current.x
      const my = mouseRef.current.y
      const t = timestamp * 0.001
      const blobs = blobsRef.current

      for (let i = 0; i < blobs.length; i++) {
        const b = blobs[i]

        // Sine wave motion
        const offsetX = Math.sin(t * b.speed * 0.7 + b.phase) * b.amplitude
        const offsetY = Math.cos(t * b.speed * 0.6 + b.phase + 1) * b.amplitude * 0.8

        // Gentle attraction toward mouse
        const dx = mx - b.baseX
        const dy = my - b.baseY
        const pullX = mx > 0 ? dx * 0.03 : 0
        const pullY = my > 0 ? dy * 0.03 : 0

        b.x = b.baseX + offsetX + pullX
        b.y = b.baseY + offsetY + pullY

        const alpha = 0.18 - i * 0.02

        // Outer glow (large, faint)
        ctx.fillStyle = b.color
        ctx.globalAlpha = alpha * 0.6
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2)
        ctx.fill()

        // Main blob
        ctx.fillStyle = b.color
        ctx.globalAlpha = alpha
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.radius * 0.7, 0, Math.PI * 2)
        ctx.fill()

        // Inner bright core
        ctx.globalAlpha = alpha * 1.5
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.radius * 0.35, 0, Math.PI * 2)
        ctx.fill()
      }

      ctx.globalAlpha = 1
      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(rafRef.current)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMouse)
    }
  }, [])

  // Re-init blob positions on window resize
  useEffect(() => {
    const onResize = () => {
      blobsRef.current.forEach((b, i) => {
        const angle = (i / blobsRef.current.length) * Math.PI * 2
        b.baseX = window.innerWidth * (0.3 + Math.cos(angle) * 0.25)
        b.baseY = window.innerHeight * (0.4 + Math.sin(angle) * 0.25)
        b.radius = Math.min(window.innerWidth, window.innerHeight) * (0.28 + i * 0.04)
      })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: -1,
        pointerEvents: 'none',
        opacity: 0.7,
      }}
      aria-hidden="true"
    />
  )
}
