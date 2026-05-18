# 前端视觉升级设计文档

**日期:** 2026-05-18
**范围:** 前端全局视觉效果 + 动效升级
**方向:** 次世代玻璃 morphism + 极致动效 + 多色流体渐变

---

## 一、架构与文件结构

### 新增文件
```
frontend/src/
├── effects/
│   ├── FluidBackground.tsx    # Canvas 流体渐变背景
│   ├── CursorTrail.tsx        # 光标光晕轨迹
│   └── ParticleField.tsx      # 浮动粒子场
├── hooks/
│   └── useAnimationFrame.ts   # rAF 管理 hook
```

### 修改文件
```
frontend/src/
├── styles.css          # 强化玻璃效果、新增动效、多色渐变 token
├── App.tsx             # 挂载 FluidBackground + CursorTrail
├── components/
│   ├── MediaCard.tsx   # 强化 3D 视差 + 流光边框 + 玻璃反射
│   ├── MediaGrid.tsx   # 滚动视差 + 卡片错峰入场
│   ├── Filters.tsx     # 侧栏光效强化
│   └── Lightbox.tsx    # 背景粒子 + 过渡升级
```

### 设计原则
- Canvas 层只负责背景效果 (z-index: -1)，不影响现有 DOM 结构和交互逻辑
- CSS 层在现有设计系统上叠加更激进的动效和色彩
- 不引入任何新 npm 依赖，纯 Canvas + CSS 实现
- 移动端自动降级（跳过粒子/光标轨迹），仅保留 CSS 动效

---

## 二、视觉效果设计

### 2.1 流体渐变背景 (FluidBackground.tsx)

- Canvas 渲染，挂载在 App 最外层
- 3-5 个大型色彩斑块（紫 #8B5CF6、蓝 #3B82F6、青 #06B6D4、粉 #EC4899），在画布上缓慢漂移
- 使用径向渐变叠加 + CSS blur filter 模拟 metaball 液体融合效果
- 各色块有独立运动轨迹（正弦波叠加，周期不同避免重复）
- 整体透明度 0.6-0.8，确保内容可读
- 鼠标位置影响：光标附近色温偏暖，远处偏冷（色块朝光标位置微偏）

### 2.2 粒子场 (ParticleField.tsx)

- 80-120 个微小发光粒子，随机分布全屏
- 粒子属性：x, y, vx, vy, radius(1-3px), opacity, hue（继承流体色系）
- 缓慢上浮（vy -= 0.02），超出屏幕后从底部重新生成
- 粒子间距离 < 150px 时绘制半透明连线（constellation 效果）
- 粒子靠近光标 (< 120px) 时被轻微吸引，形成微弱的交互感
- 仅在桌面端启用

### 2.3 光标轨迹 (CursorTrail.tsx)

- 独立 Canvas 层，pointer-events: none
- 追踪鼠标位置，在历史位置绘制逐渐消散的光晕圆斑
- 使用衰减队列（最多 8 个历史点），每个点半径递减（80px → 10px）
- 光晕颜色采样自当前最近流体色块
- 使用 globalAlpha 渐变让轨迹自然消散
- 仅在桌面端启用

### 2.4 卡片玻璃材质升级

- backdrop-filter: saturate(200%) blur(24px) brightness(1.05)
- 边框：从单色 `var(--line)` 升级为渐变描边
  - 实现：伪元素 `::before` 做渐变边框（紫→蓝→青→粉）
  - 静态时透明度 0，hover 时淡入至 0.6
- hover 抬升从 3px → 6px
- 阴影从灰色改为紫色调：`0 8px 32px rgba(139,92,246,0.12), 0 2px 8px rgba(99,102,241,0.08)`
- 卡内光效扫描线（shine 效果增强）

### 2.5 色彩 Token 重构

- 背景主色改为支持渐变叠加的变量体系
- accent 拆分为多色系：`--accent-purple` (#8B5CF6), `--accent-blue` (#3B82F6), `--accent-cyan` (#06B6D4), `--accent-pink` (#EC4899)
- 新增 `--glass-tint` 变量，支持动态色彩倾向
- 保持现有浅色模式 --surface / --glass 体系不变，叠加新变量

---

## 三、动效与交互设计

### 3.1 卡片 3D 视差

- tilt 效果旋转角度加深：RX ±8°, RY ±10°
- 卡片内图片层独立反向视差（图片向鼠标方向偏移 4-6px）
- hover 光效扫描线：一道 30% 宽的半透明光带从卡片表面斜向扫过
- 离开时回弹动画（spring 曲线，300ms）

### 3.2 卡片入场动画

- 从统一动画改为错峰入场（staggered entrance）：
  - 列位置感知：左侧列先到，每列延迟 60ms
  - 行位置叠加：每行额外延迟 40ms
  - 整体形成波浪式入场效果
  - 添加水平位移分量（从卡片所在列偏移 ±8px 滑入）

### 3.3 滚动视差

- 侧栏 Filters 背景色随滚动位置偏移渐变（顶部偏紫 → 底部偏蓝）
- 卡片在视口边缘时有微弱缩放过渡（0.97 → 1 → 0.97）

### 3.4 Lightbox 升级

- 打开：从点击卡片位置做圆形遮罩展开动画
- 关闭：回缩到卡片位置
- 背景粒子密度在 lightbox 打开时增加
- 左右切换图片：3D 翻转过渡（rotateY + perspective, 400ms）

### 3.5 微交互

- 点赞 +1：从当前效果升级为粒子爆散（6-8 个小粒子向四周飞出）
- 批量选择：选中卡片有呼吸光晕（box-shadow 脉冲动画）
- 侧栏 chip 点击：水波扩散效果（类似 Material ripple 但用渐变色）
- 按钮 hover：背景色渐变切换 + 微抬升

### 3.6 全局细节

- 滚动条自定义：渐变色滑块（紫→蓝）
- 页面首次加载：顶部渐变色进度条
- 回到顶部按钮：旋转光环动画（::after 伪元素做旋转渐变环）
- 页面 visibility 变化时暂停/恢复 Canvas 动画

---

## 四、兼容性与降级

- 移动端（< 768px）：跳过 FluidBackground Canvas、CursorTrail、ParticleField
- `prefers-reduced-motion: reduce`：禁用所有非必要动画，保留基础过渡
- Canvas 初始化失败时静默降级，不影响页面功能
- 低性能设备检测（通过帧率采样）：连续 3 秒 < 30fps 自动关闭粒子场

---

## 五、实现顺序

1. Color Token 重构 + CSS 卡片升级（基础，后续依赖）
2. FluidBackground Canvas 组件
3. ParticleField + CursorTrail
4. 卡片 3D 视差强化 + 错峰入场
5. Lightbox 升级
6. 微交互 + 全局细节
7. 兼容性/降级处理
8. 测试验证

---

## 六、成功标准

- 视觉效果：卡片有明显玻璃反射/渐变边框/hover 光效，背景有流体渐变运动
- 动效流畅：所有动画保持 60fps（桌面端），无掉帧感
- 功能不受影响：所有现有交互（筛选、批量操作、lightbox、点赞等）正常工作
- 移动端降级正确：小屏幕下无 Canvas 开销，CSS 动效正常
- 无新依赖：npm 依赖不变
