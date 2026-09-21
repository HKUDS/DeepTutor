'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, FolderInput, RefreshCw } from 'lucide-react'
import { apiFetch, apiUrl } from '@/lib/api'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'
import { activeWorkspaceId } from '@/lib/workspace-scope'

type Feature = {
  feature: string
  label: string
  path: string
  files: number
  bytes: number
  sessions?: number
  error: string
}
type Discovery = { features: Feature[]; historical: { path: string }[]; session_backend: string }
type Preview = {
  features: string[]
  dependencies: string[]
  sessions: number
  files: number
  bytes: number
  blockers: string[]
}
type Operation = {
  id: string
  status: string
  created_at: string
  error?: string
  download_url?: string
  recovery_path?: string
}
const endpoint = '/api/settings/workspace/data'
const labels: Record<string, [string, string]> = {
  chat: ['Conversations', '对话'],
  book: ['Books', '书籍'],
  learning: ['Mastery Path', '掌握路径'],
  reading: ['Immersive Reading', '沉浸式阅读'],
  timed_media: ['Immersive Watching', '沉浸式观看'],
  notebook: ['Notebooks', '笔记本'],
  'co-writer': ['Writing', '协作写作'],
  courses: ['Courses', '课程'],
  files: ['File library', '文件库'],
  knowledge_bases: ['Knowledge bases', '知识库'],
  parse_cache: ['Document cache', '文档解析缓存'],
  outputs: ['Generated outputs', '生成产物'],
  presentations: ['Presented files', '已展示文件'],
  attachments: ['Conversation attachments', '对话附件'],
  historical_chat: ['Historical conversation database', '历史对话数据库'],
  historical_agent: ['Historical agent outputs', '历史智能体产物'],
  historical_output: ['Historical output folder', '历史输出目录'],
  historical_archive: ['Historical archives', '历史归档'],
}

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await apiFetch(
    apiUrl(`${endpoint}${path}`),
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : undefined
  )
  const value = await response.json()
  if (!response.ok) throw new Error(value.detail || `Request failed (${response.status})`)
  return value as T
}

export default function DataMigrationSettingsSection() {
  const { i18n } = useTranslation()
  const zh = i18n.language.startsWith('zh')
  const text = (en: string, cn: string) => (zh ? cn : en)
  const { workspaces } = useChatWorkspaces()
  const [source, setSource] = useState(activeWorkspaceId)
  const [target, setTarget] = useState('')
  const [discovery, setDiscovery] = useState<Discovery | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [operations, setOperations] = useState<Operation[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [historical, setHistorical] = useState(false)
  const label = (key: string) => labels[key]?.[zh ? 1 : 0] ?? key
  const statusLabel = (key: string) => ({
    preparing: text('Preparing', '准备中'), copying: text('Copying', '复制中'),
    transferring: text('Transferring', '迁移中'), committed: text('Finishing', '收尾中'),
    completed: text('Completed', '已完成'), exported: text('Exported', '已导出'),
    recovered: text('Recovered', '已恢复'), failed: text('Failed; source retained', '失败，来源数据已保留'),
    cleanup_required: text('Cleanup required', '需要完成清理'),
    recovery_required: text('Recovery required', '需要恢复'),
  }[key] || key)
  const input = {
    source_workspace_id: source,
    target_workspace_id: target,
    features: selected,
    include_historical: historical,
  }
  useEffect(() => {
    setPreview(null)
  }, [source, target, selected])
  useEffect(() => {
    let alive = true
    const timer = window.setInterval(() => {
      request<{ operations: Operation[] }>('/operations')
        .then(value => {
          if (alive) setOperations(value.operations)
        })
        .catch(() => {})
    }, 5000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])
  useEffect(() => {
    let alive = true
    setDiscovery(null)
    setSelected([])
    setError('')
    request<Discovery>(`/discover?source_workspace_id=${encodeURIComponent(source)}`)
      .then(value => {
        if (alive) setDiscovery(value)
      })
      .catch(err => {
        if (alive) setError(String(err.message))
      })
    request<{ operations: Operation[] }>('/operations')
      .then(value => {
        if (alive) setOperations(value.operations)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [source])
  async function run(action: 'preview' | 'migrate' | 'export') {
    setBusy(true)
    setError('')
    try {
      if (action === 'preview') setPreview(await request<Preview>('/preview', input))
      else {
        const result = await request<Operation>(`/${action}`, input)
        setOperations(old => [result, ...old])
        if (action === 'migrate') {
          setPreview(null)
          setSelected([])
          setDiscovery(
            await request<Discovery>(`/discover?source_workspace_id=${encodeURIComponent(source)}`)
          )
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  async function recover(id: string) {
    setBusy(true)
    setError('')
    try {
      const result = await request<Operation>(`/operations/${id}/recover`, {})
      setOperations(old => old.map(row => (row.id === id ? result : row)))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  const options = (
    <>
      <option value="">{text('Default workspace', '默认工作区')}</option>
      {workspaces
        .filter(row => !row.archived)
        .map(row => (
          <option key={row.workspace_id} value={row.workspace_id}>
            {row.display_name}
          </option>
        ))}
    </>
  )
  return (
    <section className="space-y-5">
      <h2 className="text-lg font-semibold">{text('Data migration', '数据迁移')}</h2>
      <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
        {text(
          'Discover stored learning data, move it with its related conversations, or download an archive. Verified recovery copies are retained after migration.',
          '查找已有学习数据，将资料和关联对话一并迁移，或下载备份。迁移后会保留经过校验的恢复副本。'
        )}
      </p>
      <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
        {text(
          'Learning data moves as a complete feature bundle. Preview includes related sources and conversations. Choose a destination with no existing data for these features.',
          '学习数据按功能整体迁移，预览会列出关联资料和对话。目标工作区中对应功能应为空，以免覆盖已有学习记录。'
        )}
      </p>
      {selected.some(key => key.startsWith('historical_')) ? (
        <p className="text-sm text-[var(--muted-foreground)]">
          {text(
            'Historical data is retained as an archive inside the destination workspace. It is not automatically merged into current learning records.',
            '历史数据将作为档案保存在目标工作区内，不会自动合并到当前学习记录。'
          )}
        </p>
      ) : null}
      <fieldset disabled={busy} className="space-y-4 disabled:opacity-60">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-sm">
            <span>{text('Source workspace', '来源工作区')}</span>
            <select
              value={source}
              onChange={event => setSource(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
            >
              {options}
            </select>
          </label>
          <label className="space-y-2 text-sm">
            <span>{text('Destination workspace', '目标工作区')}</span>
            <select
              value={target}
              onChange={event => setTarget(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
            >
              {options}
            </select>
          </label>
        </div>
        <div className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)]">
          {!discovery ? (
            <p className="p-4 text-sm" aria-busy="true">
              {text('Searching stored data…', '正在查找已有数据…')}
            </p>
          ) : (
            discovery.features.map(row => (
              <label key={row.feature} className="flex cursor-pointer items-start gap-3 p-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.includes(row.feature)}
                  disabled={!!row.error || (!row.files && !row.sessions)}
                  onChange={event =>
                    setSelected(old =>
                      event.target.checked
                        ? [...old, row.feature]
                        : old.filter(key => key !== row.feature)
                    )
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{label(row.feature)}</span>
                  <span className="block text-xs text-[var(--muted-foreground)]">
                    {row.sessions !== undefined
                      ? `${row.sessions} ${text('conversations', '个对话')} · `
                      : ''}
                    {row.files} {text('files', '个文件')} · {(row.bytes / 1024 / 1024).toFixed(1)}{' '}
                    MB
                  </span>
                  <span className="mt-1 block break-all text-[11px] text-[var(--muted-foreground)]">
                    {row.error || row.path}
                  </span>
                </span>
              </label>
            ))
          )}
        </div>
        {discovery?.historical.length ? (
          <details className="rounded-lg border border-[var(--border)] p-3 text-sm">
            <summary>
              {text('Additional historical data', '其他历史数据')} ({discovery.historical.length})
            </summary>
            <p className="my-2 text-xs text-[var(--muted-foreground)]">
              {text(
                'Historical archives can be included in exports for recovery and inspection.',
                '可在导出中包含这些历史目录，便于检查和恢复。'
              )}
            </p>
            {discovery.historical.map(row => (
              <p key={row.path} className="break-all text-xs">
                {row.path}
              </p>
            ))}
            <label className="mt-3 flex items-center gap-2">
              <input
                type="checkbox"
                checked={historical}
                onChange={event => setHistorical(event.target.checked)}
              />
              {text('Include in export', '导出时包含历史目录')}
            </label>
          </details>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button
            disabled={!selected.length}
            onClick={() => void run('preview')}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
          >
            <RefreshCw size={14} />
            {text('Preview migration', '预览迁移')}
          </button>
          <button
            disabled={!selected.length}
            onClick={() => void run('export')}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
          >
            <Download size={14} />
            {text('Export selected data', '导出所选数据')}
          </button>
        </div>
        {preview ? (
          <div className="space-y-3 rounded-xl border border-[var(--border)] p-4">
            <p className="text-sm">
              {preview.sessions} {text('conversations', '个对话')} · {preview.files}{' '}
              {text('files', '个文件')} · {(preview.bytes / 1024 / 1024).toFixed(1)} MB
            </p>
            <p className="text-sm">
              {text('Included features', '包含功能')}: {preview.features.map(label).join('、')}
            </p>
            {preview.dependencies.length ? (
              <p className="text-xs text-[var(--muted-foreground)]">
                {text(
                  'Related source data included to preserve references',
                  '为保留引用，额外包含关联来源数据'
                )}
                : {preview.dependencies.map(label).join('、')}
              </p>
            ) : null}
            {preview.blockers.map((reason, i) => (
              <p key={i} className="text-sm text-[var(--destructive)]">
                {reason}
              </p>
            ))}
            <button
              disabled={preview.blockers.length > 0}
              onClick={() => void run('migrate')}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-40"
            >
              <FolderInput size={14} />
              {text('Migrate these data', '迁移以上数据')}
            </button>
          </div>
        ) : null}
      </fieldset>
      {busy ? (
        <p role="status" className="text-sm">
          {text(
            'Processing. You can return to this page to view the result.',
            '正在处理。可以稍后回到此页查看结果。'
          )}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-[var(--destructive)]">
          {error}
        </p>
      ) : null}
      {operations.length ? (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{text('Recent operations', '最近操作')}</h3>
          {operations.slice(0, 10).map(row => (
            <div
              key={row.id}
              className="space-y-1 rounded-lg border border-[var(--border)] p-3 text-xs"
            >
              <p>
                {statusLabel(row.status)} · {new Date(row.created_at).toLocaleString()}
              </p>
              {row.error ? <p className="text-[var(--destructive)]">{row.error}</p> : null}
              {row.download_url ? (
                <a
                  href={apiUrl(row.download_url)}
                  className="inline-flex items-center gap-1 text-[var(--primary)]"
                >
                  <Download size={12} />
                  {text('Download archive', '下载备份')}
                </a>
              ) : null}
              {!['completed', 'exported', 'recovered'].includes(row.status) ? (
                <button
                  disabled={busy}
                  onClick={() => void recover(row.id)}
                  className="rounded border border-[var(--border)] px-2 py-1"
                >
                  {text('Recover migration', '恢复迁移')}
                </button>
              ) : null}
              {row.recovery_path ? (
                <p className="break-all text-[var(--muted-foreground)]">
                  {text('Recovery copy', '恢复副本')}: {row.recovery_path}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
