import { describe, expect, it } from 'vitest'
import { formatDurationZh, formatFileSize, isVideoFile, stripMediaExtension } from './format'

describe('isVideoFile', () => {
  it('recognizes video/audio extensions case-insensitively', () => {
    expect(isVideoFile('mp4')).toBe(true)
    expect(isVideoFile('MP4')).toBe(true)
    expect(isVideoFile('mp3')).toBe(true)
    expect(isVideoFile('m4a')).toBe(true)
  })

  it('rejects images, unknown types and empty values', () => {
    expect(isVideoFile('jpg')).toBe(false)
    expect(isVideoFile('png')).toBe(false)
    expect(isVideoFile('')).toBe(false)
    expect(isVideoFile(null)).toBe(false)
    expect(isVideoFile(undefined)).toBe(false)
  })
})

describe('formatFileSize', () => {
  it('formats bytes, KB, MB and GB', () => {
    expect(formatFileSize(0)).toBeNull()
    expect(formatFileSize(null)).toBeNull()
    expect(formatFileSize(512)).toBe('0.50k')
    expect(formatFileSize(1024 * 1024)).toBe('1.00M')
    expect(formatFileSize(1024 * 1024 * 1024 * 2)).toBe('2.00G')
  })
})

describe('formatDurationZh', () => {
  it('formats seconds/minutes/hours in Chinese', () => {
    expect(formatDurationZh(0)).toBeNull()
    expect(formatDurationZh(null)).toBeNull()
    expect(formatDurationZh(65_000)).toBe('1分05秒')
    expect(formatDurationZh(3_661_000)).toBe('1时01分01秒')
  })
})

describe('stripMediaExtension', () => {
  it('strips a known media extension', () => {
    expect(stripMediaExtension('photo.jpg')).toBe('photo')
    expect(stripMediaExtension('clip.MP4')).toBe('clip')
    expect(stripMediaExtension('no-extension')).toBe('no-extension')
    expect(stripMediaExtension('file.tar.gz')).toBe('file.tar.gz')
  })
})
