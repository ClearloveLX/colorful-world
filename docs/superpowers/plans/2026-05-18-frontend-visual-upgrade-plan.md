# 前端视觉升级实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标:** 将前端从 Apple Frosted Glass 风格升级为次世代玻璃 morphism + 极致动效 + 多色流体渐变

**架构:** Canvas 层负责背景流体渐变/粒子/光标轨迹 (z-index: -1)，CSS 层负责组件玻璃质感/动效/交互反馈，两者通过 React 生命周期解耦，不引入任何新 npm 依赖

**技术栈:** React 18 + TypeScript + CSS + Canvas 2D API

---

## 图示: 实现顺序

```
Task 1: useAnimationFrame hook            ──┐
Task 2: CSS Token 重构                     ──┤ 基础层 (无依赖，可并行)
Task 3: FluidBackground Canvas             ──┘
Task 4: ParticleField + CursorTrail        ── 依赖 Task 1
Task 5: 卡片 3D 视差 + 错峰入场            ── 依赖 Task 2
Task 6: Lightbox 升级                      ── 依赖 Task 2
Task 7: 微交互 + 全局细节                  ── 依赖 Task 2,5
Task 8: 兼容性与降级                       ── 依赖 Task 3,4,5
```

---

### Task 1: 创建 useAnimationFrame hook

**文件:**
- 创建: `frontend/src/hooks/useAnimationFrame.ts`

- [ ] **Step 1: 编写 useAnimationFrame hook**

```typescript
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
```

- [ ] **Step 2: 验证编译通过**

```bash
cd frontend && npx tsc --noEmit src/hooks/useAnimationFrame.ts
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/hooks/useAnimationFrame.ts
git commit -m "feat: 添加 useAnimationFrame rAF 管理 hook"
```

---

### Task 2: CSS Token 重构 + 全局变量

**文件:**
- 修改: `frontend/src/styles.css:1-63` (Design Tokens 区域)
- 修改: `frontend/src/styles.css:82-100` (背景 blob 替换)
- 修改: `frontend/src/styles.css:1639` 前插入新 keyframes

- [ ] **Step 1: 重构 :root 变量区块**

将现有 `:root` 中的 accent 相关变量替换为多色系，并新增渐变和光效变量。定位到 `frontend/src/styles.css` 第 26-33 行，将 accent 区块替换：

```css
  /* Accent — Multi-color Spectrum */
  --accent-purple: #8B5CF6;
  --accent-blue: #3B82F6;
  --accent-cyan: #06B6D4;
  --accent-pink: #EC4899;
  --accent: var(--accent-blue);
  --accent-hover: #0066d6;
  --accent-pressed: #0055b3;
  --accent-bg: rgba(59,130,246,0.08);
  --accent-bg-hover: rgba(59,130,246,0.14);
  --accent-border: rgba(59,130,246,0.25);

  /* Glass enhanced */
  --glass-stronger: rgba(255,255,255,0.88);
  --glass-blur-strong: saturate(200%) blur(24px) brightness(1.05);

  /* Neon Glow */
  --glow-purple: 0 0 20px rgba(139,92,246,0.3), 0 0 60px rgba(139,92,246,0.1);
  --glow-blue: 0 0 20px rgba(59,130,246,0.3), 0 0 60px rgba(59,130,246,0.1);
  --glow-cyan: 0 0 20px rgba(6,182,212,0.3), 0 0 60px rgba(6,182,212,0.1);
  --glow-pink: 0 0 20px rgba(236,72,153,0.3), 0 0 60px rgba(236,72,153,0.1);

  /* Card hover shadow (purple-tinted) */
  --shadow-card-hover: 0 8px 32px rgba(139,92,246,0.12), 0 2px 8px rgba(99,102,241,0.08), 0 0 0 1px rgba(139,92,246,0.08);

  /* Gradient accent for borders */
  --gradient-accent: linear-gradient(135deg, var(--accent-purple), var(--accent-blue), var(--accent-cyan), var(--accent-pink));
  --gradient-accent-h: linear-gradient(180deg, var(--accent-purple), var(--accent-blue), var(--accent-cyan));
```

- [ ] **Step 2: 替换背景 blob 动画为更丰富的多色版本**

将 `frontend/src/styles.css` 第 82-100 行替换：

```css
/* ── Animated Background Blobs (multi-color) ─── */
.bg-anim:before, .bg-anim:after, .bg-anim .bg-blob-3 {
  content: "";
  position: fixed;
  border-radius: 50%;
  pointer-events: none;
  z-index: -1;
}
.bg-anim:before {
  inset: -30vmax auto auto -20vmax;
  width: 70vmax;
  height: 70vmax;
  background: radial-gradient(closest-side, rgba(139,92,246,0.18), transparent 68%);
  filter: blur(60px);
  animation: blobA 18s ease-in-out infinite;
}
.bg-anim:after {
  inset: auto -25vmax -25vmax auto;
  width: 65vmax;
  height: 65vmax;
  background: radial-gradient(closest-side, rgba(6,182,212,0.15), transparent 68%);
  filter: blur(55px);
  animation: blobB 22s ease-in-out infinite;
}
.bg-anim .bg-blob-3 {
  inset: 40vh auto auto 40vw;
  width: 55vmax;
  height: 55vmax;
  background: radial-gradient(closest-side, rgba(236,72,153,0.12), transparent 68%);
  filter: blur(50px);
  animation: blobC 20s ease-in-out infinite;
}
.app-layout.bg-anim { position: relative; }
```

- [ ] **Step 3: 新增 keyframes**

在 `frontend/src/styles.css` 第 1578 行 `@keyframes blob` 处替换原有 blob keyframe 并新增两个变体：

```css
@keyframes blobA {
  0% { transform: translate(0,0) scale(1); }
  33% { transform: translate(12vmax,-6vmax) scale(1.15); }
  66% { transform: translate(-4vmax,8vmax) scale(0.92); }
  100% { transform: translate(0,0) scale(1); }
}
@keyframes blobB {
  0% { transform: translate(0,0) scale(1); }
  33% { transform: translate(-8vmax,-4vmax) scale(1.1); }
  66% { transform: translate(6vmax,8vmax) scale(0.95); }
  100% { transform: translate(0,0) scale(1); }
}
@keyframes blobC {
  0% { transform: translate(0,0) scale(1); }
  50% { transform: translate(-6vmax,10vmax) scale(1.08); }
  100% { transform: translate(0,0) scale(1); }
}
```

- [ ] **Step 4: 添加渐变色滚动条样式**

在 `frontend/src/styles.css` 的 Responsive section 之前 (@media 之前) 添加：

```css
/* ── Gradient Scrollbar ──────────────────────── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track {
  background: rgba(0,0,0,0.03);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, var(--accent-purple), var(--accent-blue), var(--accent-cyan));
  border-radius: 4px;
  border: 2px solid transparent;
  background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, var(--accent-blue), var(--accent-cyan), var(--accent-pink));
  background-clip: content-box;
}
```

- [ ] **Step 5: 验证编译**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles.css
git commit -m "feat: CSS Token 重构 — 多色系 accent、渐变滚动条、增强背景 blob"
```

---

### Task 3: FluidBackground Canvas 组件

**文件:**
- 创建: `frontend/src/effects/FluidBackground.tsx`
- 修改: `frontend/src/App.tsx:167-168` (挂载组件)
- 修改: `frontend/src/App.tsx:1` (添加 import)

- [ ] **Step 1: 编写 FluidBackground 组件**

创建 `frontend/src/effects/FluidBackground.tsx`：

```typescript
import { useEffect, useRef } from 'react'

interface Blob {
  x: number
  y: number
  radius: number
  color: string
  vx: number
  vy: number
  phase: number
  speed: number
  amplitude: number
  baseX: number
  baseY: number
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
    blobsRef.current = BLOB_COLORS.map((color, i) => {
      const angle = (i / BLOB_COLORS.length) * Math.PI * 2
      return {
        x: window.innerWidth * (0.3 + Math.cos(angle) * 0.3),
        y: window.innerHeight * (0.4 + Math.sin(angle) * 0.3),
        baseX: window.innerWidth * (0.3 + Math.cos(angle) * 0.3),
        baseY: window.innerHeight * (0.4 + Math.sin(angle) * 0.3),
        radius: Math.min(window.innerWidth, window.innerHeight) * (0.28 + i * 0.04),
        color,
        vx: 0,
        vy: 0,
        phase: i * 1.3,
        speed: 0.0003 + i * 0.00008,
        amplitude: 80 + i * 40,
      }
    })

    const onMouse = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY }
    }
    window.addEventListener('mousemove', onMouse, { passive: true })

    const draw = (timestamp: number) => {
      if (!ctx || !canvas) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const mx = mouseRef.current.x
      const my = mouseRef.current.y
      const blobs = blobsRef.current

      for (let i = 0; i < blobs.length; i++) {
        const b = blobs[i]
        const t = timestamp * 0.001 // seconds

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

        // Draw blob as radial gradient
        const gradient = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.radius)
        gradient.addColorStop(0, b.color)
        gradient.addColorStop(0.5, b.color.replace(/[\d.]+\)$/, `${parseFloat(b.color.match(/[\d.]+\)$/)![0]) * 0.6})`))
        gradient.addColorStop(1, 'transparent')

        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2)
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

  // Reattach resize handler when window resizes (update base positions)
  useEffect(() => {
    const onResize = () => {
      blobsRef.current.forEach((b, i) => {
        const angle = (i / blobsRef.current.length) * Math.PI * 2
        b.baseX = window.innerWidth * (0.3 + Math.cos(angle) * 0.3)
        b.baseY = window.innerHeight * (0.4 + Math.sin(angle) * 0.3)
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
```

> 注意：上述 gradient color stop 的 parseFloat 逻辑过于脆弱。下面 Step 1b 用更稳健的写法替换。

- [ ] **Step 1b: 用稳健版本替换**

上述 blob 绘制中的 `addColorStop(0.5, ...)` 写法有运行时解析问题。实际写入时使用以下绘制循环替换 Step 1 中的 `for (let i = 0; i < blobs.length; i++)` 循环体：

```typescript
      for (let i = 0; i < blobs.length; i++) {
        const b = blobs[i]
        const t = timestamp * 0.001

        const offsetX = Math.sin(t * b.speed * 0.7 + b.phase) * b.amplitude
        const offsetY = Math.cos(t * b.speed * 0.6 + b.phase + 1) * b.amplitude * 0.8

        const dx = mx - b.baseX
        const dy = my - b.baseY
        const pullX = mx > 0 ? dx * 0.03 : 0
        const pullY = my > 0 ? dy * 0.03 : 0

        b.x = b.baseX + offsetX + pullX
        b.y = b.baseY + offsetY + pullY

        // Solid color with varying opacity for blend
        const alpha = 0.18 - i * 0.02
        ctx.fillStyle = b.color
        ctx.globalAlpha = alpha
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2)
        ctx.fill()

        // Inner brighter core
        ctx.fillStyle = b.color
        ctx.globalAlpha = alpha * 1.4
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.radius * 0.55, 0, Math.PI * 2)
        ctx.fill()

        ctx.globalAlpha = 1
      }
```

> 实际实现时，Step 1 的完整文件应包含 Step 1b 的绘制循环，不含脆弱的正则解析。

- [ ] **Step 2: 在 App.tsx 中挂载 FluidBackground**

修改 `frontend/src/App.tsx` 第 1 行添加 import：

```typescript
import FluidBackground from './effects/FluidBackground'
```

修改 `frontend/src/App.tsx` 第 168 行，在 `<div className={`app-layout${locked ? ' bg-anim' : ''}`}>` 内顶部添加：

```tsx
    <div className={`app-layout${locked ? ' bg-anim' : ''}`}>
      <FluidBackground />
      {/* 其余内容不变 */}
```

具体修改：在第 168 行 `<div className={`app-layout...`}>` 和 第 169 行 `{locked && (` 之间插入 `<FluidBackground />`。

- [ ] **Step 3: 验证编译**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/effects/FluidBackground.tsx frontend/src/App.tsx
git commit -m "feat: FluidBackground Canvas 流体渐变背景组件"
```

---

### Task 4: ParticleField + CursorTrail

**文件:**
- 创建: `frontend/src/effects/ParticleField.tsx`
- 创建: `frontend/src/effects/CursorTrail.tsx`
- 修改: `frontend/src/App.tsx` (挂载两个组件)

- [ ] **Step 1: 编写 ParticleField 组件**

创建 `frontend/src/effects/ParticleField.tsx`：

```typescript
import { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  hue: number
  life: number
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
      // Respawn particles on resize
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
        life: Math.random(),
      }))
    }

    resize()
    window.addEventListener('resize', resize)

    const onMouse = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY }
    }
    window.addEventListener('mousemove', onMouse, { passive: true })

    const draw = () => {
      if (!ctx || !canvas) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const mx = mouseRef.current.x
      const my = mouseRef.current.y
      const particles = particlesRef.current

      // Update and draw particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]

        // Attract toward cursor
        const dx = mx - p.x
        const dy = my - p.y
        const distToCursor = Math.sqrt(dx * dx + dy * dy)
        if (distToCursor < CURSOR_RADIUS && distToCursor > 0) {
          const force = (1 - distToCursor / CURSOR_RADIUS) * 0.04
          p.vx += (dx / distToCursor) * force
          p.vy += (dy / distToCursor) * force
        }

        // Damping
        p.vx *= 0.998
        p.vy *= 0.998

        p.x += p.vx
        p.y += p.vy

        // Wrap around
        if (p.y < -20) { p.y = canvas.height + 20; p.x = Math.random() * canvas.width }
        if (p.y > canvas.height + 20) { p.y = -20; p.x = Math.random() * canvas.width }
        if (p.x < -20) p.x = canvas.width + 20
        if (p.x > canvas.width + 20) p.x = -20

        // Draw particle
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
        ctx.fillStyle = `hsla(${p.hue}, 70%, 65%, 0.5)`
        ctx.fill()

        // Connections
        for (let j = i + 1; j < particles.length; j++) {
          const q = particles[j]
          const cdx = p.x - q.x
          const cdy = p.y - q.y
          const cdist = Math.sqrt(cdx * cdx + cdy * cdy)
          if (cdist < CONNECT_DIST) {
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(q.x, q.y)
            ctx.strokeStyle = `hsla(${p.hue}, 60%, 70%, ${0.08 * (1 - cdist / CONNECT_DIST)})`
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
```

- [ ] **Step 2: 编写 CursorTrail 组件**

创建 `frontend/src/effects/CursorTrail.tsx`：

```typescript
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
  const prevRef = useRef<number>(0)

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

    const draw = (timestamp: number) => {
      if (!ctx || !canvas) return
      const delta = prevRef.current ? timestamp - prevRef.current : 16
      prevRef.current = timestamp

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
        gradient.addColorStop(1, `rgba(6,182,212,0)`)

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
```

- [ ] **Step 3: 在 App.tsx 中挂载**

修改 `frontend/src/App.tsx` 第 1 行，在现有 import 后添加：

```typescript
import ParticleField from './effects/ParticleField'
import CursorTrail from './effects/CursorTrail'
```

在 `<FluidBackground />` 之后添加：

```tsx
      <FluidBackground />
      <ParticleField />
      <CursorTrail />
```

- [ ] **Step 4: 验证编译**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/effects/ParticleField.tsx frontend/src/effects/CursorTrail.tsx frontend/src/App.tsx
git commit -m "feat: ParticleField 粒子场 + CursorTrail 光标轨迹组件"
```

---

### Task 5: 卡片 3D 视差 + 流光边框 + 错峰入场

**文件:**
- 修改: `frontend/src/styles.css:511-789` (Media Card 区块)
- 修改: `frontend/src/components/MediaCard.tsx:61-108` (tilt + hover 逻辑增强)
- 修改: `frontend/src/components/MediaCard.tsx:221-222` (DOM 结构微调)
- 修改: `frontend/src/components/MediaGrid.tsx:568-570` (列渲染加 style)

- [ ] **Step 1: 升级 CSS 卡片样式**

修改 `frontend/src/styles.css` 第 511-531 行 `.card` 基础样式：

```css
/* ── Media Card ──────────────────────────────── */
.card {
  break-inside: avoid;
  border-radius: var(--r-xl);
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--surface-solid);
  box-shadow: var(--shadow-card);
  transform: translateZ(0);
  animation: cardEnter 0.45s var(--ease-spring) both;
  transition: transform 0.35s var(--ease-spring), box-shadow 0.35s var(--ease), border-color 0.35s var(--ease);
  position: relative;
}
/* Gradient border via pseudo-element */
.card::before {
  content: "";
  position: absolute;
  inset: -1px;
  border-radius: var(--r-xl);
  padding: 1px;
  background: var(--gradient-accent);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.35s var(--ease);
  z-index: 10;
  pointer-events: none;
}
.card:hover::before {
  opacity: 0.65;
}
.masonry .card { width: 100%; margin-bottom: 0; }

.card:hover {
  transform: translateY(-6px);
  border-color: var(--accent-border);
  box-shadow: var(--shadow-card-hover);
}
.card.tilt { transition: transform 0.08s linear; }
.card.tilt:hover { transition: transform 0.08s linear; }
```

修改第 575-590 行 shine/beam 效果增强：

```css
/* Shine & gloss effects */
.shine {
  position: absolute;
  top: -30%;
  left: -60%;
  width: 60%;
  height: 160%;
  background: linear-gradient(105deg, transparent 20%, rgba(255,255,255,0.15) 40%, rgba(255,255,255,0.5) 50%, rgba(255,255,255,0.15) 60%, transparent 80%);
  transform: skewX(-15deg) rotate(5deg);
  opacity: 0;
  transition: transform 0.6s var(--ease-out), opacity 0.4s var(--ease-out);
  z-index: 2;
  pointer-events: none;
}
.card:hover .shine { opacity: 0.55; transform: translateX(220%) skewX(-15deg) rotate(5deg); }

.hover-beam {
  position: absolute;
  top: -10%;
  left: 0;
  width: 50%;
  height: 160%;
  background: linear-gradient(90deg, transparent, rgba(139,92,246,0.25), rgba(59,130,246,0.2), transparent);
  filter: blur(14px);
  opacity: 0;
  pointer-events: none;
  transform: translateX(-60%) rotate(-12deg);
  transition: opacity 0.2s var(--ease);
  z-index: 3;
}
.card:hover .hover-beam { opacity: 0.45; }
```

在 card-cover 区域内添加图片层独立视差样式（在 `.card-cover img` 后添加）：

```css
/* Image layer parallax — translate on hover */
.card-cover .img-parallax {
  transition: transform 0.15s ease-out;
}
```

- [ ] **Step 2: 增强 MediaCard tilt 逻辑**

修改 `frontend/src/components/MediaCard.tsx` 第 61-80 行 `onMove` 函数：

```typescript
  const onMove = (e: React.MouseEvent) => {
    if (dragging) return
    const el = cardRef.current
    if (!el) return
    if (tiltFrameRef.current) return
    tiltFrameRef.current = requestAnimationFrame(() => {
      tiltFrameRef.current = null
      const r = el.getBoundingClientRect()
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      const rx = ((y / r.height) - 0.5) * -10
      const ry = ((x / r.width) - 0.5) * 12
      el.style.transform = `perspective(700px) rotateX(${rx}deg) rotateY(${ry}deg) translateZ(4px)`
      // Image layer reverse parallax
      const img = el.querySelector('.img-parallax') as HTMLElement | null
      if (img) {
        const ix = ((x / r.width) - 0.5) * 8
        const iy = ((y / r.height) - 0.5) * 6
        img.style.transform = `translate(${ix}px, ${iy}px) scale(1.03)`
      }
      // Beam tracking
      const beam = beamRef.current
      if (beam) {
        const tx = Math.max(0, Math.min(r.width, x)) - r.width * 0.15
        beam.style.transform = `translate(${tx}px, -10%) rotate(-12deg)`
      }
    })
  }
```

修改第 81-88 行 `onLeave`：

```typescript
  const onLeave = () => {
    if (tiltFrameRef.current) {
      cancelAnimationFrame(tiltFrameRef.current)
      tiltFrameRef.current = null
    }
    if (cardRef.current) cardRef.current.style.transform = ''
    if (beamRef.current) beamRef.current.style.transform = ''
    const img = cardRef.current?.querySelector('.img-parallax') as HTMLElement | null
    if (img) img.style.transform = ''
  }
```

- [ ] **Step 3: 给 card-cover 内 img 添加 parallax class**

修改 `frontend/src/components/MediaCard.tsx` 第 231-247 行 `<img>` 标签，在 className 中添加 `img-parallax`：

```tsx
        <img
          src={imgSrc}
          alt={item.title}
          loading="lazy"
          decoding="async"
          className={`img-parallax${imgLoaded && inView ? ' img-loaded img-fade' : ' img-loading'}`}
          style={{ height: aspect ? '100%' as const : 'auto' }}
```

- [ ] **Step 4: 错峰入场动画**

修改 `frontend/src/components/MediaGrid.tsx` 第 568-570 行 `columns.map`，给每个 `.col` 和 card 添加 CSS 自定义属性传递列/行索引：

```tsx
        {items.length > 0 && columns.map((col, ci) => (
          <div className="col" key={`col-${ci}`} style={{ ['--col-index' as any]: ci }}>
            {col.map(({ item, idx }, ri) => (
              <MediaCard
                key={item.id}
                item={item}
                ...
              />
            ))}
```

注意：`MediaCard` 调用已有代码不变，仅在 `.col` 包装 div 上添加 `--col-index`。同时需要给 MediaCard 传递行索引用于错峰计算。更简单的方式：在 `.col` 的 CSS 中用 `--col-index` 计算每个子 card 的 animation-delay。

在 `frontend/src/styles.css` 的 `.card` 样式中动画部分增强，修改 `animation: cardEnter ...`：

```css
.card {
  /* ... 保持其他属性 ... */
  animation: cardEnter 0.5s var(--ease-spring) both;
  animation-delay: calc(var(--col-index, 0) * 60ms + var(--row-index, 0) * 40ms);
}
```

同时在 MediaGrid.tsx 的列渲染中给每行传递 `--row-index`：

```tsx
{col.map(({ item, idx }, ri) => (
  <div key={item.id} style={{ ['--row-index' as any]: ri }}>
    <MediaCard ... />
  </div>
))}
```

- [ ] **Step 5: 更新 cardEnter keyframe 添加水平位移**

修改 `frontend/src/styles.css` 第 1584-1587 行：

```css
@keyframes cardEnter {
  from { opacity: 0; transform: translateY(16px) translateX(-6px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) translateX(0) scale(1); }
}
```

- [ ] **Step 5b: 侧栏背景色滚动渐变**

在 `frontend/src/styles.css` 的 `.app-sidebar-shell` 样式后添加滚动驱动渐变：

```css
.app-sidebar-shell {
  /* ...保持已有属性... */
  transition: background 0.6s var(--ease-out);
}
```

在 `frontend/src/App.tsx` 中添加 scroll 监听，通过 CSS 自定义属性传递滚动进度给侧栏：

```typescript
// 在 App 组件内，现有 scroll 监听 useEffect 中扩展：
useEffect(() => {
  const onScroll = () => {
    setShowTop(window.scrollY > 600)
    // Sidebar color shift
    const sidebar = document.querySelector('.app-sidebar-shell') as HTMLElement | null
    if (sidebar) {
      const progress = Math.min(window.scrollY / 800, 1)
      const purple = Math.round(139 + (59 - 139) * progress)  // 139 → 59
      const green = Math.round(92 + (130 - 92) * progress)     // 92 → 130
      const blue = Math.round(246 + (246 - 246) * progress)    // 246 → 246
      sidebar.style.background = `rgba(255,255,255,${0.72 + progress * 0.12})`
      sidebar.style.borderRightColor = `rgba(${purple},${green},${blue},${0.06 + progress * 0.08})`
    }
  }
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
  return () => window.removeEventListener('scroll', onScroll)
}, [])
```

注意：这会与现有 App.tsx 中的 scroll 监听合并。实际实现时需将两个逻辑合并到同一个 useEffect。

- [ ] **Step 6: 验证编译**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 7: 提交**

```bash
git add frontend/src/styles.css frontend/src/components/MediaCard.tsx frontend/src/components/MediaGrid.tsx
git commit -m "feat: 卡片 3D 视差增强 + 渐变边框 + 错峰入场动画"
```

---

### Task 6: Lightbox 过渡升级

**文件:**
- 修改: `frontend/src/styles.css:820-939` (Lightbox 区块)
- 修改: `frontend/src/components/Lightbox.tsx` (动画状态管理)

- [ ] **Step 1: 升级 lightbox CSS 动画**

修改 `frontend/src/styles.css` 第 820-831 行 `.lightbox-backdrop`：

```css
/* ── Lightbox ────────────────────────────────── */
.lightbox-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  display: grid;
  place-items: center;
  z-index: 100;
  animation: lightboxReveal 0.4s var(--ease-spring);
}
.lightbox-backdrop.closing {
  animation: lightboxHide 0.3s var(--ease-in) forwards;
}
```

修改 `.lightbox-body.anim-in` 样式 (第 873 行)：

```css
.lightbox-body.anim-in { animation: lightboxEnter 0.4s var(--ease-spring); }
```

修改第 931-939 行导航按钮，给 prev/next 切换添加动画提示。在 `.lightbox-nav` 区块后添加图片切换翻转动画样式：

```css
.lightbox-media.flip-in {
  animation: flipEnter 0.35s var(--ease-spring);
}
.lightbox-media.flip-out {
  animation: flipExit 0.25s var(--ease-in);
}
```

- [ ] **Step 2: 新增 lightbox keyframes**

在 `frontend/src/styles.css` 的 keyframes 区域 (第 1604 行 `@keyframes lightboxEnter` 之后) 添加：

```css
@keyframes lightboxReveal {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes lightboxHide {
  from { opacity: 1; }
  to { opacity: 0; }
}
@keyframes flipEnter {
  from { opacity: 0; transform: perspective(800px) rotateY(12deg) scale(0.94); }
  to { opacity: 1; transform: perspective(800px) rotateY(0deg) scale(1); }
}
@keyframes flipExit {
  from { opacity: 1; transform: perspective(800px) rotateY(0deg) scale(1); }
  to { opacity: 0; transform: perspective(800px) rotateY(-10deg) scale(0.95); }
}
```

- [ ] **Step 3: Lightbox 组件添加翻转状态**

修改 `frontend/src/components/Lightbox.tsx`，添加切换动画状态管理。在 Props 中新增 `flipKey`:

```typescript
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
  flipKey?: string | number  // 新增：触发翻转动画的 key
}
```

在组件内添加状态：

```typescript
export default function Lightbox({ open, onClose, onPrev, onNext, canPrev = true, canNext = true, children, footer, leftAside, rightAside, flipKey }: Props) {
  const [closing, setClosing] = useState(false)
  const [flipDir, setFlipDir] = useState<'in' | 'out' | null>(null)
  const prevFlipKey = useRef(flipKey)

  useEffect(() => {
    if (flipKey !== undefined && prevFlipKey.current !== undefined && flipKey !== prevFlipKey.current) {
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
    }, 280)
  }, [onClose])
```

需要添加 useState, useEffect, useCallback, useRef 的 import。

将 backdrop 的 onClick 从 `onClose` 改为 `handleClose`，className 增加 closing 状态：

```tsx
    <div className={`lightbox-backdrop blur${closing ? ' closing' : ''}`} onClick={handleClose} ...>
```

将 lightbox-media 的 className 增加 flip 状态：

```tsx
        <div className={`lightbox-media${flipDir === 'in' ? ' flip-in' : ''}${flipDir === 'out' ? ' flip-out' : ''}`}>
```

- [ ] **Step 4: MediaGrid 传递 flipKey 给 Lightbox**

修改 `frontend/src/components/MediaGrid.tsx` 中 Lightbox 调用 (约第 653 行)，添加 `flipKey={selectedIndex}`:

```tsx
      <Lightbox
        open={selectedIndex !== null && items[selectedIndex] !== undefined}
        onClose={() => setSelectedIndex(null)}
        onPrev={...}
        onNext={...}
        canPrev={...}
        canNext={...}
        flipKey={selectedIndex}
        leftAside={...}
        rightAside={...}
      >
```

- [ ] **Step 5: 验证编译**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles.css frontend/src/components/Lightbox.tsx frontend/src/components/MediaGrid.tsx
git commit -m "feat: Lightbox 圆形展开/翻转切换过渡升级"
```

---

### Task 7: 微交互 + 全局细节

**文件:**
- 修改: `frontend/src/styles.css` (多处：chip ripple、呼吸光晕、进度条、回到顶部光环)
- 修改: `frontend/src/components/MediaCard.tsx` (点赞粒子爆散)
- 修改: `frontend/src/App.tsx` (页面加载进度条)

- [ ] **Step 1: 选中卡片呼吸光晕**

在 `frontend/src/styles.css` 第 532-535 行 `.card-selected` 替换：

```css
.card-selected {
  border-color: var(--accent-purple);
  box-shadow: 0 0 0 3px rgba(139,92,246,0.25), var(--shadow-md);
  animation: selectedBreathe 2s ease-in-out infinite;
}
```

在 keyframes 区域新增：

```css
@keyframes selectedBreathe {
  0%, 100% { box-shadow: 0 0 0 3px rgba(139,92,246,0.25), var(--shadow-md); }
  50% { box-shadow: 0 0 0 6px rgba(139,92,246,0.12), 0 0 24px rgba(139,92,246,0.15), var(--shadow-md); }
}
```

- [ ] **Step 2: Chip 水波点击效果**

在 `frontend/src/styles.css` 第 260-263 行 chip active 状态后新增 ripple 伪元素：

```css
.chip, .tag-chip {
  position: relative;
  overflow: hidden;
}
```

在 chip 区块末尾新增：

```css
.chip-ripple {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(circle, rgba(139,92,246,0.4) 0%, transparent 70%);
  transform: translate(-50%, -50%) scale(0);
  animation: chipRipple 0.7s var(--ease-out);
  z-index: 0;
}
@keyframes chipRipple {
  to { transform: translate(-50%, -50%) scale(4); opacity: 0; }
}
```

- [ ] **Step 3: 点赞粒子爆散**

修改 `frontend/src/components/MediaCard.tsx`，将点赞 `+1` 飞字替换为粒子爆散。在 like-fly 的 DOM 部分（第 308-309 行）：

```tsx
          {flyKey && (
            <>
              <span key={`f1-${flyKey}`} className="like-particle" style={{ '--angle': '0deg' } as React.CSSProperties} />
              <span key={`f2-${flyKey}`} className="like-particle" style={{ '--angle': '72deg' } as React.CSSProperties} />
              <span key={`f3-${flyKey}`} className="like-particle" style={{ '--angle': '144deg' } as React.CSSProperties} />
              <span key={`f4-${flyKey}`} className="like-particle" style={{ '--angle': '216deg' } as React.CSSProperties} />
              <span key={`f5-${flyKey}`} className="like-particle" style={{ '--angle': '288deg' } as React.CSSProperties} />
            </>
          )}
```

在 `frontend/src/styles.css` 中 `.like-fly` 之后添加：

```css
.like-particle {
  position: absolute;
  right: 18px;
  top: 6px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--danger);
  animation: particleBurst 550ms ease-out forwards;
  --angle: 0deg;
  animation-delay: calc(var(--angle, 0deg) * 0.002);
  pointer-events: none;
  z-index: 5;
}
@keyframes particleBurst {
  0% { opacity: 1; transform: translate(0, 0) scale(1); }
  100% { opacity: 0; transform: translate(calc(cos(var(--angle)) * 36px), calc(sin(var(--angle)) * 36px)) scale(0); }
}
```

注意：CSS `cos()`/`sin()` 在较新浏览器中支持。为兼容，使用预计算的 translate 值。改用多个具体 keyframe 或直接用不同 class：

```css
.like-particle.p0 { --tx: 0; --ty: -36px; }
.like-particle.p1 { --tx: 28px; --ty: -22px; }
.like-particle.p2 { --tx: 36px; --ty: 6px; }
.like-particle.p3 { --tx: 18px; --ty: 30px; }
.like-particle.p4 { --tx: -18px; --ty: 30px; }
.like-particle.p5 { --tx: -36px; --ty: 6px; }
.like-particle.p6 { --tx: -28px; --ty: -22px; }
@keyframes particleBurst {
  0% { opacity: 1; transform: translate(0, 0) scale(1); }
  100% { opacity: 0; transform: translate(var(--tx), var(--ty)) scale(0); }
}
```

- [ ] **Step 4: 回到顶部按钮光环**

修改 `frontend/src/styles.css` 第 1292-1320 行 `.back-to-top`：

```css
.back-to-top {
  /* 保持已有样式 */
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--glass-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  color: var(--text);
  box-shadow: var(--shadow-lg);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 18px;
  opacity: 0;
  transform: translateY(12px) scale(0.94);
  transition: opacity 0.3s var(--ease), transform 0.3s var(--ease-spring), box-shadow 0.3s var(--ease), color 0.3s var(--ease);
  z-index: 99;
  overflow: visible;
}
.back-to-top::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: var(--gradient-accent);
  opacity: 0;
  transition: opacity 0.3s var(--ease);
  animation: ringSpin 3s linear infinite;
  z-index: -1;
}
.back-to-top.show::after { opacity: 0.7; }
.back-to-top.show { opacity: 1; transform: translateY(0) scale(1); }
.back-to-top:hover {
  transform: translateY(-2px) scale(1.04);
  box-shadow: var(--shadow-xl);
  color: var(--accent);
}
.back-to-top:hover::after { opacity: 1; }
```

新增 keyframe：

```css
@keyframes ringSpin {
  to { transform: rotate(360deg); }
}
```

- [ ] **Step 5: 页面加载渐变色进度条**

在 `frontend/src/styles.css` 第 303 行 Main Content Shell 之前添加：

```css
/* ── Page Load Progress Bar ──────────────────── */
.page-progress {
  position: fixed;
  top: 0;
  left: 0;
  height: 3px;
  z-index: 9999;
  background: var(--gradient-accent);
  transition: width 0.3s var(--ease-out), opacity 0.4s var(--ease-out);
  border-radius: 0 2px 2px 0;
  box-shadow: 0 0 12px rgba(139,92,246,0.4);
}
.page-progress.done { opacity: 0; transition: opacity 0.6s var(--ease-out); }
```

在 `frontend/src/App.tsx` 中添加进度条状态和 UI：

```typescript
// 在 App 组件内添加
const [pageProgress, setPageProgress] = useState({ width: 0, done: false })

useEffect(() => {
  // 模拟加载进度
  let w = 0
  const timer = setInterval(() => {
    w += (100 - w) * 0.25
    if (w > 99) { w = 100; clearInterval(timer); setPageProgress({ width: 100, done: true }) }
    else setPageProgress({ width: w, done: false })
  }, 100)
  return () => clearInterval(timer)
}, [])
```

在 JSX 中添加（在 `<div className="app-layout...">` 内部顶部）：

```tsx
      <div className={`page-progress${pageProgress.done ? ' done' : ''}`} style={{ width: `${pageProgress.width}%` }} />
```

- [ ] **Step 5b: 侧栏背景色滚动渐变**

在 `frontend/src/styles.css` 的 `.app-sidebar-shell` 样式后添加滚动驱动渐变：

```css
.app-sidebar-shell {
  /* ...保持已有属性... */
  transition: background 0.6s var(--ease-out);
}
```

在 `frontend/src/App.tsx` 中添加 scroll 监听，通过 CSS 自定义属性传递滚动进度给侧栏：

```typescript
// 在 App 组件内，现有 scroll 监听 useEffect 中扩展：
useEffect(() => {
  const onScroll = () => {
    setShowTop(window.scrollY > 600)
    // Sidebar color shift
    const sidebar = document.querySelector('.app-sidebar-shell') as HTMLElement | null
    if (sidebar) {
      const progress = Math.min(window.scrollY / 800, 1)
      const purple = Math.round(139 + (59 - 139) * progress)  // 139 → 59
      const green = Math.round(92 + (130 - 92) * progress)     // 92 → 130
      const blue = Math.round(246 + (246 - 246) * progress)    // 246 → 246
      sidebar.style.background = `rgba(255,255,255,${0.72 + progress * 0.12})`
      sidebar.style.borderRightColor = `rgba(${purple},${green},${blue},${0.06 + progress * 0.08})`
    }
  }
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
  return () => window.removeEventListener('scroll', onScroll)
}, [])
```

注意：这会与现有 App.tsx 中的 scroll 监听合并。实际实现时需将两个逻辑合并到同一个 useEffect。

- [ ] **Step 6: 验证编译**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 7: 提交**

```bash
git add frontend/src/styles.css frontend/src/components/MediaCard.tsx frontend/src/App.tsx
git commit -m "feat: 微交互 — 呼吸光晕、chip水波、粒子爆散、旋转光环、渐变色进度条"
```

---

### Task 8: 兼容性与降级处理

**文件:**
- 修改: `frontend/src/App.tsx` (移动端检测、prefers-reduced-motion)
- 修改: `frontend/src/styles.css:1674` 后 (补全 reduced-motion)

- [ ] **Step 1: 移动端检测 hook + 条件渲染**

修改 `frontend/src/App.tsx`，添加移动端检测和 prefers-reduced-motion 检测，条件渲染 Canvas 组件：

```typescript
// 在 App 组件内添加
const [isMobile, setIsMobile] = useState(false)
const [reduceMotion, setReduceMotion] = useState(false)

useEffect(() => {
  const check = () => setIsMobile(window.innerWidth < 768)
  check()
  window.addEventListener('resize', check)
  return () => window.removeEventListener('resize', check)
}, [])

useEffect(() => {
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
  setReduceMotion(mq.matches)
  const onChange = (e: MediaQueryListEvent) => setReduceMotion(e.matches)
  mq.addEventListener('change', onChange)
  return () => mq.removeEventListener('change', onChange)
}, [])
```

将 FluidBackground、ParticleField、CursorTrail 加上条件：

```tsx
      {!isMobile && !reduceMotion && <FluidBackground />}
      {!isMobile && !reduceMotion && <ParticleField />}
      {!isMobile && !reduceMotion && <CursorTrail />}
```

- [ ] **Step 2: 补全 prefers-reduced-motion 样式**

修改 `frontend/src/styles.css` 第 1674 行 `@media (prefers-reduced-motion: reduce) {` 区块，补全内容：

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .bg-anim:before, .bg-anim:after, .bg-anim .bg-blob-3 { animation: none !important; }
  .card.tilt { transition: none !important; }
}
```

- [ ] **Step 3: Canvas 初始化失败静默降级**

在 `FluidBackground.tsx`、`ParticleField.tsx`、`CursorTrail.tsx` 中，canvas 的 `getContext('2d')` 返回 null 时已有提前 return，无需额外处理。组件本身渲染空 canvas（aria-hidden），不影响页面。

- [ ] **Step 4: 验证编译并运行**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: 兼容性降级 — 移动端跳过Canvas、prefers-reduced-motion 支持"
```

---

### Task 9: 最终验证

**文件:**
- 无新文件

- [ ] **Step 1: 完整构建验证**

```bash
cd frontend && npm run build
```
预期: 构建成功，无 TS 错误，无 CSS 警告。

- [ ] **Step 2: 检查 bundle 大小**

```bash
ls -lh frontend/dist/assets/*.js
```
预期: 无大幅增长（未引入新依赖，仅新增 ~500 行 TS + ~200 行 CSS）。

- [ ] **Step 3: 启动开发服务器预览**

```bash
cd frontend && npm run dev
```

在浏览器中验证:
- 背景有流体渐变色块缓慢运动
- 粒子在屏幕中漂浮，靠近光标时被吸引
- 光标移动时有渐变色光晕轨迹
- 卡片 hover 时有 3D 倾斜 + 渐变边框 + 光效扫描线
- 卡片入场有波浪式错峰动画
- 选中卡片有呼吸光晕
- 点赞按钮点击有粒子爆散
- Lightbox 打开/关闭有过渡动画
- 回到顶部按钮有旋转光环
- 缩小浏览器宽度到 768px 以下，Canvas 效果消失

- [ ] **Step 4: 提交验证结果**

```bash
git add -A && git diff --cached --stat
git commit -m "chore: 最终验证 — 构建通过，功能正常"
```
