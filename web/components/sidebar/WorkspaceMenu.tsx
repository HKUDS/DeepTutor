'use client'

import Image from 'next/image'
import Link from 'next/link'
import { useId, useState, type ReactNode } from 'react'
import { Check, ChevronDown, Settings, Settings2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import Tooltip from '@/shared/ui/Tooltip'
import { useWorkspaceChoices } from '@/components/workspaces/useWorkspaceChoices'
import { VersionBadge } from '@/components/sidebar/VersionBadge'

const GLYPH_TINTS = ['#e3655b', '#d9822b', '#c9a227', '#4f9d69', '#3d8fb8', '#6c6fd1', '#a35fc0', '#c25b8a']

/** A stable letter tile for a workspace; the general one wears the logo. */
export function WorkspaceGlyph({ name, general, size = 22 }: { name: string; general: boolean; size?: number }) {
  if (general)
    return (
      <span aria-hidden className="dt-workspace-glyph is-general" style={{ width: size, height: size }}>
        <Image src="/brand/color-logo.png" alt="" width={size} height={size} className="h-full w-full object-contain" />
      </span>
    )
  let hash = 0
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) | 0
  return (
    <span
      aria-hidden
      className="dt-workspace-glyph"
      style={{ width: size, height: size, background: GLYPH_TINTS[Math.abs(hash) % GLYPH_TINTS.length], fontSize: size * 0.5 }}
    >
      {[...name.trim()][0]?.toUpperCase() ?? '·'}
    </span>
  )
}

/** The workspaces as menu items, the current one checked. */
export function WorkspaceChoiceList({ onChoose }: { onChoose?: () => void }) {
  const { t } = useTranslation()
  const { active, choices, choose } = useWorkspaceChoices()
  return (
    <>
      <div className="dt-menu-label">{t('Workspace')}</div>
      {choices.map(row => (
        <button
          key={row.workspace_id || 'general'}
          type="button"
          role="menuitem"
          aria-current={row.workspace_id === active ? 'page' : undefined}
          onClick={() => {
            onChoose?.()
            choose(row.workspace_id)
          }}
          className="dt-menu-item"
        >
          <WorkspaceGlyph name={row.display_name} general={!row.workspace_id} size={20} />
          <span className="min-w-0 flex-1 truncate">{row.display_name}</span>
          {row.workspace_id === active && <Check size={15} strokeWidth={2} className="shrink-0" />}
        </button>
      ))}
      <Link role="menuitem" href="/settings/workspace" prefetch={false} onClick={onChoose} className="dt-menu-item is-quiet">
        <Settings2 size={16} strokeWidth={1.6} />
        <span>{t('Manage workspaces')}</span>
      </Link>
    </>
  )
}

/**
 * The sidebar's header: which workspace this is, and the account-level
 * places (workspaces, settings, profile) that used to sit in the footer.
 */
export function WorkspaceMenu({
  accountSlot,
  onNavigate,
  compact = false,
}: {
  accountSlot?: ReactNode
  onNavigate?: () => void
  /** The collapsed rail's form: the workspace's mark alone, opening beside the rail. */
  compact?: boolean
}) {
  const { t } = useTranslation()
  const { active, currentName } = useWorkspaceChoices()
  const [open, setOpen] = useState(false)
  const rootRef = useMenuPopover<HTMLDivElement>(open, setOpen)
  const menuId = useId()
  const close = () => {
    setOpen(false)
    onNavigate?.()
  }
  return (
    <div ref={rootRef} className={`dt-workspace-menu ${compact ? 'is-rail' : ''}`}>
      {compact ? (
        <Tooltip label={currentName} description={t('Manage workspaces')} side="right" suppressed={open}>
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={menuId}
            aria-label={currentName}
            onClick={() => setOpen(value => !value)}
            className="dt-workspace-trigger"
          >
            <WorkspaceGlyph name={currentName} general={!active} />
          </button>
        </Tooltip>
      ) : (
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => setOpen(value => !value)}
          className="dt-workspace-trigger"
        >
          <WorkspaceGlyph name={currentName} general={!active} />
          <span className="min-w-0 flex-1 truncate text-left">{currentName}</span>
          <ChevronDown size={14} strokeWidth={1.8} className="shrink-0 opacity-60" />
        </button>
      )}
      {open && (
        <div id={menuId} role="menu" aria-label={t('Manage workspaces')} className="dt-popover dt-workspace-panel">
          <WorkspaceChoiceList onChoose={close} />
          <div className="dt-menu-divider" />
          <Link role="menuitem" href="/settings" prefetch={false} onClick={close} className="dt-menu-item">
            <Settings size={16} strokeWidth={1.6} />
            <span className="flex-1">{t('Settings')}</span>
          </Link>
          {accountSlot ? <div className="dt-menu-slot">{accountSlot}</div> : null}
          <div className="dt-menu-divider" />
          <div className="dt-menu-footer">
            <span>DeepTutor</span>
            <VersionBadge onNavigate={close} />
          </div>
        </div>
      )}
    </div>
  )
}
