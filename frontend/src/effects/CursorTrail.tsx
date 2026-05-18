import { useEffect, useRef } from 'react'

interface TrailPoint {
  x: number
  y: number
  age: number
}

const MAX_POINTS = 12
const MAX_AGE = 800 // ms

export default function CursorTrail() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const pointsRef = useRef<TrailPoint[]>([])
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

    const onMouse = (e: MouseEvent) => {
      pointsRef.current.push({ x: e.clientX, y: e.clientY, age: 0 })
      if (pointsRef.current.length > MAX_POINTS) {
        pointsRef.current.shift()
      }
    }
    window.addEventListener('mousemove', onMouse, { passive: true })

    let prevTime = 0
    const draw = (timestamp: number) => {
      if (!ctx || !canvas) return
      const delta = prevTime ? timestamp - prevTime : 16
      prevTime = timestamp

      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const points = pointsRef.current

      // Age all points
      for (let i = points.length - 1; i >= 0; i--) {
        points[i].age += delta
        if (points[i].age > MAX_AGE) {
          points.splice(i, 1)
        }
      }

      // Draw trail
      for (let i = 0; i < points.length; i++) {
        const p = points[i]
        const progress = p.age / MAX_AGE
        const alpha = 1 - progress
        const radius = 80 * (1 - progress * 0.85)

        const gradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius)
        gradient.addColorStop(0, `rgba(139,92,246,${alpha * 0.3})`)
        gradient.addColorStop(0.4, `rgba(59,130,246,${alpha * 0.15})`)
        gradient.addColorStop(1, 'rgba(6,182,212,0)')

        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2)
        ctx.fill()
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(rafRef.current)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMouse)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        pointerEvents: 'none',
      }}
      aria-hidden="true"
    />
  )
}
