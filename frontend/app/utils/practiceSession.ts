/** Pure helpers for the practice page (end-of-session summary, option shuffle, timers). */

export interface SessionResultLike {
  is_correct: boolean | null
}

export interface SessionSummary {
  answered: number
  correct: number
  incorrect: number
  ungraded: number
  accuracy: number | null
}

export function summarizeSession(results: SessionResultLike[]): SessionSummary {
  const correct = results.filter((r) => r.is_correct === true).length
  const incorrect = results.filter((r) => r.is_correct === false).length
  const ungraded = results.filter((r) => r.is_correct === null).length
  const graded = correct + incorrect
  return {
    answered: results.length,
    correct,
    incorrect,
    ungraded,
    accuracy: graded ? Math.round((correct / graded) * 1000) / 10 : null,
  }
}

export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

/** Deterministic Fisher-Yates shuffle seeded by a number (stable per question within a session). */
export function seededShuffle<T>(items: readonly T[], seed: number): T[] {
  const out = [...items]
  let state = (seed >>> 0) || 1
  const next = () => {
    state ^= state << 13
    state >>>= 0
    state ^= state >>> 17
    state ^= state << 5
    state >>>= 0
    return state / 0x100000000
  }
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1))
    ;[out[i], out[j]] = [out[j] as T, out[i] as T]
  }
  return out
}

const PINNED_LAST_PATTERNS = [
  /^以上(都|全|均)?(对|正确|是|错|不对|错误|都不对|都不是|皆非|皆是)/,
  /^以上(选项|说法|答案)?(都|全|均)/,
  /^(都|全)(对|不对|正确|错误)$/,
  /^(all|none|both|neither) of the (above|options)/i,
]

/** True for options such as「以上都对」「以上都不对」「All of the above」that must stay last. */
export function isPinnedLastOption(text: string): boolean {
  const normalized = text.trim().replace(/^[（(]?[A-Za-z][)）.、．:：]\s*/, '').trim()
  return PINNED_LAST_PATTERNS.some((re) => re.test(normalized))
}

export interface ShufflableOption {
  id: string
  label: string
}

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

/**
 * Shuffle choice options for display. Option ids (the keys used for grading and
 * telemetry) are untouched; only the display order and display letters change.
 * Options matching「以上都对」etc. keep their relative order at the end.
 */
export function shuffleChoiceOptions<T extends ShufflableOption>(
  options: readonly T[],
  seed: number,
  textOf: (option: T) => string,
): T[] {
  const pinned = options.filter((o) => isPinnedLastOption(textOf(o)))
  const free = options.filter((o) => !pinned.includes(o))
  return [...seededShuffle(free, seed), ...pinned].map((o, i) => ({ ...o, label: LETTERS[i] ?? o.label }))
}
