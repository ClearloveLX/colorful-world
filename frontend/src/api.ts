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
  page?: number
  page_size?: number
  strict?: boolean
  order?: 'recent' | 'random' | 'duration'
  seed?: number
}

export async function fetchMedia(params: MediaQuery): Promise<{ items: MediaItem[]; hasMore: boolean }> {
  const s = q({
    model_ids: params.model_ids?.join(',') || undefined,
    tag_ids: params.tag_ids?.join(',') || undefined,
    page: params.page ?? 1,
    page_size: params.page_size ?? 30,
    strict: params.strict ?? true,
    order: params.order,
    seed: params.seed
  })
  try {
    return await getRetry<{ items: MediaItem[]; hasMore: boolean }>(`/media?${s}`)
  } catch {
    return { items: [], hasMore: false }
  }
}
