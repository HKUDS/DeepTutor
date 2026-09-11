'use client'

import { useEffect, useState } from 'react'
import { FolderOpen, Loader2, RotateCcw } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  inputClass,
} from '@/components/settings/shared'
import { apiFetch, apiUrl } from '@/lib/api'
import { notify } from '@/lib/notifications'

type WorkspaceSettings = {
  workspace_id: string
  path: string
  display_name: string
  is_default: boolean
  locked: boolean
  status: 'ready' | 'invalid'
  security_level: 'hard' | 'best_effort' | 'off'
  error?: string
}

export default function WorkspaceSettingsSection() {
  const { i18n } = useTranslation()
  const zh = i18n.language?.toLowerCase().startsWith('zh')
  const copy = zh
    ? {
        title: 'Workspace',
        description:
          '选择 DeepTutor 读取资料和保存生成内容的文件夹。设置、密钥、数据库和记忆不会放进这里。',
        location: '当前文件夹',
        locationDescription:
          'Agent 可读取整个 Workspace；新建、下载和生成的内容默认只写入 outputs/。远程部署中的路径指服务器文件系统。',
        save: '使用此文件夹',
        reset: '恢复默认',
        loading: '正在读取 Workspace…',
        ready: '可用',
        invalid: '不可用',
        hard: '文件系统硬隔离',
        bestEffort: '本地兼容模式：执行工具没有完整文件系统隔离',
        off: '执行工具不可用',
        locked: '此 Docker/服务器部署已在启动时锁定 Workspace。',
        saved: 'Workspace 已更新',
        resetDone: '已恢复默认 Workspace',
        failed: 'Workspace 更新失败',
      }
    : {
        title: 'Workspace',
        description:
          'Choose the folder DeepTutor reads from and uses for generated content. Settings, secrets, databases, and memory stay elsewhere.',
        location: 'Current folder',
        locationDescription:
          'The agent can read this workspace; new, downloaded, and generated content goes only to outputs/ by default. On a remote deployment this is a server path.',
        save: 'Use this folder',
        reset: 'Restore default',
        loading: 'Loading workspace…',
        ready: 'Ready',
        invalid: 'Unavailable',
        hard: 'Filesystem-enforced isolation',
        bestEffort: 'Local compatibility mode: exec lacks full filesystem isolation',
        off: 'Execution tools unavailable',
        locked: 'This Docker/server deployment locks the workspace at startup.',
        saved: 'Workspace updated',
        resetDone: 'Default workspace restored',
        failed: 'Could not update workspace',
      }
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null)
  const [path, setPath] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await apiFetch(apiUrl('/api/settings/workspace'))
      const payload = (await response.json().catch(() => ({}))) as
        WorkspaceSettings | { detail?: string }
      if (!response.ok) throw new Error('detail' in payload ? payload.detail : copy.failed)
      const next = payload as WorkspaceSettings
      setSettings(next)
      setPath(next.path)
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.failed)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // Language only changes copy; it must not refetch or replace an in-progress edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async (nextPath: string | null) => {
    setSaving(true)
    setError('')
    try {
      const response = await apiFetch(apiUrl('/api/settings/workspace'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: nextPath }),
      })
      const payload = (await response.json().catch(() => ({}))) as
        WorkspaceSettings | { detail?: string }
      if (!response.ok) throw new Error('detail' in payload ? payload.detail : copy.failed)
      const next = payload as WorkspaceSettings
      setSettings(next)
      setPath(next.path)
      notify(nextPath === null ? copy.resetDone : copy.saved, { tone: 'success' })
    } catch (err) {
      const message = err instanceof Error ? err.message : copy.failed
      setError(message)
      notify(message, { tone: 'error' })
    } finally {
      setSaving(false)
    }
  }

  const securityCopy = settings
    ? settings.security_level === 'hard'
      ? copy.hard
      : settings.security_level === 'best_effort'
        ? copy.bestEffort
        : copy.off
    : ''

  return (
    <div>
      <SettingsPageHeader title={copy.title} description={copy.description} />
      {loading ? (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {copy.loading}
        </div>
      ) : (
        <SettingSection title={copy.location} description={copy.locationDescription}>
          <SettingRow
            title={settings?.display_name || copy.location}
            description={`${settings?.status === 'ready' ? copy.ready : copy.invalid} · ${securityCopy}`}
            control={
              <span className="flex max-w-[min(62vw,680px)] items-center gap-2">
                <FolderOpen className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                <input
                  className={`${inputClass} min-w-64 font-mono text-[12px]`}
                  value={path}
                  disabled={saving || settings?.locked}
                  onChange={event => setPath(event.target.value)}
                  aria-label={copy.location}
                />
                <button
                  type="button"
                  disabled={saving || settings?.locked || !path.trim()}
                  onClick={() => void save(path.trim())}
                  className="shrink-0 rounded-lg bg-[var(--foreground)] px-3 py-2 text-[12px] font-medium text-[var(--background)] disabled:opacity-40"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : copy.save}
                </button>
                <button
                  type="button"
                  disabled={saving || settings?.locked || settings?.is_default}
                  onClick={() => void save(null)}
                  className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] disabled:opacity-40"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {copy.reset}
                </button>
              </span>
            }
          />
          {settings?.locked && (
            <p className="mt-2 text-[12px] text-[var(--muted-foreground)]">{copy.locked}</p>
          )}
          {error && (
            <p className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-600 dark:text-red-300">
              {error}
            </p>
          )}
        </SettingSection>
      )}
    </div>
  )
}
