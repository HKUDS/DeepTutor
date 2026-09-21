'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Archive, ArchiveRestore, Folder, FolderInput, Globe2, Pencil, Plus, Settings2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { SettingSection, SettingsPageHeader, inputClass, subPanelClass } from '@/components/settings/shared'
import { WorkspaceResourcePicker } from '@/components/workspaces/WorkspaceResourcePicker'
import { SystemWorkspaceSnapshot } from '@/components/workspaces/SystemWorkspaceSnapshot'
import {
  getWorkspaceCatalog, saveWorkspace, migrateWorkspace, workspaceChatHref, inheritedWorkspaceResources,
  type WorkspaceCatalog, type ChatWorkspaceRegistration,
} from '@/lib/workspaces-api'

type RunAction = (action: () => Promise<unknown>) => Promise<boolean>
const actionClass = 'inline-flex items-center justify-center gap-1.5 rounded-lg px-2.5 py-2 text-xs text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50'
const primaryClass = 'inline-flex items-center justify-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50'

function WorkspaceRow({ row, run, busy }: { row: ChatWorkspaceRegistration; run: RunAction; busy: boolean }) {
  const { t } = useTranslation()
  const [resourcesOpen, setResourcesOpen] = useState(false)
  const [resources, setResources] = useState(row.resources ?? inheritedWorkspaceResources())
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(row.display_name)
  const [moving, setMoving] = useState(false)
  const [destination, setDestination] = useState('')
  const custom = row.kind === 'workspace'
  const Icon = row.kind === 'system' ? Settings2 : row.kind === 'general' ? Globe2 : Folder
  const label = row.kind === 'system' ? t('System workspace') : row.kind === 'general' ? t('Default workspace') : row.display_name
  return (
    <article aria-label={label} className="group min-w-0 border-b border-[var(--border)] py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Icon size={18} strokeWidth={1.6} className="shrink-0 text-[var(--muted-foreground)]" />
        <h3 className="min-w-0 flex-1 break-words text-[14px] font-medium">{label}</h3>
        {row.archived && <span className="text-xs text-[var(--muted-foreground)]">{t('Archived')}</span>}
        <div className="flex items-center gap-0.5 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
          {row.kind !== 'system' && !row.archived && row.status === 'ready' && !busy && (
            <Link className={actionClass} href={row.kind === 'general' ? '/chat?dt_workspace=' : workspaceChatHref(row.workspace_id)}>
              <Plus size={14} />{t('New chat')}
            </Link>
          )}
          {row.kind !== 'system' && !row.archived && <button type="button" className={actionClass} onClick={() => { setResources(row.resources ?? inheritedWorkspaceResources()); setResourcesOpen(!resourcesOpen) }}><Settings2 size={14} />{t('Assigned resources')}</button>}
          {custom && <button type="button" className={actionClass} aria-label={t('Rename workspace')} title={t('Rename workspace')} onClick={() => { setName(row.display_name); setEditing(!editing); setMoving(false) }}><Pencil size={14} /></button>}
          <button type="button" className={actionClass} aria-label={t('Move folder')} title={t('Move folder')} onClick={() => { setMoving(!moving); setEditing(false); setDestination('') }}><FolderInput size={14} /></button>
          {custom && <button type="button" className={actionClass} aria-label={row.archived ? t('Restore workspace') : t('Archive workspace')} title={row.archived ? t('Restore workspace') : t('Archive workspace')} onClick={() => void run(() => saveWorkspace({ archived: !row.archived }, row.workspace_id))}>{row.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}</button>}
        </div>
      </div>
      <div className="mt-1.5 min-w-0 sm:pl-[30px]">
        {!custom && <p className="mb-2 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">{row.kind === 'system' ? t('Sanitized configuration snapshots, Skill files and MCP inventory. API keys and tokens remain in private configuration.') : t('Conversations without a selected workspace share files in this folder.')}</p>}
        <p className="select-all break-all font-mono text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">{row.path}</p>
        {row.archived && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t('Archived. Existing conversations and files are kept.')}</p>}
        {resourcesOpen && (
          <form className={`${subPanelClass} mt-3 space-y-3 p-4`} onSubmit={async event => { event.preventDefault(); if (await run(() => saveWorkspace({ resources }, row.workspace_id))) setResourcesOpen(false) }}>
            <WorkspaceResourcePicker value={resources} onChange={setResources} workspaceId={row.workspace_id} />
            <p className="text-xs text-[var(--muted-foreground)]">{t('Changes apply to subsequent turns. Existing conversations and files are kept.')}</p>
            <div className="flex gap-2"><button type="submit" className={primaryClass}>{t('Save')}</button><button type="button" className={actionClass} onClick={() => setResourcesOpen(false)}>{t('Cancel')}</button></div>
          </form>
        )}
        {editing && (
          <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={async event => { event.preventDefault(); if (await run(() => saveWorkspace({ name: name.trim() }, row.workspace_id))) setEditing(false) }}>
            <label className="min-w-0 flex-1 text-xs">{t('Workspace name')}<input autoFocus className={`${inputClass} mt-1`} value={name} onChange={event => setName(event.target.value)} maxLength={100} required /></label>
            <button className={primaryClass} disabled={!name.trim()} type="submit">{t('Save')}</button>
            <button className={actionClass} type="button" onClick={() => setEditing(false)}>{t('Cancel')}</button>
          </form>
        )}
        {moving && (
          <form className={`${subPanelClass} mt-3 space-y-3 p-4`} onSubmit={async event => { event.preventDefault(); if (await run(() => migrateWorkspace(destination.trim(), row.workspace_id))) setMoving(false) }}>
            <p className="text-xs text-[var(--muted-foreground)]">{row.follows_root ? t('Follows root') : t('Custom location')}</p>
            <label className="block text-xs">{t('New storage folder')}<input autoFocus className={`${inputClass} mt-1 font-mono`} value={destination} onChange={event => setDestination(event.target.value)} required placeholder={t('Enter a destination folder that does not exist yet')} /></label>
            <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">{t('Copy and verify before switching. The workspace ID and conversation bindings stay unchanged; the old folder is kept as a backup.')}</p>
            <div className="flex gap-2"><button type="submit" disabled={!destination.trim()} className={primaryClass}>{t('Start migration')}</button><button type="button" className={actionClass} onClick={() => setMoving(false)}>{t('Cancel')}</button></div>
          </form>
        )}
        {row.error && <p role="alert" className="mt-2 text-xs text-[var(--destructive)]">{row.error}</p>}
        {row.kind === 'system' && <SystemWorkspaceSnapshot />}
      </div>
    </article>
  )
}

export default function WorkspaceSettingsSection() {
  const { t } = useTranslation()
  const [catalog, setCatalog] = useState<WorkspaceCatalog | null>(null)
  const [root, setRoot] = useState('')
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)
  const [resources, setResources] = useState(inheritedWorkspaceResources)
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const refresh = useCallback(async () => {
    const next = await getWorkspaceCatalog()
    setCatalog(next)
    setRoot(next.root)
    setError('')
  }, [])
  useEffect(() => { void refresh().catch(err => setError(String(err.message))) }, [refresh])
  const run: RunAction = async action => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      await refresh()
      setNotice(t('Workspace updated.'))
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return false
    } finally { setBusy(false) }
  }
  return (
    <div>
      <SettingsPageHeader title={t('Workspaces')} description={t('Keep conversations, learning materials and progress together in one workspace.')} actions={
        <button type="button" disabled={busy || !catalog} onClick={() => setCreating(!creating)} className={primaryClass}><Plus size={15} />{t('New workspace')}</button>
      } />
      {error && <div role="alert" className="mb-4 rounded-lg border border-[var(--destructive)] p-3 text-sm text-[var(--destructive)]">{error}{!catalog && <button className="ml-3 underline" onClick={() => void refresh().catch(err => setError(String(err.message)))}>{t('Retry')}</button>}</div>}
      {(busy || notice) && <p role="status" className="mb-4 text-sm text-[var(--muted-foreground)]">{busy ? t('Working. Migration copies and verifies your files; please wait…') : notice}</p>}
      {!catalog ? (!error && <div aria-busy="true" className="h-44 animate-pulse rounded-xl bg-[var(--muted)]" />) : (
        <fieldset disabled={busy} className="min-w-0 disabled:opacity-70">
          <SettingSection title={t('Custom workspaces')} description={t('Books, Mastery Path, Reading, Watching and conversations are isolated by workspace.')}>
            {creating && (
              <form className={`${subPanelClass} my-4 space-y-3 p-4 sm:p-5`} onSubmit={async event => {
                event.preventDefault()
                if (await run(() => saveWorkspace({ name: name.trim(), resources, ...(path.trim() ? { path: path.trim() } : {}) }))) { setName(''); setPath(''); setResources(inheritedWorkspaceResources()); setCreating(false) }
              }}>
                <label className="block text-sm">{t('Workspace name')}<input autoFocus className={`${inputClass} mt-1`} value={name} onChange={event => setName(event.target.value)} required maxLength={100} placeholder={t('e.g. Probability')} /></label>
                <label className="block text-sm">{t('Existing folder path (optional)')}<input className={`${inputClass} mt-1 font-mono`} value={path} onChange={event => setPath(event.target.value)} placeholder={t('Leave empty to create under root')} /></label>
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">{t('Place files in the folder for the agent to read. Generated files go into outputs/.')}</p>
                <WorkspaceResourcePicker value={resources} onChange={setResources} />
                <div className="flex gap-2"><button type="submit" disabled={!name.trim()} className={primaryClass}>{t('Create workspace')}</button><button type="button" className={actionClass} onClick={() => setCreating(false)}>{t('Cancel')}</button></div>
              </form>
            )}
            {catalog.workspaces.filter(row => row.kind === 'workspace').map(row => <WorkspaceRow key={row.workspace_id} row={row} run={run} busy={busy} />)}
            {!catalog.workspaces.some(row => row.kind === 'workspace') && !creating && <div className="flex flex-col items-center gap-3 py-10 text-center text-[var(--muted-foreground)]"><Folder size={28} strokeWidth={1.2} /><p className="max-w-sm text-sm leading-relaxed">{t('Create a workspace for a topic or project so related conversations share its files.')}</p></div>}
          </SettingSection>
          <SettingSection title={t('Built-in workspaces')}>
            {catalog.workspaces.filter(row => row.kind !== 'workspace').map(row => <WorkspaceRow key={row.workspace_id} row={row} run={run} busy={busy} />)}
          </SettingSection>
          <SettingSection title={t('Storage location')} description={t('Workspaces default to root / workspace ID. Changing root migrates folders that follow it; custom locations stay in place. Remote deployments use server folders.')}>
            <form className="space-y-3 py-4" onSubmit={async event => { event.preventDefault(); await run(() => migrateWorkspace(root.trim())) }}>
              <label className="block text-sm">{t('Workspace root folder')}<input className={`${inputClass} mt-2 font-mono`} value={root} onChange={event => setRoot(event.target.value)} required /></label>
              {root.trim() !== catalog.root && <div className="flex flex-wrap items-center gap-3"><button type="submit" disabled={!root.trim()} className={primaryClass}>{t('Migrate to new root')}</button><p className="text-xs text-[var(--muted-foreground)]">{t('Old folders are kept as a backup. Finish running conversations before migrating.')}</p></div>}
            </form>
          </SettingSection>
        </fieldset>
      )}
    </div>
  )
}
