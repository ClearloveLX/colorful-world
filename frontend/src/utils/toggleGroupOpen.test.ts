import { describe, expect, it } from 'vitest'
import { toggleGroupOpen } from './toggleGroupOpen'

describe('toggleGroupOpen', () => {
  it('closes a group on first toggle when the default state is open', () => {
    expect(toggleGroupOpen(undefined)).toBe(false)
  })

  it('reopens a group after it has been closed', () => {
    expect(toggleGroupOpen(false)).toBe(true)
  })
})
