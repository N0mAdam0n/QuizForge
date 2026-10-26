import { useColorMode } from '@vueuse/core'
import { watch } from 'vue'

export type PracticeDefaultMode = 'sequential' | 'random' | 'wrong'
export type ThemePreference = 'auto' | 'light' | 'dark'
export type FontSizePreference = 'small' | 'medium' | 'large'

export interface UserPreferences {
  questions_per_round: number
  default_mode: PracticeDefaultMode
  show_explanation_immediately: boolean
  shuffle_options: boolean
  timer_hint: boolean
  theme: ThemePreference
  font_size: FontSizePreference
  auto_check_update: boolean
}

export const QUESTIONS_PER_ROUND_OPTIONS = [10, 20, 40, 60, 80, 100] as const

export const DEFAULT_PREFERENCES: UserPreferences = {
  questions_per_round: 20,
  default_mode: 'sequential',
  show_explanation_immediately: true,
  shuffle_options: false,
  timer_hint: false,
  theme: 'auto',
  font_size: 'medium',
  auto_check_update: true,
}

const FONT_SIZE_PX: Record<FontSizePreference, string> = {
  small: '14px',
  medium: '16px',
  large: '18px',
}

export function fontSizeToPx(size: FontSizePreference): string {
  return FONT_SIZE_PX[size] ?? FONT_SIZE_PX.medium
}

export function themeToColorMode(theme: ThemePreference): 'auto' | 'light' | 'dark' {
  return theme === 'light' || theme === 'dark' ? theme : 'auto'
}

/** Per-user preferences persisted server-side at /users/me/preferences. */
export function usePreferences() {
  const { $api } = useNuxtApp()
  const preferences = useState<UserPreferences>('user-preferences', () => ({ ...DEFAULT_PREFERENCES }))
  const loaded = useState<boolean>('user-preferences-loaded', () => false)

  const load = async (force = false) => {
    if (loaded.value && !force) return preferences.value
    try {
      const data = await $api<UserPreferences>('/users/me/preferences')
      preferences.value = { ...DEFAULT_PREFERENCES, ...data }
      loaded.value = true
    } catch (error) {
      console.debug('Could not load user preferences', error)
    }
    return preferences.value
  }

  const save = async (patch: Partial<UserPreferences>) => {
    const previous = { ...preferences.value }
    preferences.value = { ...preferences.value, ...patch }
    try {
      const data = await $api<UserPreferences>('/users/me/preferences', { method: 'PUT', body: patch })
      preferences.value = { ...DEFAULT_PREFERENCES, ...data }
      loaded.value = true
      return true
    } catch (error) {
      preferences.value = previous
      throw error
    }
  }

  return { preferences, loaded, load, save }
}

/** Apply theme and font size globally; call once from the default layout (client side). */
export function useApplyPreferences() {
  const { preferences } = usePreferences()
  const colorMode = useColorMode()
  watch(
    () => preferences.value.theme,
    (theme, previous) => {
      // Only override the sidebar toggle when the preference itself changes (or on first load).
      if (previous === undefined && theme === 'auto') return
      colorMode.value = themeToColorMode(theme)
    },
    { immediate: true },
  )
  watch(
    () => preferences.value.font_size,
    (size) => {
      if (typeof document !== 'undefined') document.documentElement.style.fontSize = fontSizeToPx(size)
    },
    { immediate: true },
  )
}
