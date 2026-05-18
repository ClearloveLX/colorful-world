import { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  hue: number
}

const PARTICLE_COUNT = 100
const CONNECT_DIST = 150
const CURSOR_RADIUS = 120
const HUE_POOL = [271, 217, 192, 330, 243] // purple, blue, cyan, pink, indigo

export default function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const particlesRef = useRef<Particle[]>([])
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
      initParticles()
    }

    const initParticles = () => {
      particlesRef.current = Array.from({ length: PARTICLE_COUNT }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: -(Math.random() * 0.15 + 0.03),
        radius: Math.random() * 2 + 1,
        hue: HUE_POOL[Math.floor(Math.random() * HUE_POOL.length)],
      }))
    }

    resize()
    window.addEventListener('resize', resize)

    const onMouse = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY }
    }
    window.addEventListener('mousemove', onMouse, { passive: true })

    let prevTime = 0
    const draw = (timestamp: number) => {
      if (!ctx || !canvas) return
      if (timestamp - prevTime < 32) {
        rafRef.current = requestAnimationFrame(draw)
        return
      }
      prevTime = timestamp

      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const mx = mouseRef.current.x
      const my = mouseRef.current.y
      const particles = particlesRef.current

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]

        // Attract toward cursor
        const dx = mx - p.x
        const dy = my - p.y
        const distToCursor = Math.sqrt(dx * dx + dy * dy)
        if (mx >= 0 && distToCursor < CURSOR_RADIUS && distToCursor > 0) {
          const force = (1 - distToCursor / CURSOR_RADIUS) * 0.04
          p.vx += (dx / distToCursor) * force
          p.vy += (dy / distToCursor) * force
        }

        // Damping
        p.vx *= 0.998
        p.vy *= 0.998

        p.x += p.vx
        p.y += p.vy

        // Wrap around edges
        if (p.y < -20) { p.y = canvas.height + 20; p.x = Math.random() * canvas.width }
        if (p.y > canvas.height + 20) { p.y = -20; p.x = Math.random() * canvas.width }
        if (p.x < -20) p.x = canvas.width + 20
        if (p.x > canvas.width + 20) p.x = -20

        // Draw particle
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
        ctx.fillStyle = `hsla(${p.hue}, 70%, 65%, 0.5)`
        ctx.fill()

        // Draw connections to other particles
        for (let j = i + 1; j < particles.length; j++) {
          const q = particles[j]
          const cdx = p.x - q.x
          const cdy = p.y - q.y
          const cdist = Math.sqrt(cdx * cdx + cdy * cdy)
          if (cdist < CONNECT_DIST) {
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(q.x, q.y)
            const alpha = 0.08 * (1 - cdist / CONNECT_DIST)
            ctx.strokeStyle = `hsla(${p.hue}, 60%, 70%, ${alpha})`
            ctx.lineWidth = 0.5
            ctx.stroke()
          }
        }
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
        zIndex: -1,
        pointerEvents: 'none',
      }}
      aria-hidden="true"
    />
  )
}
