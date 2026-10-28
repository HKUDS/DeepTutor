'use client'
import { useId, type ReactNode } from 'react'
import { m, useReducedMotion } from 'framer-motion'
import {
  Home,
  MessageCircle,
  BookOpen,
  Library,
  Search,
  Plus,
  LayoutGrid,
  Columns3,
  PenLine,
  Bot,
  ChevronRight,
  Users,
  type LucideIcon,
} from 'lucide-react'
import Tooltip from '@/shared/ui/Tooltip'
import PartnerAvatar from '@/components/partners/PartnerAvatar'
import { useSidebarDrawer } from '@/components/layout/AppShell'
import { DASHBOARD_GROUPS } from '@/components/space/dashboard-groups'
import { learningKinds, type Category, type Collections, type LearningRecord } from './collections'
import type { PreviewView } from './fixtures'

const categories = [
  { id: 'home', label: '主页', icon: Home },
  { id: 'partners', label: '伙伴', icon: MessageCircle },
  { id: 'learning', label: '学习', icon: BookOpen },
  { id: 'library', label: '资料', icon: Library },
] as const
export function CategoryTabs({
  category,
  collapsed,
  onChange,
  onSearch,
}: {
  category: Category
  collapsed: boolean
  onChange: (c: Category) => void
  onSearch: () => void
}) {
  const reduce = useReducedMotion()
  const id = useId()
  return (
    <div className={`preview-category-bar ${collapsed ? 'is-collapsed' : ''}`}>
      <div
        role="tablist"
        aria-label="主要栏目"
        aria-orientation={collapsed ? 'vertical' : 'horizontal'}
      >
        {categories.map((item, index) => (
          <Tooltip key={item.id} label={item.label} side="bottom">
            <button
              role="tab"
              aria-label={item.label}
              aria-selected={category === item.id}
              aria-controls="preview-category-content"
              tabIndex={category === item.id ? 0 : -1}
              onKeyDown={event => {
                const delta =
                  event.key === 'ArrowRight' || event.key === 'ArrowDown'
                    ? 1
                    : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
                      ? -1
                      : 0
                if (!delta && event.key !== 'Home' && event.key !== 'End') return
                event.preventDefault()
                const next =
                  event.key === 'Home' ? 0 : event.key === 'End' ? 3 : (index + delta + 4) % 4
                onChange(categories[next].id)
                const buttons = event.currentTarget
                  .closest('[role=tablist]')
                  ?.querySelectorAll<HTMLButtonElement>('[role=tab]')
                buttons?.[next].focus()
              }}
              onClick={() => onChange(item.id)}
              className={category === item.id ? 'is-active' : ''}
            >
              {category === item.id && (
                <m.span
                  layoutId={`category-pill-${id}`}
                  className="preview-category-pill"
                  transition={{ duration: reduce ? 0 : 0.22, ease: [0.22, 1, 0.36, 1] }}
                />
              )}
              <item.icon size={20} strokeWidth={1.65} />
              <span
                className="preview-category-name"
                style={{
                  maxWidth: category === item.id && !collapsed ? 36 : 0,
                  opacity: category === item.id && !collapsed ? 1 : 0,
                }}
              >
                {item.label}
              </span>
            </button>
          </Tooltip>
        ))}
      </div>
      <Tooltip label="搜索 · ⌘ K" side="bottom">
        <button className="preview-category-search" aria-label="搜索" onClick={onSearch}>
          <Search size={20} strokeWidth={1.65} />
        </button>
      </Tooltip>
    </div>
  )
}
export function SidebarRow({
  icon: Icon,
  label,
  active,
  onClick,
  trailing,
}: {
  icon: LucideIcon
  label: string
  active?: boolean
  onClick: () => void
  trailing?: ReactNode
}) {
  const drawer = useSidebarDrawer()
  return (
    <button
      className={`preview-nav-row ${active ? 'is-active' : ''}`}
      aria-current={active ? 'page' : undefined}
      onClick={() => {
        onClick()
        drawer?.close()
      }}
    >
      <Icon size={18} strokeWidth={1.6} />
      <span>{label}</span>
      {trailing}
    </button>
  )
}
function SectionLabel({
  label,
  action,
  onAction,
}: {
  label: string
  action?: string
  onAction?: () => void
}) {
  return (
    <div className="preview-sidebar-section-label">
      <span>{label}</span>
      {onAction && (
        <Tooltip label={action || '新建'}>
          <button aria-label={action || '新建'} onClick={onAction}>
            <Plus size={17} />
          </button>
        </Tooltip>
      )}
    </div>
  )
}
export function CategoryBody({
  category,
  collapsed,
  view,
  collections,
  activeRecord,
  activePartner,
  resourceHref,
  onGo,
  onRecord,
  onCreate,
  onPartner,
  onNewPartner,
  onNewGroup,
  onResource,
}: {
  category: Category
  collapsed: boolean
  view: PreviewView
  collections: Collections
  activeRecord: string
  activePartner: string
  resourceHref: string
  onGo: (v: PreviewView) => void
  onRecord: (r: LearningRecord) => void
  onCreate: () => void
  onPartner: (id: string) => void
  onNewPartner: () => void
  onNewGroup: () => void
  onResource: (href: string) => void
}) {
  const drawer = useSidebarDrawer()
  const create = () => {
    onCreate()
    drawer?.close()
  }
  const createPartner = () => {
    onNewPartner()
    drawer?.close()
  }
  const createGroup = () => {
    onNewGroup()
    drawer?.close()
  }
  const selectPartner = (id: string) => {
    onPartner(id)
    drawer?.close()
  }
  if (collapsed) return null
  return (
    <div
      key={category}
      id="preview-category-content"
      role="tabpanel"
      aria-label={`${categories.find(c => c.id === category)?.label}栏目`}
      className="preview-category-content"
    >
      {category === 'home' && (
        <>
          <SectionLabel label="我的空间" />
          <SidebarRow
            icon={Home}
            label="主页"
            active={view === 'home'}
            onClick={() => onGo('home')}
          />
          <SidebarRow
            icon={Columns3}
            label="任务看板"
            active={view === 'kanban'}
            onClick={() => onGo('kanban')}
          />
          <SidebarRow
            icon={PenLine}
            label="智能写作"
            active={view === 'writing'}
            onClick={() => onGo('writing')}
          />
          <SidebarRow
            icon={Bot}
            label="智能体"
            active={view === 'agents'}
            onClick={() => onGo('agents')}
          />
          <SectionLabel label="最近对话" />
          <SidebarRow
            icon={MessageCircle}
            label="与 Dito 对话"
            active={view === 'chat'}
            onClick={() => onGo('chat')}
          />
        </>
      )}
      {category === 'partners' && (
        <>
          <SectionLabel label="我的伙伴" action="新建伙伴" onAction={createPartner} />
          <div className="preview-partner-roster">
            {collections.partners.map(p => (
              <button
                key={p.id}
                aria-label={`打开伙伴 ${p.name}`}
                className={activePartner === p.id && view === 'partners' ? 'is-active' : ''}
                onClick={() => selectPartner(p.id)}
              >
                <PartnerAvatar name={p.name} color={p.color} size={45} />
                <span>{p.name}</span>
              </button>
            ))}
            <button onClick={createPartner} aria-label="添加伙伴">
              <span className="preview-add-avatar">
                <Plus size={23} strokeWidth={1.5} />
              </span>
              <span>新伙伴</span>
            </button>
          </div>
          <SidebarRow
            icon={LayoutGrid}
            label="所有伙伴"
            onClick={() => onPartner('')}
            active={view === 'partners' && !activePartner}
          />
          <SectionLabel label="群组" action="新建群组" onAction={createGroup} />
          {collections.groups.map(g => (
            <SidebarRow
              key={g.id}
              icon={Users}
              label={g.name}
              active={view === 'partners' && activePartner === g.id}
              onClick={() => onPartner(g.id)}
              trailing={<small>{g.members.length}</small>}
            />
          ))}
          <SectionLabel label="最近会话" />
          {collections.sessions.map(s => (
            <SidebarRow
              key={s.id}
              icon={MessageCircle}
              label={s.title}
              active={view === 'partners' && activePartner === s.id}
              onClick={() => onPartner(s.id)}
            />
          ))}
        </>
      )}
      {category === 'learning' && (
        <>
          <SidebarRow
            icon={Plus}
            label="新建学习"
            active={view === 'new-learning'}
            onClick={create}
          />
          <SidebarRow
            icon={LayoutGrid}
            label="所有学习"
            onClick={() => onGo('learning')}
            active={view === 'learning'}
          />
          <SectionLabel label="我的学习记录" />
          {collections.learning.map(r => (
            <SidebarRow
              key={r.id}
              icon={learningKinds.find(k => k.id === r.kind)!.icon}
              label={r.title}
              active={activeRecord === r.id && ['record', 'reading', 'mastery'].includes(view)}
              onClick={() => onRecord(r)}
            />
          ))}
        </>
      )}
      {category === 'library' && (
        <>
          <SectionLabel label="学习空间" />
          <SidebarRow
            icon={LayoutGrid}
            label="资料总览"
            active={view === 'library'}
            onClick={() => onGo('library')}
          />
          {DASHBOARD_GROUPS.filter(g => g.items.some(i => !i.requiresCapability)).map(g => (
            <div key={g.label.zh}>
              <SectionLabel label={g.label.zh} />
              {g.items
                .filter(i => !i.requiresCapability)
                .map(item => (
                  <SidebarRow
                    key={item.key}
                    icon={item.icon}
                    label={item.title.zh}
                    active={view === 'resource' && resourceHref === item.href}
                    onClick={() => onResource(item.href)}
                    trailing={<ChevronRight className="preview-row-reveal" size={13} />}
                  />
                ))}
            </div>
          ))}
        </>
      )}
    </div>
  )
}
