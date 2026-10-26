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
