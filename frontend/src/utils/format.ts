/** 视作视频/音频的类型集合（用于播放器、时长、角标展示） */
const VIDEO_TYPES = ['mp4', 'avi', 'mov', 'mkv', 'webm', 'mpeg', 'mpg', 'm4v', 'mp3', 'm4a']

export function isVideoFile(fileType?: string | null): boolean {
  return VIDEO_TYPES.includes((fileType || '').toLowerCase())
}

export function formatFileSize(bytes?: number | null): string | null {
  if (!bytes || bytes <= 0) return null
  const kb = bytes / 1024
  const mb = kb / 1024
  const gb = mb / 1024
  if (gb >= 1) return `${gb.toFixed(2)}G`
  if (mb >= 1) return `${mb.toFixed(2)}M`
  const k = Number(kb.toFixed(2))
  return `${(k <= 0 ? 0.01 : k).toFixed(2)}k`
}

export function formatDurationZh(ms?: number | null): string | null {
  if (!ms || ms <= 0) return null
  const total = Math.round(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (h > 0) return `${h}时${pad(m)}分${pad(s)}秒`
  return `${m}分${pad(s)}秒`
}

/** 去掉常见媒体扩展名，用于灯箱标题展示 */
export function stripMediaExtension(title: string): string {
  const m = title.match(/^(.*?)(\.(jpg|jpeg|png|gif|webp|bmp|tiff|svg|mp4|avi|mov|mkv|webm|mpeg|mpg|m4v|mp3|m4a))$/i)
  return m ? m[1] : title
}
