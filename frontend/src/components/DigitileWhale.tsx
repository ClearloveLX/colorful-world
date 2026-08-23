import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/**
 * 数字瓦片鲸鱼 —— 逐字移植 deepseek.com/harness 的 HeroDigitileR3F
 * （deepseek-harness 官网 "fish" 主视觉：Three.js InstancedMesh + 自定义着色器）
 * 原实现：官方 hero-whale.svg → 边缘像素采样 → 小方块瓦片实例；
 * 着色器含装配动画、尾部摆动、鼠标散开、世界灯光明暗，AdditiveBlending 发光。
 * 这里去掉 React Three Fiber，改用原生 Three.js，逻辑/参数与原版一致。
 */

const LIGHT = { x: 4.5, y: 5.5, z: 3, range: 14, shadeMin: 0.2, shadeMax: 0.4 * 2.79, followX: 1.05 }
const MOUSE = { radius: 4.9, strength: 0.8, decay: 0.2, distort: 5 }

const VERT = `
  attribute float aOpacity;
  attribute float aIndex;
  attribute float aEdge;
  attribute vec3 aScattered;

  uniform float uTime;
  uniform float uWaveSpeed;
  uniform float uWaveAmount;
  uniform vec2 uMouse;
  uniform float uMouseRadius;
  uniform float uMouseStrength;
  uniform float uMouseDistort;
  uniform float uAssembly;
  uniform float uLoose;
  uniform float uScatter;
  uniform vec3 uLightPos;
  uniform float uLightRange;
  uniform float uShadeMin;
  uniform float uShadeMax;

  varying float vOpacity;
  varying vec3 vWorldPos;
  varying float vAssembly;
  varying float vLight;

  void main() {
    vOpacity = aOpacity;
    vAssembly = uAssembly;

    vec3 targetCenter = (instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
    vec3 localOffset = (instanceMatrix * vec4(position, 1.0)).xyz - targetCenter;

    vec3 scatteredCenter = aScattered;

    float assembly = smoothstep(0.0, 1.0, uAssembly);

    vec3 center = mix(scatteredCenter, targetCenter, assembly);
    vec3 pos = center + localOffset;
    vWorldPos = center;

    float loose = uLoose * mix(0.25, 1.0, aEdge) * assembly;
    if (loose > 0.001) {
      vec3 jitter = vec3(
        fract(sin(aIndex * 12.9898) * 43758.5453) - 0.5,
        fract(sin(aIndex * 78.2330) * 12543.1230) - 0.5,
        fract(sin(aIndex * 39.4250) * 26711.7700) - 0.5
      );
      pos += jitter * 0.05 * loose;
      pos.x += sin(uTime * 0.50 + aIndex * 0.53) * 0.06 * loose;
      pos.y += cos(uTime * 0.42 + aIndex * 0.71) * 0.06 * loose;
      pos.z += sin(uTime * 0.36 + aIndex * 0.91) * 0.08 * loose;

      float tail = smoothstep(0.5, 4.5, targetCenter.x) * uLoose * assembly;
      pos.y += sin(uTime * 1.1 - targetCenter.x * 0.7) * 0.1 * tail;
      pos.z += cos(uTime * 0.9 - targetCenter.x * 0.55) * 0.06 * tail;
    }

    if (uScatter > 0.001) {
      float disperse = uScatter * mix(0.5, 1.0, aEdge);
      pos += (scatteredCenter - center) * disperse;
      pos.z += sin(uTime * 0.6 + aIndex * 0.3) * disperse * 0.6;
    }

    if (assembly > 0.95) {
      float effectStrength = (assembly - 0.95) * 20.0;
      float dist = length(center.xy);
      float waveFade = smoothstep(0.0, 3.0, dist);
      float wave = sin(dist * 3.0 - uTime * uWaveSpeed) * uWaveAmount * effectStrength * waveFade;
      pos.z += wave;
    }

    if (assembly > 0.8) {
      float mouseEffect = (assembly - 0.8) * 5.0;
      vec2 toMouse = center.xy - uMouse;
      float mouseDist = length(toMouse);

      if (mouseDist < uMouseRadius && mouseDist > 0.001) {
        float t = 1.0 - mouseDist / uMouseRadius;
        float force = t * t * t * mouseEffect * uMouseStrength;

        vec2 radialDir = toMouse / mouseDist;
        float noiseAngle = sin(aIndex * 0.37 + uTime * 0.5) * uMouseDistort;
        float ca = cos(noiseAngle);
        float sa = sin(noiseAngle);
        vec2 pushDir = vec2(radialDir.x * ca - radialDir.y * sa, radialDir.x * sa + radialDir.y * ca);

        pos.xy += pushDir * force * 2.0;
        pos.z += sin(aIndex * 1.7 + uTime) * force * 0.8;
      }
    }

    if (assembly < 0.9) {
      float scatter = smoothstep(0.9, 0.0, assembly);
      pos.x += sin(uTime * 0.5 + aIndex * 0.1) * 0.2 * scatter;
      pos.y += cos(uTime * 0.4 + aIndex * 0.07) * 0.2 * scatter;
      pos.z += sin(uTime * 0.3 + aIndex * 0.13) * 0.15 * scatter;
    }

    vec4 worldPos = modelMatrix * vec4(pos, 1.0);
    float lightDist = distance(worldPos.xyz, uLightPos);
    float lit = clamp(1.0 - lightDist / uLightRange, 0.0, 1.0);
    vLight = mix(uShadeMin, uShadeMax, lit * lit);

    vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mvPosition;
  }
`

const FRAG = `
  varying float vOpacity;
  varying vec3 vWorldPos;
  varying float vAssembly;
  varying float vLight;

  uniform float uTime;
  uniform vec3 uColor;

  void main() {
    float dist = length(vWorldPos.xy);
    float glow = smoothstep(8.0, 0.0, dist) * 0.3 * vAssembly;

    float baseAlpha = mix(0.45, 0.75, vAssembly);
    float alpha = vOpacity * (baseAlpha + glow);
    float shimmer = sin(uTime * 1.5 + vWorldPos.x * 5.0 + vWorldPos.y * 3.0) * 0.1 + 0.9;
    alpha *= shimmer * min(vLight, 1.0);

    vec3 color = (uColor + glow * vec3(0.2, 0.3, 0.5)) * vLight;
    color = mix(color, color * vec3(1.07, 1.02, 0.94), clamp(vLight - 1.0, 0.0, 1.0));
    gl_FragColor = vec4(color, alpha);
  }
`

type PixelData = {
  positions: Float32Array
  scatteredPositions: Float32Array
  opacities: Float32Array
  edges: Float32Array
  count: number
}

function extractPixels(img: HTMLImageElement, size = 60): PixelData {
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const c = canvas.getContext('2d')!
  c.fillStyle = '#000'
  c.fillRect(0, 0, size, size)
  const r = Math.min(size / img.width, size / img.height)
  const w = img.width * r
  const h = img.height * r
  c.drawImage(img, (size - w) / 2, (size - h) / 2, w, h)
  const data = c.getImageData(0, 0, size, size).data
  const gray = new Float32Array(size * size)
  for (let i = 0; i < size * size; i++) {
    const p = 4 * i
    gray[i] = (0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2]) / 255
  }
  const isEdge = (x: number, y: number) => {
    for (let a = -2; a <= 2; a++) {
      for (let b = -2; b <= 2; b++) {
        if (a === 0 && b === 0) continue
        const nx = x + a
        const ny = y + b
        if (nx < 0 || ny < 0 || nx >= size || ny >= size || gray[ny * size + nx] <= 0.2) return true
      }
    }
    return false
  }
  const pos: number[] = []
  const scat: number[] = []
  const op: number[] = []
  const ed: number[] = []
  const d = size / 2
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const v = gray[y * size + x]
      if (v <= 0.2 || !isEdge(x, y)) continue
      pos.push((x - d) * 0.18, (d - y) * 0.18, 0)
      op.push(v)
      let e = 0
      for (let a = -1; a <= 1; a++) {
        for (let b = -1; b <= 1; b++) {
          if (a === 0 && b === 0) continue
          const nx = x + a
          const ny = y + b
          if (nx < 0 || ny < 0 || nx >= size || ny >= size || gray[ny * size + nx] <= 0.2) e++
        }
      }
      ed.push(e / 8)
      const th = Math.random() * Math.PI * 2
      const ph = Math.acos(2 * Math.random() - 1)
      const rr = 3 * (0.4 + 0.6 * Math.random())
      scat.push(Math.sin(ph) * Math.cos(th) * rr, Math.sin(ph) * Math.sin(th) * rr, Math.cos(ph) * rr * 0.5)
    }
  }
  return {
    positions: new Float32Array(pos),
    scatteredPositions: new Float32Array(scat),
    opacities: new Float32Array(op),
    edges: new Float32Array(ed),
    count: pos.length / 3,
  }
}

export default function DigitileWhale({ className, spin = false, loose = 1 }: { className?: string; spin?: boolean; loose?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true })
    renderer.setClearColor(0x000000, 0)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100)
    camera.position.set(0, 0, 18)
    const scene = new THREE.Scene()
    const group = new THREE.Group()
    scene.add(group)

    let disposed = false
    let raf = 0
    let mesh: THREE.InstancedMesh | null = null
    let geometry: THREE.BoxGeometry | null = null
    let material: THREE.ShaderMaterial | null = null
    let uniforms: Record<string, THREE.IUniform> | null = null
    let visible = true
    let last = performance.now()
    let lastFrame = 0
    let elapsed = 0
    let acc = 0
    let mouseActive = false
    let mouseHasMoved = false
    const mouse = { nx: 0, ny: 0 }
    const worldMouse = new THREE.Vector2(0, 0)
    const inv = new THREE.Matrix4()
    const tmp = new THREE.Vector3()

    const resize = () => {
      const w = canvas.clientWidth || window.innerWidth
      const h = canvas.clientHeight || window.innerHeight
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }

    const loadWhale = () => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        if (disposed) return
        const pd = extractPixels(img, 60)
        geometry = new THREE.BoxGeometry(0.06, 0.06, 0.018)
        geometry.setAttribute('aOpacity', new THREE.InstancedBufferAttribute(pd.opacities, 1))
        geometry.setAttribute('aIndex', new THREE.InstancedBufferAttribute(Float32Array.from({ length: pd.count }, (_, i) => i), 1))
        geometry.setAttribute('aScattered', new THREE.InstancedBufferAttribute(pd.scatteredPositions, 3))
        geometry.setAttribute('aEdge', new THREE.InstancedBufferAttribute(pd.edges, 1))
        uniforms = {
          uTime: { value: 0 },
          uWaveSpeed: { value: 1.5 },
          uWaveAmount: { value: 0.06 },
          uLightPos: { value: new THREE.Vector3(LIGHT.x, LIGHT.y, LIGHT.z) },
          uLightRange: { value: LIGHT.range },
          uShadeMin: { value: LIGHT.shadeMin },
          uShadeMax: { value: LIGHT.shadeMax },
          uColor: { value: new THREE.Color(0.75, 0.8, 0.9) },
          uMouse: { value: new THREE.Vector2(0, 0) },
          uMouseRadius: { value: MOUSE.radius },
          uMouseStrength: { value: 0.4 },
          uMouseDistort: { value: MOUSE.distort },
          uAssembly: { value: 0 },
          uLoose: { value: loose },
          uScatter: { value: 0 },
        }
        material = new THREE.ShaderMaterial({
          vertexShader: VERT,
          fragmentShader: FRAG,
          transparent: true,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          uniforms,
        })
        mesh = new THREE.InstancedMesh(geometry, material, pd.count)
        mesh.frustumCulled = false
        const obj = new THREE.Object3D()
        for (let i = 0; i < pd.count; i++) {
          obj.position.set(pd.positions[i * 3], pd.positions[i * 3 + 1], pd.positions[i * 3 + 2])
          const s = 0.5 + Math.random()
          obj.scale.set(s, s, s)
          obj.updateMatrix()
          mesh.setMatrixAt(i, obj.matrix)
        }
        mesh.instanceMatrix.needsUpdate = true
        group.add(mesh)
      }
      img.src = '/whale.svg'
    }

    const step = (delta: number) => {
      if (!visible || !mesh || !uniforms) return
      elapsed += delta
      acc += delta
      // 快速成型：0.15s 延迟 + 0.8s 装配（官网为 0.3s + 2.5s，等待感太强）
      const I = acc - 0.15
      const Lv = Math.max(0, Math.min(1, I / 0.8))
      const D = 1 - Math.pow(1 - Lv, 3)
      if (Lv <= 0) {
        group.scale.setScalar(0)
        renderer.render(scene, camera)
        return
      }
      const E = Math.min(1, window.scrollY / Math.max(1, window.innerHeight))
      uniforms.uTime.value = elapsed
      uniforms.uAssembly.value = D
      uniforms.uLoose.value = loose
      uniforms.uScatter.value = 1.6 * Math.min(1, 1.5 * E)
      uniforms.uMouseRadius.value = MOUSE.radius
      uniforms.uMouseDistort.value = MOUSE.distort
      const target = mouseActive ? MOUSE.strength : 0
      uniforms.uMouseStrength.value += (target - uniforms.uMouseStrength.value) * (1 - Math.pow(0.05, delta))
      // 视口归一化鼠标 → 世界坐标
      const vh = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.position.z
      const vw = vh * camera.aspect
      const tx = mouse.nx * vw * 0.5
      const ty = mouse.ny * vh * 0.5
      if (mouseHasMoved) {
        worldMouse.x += (tx - worldMouse.x) * MOUSE.decay
        worldMouse.y += (ty - worldMouse.y) * MOUSE.decay
      }
      // 灯光跟随平滑鼠标 x（与页面一致）
      uniforms.uLightPos.value.set(LIGHT.x + worldMouse.x * LIGHT.followX, LIGHT.y, LIGHT.z)
      uniforms.uLightRange.value = LIGHT.range
      uniforms.uShadeMin.value = LIGHT.shadeMin
      uniforms.uShadeMax.value = LIGHT.shadeMax
      // 鼠标位置转到 group 局部坐标（与选择器矩阵一致）
      inv.copy(group.matrixWorld).invert()
      tmp.set(worldMouse.x, worldMouse.y, 0).applyMatrix4(inv)
      uniforms.uMouse.value.set(tmp.x, tmp.y)
      const P = D * Math.max(0, 1 - 1.5 * E)
      uniforms.uColor.value.setRGB(0.75 * P, 0.8 * P, 0.9 * P)
      // 与页面一致的旋转 / 呼吸 / 缩放
      group.rotation.z = elapsed * ((spin ? 0.12 : 0) + (1 - D) * 0.3) + (spin ? 0 : 0.04 * Math.sin(0.25 * elapsed))
      group.rotation.x = 0.05 * Math.sin(0.08 * elapsed * 0.7)
      group.rotation.y = 0.1 * Math.sin(0.08 * elapsed)
      group.scale.setScalar((0.75 + 0.25 * D) * (1 - 0.5 * E))
      group.position.y = 0.15 * Math.sin(0.4 * elapsed) + 2.5 * E
      renderer.render(scene, camera)
    }

    const tick = (now: number) => {
      if (disposed) return
      const delta = Math.min(0.1, (now - last) / 1000)
      last = now
      if (now - lastFrame >= 1000 / 30) {
        lastFrame = now
        step(delta)
      }
      raf = requestAnimationFrame(tick)
    }

    const onPointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return
      mouse.nx = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mouse.ny = -(((e.clientY - rect.top) / rect.height) * 2 - 1)
      mouseActive = true
      mouseHasMoved = true
    }
    const onMouseLeave = () => {
      mouseActive = false
    }
    const onVisibility = () => {
      if (document.hidden) mouseActive = false
    }

    resize()
    loadWhale()
    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    window.addEventListener('mouseleave', onMouseLeave)
    document.addEventListener('visibilitychange', onVisibility)
    const io = new IntersectionObserver(entries => {
      visible = entries[0]?.isIntersecting ?? true
    }, { rootMargin: '100px' })
    io.observe(canvas)

    if (reduceMotion) {
      acc = 3
      elapsed = 0
      step(0)
    } else {
      raf = requestAnimationFrame(tick)
    }

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      io.disconnect()
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('mouseleave', onMouseLeave)
      document.removeEventListener('visibilitychange', onVisibility)
      geometry?.dispose()
      material?.dispose()
      mesh?.dispose()
      renderer.dispose()
    }
  }, [spin, loose])

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />
}
