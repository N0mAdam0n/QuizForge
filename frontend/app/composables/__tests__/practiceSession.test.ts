import { describe, expect, it } from 'vitest'
import { formatDuration, seededShuffle, summarizeSession } from '../../utils/practiceSession'
import { fontSizeToPx, themeToColorMode } from '../usePreferences'

describe('summarizeSession', () => {
  it('computes accuracy over graded answers only', () => {
    const s = summarizeSession([{ is_correct: true }, { is_correct: false }, { is_correct: true }, { is_correct: null }])
    expect(s).toEqual({ answered: 4, correct: 2, incorrect: 1, ungraded: 1, accuracy: 66.7 })
  })
  it('returns null accuracy when nothing graded', () => {
    expect(summarizeSession([]).accuracy).toBeNull()
  })
})

describe('formatDuration', () => {
  it('formats mm:ss and h:mm:ss', () => {
    expect(formatDuration(65_000)).toBe('01:05')
    expect(formatDuration(3_725_000)).toBe('1:02:05')
    expect(formatDuration(-5)).toBe('00:00')
  })
})

describe('seededShuffle', () => {
  it('is a stable permutation for the same seed', () => {
    const items = ['a', 'b', 'c', 'd', 'e']
    const a = seededShuffle(items, 42)
    expect(seededShuffle(items, 42)).toEqual(a)
    expect([...a].sort()).toEqual(items)
    expect(items).toEqual(['a', 'b', 'c', 'd', 'e'])
  })
})

describe('preference helpers', () => {
  it('maps font size and theme', () => {
    expect(fontSizeToPx('large')).toBe('18px')
    expect(fontSizeToPx('medium')).toBe('16px')
    expect(themeToColorMode('dark')).toBe('dark')
    expect(themeToColorMode('auto')).toBe('auto')
  })
})
