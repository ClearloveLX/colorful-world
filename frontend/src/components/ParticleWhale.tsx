import { useEffect, useRef } from 'react'

/**
 * 交互式粒子鲸鱼（复刻 deepseek.com/harness 的交互质感）
 * 两层效果：
 *  1. 全屏点阵网格（参考页面 h() 组件）：90px 网格、弹簧物理、鼠标推挤、
 *     相邻点连线 + 方块点，颜色 rgba(60,100,160,…)
 *  2. 粒子鲸鱼：把官方 hero-whale.svg 采样为粒子目标点，白色/品牌蓝粒子
 *     汇聚成鲸鱼剪影，随鼠标推挤、呼吸浮动、点击爆散
 * prefers-reduced-motion 下降级为静态绘制
 */

type MeshPoint = {
  restX: number
  restY: number
  x: number
  y: number
  vx: number
  vy: number
}

type WhaleParticle = {
  x: number
  y: number
  vx: number
  vy: number
  tx: number
  ty: number
  phase: number
  size: number
  blue: boolean
}

type Props = {
  className?: string
  /** 鲸鱼粒子数量 */
  density?: number
  /** 画布整体不透明度 */
  opacity?: number
  /** 是否响应鼠标（推挤 + 连线 + 点击爆散） */
  interactive?: boolean
  /** 鲸鱼宽度占视口宽度的比例（0-1） */
  size?: number
  /** 鲸鱼垂直位置：0=顶部，0.5=居中，1=底部 */
  offsetY?: number
  /** 是否绘制全屏点阵网格背景 */
  showMesh?: boolean
  /** 是否绘制粒子鲸鱼（false 时仅保留点阵网格，适合内容页氛围） */
  showWhale?: boolean
}

const MESH_GAP = 90
const MOUSE_R = 140
const WHALE_SRC = '/whale.svg'

export default function ParticleWhale({ className, density = 1600, opacity = 1, interactive = true, size = 0.62, offsetY = 0.5, showMesh = true, showWhale = true }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const interactiveRef = useRef(interactive)
  interactiveRef.current = interactive

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const coarsePointer = window.matchMedia('(hover: none), (pointer: coarse)').matches

    let raf = 0
    let width = 0
    let height = 0
    let mesh: MeshPoint[] = []
    let meshCols = 0
    let meshRows = 0
    let whale: WhaleParticle[] = []
    const mouse = { x: NaN, y: NaN }

    const buildMesh = () => {
      meshCols = Math.ceil(width / MESH_GAP) + 1
      meshRows = Math.ceil(height / MESH_GAP) + 1
      const ox = (width - (meshCols - 1) * MESH_GAP) / 2
      const oy = (height - (meshRows - 1) * MESH_GAP) / 2
      mesh = []
      for (let r = 0; r < meshRows; r++) {
        for (let c = 0; c < meshCols; c++) {
          mesh.push({ restX: ox + c * MESH_GAP, restY: oy + r * MESH_GAP, x: ox + c * MESH_GAP, y: oy + r * MESH_GAP, vx: 0, vy: 0 })
        }
      }
    }

    const whaleGeom = () => {
      // 同时受宽度与高度约束，保证整只鲸鱼落在视口内（宽 4:3）
      const w = Math.min(width * size, 1280, height * 1.15)
      const h = w * 18 / 24
      return { w, h, x: (width - w) / 2, y: (height - h) * offsetY }
    }

    const sampleWhale = (): Array<{ x: number; y: number }> => {
      const img = new Image()
      let points: Array<{ x: number; y: number }> = []
      img.onload = () => {
        const S = 960
        const SH = Math.round(S * 18 / 24)
        const off = document.createElement('canvas')
        off.width = S
        off.height = SH
        const og = off.getContext('2d')
        if (!og) return
        og.drawImage(img, 0, 0, S, SH)
        const data = og.getImageData(0, 0, S, SH).data
        const cand: Array<{ x: number; y: number }> = []
        for (let y = 0; y < SH; y++) {
          for (let x = 0; x < S; x++) {
            if (data[(y * S + x) * 4 + 3] > 100) cand.push({ x, y })
          }
        }
        const { w: whaleW, x: ox, y: oy } = whaleGeom()
        const scale = whaleW / S
        const used = new Set<number>()
        points = []
        for (let i = 0; i < cand.length; i++) {
          let idx: number
          if (used.size < cand.length) {
            do { idx = Math.floor(Math.random() * cand.length) } while (used.has(idx))
            used.add(idx)
          } else {
            idx = Math.floor(Math.random() * cand.length)
          }
          const p = cand[idx]
          points.push({ x: ox + p.x * scale, y: oy + p.y * scale })
        }
        seedWhale(points)
      }
      img.src = WHALE_SRC
      return points
    }

    const seedWhale = (targets: Array<{ x: number; y: number }>) => {
      const n = density
      whale = []
      for (let i = 0; i < n; i++) {
        const t = targets.length > 0 ? targets[i % targets.length] : { x: width / 2, y: height * offsetY }
        whale.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: 0,
          vy: 0,
          tx: t.x,
          ty: t.y,
          phase: (i % 997) / 997 * Math.PI * 2,
          size: 1.4 + Math.random() * 1.7,
          blue: Math.random() < 0.22,
        })
      }
    }

    const resize = () => {
      width = window.innerWidth
      height = window.innerHeight
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      if (!coarsePointer && showMesh) buildMesh()
      if (showWhale) sampleWhale()
    }

    const drawDots = () => {
      const now = performance.now() / 1000
      // 鲸鱼背后的柔光衬托轮廓
      if (whale.length > 0) {
        const g = whaleGeom()
        const cx = g.x + g.w / 2
        const cy = g.y + g.h / 2
        const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, g.w * 0.55)
        glow.addColorStop(0, 'rgba(103,153,254,0.12)')
        glow.addColorStop(1, 'rgba(103,153,254,0)')
        ctx.fillStyle = glow
        ctx.fillRect(0, 0, width, height)
      }
      const white: WhaleParticle[] = []
      const blue: WhaleParticle[] = []
      let maxSpeed = 0
      for (const p of whale) {
        const bobX = Math.sin(now * 0.5 + p.phase) * 1.6
        const bobY = Math.cos(now * 0.42 + p.phase) * 2
        let fx = p.tx + bobX - p.x
        let fy = p.ty + bobY - p.y
        if (interactiveRef.current && !Number.isNaN(mouse.x)) {
          const dx = p.x - mouse.x
          const dy = p.y - mouse.y
          const d2 = dx * dx + dy * dy
          if (d2 < MOUSE_R * MOUSE_R) {
            const d = Math.sqrt(d2) || 1
            const f = (1 - d / MOUSE_R) * 10
            fx += (dx / d) * f
            fy += (dy / d) * f
          }
        }
        p.vx += fx * 0.032
        p.vy += fy * 0.032
        p.vx *= 0.85
        p.vy *= 0.85
        p.x += p.vx
        p.y += p.vy
        maxSpeed = Math.max(maxSpeed, Math.abs(p.vx) + Math.abs(p.vy))
        ;(p.blue ? blue : white).push(p)
      }
      const drawBatch = (list: WhaleParticle[], color: string, alpha: number) => {
        ctx.globalAlpha = alpha
        ctx.fillStyle = color
        for (const p of list) {
          const s = p.size * 2
          ctx.fillRect(p.x - p.size, p.y - p.size, s, s)
        }
        ctx.globalAlpha = 1
      }
      drawBatch(white, 'rgba(255,255,255,0.92)', 0.85)
      drawBatch(blue, 'rgba(103,153,254,0.95)', 0.8)
      return maxSpeed
    }

    const drawMesh = () => {
      for (const p of mesh) {
        if (interactiveRef.current && !Number.isNaN(mouse.x)) {
          const dx = p.x - mouse.x
          const dy = p.y - mouse.y
          const d = Math.sqrt(dx * dx + dy * dy)
          if (d < MOUSE_R && d > 0.1) {
            const f = (1 - d / MOUSE_R) * 3
            p.vx += (dx / d) * f
            p.vy += (dy / d) * f
          }
        }
        const sx = p.restX - p.x
        const sy = p.restY - p.y
        p.vx += sx * 0.05
        p.vy += sy * 0.05
        p.vx *= 0.85
        p.vy *= 0.85
        p.x += p.vx
        p.y += p.vy
      }
      // 相邻点连线（参考实现：两端各留 10px 间隙）
      ctx.strokeStyle = 'rgba(60, 100, 160, 0.1)'
      ctx.lineWidth = 0.5
      for (let r = 0; r < meshRows; r++) {
        for (let c = 0; c < meshCols - 1; c++) {
          const a = mesh[r * meshCols + c]
          const b = mesh[r * meshCols + c + 1]
          const dx = b.x - a.x
          const dy = b.y - a.y
          const d = Math.sqrt(dx * dx + dy * dy)
          if (d < 20) continue
          const ux = dx / d
          const uy = dy / d
          ctx.beginPath()
          ctx.moveTo(a.x + 10 * ux, a.y + 10 * uy)
          ctx.lineTo(b.x - 10 * ux, b.y - 10 * uy)
          ctx.stroke()
        }
      }
      for (let c = 0; c < meshCols; c++) {
        for (let r = 0; r < meshRows - 1; r++) {
          const a = mesh[r * meshCols + c]
          const b = mesh[(r + 1) * meshCols + c]
          const dx = b.x - a.x
          const dy = b.y - a.y
          const d = Math.sqrt(dx * dx + dy * dy)
          if (d < 20) continue
          const ux = dx / d
          const uy = dy / d
          ctx.beginPath()
          ctx.moveTo(a.x + 10 * ux, a.y + 10 * uy)
          ctx.lineTo(b.x - 10 * ux, b.y - 10 * uy)
          ctx.stroke()
        }
      }
      // 方块点（参考实现：1.8px 基准，靠近鼠标变大变亮）
      ctx.fillStyle = 'rgba(60, 100, 160, 0.2)'
      for (const p of mesh) {
        let s = 1.8
        let alpha = 0.2
        if (!Number.isNaN(mouse.x) && !Number.isNaN(mouse.y)) {
          const dx = p.x - mouse.x
          const dy = p.y - mouse.y
          const d = Math.sqrt(dx * dx + dy * dy)
          const k = Math.max(0, 1 - d / MOUSE_R)
          s = 1.8 + 2 * k
          alpha = 0.2 + 0.4 * k
        }
        ctx.globalAlpha = alpha
        ctx.fillRect(p.x - s, p.y - s, s * 2, s * 2)
      }
      ctx.globalAlpha = 1
    }

    const drawMouse = () => {
      if (!interactiveRef.current || Number.isNaN(mouse.x)) return
      ctx.strokeStyle = 'rgba(103,153,254,0.12)'
      ctx.lineWidth = 1
      ctx.beginPath()
      const join = (p: { x: number; y: number }) => {
        if (p.x < 0 || p.y < 0) return
        const dx = p.x - mouse.x
        const dy = p.y - mouse.y
        if (dx * dx + dy * dy < MOUSE_R * MOUSE_R) {
          ctx.moveTo(p.x, p.y)
          ctx.lineTo(mouse.x, mouse.y)
        }
      }
      whale.forEach(join)
      mesh.forEach(join)
      ctx.stroke()
      const glow = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, 80)
      glow.addColorStop(0, 'rgba(103,153,254,0.12)')
      glow.addColorStop(1, 'rgba(103,153,254,0)')
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(mouse.x, mouse.y, 80, 0, Math.PI * 2)
      ctx.fill()
    }

    const frame = () => {
      ctx.clearRect(0, 0, width, height)
      if (!coarsePointer && showMesh) drawMesh()
      drawDots()
      drawMouse()
      raf = requestAnimationFrame(frame)
    }

    const onPointerMove = (e: PointerEvent) => {
      mouse.x = e.clientX
      mouse.y = e.clientY
    }
    const onPointerLeave = () => {
      mouse.x = NaN
      mouse.y = NaN
    }
    const onPointerDown = (e: PointerEvent) => {
      const burst = (p: { x: number; y: number; vx: number; vy: number }) => {
        const dx = p.x - e.clientX
        const dy = p.y - e.clientY
        const d2 = dx * dx + dy * dy
        const R = 220
        if (d2 < R * R) {
          const d = Math.sqrt(d2) || 1
          const f = (1 - d / R) * 14
          p.vx += (dx / d) * f
          p.vy += (dy / d) * f
        }
      }
      whale.forEach(burst)
      mesh.forEach(burst)
    }

    resize()
    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    window.addEventListener('pointerleave', onPointerLeave)
    if (interactive) window.addEventListener('pointerdown', onPointerDown)

    if (reduceMotion) {
      ctx.clearRect(0, 0, width, height)
      if (!coarsePointer && showMesh) drawMesh()
      drawDots()
    } else {
      raf = requestAnimationFrame(frame)
    }

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerleave', onPointerLeave)
      window.removeEventListener('pointerdown', onPointerDown)
    }
  }, [density, size, offsetY, showMesh, showWhale])

  return <canvas ref={canvasRef} className={className} style={{ opacity }} aria-hidden="true" />
}
