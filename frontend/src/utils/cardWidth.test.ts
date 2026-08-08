import { describe, expect, it, vi } from 'vitest'
import { CARD_WIDTH_KEY, DEFAULT_CARD_WIDTH, loadCardWidth, sanitizeCardWidth, saveCardWidth } from './cardWidth'

describe('sanitizeCardWidth', () => {
  it('accepts a valid number in range', () => {
    expect(sanitizeCardWidth('300')).toBe(300)
    expect(sanitizeCardWidth('200')).toBe(200)
    expect(sanitizeCardWidth('230')).toBe(230)
  })

  it('falls back to default for non-numeric input', () => {
    expect(sanitizeCardWidth('abc')).toBe(DEFAULT_CARD_WIDTH)
    expect(sanitizeCardWidth(null)).toBe(DEFAULT_CARD_WIDTH)
    expect(sanitizeCardWidth(undefined)).toBe(DEFAULT_CARD_WIDTH)
  })

  it('falls back to default for out-of-range input', () => {
    expect(sanitizeCardWidth('999')).toBe(DEFAULT_CARD_WIDTH)
    expect(sanitizeCardWidth('100')).toBe(DEFAULT_CARD_WIDTH)
  })
})

describe('loadCardWidth', () => {
  it('returns default when storage has no value', () => {
    const storage = { getItem: vi.fn(() => null) }
    expect(loadCardWidth(storage)).toBe(DEFAULT_CARD_WIDTH)
  })

  it('returns the stored value when valid', () => {
    const storage = { getItem: vi.fn(() => '240') }
    expect(loadCardWidth(storage)).toBe(240)
  })

  it('falls back to default for corrupted values', () => {
    const storage = { getItem: vi.fn(() => 'oops') }
    expect(loadCardWidth(storage)).toBe(DEFAULT_CARD_WIDTH)
  })
})

describe('saveCardWidth', () => {
  it('persists the width with the expected key', () => {
    const storage = { setItem: vi.fn() }
    saveCardWidth(240, storage)
    expect(storage.setItem).toHaveBeenCalledWith(CARD_WIDTH_KEY, '240')
  })
})
