import { describe, expect, it, vi } from 'vitest'
import { scrollWindowToTop } from './scrollToTop'

describe('scrollWindowToTop', () => {
  it('requests a smooth scroll to the page top', () => {
    const scrollTo = vi.fn()

    scrollWindowToTop({ scrollTo })

    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
  })
})
