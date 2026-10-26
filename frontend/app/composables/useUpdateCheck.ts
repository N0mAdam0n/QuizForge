import { useLocalStorage } from '@vueuse/core'

/**
 * Desktop update check.
 *
 * Compares the running app version (from the backend `/system/version`) against
 * the latest published GitHub Release and exposes whether an update is
 * available. The result is shared app-wide via `useState` so both the sidebar
 * entry and the startup toast read the same data.
 */

interface VersionInfo {
  version: string
  repo: string
  releases_url: string
  portable?: boolean
  updater?: string
}

interface PortableUpdateInfo {
  phase: string
  current_version: string
  latest_version: string
  available: boolean
  is_patch: boolean
  size: number
  downloaded: number
  error: string
}

interface UpdateState {
  current: string
  latest: string
  hasUpdate: boolean
  releaseUrl: string
  checkedAt: number
  checking: boolean
  error: string | null
  portable: boolean
  portableInstall: boolean
  phase: string
  size: number
  downloaded: number
  isPatch: boolean
}

interface ParsedVersion {
  core: number[]
  /** `null` means no pre-release suffix (a full release, which outranks any pre-release). */
  prerelease: string[] | null
}

/** Parse `v1.2.3-beta.1` into its numeric core and pre-release identifiers, per semver rules. */
function parseVersion(v: string): ParsedVersion {
  const stripped = v.replace(/^v/, '').split('+')[0] ?? ''
  const [corePart, ...preParts] = stripped.split('-')
  const core = (corePart ?? '').split('.').map((n) => Number.parseInt(n, 10) || 0)
  const prereleaseStr = preParts.join('-')
  const prerelease = prereleaseStr ? prereleaseStr.split('.') : null
  return { core, prerelease }
}

/** Compares two semver-like identifiers the way semver does: numeric fields compare numerically. */
function compareIdentifier(a: string, b: string): number {
  const na = Number.parseInt(a, 10)
  const nb = Number.parseInt(b, 10)
  const aIsNum = !Number.isNaN(na) && String(na) === a
  const bIsNum = !Number.isNaN(nb) && String(nb) === b
  if (aIsNum && bIsNum) return na - nb
  if (aIsNum) return -1 // numeric identifiers sort before alphanumeric ones
  if (bIsNum) return 1
  return a < b ? -1 : a > b ? 1 : 0
}

/** Returns >0 if `latest` is newer than `current`, <0 if older, 0 if equal. */
function compareVersions(latest: string, current: string): number {
  const a = parseVersion(latest)
  const b = parseVersion(current)
  const len = Math.max(a.core.length, b.core.length)
  for (let i = 0; i < len; i++) {
    const diff = (a.core[i] ?? 0) - (b.core[i] ?? 0)
    if (diff !== 0) return diff
  }
  // Same core version: no pre-release suffix outranks any pre-release (1.0.0 > 1.0.0-beta.1).
  if (a.prerelease === null && b.prerelease === null) return 0
  if (a.prerelease === null) return 1
  if (b.prerelease === null) return -1
  const preLen = Math.max(a.prerelease.length, b.prerelease.length)
  for (let i = 0; i < preLen; i++) {
    if (a.prerelease[i] === undefined) return -1
    if (b.prerelease[i] === undefined) return 1
    const diff = compareIdentifier(a.prerelease[i]!, b.prerelease[i]!)
    if (diff !== 0) return diff
  }
  return 0
}

/** Returns true when `latest` is strictly newer than `current`. */
function isNewer(latest: string, current: string): boolean {
  return compareVersions(latest, current) > 0
}

interface GithubRelease {
  tag_name: string
  html_url: string
  draft: boolean
  prerelease: boolean
}

/**
 * `/releases/latest` silently ignores pre-releases, so a user tracking a pre-release
 * channel would never be told about a newer alpha/beta/rc. When the installed version
 * is itself a pre-release, fall back to the full releases list instead.
 */
async function fetchLatestRelease(repo: string, includePrerelease: boolean): Promise<GithubRelease | null> {
  const headers = { Accept: 'application/vnd.github+json' }
  if (!includePrerelease) {
    return $fetch<GithubRelease>(`https://api.github.com/repos/${repo}/releases/latest`, { headers })
  }
  const releases = await $fetch<GithubRelease[]>(`https://api.github.com/repos/${repo}/releases`, { headers })
  return releases.find((r) => !r.draft) ?? null
}

export function useUpdateCheck() {
  const state = useLocalStorage<UpdateState>('quizforge-update-check', {
    current: '',
    latest: '',
    hasUpdate: false,
    releaseUrl: '',
    checkedAt: 0,
    checking: false,
    error: null,
    portable: false,
    portableInstall: false,
    phase: 'idle',
    size: 0,
    downloaded: 0,
    isPatch: false,
  })

  const { $api } = useNuxtApp()

  async function check(force = false): Promise<void> {
    // 'installing'/'downloading' are transient and must never survive a reload:
    // after the installer restarts the app the persisted phase would otherwise
    // stay stuck on "正在重启" until the 6-hour cache expires.
    if (state.value.phase === 'installing' || state.value.phase === 'downloading') {
      force = true
    }
    if (!force && state.value.current) {
      // Cheap local call: a changed running version invalidates the cache.
      try {
        const info = await $api<VersionInfo>('/system/version')
        if (info.version !== state.value.current) force = true
      } catch {
        // fall through to the normal cache rules
      }
    }
    // Skip if checked within the last 6 hours, unless forced.
    const sixHours = 6 * 60 * 60 * 1000
    if (!force && state.value.checkedAt && Date.now() - state.value.checkedAt < sixHours) {
      return
    }
    if (state.value.checking && !force) return

    state.value.checking = true
    state.value.error = null
    try {
      // Current version + release repo from our own backend.
      const info = await $api<VersionInfo>('/system/version')
      state.value.current = info.version
      state.value.portableInstall = !!info.portable

      if (info.portable && info.updater === 'tufup') {
        const update = await $api<PortableUpdateInfo>('/system/update/check')
        state.value.portable = true
        state.value.latest = update.latest_version
        state.value.hasUpdate = update.available
        state.value.releaseUrl = info.releases_url
        state.value.phase = update.phase
        state.value.size = update.size
        state.value.downloaded = update.downloaded
        state.value.isPatch = update.is_patch
        state.value.error = update.phase === 'failed' ? update.error : null
        return
      }

      state.value.portable = false
      state.value.phase = info.portable ? 'unconfigured' : 'idle'
      // Latest release from GitHub (public API, CORS-enabled).
      const isCurrentPrerelease = parseVersion(info.version).prerelease !== null
      const release = await fetchLatestRelease(info.repo, isCurrentPrerelease)
      const latest = release?.tag_name?.replace(/^v/, '') ?? ''
      state.value.latest = latest
      state.value.releaseUrl = release?.html_url || info.releases_url
      state.value.hasUpdate = latest !== '' && isNewer(latest, info.version)
    } catch (e: unknown) {
      state.value.error = e instanceof Error ? e.message : 'update check failed'
    } finally {
      state.value.checking = false
      state.value.checkedAt = Date.now()
    }
  }

  async function downloadAndInstall(): Promise<void> {
    if (!state.value.portable) {
      throw new Error('此版本不支持应用内更新')
    }

    if (state.value.phase === 'ready') {
      if (!window.confirm(`更新 v${state.value.latest} 已下载完成，立即重启安装吗？`)) {
        return
      }
      await $api('/system/update/install', { method: 'POST' })
      state.value.phase = 'installing'
      return
    }

    await $api('/system/update/download', { method: 'POST' })
    state.value.phase = 'downloading'
    const deadline = Date.now() + 15 * 60 * 1000
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      const update = await $api<PortableUpdateInfo>('/system/update/status')
      state.value.phase = update.phase
      state.value.size = update.size
      state.value.downloaded = update.downloaded
      state.value.error = update.error || null
      if (update.phase === 'failed') {
        throw new Error(update.error || '更新下载失败，请稍后重试')
      }
      if (update.phase === 'ready') {
        if (!window.confirm(`更新 v${state.value.latest} 已下载完成，立即重启安装吗？`)) {
          return
        }
        await $api('/system/update/install', { method: 'POST' })
        state.value.phase = 'installing'
        return
      }
    }
    throw new Error('更新下载仍在进行，请稍后查看状态')
  }

  return { state, check, downloadAndInstall }
}
