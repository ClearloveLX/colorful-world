import type { Model, Tag, MediaItem } from './types'

const API_BASE = '/api'

const q = (params: Record<string, string | number | boolean | undefined>) => {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null) sp.append(k, String(v))
  })
  return sp.toString()
}

async function get<T>(url: string, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const onAbort = () => controller.abort()
  try {
    if (init?.signal) {
      if (init.signal.aborted) controller.abort()
      else init.signal.addEventListener('abort', onAbort, { once: true })
    }
    const r = await fetch(url, { ...init, signal: controller.signal })
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
  } finally {
    clearTimeout(timer)
    if (init?.signal) init.signal.removeEventListener('abort', onAbort)
  }
}

async function getWithFallback<T>(path: string): Promise<T> {
  const base = API_BASE
  const abs = path.startsWith('http') ? path : `${base}${path}`
  return await get<T>(abs)
}

async function getRetry<T>(path: string, attempts = 3, delayMs = 400): Promise<T> {
  let lastErr: any
  for (let i = 0; i < attempts; i++) {
    try {
      return await getWithFallback<T>(path)
    } catch (e) {
      lastErr = e
      await new Promise(r => setTimeout(r, delayMs))
    }
  }
  throw lastErr
}

export async function fetchModels(): Promise<Model[]> {
  try {
    return await getRetry<Model[]>('/models')
  } catch {
    return []
  }
}

export async function fetchTags(): Promise<Tag[]> {
  try {
    return await getRetry<Tag[]>('/tags')
  } catch {
    return []
  }
}

export type MediaQuery = {
  model_ids?: string[]
  tag_ids?: string[]
  exclude_tag_ids?: string[]
  page?: number
  page_size?: number
  strict?: boolean
  min_heat?: number
  max_heat?: number
  order?: 'recent' | 'recent_asc' | 'random' | 'duration' | 'duration_asc' | 'heat' | 'heat_asc'
  seed?: number
  name?: string
  edit_mode?: boolean
  true_random?: boolean
}

export type TrueRandomCacheMeta = {
  enabled: boolean
  active: boolean
  cached_count: number
}

export type MediaResponse = {
  items: MediaItem[]
  hasMore: boolean
  true_random_cache?: TrueRandomCacheMeta
}

export type TrueRandomCacheSettings = {
  enabled: boolean
  cached_count: number
  source: string
}

export async function fetchMedia(params: MediaQuery, signal?: AbortSignal): Promise<MediaResponse> {
  const s = q({
    model_ids: params.model_ids?.join(',') || undefined,
    tag_ids: params.tag_ids?.join(',') || undefined,
    exclude_tag_ids: params.exclude_tag_ids?.join(',') || undefined,
    page: params.page ?? 1,
    page_size: params.page_size ?? 30,
    strict: params.strict ?? true,
    min_heat: params.min_heat,
    max_heat: params.max_heat,
    order: params.order,
    seed: params.seed,
    name: (params.name ?? '').trim() || undefined,
    edit_mode: params.edit_mode,
    true_random: params.true_random,
  })
  const base = API_BASE
  const url = `${base}/media?${s}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 15000)
  const onExternalAbort = () => controller.abort()
  try {
    if (signal) {
      if (signal.aborted) controller.abort()
      else signal.addEventListener('abort', onExternalAbort, { once: true })
    }
    const r = await fetch(url, { signal: controller.signal })
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', onExternalAbort)
  }
}

export async function likeMedia(fileId: string): Promise<{ ok: boolean; heat_value: number }> {
  const base = API_BASE
  const path = `/media/${encodeURIComponent(fileId)}/like`
  const r = await fetch(`${base}${path}`, { method: 'POST' })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function dislikeMedia(fileId: string): Promise<{ ok: boolean; heat_value: number }> {
  const base = API_BASE
  const path = `/media/${encodeURIComponent(fileId)}/dislike`
  const r = await fetch(`${base}${path}`, { method: 'POST' })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function bulkUpdateHeat(fileIds: string[], delta: number): Promise<{ ok: boolean; updated: number; skipped: number; errors: number }> {
  const r = await fetch(`${API_BASE}/files/bulk/heat`, {
    method: 'POST',
    headers: { 'Content-Type':'application/json' },
    body: JSON.stringify({ file_ids: fileIds, delta })
  })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function validatePassword(code: string): Promise<{ ok: boolean }> {
  const base = API_BASE
  const s = q({ code })
  return await getRetry<{ ok: boolean }>(`/password/validate?${s}`)
}

export async function fetchCurrentPassword(): Promise<{ code: string }> {
  return await getRetry<{ code: string }>(`/password/current`)
}

export async function bulkAddTags(fileIds: string[], tagIds: string[]): Promise<{ ok: boolean; updated: number; skipped: number; errors: number }> {
  const r = await fetch(`${API_BASE}/files/bulk/add_tags`, {
    method: 'POST',
    headers: { 'Content-Type':'application/json' },
    body: JSON.stringify({ file_ids: fileIds, tag_ids: tagIds })
  })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function bulkRemoveTags(fileIds: string[], tagIds: string[]): Promise<{ ok: boolean; updated: number; skipped: number; errors: number }> {
  const r = await fetch(`${API_BASE}/files/bulk/remove_tags`, {
    method: 'POST',
    headers: { 'Content-Type':'application/json' },
    body: JSON.stringify({ file_ids: fileIds, tag_ids: tagIds })
  })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function fetchTrueRandomCacheSettings(): Promise<TrueRandomCacheSettings> {
  return await getRetry<TrueRandomCacheSettings>('/settings/true-random-cache')
}

export async function updateTrueRandomCacheSettings(enabled: boolean): Promise<TrueRandomCacheSettings & { ok: boolean }> {
  const r = await fetch(`${API_BASE}/settings/true-random-cache`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

export async function clearTrueRandomCache(): Promise<{ ok: boolean; deleted: number; cached_count: number }> {
  const r = await fetch(`${API_BASE}/true-random-cache/clear`, { method: 'POST' })
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}
