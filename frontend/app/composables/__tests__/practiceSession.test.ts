import { describe, expect, it } from 'vitest'
import {
  formatDuration,
  isPinnedLastOption,
  seededShuffle,
  shuffleChoiceOptions,
  summarizeSession,
} from '../../utils/practiceSession'
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

describe('shuffleChoiceOptions', () => {
  const opts = [
    { id: 'a', label: 'A', text: '甲' },
    { id: 'b', label: 'B', text: '乙' },
    { id: 'c', label: 'C', text: '丙' },
    { id: 'd', label: 'D', text: '丁' },
    { id: 'e', label: 'E', text: '以上都对' },
  ]
  const textOf = (o: { text: string }) => o.text

  it('keeps ids, relabels letters in display order and pins "以上都对" last', () => {
    for (const seed of [1, 2, 3, 99, 12345]) {
      const out = shuffleChoiceOptions(opts, seed, textOf)
      expect(out.map((o) => o.label)).toEqual(['A', 'B', 'C', 'D', 'E'])
      expect(out[4]!.id).toBe('e')
      expect(out.map((o) => o.id).sort()).toEqual(['a', 'b', 'c', 'd', 'e'])
      // the label shown for an id maps back to the same original option (grading uses id)
      for (const o of out) expect(opts.find((x) => x.id === o.id)!.text).toBe(o.text)
    }
  })

  it('is stable for the same seed and differs across seeds', () => {
    const a = shuffleChoiceOptions(opts, 7, textOf).map((o) => o.id)
    expect(shuffleChoiceOptions(opts, 7, textOf).map((o) => o.id)).toEqual(a)
    const variants = new Set([1, 2, 3, 4, 5, 6, 8, 9].map((s) => shuffleChoiceOptions(opts, s, textOf).map((o) => o.id).join()))
    expect(variants.size).toBeGreaterThan(1)
  })

  it('does not mutate the input', () => {
    shuffleChoiceOptions(opts, 3, textOf)
    expect(opts.map((o) => o.label)).toEqual(['A', 'B', 'C', 'D', 'E'])
  })

  it('recognises pinned option wording', () => {
    for (const t of ['以上都对', '以上都不对', '以上均正确', '以上说法都错误', 'All of the above', 'None of the above', 'D. 以上都是'])
      expect(isPinnedLastOption(t)).toBe(true)
    for (const t of ['甲', '以上海为例', 'All cats'])
      expect(isPinnedLastOption(t)).toBe(false)
  })
})
