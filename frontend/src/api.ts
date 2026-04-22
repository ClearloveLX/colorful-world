import type { Model, Tag, MediaItem } from './types'

const API_BASE = '/api'

const q = (params: Record<string, string | number | boolean | undefined>) => {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null) sp.append(k, String(v))
  })
  return sp.toString()
}

async function get<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
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
}

export async function fetchMedia(params: MediaQuery): Promise<{ items: MediaItem[]; hasMore: boolean }> {
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
    name: (params.name ?? '').trim() || undefined
  })
  try {
    return await getRetry<{ items: MediaItem[]; hasMore: boolean }>(`/media?${s}`)
  } catch {
    return { items: [], hasMore: false }
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
