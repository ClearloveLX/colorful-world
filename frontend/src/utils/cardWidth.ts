export const CARD_WIDTH_MIN = 180
export const CARD_WIDTH_MAX = 360
export const CARD_WIDTH_STEP = 10
export const DEFAULT_CARD_WIDTH = 300
export const CARD_WIDTH_KEY = 'cw_card_width'

export function sanitizeCardWidth(raw: unknown): number {
  const n = Number.parseInt(String(raw), 10)
  if (Number.isFinite(n) && n >= CARD_WIDTH_MIN && n <= CARD_WIDTH_MAX) return n
  return DEFAULT_CARD_WIDTH
}

export function loadCardWidth(storage?: Pick<Storage, 'getItem'>): number {
  const s = storage ?? (typeof localStorage !== 'undefined' ? localStorage : undefined)
  if (!s) return DEFAULT_CARD_WIDTH
  try {
    return sanitizeCardWidth(s.getItem(CARD_WIDTH_KEY))
  } catch {
    return DEFAULT_CARD_WIDTH
  }
}

export function saveCardWidth(width: number, storage?: Pick<Storage, 'setItem'>): void {
  const s = storage ?? (typeof localStorage !== 'undefined' ? localStorage : undefined)
  if (!s) return
  try {
    s.setItem(CARD_WIDTH_KEY, String(width))
  } catch {}
}
