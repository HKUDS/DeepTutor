'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import Image from 'next/image'
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Compass,
  FileText,
  Home,
  Users,
  Bot,
  Columns3,
  Library,
  MessageSquare,
  MoreHorizontal,
  PenLine,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Star,
  X,
  type LucideIcon,
} from 'lucide-react'
import AppShell, { useSidebarDrawer } from '@/components/layout/AppShell'
import { SidebarShell } from '@/components/sidebar/SidebarShell'
import { FeaturePage, PageHeader, pageActionClass } from '@/components/layout/FeaturePage'
import SpaceDashboard from '@/components/space/SpaceDashboard'
import { DASHBOARD_GROUPS } from '@/components/space/dashboard-groups'
import AgentsHub from '@/components/agents/AgentsHub'
import KanbanBoard from '@/features/tasks/components/KanbanBoard'
import { startTaskBoardSync } from '@/lib/task-board-store'
import { CategoryTabs, CategoryBody } from './PreviewNavigation'
import { useCollections, type Category, type LearningRecord } from './collections'
import {
  LearningOverview,
  CreateLearningPage,
  LearningRecordSurface,
  PartnerSurface,
  ResourceSurface,
  type PartnerModal,
} from './CollectionSurfaces'
import { LearningCardContent } from '@/components/learning/LearningCard'
import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from '@/components/chat/home/StandaloneComposer'
import { CHAT_CAPABILITIES } from '@/features/capabilities/presentation'
import CoWriterWorkspace from '@/features/co-writer/components/CoWriterWorkspace'
import { ReadingProvider, useReading } from '@/context/ReadingContext'
import { AnnotationList } from '@/components/reading/AnnotationList'
import { ReaderPane, READER_ASK_EVENT } from '@/components/reading/ReaderPane'
import { MasteryQuestionCard } from '@/components/chat/home/MasteryQuestionCard'
import MarkdownRenderer from '@/components/common/MarkdownRenderer'
import { Dialog } from '@/shared/ui/Dialog'
import Tooltip from '@/shared/ui/Tooltip'
import { useAppShell } from '@/context/AppShellContext'
import type { MasteryGradeResult } from '@/lib/mastery-question'
import type { JumpRequest } from '@/components/reading/PdfDocumentView'
import { material, objectives, previewItems, question, type PreviewView } from './fixtures'
import { readDemo, writeDemo } from './demo-transport'

const icons: Record<PreviewView, LucideIcon> = {
  home: Home,
  learning: Compass,
  'new-learning': Plus,
  library: Library,
  reading: BookOpen,
  writing: PenLine,
  mastery: Compass,
  chat: MessageSquare,
  partners: Users,
  kanban: Columns3,
  agents: Bot,
  resource: Library,
  record: BookOpen,
}
const titles: Record<PreviewView, string> = {
  home: '主页',
  learning: '我的学习',
  'new-learning': '新建学习',
  library: '资料',
  partners: '伙伴',
  kanban: '任务看板',
  agents: '智能体',
  resource: '资料',
  record: '学习记录',
  reading: material.title,
  writing: '我的研究计划',
  mastery: '线性代数，从直觉出发',
  chat: '与 Dito 对话',
}
const caps = CHAT_CAPABILITIES.filter(c =>
  ['', 'deep_solve', 'ask_questions', 'deep_research', 'visualize'].includes(c.value)
).map(c =>
  c.value === ''
    ? { ...c, label: 'Auto', description: '告诉 Dito 你的目标，由它选择合适的方式', icon: Sparkles }
    : c
)
type Message = {
  id: string
  role: 'user' | 'assistant'
  text: string
  target?: PreviewView
  targetLabel?: string
}
type Messages = Partial<Record<PreviewView, Message[]>>

function IconAction({
  label,
  icon: Icon,
  onClick,
  active,
}: {
  label: string
  icon: LucideIcon
  onClick: () => void
  active?: boolean
}) {
  return (
    <Tooltip label={label} side="bottom">
      <button
        type="button"
        aria-label={label}
        aria-pressed={active}
        onClick={onClick}
        className={`preview-icon ${active ? 'is-active' : ''}`}
      >
        <Icon size={16} strokeWidth={1.6} />
      </button>
    </Tooltip>
  )
}

function NavRow({
  icon: Icon,
  label,
  active,
  collapsed,
  onClick,
  trailing,
}: {
  icon: LucideIcon
  label: string
  active?: boolean
  collapsed?: boolean
  onClick: () => void
  trailing?: ReactNode
}) {
  const drawer = useSidebarDrawer()
  const row = (
    <button
      className={`preview-nav-row ${active ? 'is-active' : ''} ${collapsed ? 'is-collapsed' : ''}`}
      aria-current={active ? 'page' : undefined}
      aria-label={collapsed ? label : undefined}
      onClick={() => {
        onClick()
        drawer?.close()
      }}
    >
      <Icon size={17} strokeWidth={1.65} />
      {!collapsed && (
        <>
          <span>{label}</span>
          {trailing}
        </>
      )}
    </button>
  )
  return collapsed ? (
    <Tooltip label={label} side="right">
      {row}
    </Tooltip>
  ) : (
    row
  )
}

function ContentRow({
  item,
  onOpen,
}: {
  item: (typeof previewItems)[number]
  onOpen: (view: PreviewView) => void
}) {
  const Icon = icons[item.view]
  return (
    <button className="preview-content-row" onClick={() => onOpen(item.view)}>
      <LearningCardContent
        title={item.title}
        subtitle={item.detail}
        icon={<Icon size={20} strokeWidth={1.5} />}
        progress={item.progress}
      />
      <ChevronRight size={15} className="text-muted-foreground shrink-0" />
    </button>
  )
}

export default function PreviewWorkspace() {
  return (
    <ReadingProvider>
      <Workspace />
    </ReadingProvider>
  )
}

function Workspace() {
  useEffect(() => startTaskBoardSync({ stream: false }), [])
  const [view, setView] = useState<PreviewView>(() => {
    const hash = location.hash.slice(1).split('/')[0]
    return hash in titles ? (hash as PreviewView) : 'home'
  })
  const collections = useCollections()
  const [category, setCategory] = useState<Category>(() =>
    view === 'new-learning' ? 'learning' : readDemo('category', 'home')
  )
  const [activeRecord, setActiveRecord] = useState(
    () =>
      decodeURIComponent(location.hash.split('/')[1] || '') ||
      readDemo('active-record', 'attention')
  )
  const [activePartner, setActivePartner] = useState(() =>
    location.hash.startsWith('#partners/')
      ? decodeURIComponent(location.hash.slice(10))
      : readDemo('active-partner', '')
  )
  const [resourceHref, setResourceHref] = useState(() =>
    location.hash.startsWith('#resource/')
      ? decodeURIComponent(location.hash.slice(10))
      : readDemo('resource-href', '/notebooks')
  )
  const [partnerModal, setPartnerModal] = useState<PartnerModal>(null)
  useEffect(() => writeDemo('category', category), [category])
  useEffect(() => writeDemo('active-record', activeRecord), [activeRecord])
  useEffect(() => writeDemo('active-partner', activePartner), [activePartner])
  useEffect(() => writeDemo('resource-href', resourceHref), [resourceHref])
  const [assistantOpen, setAssistantOpen] = useState(() => location.hash.startsWith('#reading'))
  const [dialog, setDialog] = useState<'search' | 'settings' | 'about' | null>(null)
  const [query, setQuery] = useState('')
  const [favorites, setFavorites] = useState<string[]>(() =>
    readDemo('favorites', ['attention', 'research'])
  )
  const [messages, setMessages] = useState<Messages>(() => readDemo('messages', {}))
  const [pending, setPending] = useState<PreviewView | null>(null)
  const [mode, setMode] = useState('')
  const [quote, setQuote] = useState('')
  const [panelTab, setPanelTab] = useState<'dito' | 'annotations'>('dito')
  const [readingJump, setReadingJump] = useState<JumpRequest | null>(null)
  const [recentIds, setRecentIds] = useState<string[]>(() =>
    readDemo(
      'recent',
      previewItems.map(item => item.id)
    )
  )
  const [savedContent, setSavedContent] = useState(() => ({
    title: readDemo('document', { title: '我的研究计划' }).title,
    locator: readDemo('position', { locator: 1 }).locator,
  }))
  const [grade, setGrade] = useState<MasteryGradeResult | null>(() => readDemo('grade', null))
  const [objective, setObjective] = useState(2)
  const responseTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefillRef = useRef<((text: string) => void) | null>(null)
  const { theme, setTheme, setLanguage } = useAppShell()
  const { annotations, removeMark } = useReading()
  const go = useCallback((next: PreviewView, entity?: string) => {
    setPanelTab('dito')
    const item = previewItems.find(item => item.view === next)
    if (item) setRecentIds(ids => [item.id, ...ids.filter(id => id !== item.id)])
    setView(next)
    setCategory(
      ['learning', 'new-learning', 'reading', 'mastery', 'record'].includes(next)
        ? 'learning'
        : ['library', 'resource'].includes(next)
          ? 'library'
          : next === 'partners'
            ? 'partners'
            : 'home'
    )
    if (next === 'reading') setActiveRecord('attention')
    if (next === 'mastery') setActiveRecord('linear')
    location.hash = next + (entity ? '/' + encodeURIComponent(entity) : '')
    setDialog(null)
    setQuote('')
    setAssistantOpen(next === 'reading')
  }, [])

  useEffect(() => {
    setLanguage('zh')
    const onHash = () => {
      const [h, raw] = location.hash.slice(1).split('/')
      const entity = decodeURIComponent(raw || '')
      if (h in titles) {
        setView(h as PreviewView)
        if (h === 'new-learning') setCategory('learning')
        if (h === 'record' && entity) setActiveRecord(entity)
        if (h === 'partners') setActivePartner(entity)
        if (h === 'resource' && entity) setResourceHref(entity)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setDialog(d => (d === 'search' ? null : 'search'))
      }
    }
    const onAsk = (event: Event) => {
      const data = (event as CustomEvent<{ quote: string; prompt?: string }>).detail
      setPanelTab('dito')
      setQuote(data.quote)
      setAssistantOpen(true)
      if (data.prompt) requestAnimationFrame(() => prefillRef.current?.(data.prompt || ''))
    }
    const onData = (event: Event) => {
      if (!['document', 'position'].includes((event as CustomEvent<string>).detail)) return
      setSavedContent({
        title: readDemo('document', { title: '我的研究计划' }).title,
        locator: readDemo('position', { locator: 1 }).locator,
      })
    }
    window.addEventListener('dito-preview-data', onData)
    window.addEventListener('hashchange', onHash)
    window.addEventListener('keydown', onKey)
    window.addEventListener(READER_ASK_EVENT, onAsk)
    return () => {
      window.removeEventListener('dito-preview-data', onData)
      window.removeEventListener('hashchange', onHash)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(READER_ASK_EVENT, onAsk)
      if (responseTimer.current) clearTimeout(responseTimer.current)
    }
  }, [setLanguage])
  useEffect(() => writeDemo('messages', messages), [messages])
  useEffect(() => writeDemo('favorites', favorites), [favorites])
  useEffect(() => writeDemo('recent', recentIds), [recentIds])
  useEffect(() => writeDemo('grade', grade), [grade])

  const cancel = () => {
    if (responseTimer.current) clearTimeout(responseTimer.current)
    setPending(null)
  }
  function send(submission: StandaloneComposerSubmission, from = view) {
    if (pending) return
    const content = submission.content.trim()
    if (!content && !submission.attachments.length) return
    const context = from === 'home' ? 'chat' : from
    const userText = `${quote ? `> ${quote}\n\n` : ''}${content}${submission.attachments.length ? `\n\n（已附 ${submission.attachments.length} 个文件；预览不解析附件）` : ''}`
    setMessages(m => ({
      ...m,
      [context]: [...(m[context] || []), { id: crypto.randomUUID(), role: 'user', text: userText }],
    }))
    setQuote('')
    setPending(context)
    if (from === 'home') go('chat')
    const selectedMode = mode
    responseTimer.current = setTimeout(() => {
      let text =
        '我们可以从一个具体问题开始。比如读懂一份材料、解释一个概念，或把一个想法整理成文稿。下面是可以继续体验的学习材料。'
      let target: PreviewView = 'reading'
      let targetLabel = '打开注意力机制笔记'
      if (from === 'reading' || /注意力|transformer|attention/i.test(content)) {
        text =
          '理解注意力，可以先记住三步：**匹配、归一化、汇总**。\n\nQuery 表达当前词需要什么，Key 表达其他词能提供什么。两者点积得到匹配分数，经过 softmax 变成权重，再对 Value 加权求和。\n\n缩放因子 $\\sqrt{d_k}$ 用来控制点积分数的波动，避免 softmax 过度集中。\n\n试着用一句话解释：为什么 Key 与 Value 要分开？'
      } else if (from === 'writing' || /写|文稿|研究计划/.test(content)) {
        text =
          '可以把研究计划按 **问题 → 假设 → 验证 → 下一步** 组织。\n\n先写清楚想解决的学习困难，再给出一个能验证的假设。最后列出本周能完成的最小实验，避免文稿只有方向、没有行动。\n\n已准备好一份示例文稿，你可以直接进入 Co-Writer 修改。'
        target = 'writing'
        targetLabel = '在 Co-Writer 中打开'
      } else if (from === 'mastery' || /练习|学习计划|线性|复习/.test(content)) {
        text =
          '我们从你已经掌握的向量和矩阵出发，继续理解 **线性无关与基**。\n\n一组基需要满足两点：能组合出空间里的所有向量，并且其中没有多余的向量。先做一道判断题，再根据答案决定下一步。'
        target = 'mastery'
        targetLabel = '开始这道练习'
      }
      if (selectedMode)
        text = `已手动选择「${caps.find(c => c.value === selectedMode)?.label}」。以下为流程示例，未执行模型调用。\n\n${text}`
      setMessages(m => ({
        ...m,
        [context]: [
          ...(m[context] || []),
          { id: crypto.randomUUID(), role: 'assistant', text, target, targetLabel },
        ],
      }))
      setPending(null)
    }, 650)
  }

  const items = previewItems.map(item =>
    item.view === 'writing'
      ? { ...item, title: savedContent.title }
      : item.view === 'reading'
        ? {
            ...item,
            progress: savedContent.locator / 3,
            detail: `机器学习 · 第 ${savedContent.locator} / 3 节`,
          }
        : item.view === 'mastery'
          ? {
              ...item,
              progress: grade?.isCorrect ? 0.5 : 1 / 3,
              detail: `6 个学习目标 · 已完成 ${grade?.isCorrect ? 3 : 2} 个`,
            }
          : {
              ...item,
              title:
                messages.chat
                  ?.find(message => message.role === 'user')
                  ?.text.split('\n')[0]
                  .slice(0, 32) || item.title,
            }
  )
  const currentItem = items.find(i => i.view === view)
  const currentRecord = collections.learning.find(r => r.id === activeRecord)
  const currentTitle =
    view === 'record'
      ? currentRecord?.title || '学习记录'
      : view === 'resource'
        ? DASHBOARD_GROUPS.flatMap(g => g.items).find(i => i.href === resourceHref)?.title.zh ||
          '资料'
        : currentItem?.title || titles[view]
  const openRecord = (record: LearningRecord) => {
    setActiveRecord(record.id)
    go(
      record.sample && (record.kind === 'reading' || record.kind === 'mastery')
        ? record.kind
        : 'record',
      record.id
    )
  }
  const openPartner = (id: string) => {
    setActivePartner(id)
    go('partners', id)
  }
  const openResource = (href: string) => {
    setResourceHref(href)
    go('resource', href)
  }
  const isActivity = ['reading', 'writing', 'mastery'].includes(view)
  const star = () => {
    if (currentItem)
      setFavorites(f =>
        f.includes(currentItem.id) ? f.filter(id => id !== currentItem.id) : [...f, currentItem.id]
      )
  }
  const newChat = () => {
    cancel()
    setMessages(m => ({ ...m, chat: [] }))
    go('chat')
  }
  const composer = (context: PreviewView, hasMessages = false) => (
    <StandaloneComposer
      onSubmit={s => send(s, context)}
      onCancelStreaming={cancel}
      isStreaming={pending !== null}
      hasMessages={hasMessages}
      inputPlaceholder={
        context === 'home'
          ? '告诉 Dito，你今天想学什么、读什么，或完成什么…'
          : '问 Dito，或让它帮你继续…'
      }
      capabilities={caps}
      activeCapValue={mode}
      onSelectCapability={setMode}
      agentsAvailable={false}
      prefillInputRef={prefillRef}
      inputHeader={
        quote ? (
          <div className="preview-quote">
            <span>{quote}</span>
            <button aria-label="移除引用" onClick={() => setQuote('')}>
              <X size={13} />
            </button>
          </div>
        ) : undefined
      }
    />
  )
  const conversation = (context: PreviewView) => (
    <Conversation
      messages={messages[context] || []}
      pending={pending === context}
      context={context}
      onOpen={go}
      onPrompt={text =>
        send(
          {
            content: text,
            attachments: [],
            knowledgeBases: [],
            notebookReferences: [],
            historyReferences: [],
            bookReferences: [],
            questionNotebookReferences: [],
            memoryReferences: [],
            persona: null,
            llmSelection: null,
            subagentBudget: null,
          },
          context
        )
      }
    />
  )

  return (
    <div className="dito-preview">
      <AppShell
        homeHref="/preview#home"
        sidebar={
          <SidebarShell
            brandHref="/preview#home"
            initialWidth={272}
            widthStorageKey="deeptutor.dito-preview.sidebar-width"
            homeSlot={collapsed => (
              <CategoryTabs
                category={category}
                collapsed={collapsed}
                onChange={next => {
                  setCategory(next)
                  if (collapsed) go(next)
                }}
                onSearch={() => {
                  setQuery('')
                  setDialog('search')
                }}
              />
            )}
            bodySlot={collapsed => (
              <CategoryBody
                category={category}
                collapsed={collapsed}
                view={view}
                collections={collections}
                activeRecord={activeRecord}
                activePartner={activePartner}
                resourceHref={resourceHref}
                onGo={go}
                onRecord={openRecord}
                onCreate={() => go('new-learning')}
                onPartner={openPartner}
                onNewPartner={() => {
                  openPartner('')
                  setPartnerModal('partner')
                }}
                onNewGroup={() => {
                  openPartner('')
                  setPartnerModal('group')
                }}
                onResource={openResource}
              />
            )}
            footerOverride={collapsed => (
              <div className="preview-sidebar-footer">
                <NavRow
                  icon={Settings2}
                  label="偏好设置"
                  collapsed={collapsed}
                  onClick={() => setDialog('settings')}
                />
                <button
                  aria-label="新对话"
                  className={`preview-new-chat ${collapsed ? 'is-collapsed' : ''}`}
                  onClick={newChat}
                >
                  <Sparkles size={16} />
                  {!collapsed && (
                    <>
                      <span>找 Dito 聊聊</span>
                      <Plus size={15} />
                    </>
                  )}
                </button>
              </div>
            )}
          />
        }
      >
        <div className="preview-layout">
          <header className="preview-topbar">
            <div className="preview-breadcrumb">
              <button onClick={() => go('home')}>个人空间</button>
              <ChevronRight size={12} />
              <span>{currentTitle}</span>
            </div>
            <div className="preview-top-actions">
              <button className="preview-badge" onClick={() => setDialog('about')}>
                交互预览
              </button>
              {currentItem && (
                <IconAction
                  label={favorites.includes(currentItem.id) ? '取消收藏' : '收藏此页'}
                  icon={Star}
                  onClick={star}
                  active={favorites.includes(currentItem.id)}
                />
              )}
              <IconAction
                label="预览说明"
                icon={MoreHorizontal}
                onClick={() => setDialog('about')}
              />
              {isActivity && (
                <button
                  className={`preview-dito-toggle ${assistantOpen ? 'is-active' : ''}`}
                  onClick={() => setAssistantOpen(v => !v)}
                  aria-pressed={assistantOpen}
                >
                  <Sparkles size={14} />
                  Dito
                </button>
              )}
            </div>
          </header>
          <div className="preview-work-area">
            <div className="preview-main">
              {view === 'home' && (
                <FeaturePage className="preview-home">
                  <div className="preview-home-inner">
                    <div className="preview-eyebrow">你的学习，从这里继续</div>
                    <PageHeader title="你好，Frank" description="今天有什么想弄明白的？" />
                    <div className="preview-home-composer">{composer('home')}</div>
                    <div className="preview-quick-actions">
                      {[
                        { label: '任务看板', icon: Columns3, view: 'kanban' },
                        { label: '智能写作', icon: PenLine, view: 'writing' },
                        { label: '智能体', icon: Bot, view: 'agents' },
                      ].map(a => (
                        <button key={a.label} onClick={() => go(a.view as PreviewView)}>
                          <a.icon size={15} />
                          {a.label}
                          <ArrowRight size={12} />
                        </button>
                      ))}
                    </div>
                    <section className="preview-section">
                      <div className="preview-section-title">
                        <h2>继续上次的学习</h2>
                        <button onClick={() => go('learning')}>
                          查看全部
                          <ArrowRight size={13} />
                        </button>
                      </div>
                      <div className="preview-resume-list">
                        {items.slice(0, 3).map(item => (
                          <ContentRow key={item.id} item={item} onOpen={go} />
                        ))}
                      </div>
                    </section>
                    <section className="preview-review">
                      <div className="preview-review-icon">
                        <Compass size={22} strokeWidth={1.4} />
                      </div>
                      <div>
                        <h3>{grade?.isCorrect ? '今天的复习已完成' : '花几分钟，让理解更扎实'}</h3>
                        <p>
                          {grade?.isCorrect
                            ? '线性无关与基 · 已掌握这道练习'
                            : '线性无关与基 · 1 道待复习练习'}
                        </p>
                      </div>
                      <button
                        className={pageActionClass('secondary')}
                        onClick={() => go('mastery')}
                      >
                        {grade?.isCorrect ? '查看练习' : '开始复习'}
                        <ArrowRight size={14} />
                      </button>
                    </section>
                    <p className="preview-home-footnote">
                      Dito 会陪你阅读、思考和创作。你也可以随时自己选择学习方式。
                    </p>
                  </div>
                </FeaturePage>
              )}
              {view === 'learning' && (
                <LearningOverview collections={collections} onOpen={openRecord} />
              )}
              {view === 'new-learning' && (
                <CreateLearningPage
                  onBack={() => go('learning')}
                  onCreate={record => {
                    collections.setLearning(all => [record, ...all])
                    openRecord(record)
                  }}
                />
              )}
              {view === 'library' && (
                <FeaturePage>
                  <SpaceDashboard
                    title="资料"
                    description="原来的学习空间。对话、笔记、知识与能力资源，集中在这里。"
                    onNavigate={openResource}
                  />
                </FeaturePage>
              )}
              {view === 'resource' && (
                <ResourceSurface
                  key={resourceHref}
                  href={resourceHref}
                  onBack={() => go('library')}
                />
              )}
              {view === 'kanban' && <KanbanBoard />}
              {view === 'agents' && (
                <FeaturePage>
                  <AgentsHub />
                </FeaturePage>
              )}
              {view === 'partners' && (
                <PartnerSurface
                  collections={collections}
                  selected={activePartner}
                  onSelect={openPartner}
                  modal={partnerModal}
                  setModal={setPartnerModal}
                />
              )}
              {view === 'record' && currentRecord && (
                <LearningRecordSurface
                  key={currentRecord.id}
                  record={currentRecord}
                  onBack={() => go('learning')}
                  onChange={record =>
                    collections.setLearning(all => all.map(r => (r.id === record.id ? record : r)))
                  }
                />
              )}
              {view === 'reading' && (
                <ReadingSurface onClose={() => go('learning')} externalJump={readingJump} />
              )}
              {view === 'writing' && (
                <CoWriterWorkspace docId="preview-research" onBack={() => go('home')} />
              )}
              {view === 'mastery' && (
                <FeaturePage className="preview-mastery">
                  <PageHeader title="线性代数，从直觉出发" description="先建立直觉，再验证理解。" />
                  <div className="preview-mastery-layout">
                    <nav aria-label="学习目标" className="preview-objectives">
                      <div className="preview-nav-label">
                        学习目标 · {grade?.isCorrect ? 3 : 2} / 6
                      </div>
                      {objectives.map((name, i) => (
                        <button
                          key={name}
                          className={objective === i ? 'is-active' : ''}
                          onClick={() => setObjective(i)}
                        >
                          <span>
                            {i < 2 || (i === 2 && grade?.isCorrect) ? (
                              <Check size={12} />
                            ) : (
                              String(i + 1).padStart(2, '0')
                            )}
                          </span>
                          {name}
                        </button>
                      ))}
                    </nav>
                    <div className="preview-lesson">
                      <div className="preview-eyebrow">
                        当前目标 {String(objective + 1).padStart(2, '0')}
                      </div>
                      <h2>{objectives[objective]}</h2>
                      {objective === 2 ? (
                        <>
                          <p className="preview-lesson-intro">
                            想象你要在平面上描述一个位置。两个方向互不重复的向量，就能通过缩放和相加，到达平面上的任意一点。这样的两个向量构成一组基。
                          </p>
                          <MasteryQuestionCard
                            question={question}
                            grade={grade}
                            answered={grade !== null}
                            submittedAnswer={grade?.learnerAnswer || ''}
                            onSubmit={p => {
                              const answer = p.answers?.[0]?.text || p.text || ''
                              setGrade({
                                questionId: question.questionId,
                                learnerAnswer: answer,
                                isCorrect: answer === 'B',
                                correctLabel: 'B',
                                correctBody: '(1, 0) 和 (0, 1)',
                                explanation:
                                  '这两个向量线性无关，且可以组合出二维平面中的任意向量。A 的两个向量共线，C 包含零向量，都不能张成整个平面。',
                                result: answer === 'B' ? 'correct' : 'incorrect',
                              })
                              return true
                            }}
                          />
                          {grade && (
                            <div className="preview-lesson-next">
                              <button
                                className={pageActionClass('secondary')}
                                onClick={() => setGrade(null)}
                              >
                                再试一次
                              </button>
                              <button className={pageActionClass()} onClick={() => setObjective(3)}>
                                下一目标
                                <ArrowRight size={14} />
                              </button>
                            </div>
                          )}
                        </>
                      ) : (
                        <>
                          <p className="preview-lesson-intro">
                            {
                              [
                                '把向量看成一个方向和一段距离。通过缩放与相加，我们可以组合出新的向量。',
                                '一个矩阵描述了空间如何变换。它的每一列，都告诉你一个基向量被送到了哪里。',
                                '',
                                '有些向量经过变换后方向保持不变，它们就是特征向量。对应的缩放倍数就是特征值。',
                                '正交投影把一个向量分成沿着某个方向的部分，以及与这个方向垂直的部分。',
                                '从一个实际数据问题开始，观察矩阵如何表达关系，投影如何简化信息。',
                              ][objective]
                            }
                          </p>
                          <button
                            className={pageActionClass('secondary')}
                            onClick={() => setAssistantOpen(true)}
                          >
                            <Sparkles size={14} />让 Dito 帮我理解
                          </button>
                          {objective !== 2 && (
                            <button
                              className="ml-3 text-sm underline underline-offset-4"
                              onClick={() => setObjective(2)}
                            >
                              回到练习
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </FeaturePage>
              )}
              {view === 'chat' && (
                <div className="preview-chat-page">
                  <div className="preview-chat-heading">
                    <Sparkles size={17} />
                    <h1>Dito</h1>
                    <span>你的通用学习助手</span>
                    <button onClick={newChat} aria-label="清空并开始新对话">
                      <Plus size={16} />
                    </button>
                  </div>
                  {conversation('chat')}
                  <div className="preview-chat-composer">
                    {composer('chat', !!messages.chat?.length)}
                    <p>示例对话 · 未连接模型</p>
                  </div>
                </div>
              )}
            </div>
            {isActivity && assistantOpen && (
              <aside className="preview-assistant" aria-label="Dito 学习助手">
                <header>
                  <Sparkles size={16} />
                  <button
                    className={panelTab === 'dito' ? 'font-semibold' : 'text-muted-foreground'}
                    onClick={() => setPanelTab('dito')}
                  >
                    Dito
                  </button>
                  {view === 'reading' && (
                    <button
                      className={
                        panelTab === 'annotations' ? 'font-semibold' : 'text-muted-foreground'
                      }
                      onClick={() => setPanelTab('annotations')}
                    >
                      批注 {annotations.length || ''}
                    </button>
                  )}
                  <span />
                  <IconAction icon={X} label="关闭 Dito" onClick={() => setAssistantOpen(false)} />
                </header>
                <div className="preview-context-chip">
                  <FileText size={13} />
                  <span>{currentTitle}</span>
                  <span>当前内容</span>
                </div>
                {panelTab === 'annotations' && view === 'reading' ? (
                  <div className="min-h-0 flex-1 mt-3">
                    <AnnotationList
                      annotations={annotations}
                      unit="section"
                      activeId={null}
                      onSelect={mark =>
                        setReadingJump({
                          locator: mark.locator,
                          quote: mark.quote,
                          nonce: Date.now(),
                        })
                      }
                      onDelete={mark => {
                        void removeMark(mark)
                      }}
                    />
                  </div>
                ) : (
                  <>
                    {conversation(view)}
                    <div className="preview-panel-composer">
                      {composer(view, true)}
                      <p>示例对话 · 未连接模型</p>
                    </div>
                  </>
                )}
              </aside>
            )}
          </div>
        </div>
      </AppShell>
      <Dialog
        open={dialog === 'search'}
        title="搜索你的空间"
        onClose={() => setDialog(null)}
        closeLabel="关闭搜索"
      >
        <div className="preview-search-field large">
          <Search size={18} />
          <input
            data-autofocus
            aria-label="搜索内容"
            placeholder="搜索材料、文稿、学习路径…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <kbd>Esc</kbd>
        </div>
        <div className="preview-search-results">
          {collections.learning
            .filter(r => r.title.includes(query) || r.kind.includes(query))
            .map(r => (
              <button key={r.id} className="preview-session-row" onClick={() => openRecord(r)}>
                <BookOpen size={17} />
                <span>{r.title}</span>
                <ArrowRight size={14} />
              </button>
            ))}
          {items
            .filter(i => ['writing', 'chat'].includes(i.view))
            .filter(
              i => i.title.toLowerCase().includes(query.toLowerCase()) || i.kind.includes(query)
            )
            .map(item => (
              <ContentRow key={item.id} item={item} onOpen={go} />
            ))}
          {!collections.learning.some(r => r.title.includes(query)) &&
            !items.some(
              i => i.title.toLowerCase().includes(query.toLowerCase()) || i.kind.includes(query)
            ) && <p>没有匹配内容</p>}
        </div>
      </Dialog>
      <Dialog
        open={dialog === 'settings'}
        title="偏好设置"
        description="沿用 DeepTutor 现有的主题与侧栏设置。"
        onClose={() => setDialog(null)}
        closeLabel="关闭"
      >
        <h3 className="text-sm mb-3">外观</h3>
        <div className="preview-theme-options">
          {[
            { value: 'snow', label: '简白' },
            { value: 'light', label: '暖纸' },
            { value: 'dark', label: '深色' },
          ].map(item => (
            <button
              aria-pressed={theme === item.value}
              key={item.value}
              onClick={() => setTheme(item.value as typeof theme)}
              className={theme === item.value ? 'is-active' : ''}
            >
              {item.label}
              {theme === item.value && <Check size={14} />}
            </button>
          ))}
        </div>
        <p className="mt-6 text-xs text-muted-foreground leading-6">
          侧栏支持拖动调整宽度、收起与展开。搜索快捷键为 ⌘ / Ctrl
          K。文稿、阅读位置、批注、收藏和示例对话保存在当前浏览器。
        </p>
      </Dialog>
      <Dialog
        open={dialog === 'about'}
        title="这一版在探索什么"
        onClose={() => setDialog(null)}
        closeLabel="关闭"
      >
        <div className="preview-about">
          <p>四个栏目：主页、伙伴、学习、资料。</p>
          <p>
            顶部切换侧栏内容，保留当前正在看的页面。主页放
            Dito、任务看板、智能写作和智能体；伙伴放配置、群组和会话；学习保留四种学习记录；资料继承学习空间。
          </p>
          <p>
            这一版直接复用现有 WebUI
            的侧栏外壳、页面布局、输入框、沉浸式阅读器、Co-Writer、任务看板、智能体页面、学习空间总览、练习题卡和弹窗。
          </p>
          <p className="text-muted-foreground">
            这是独立 worktree 中的前端预览。内容是示例，Dito
            使用固定演示回复；编辑、阅读、批注和练习可交互。新建学习保存为草稿，资源详情是分类交互示例。模型调用、外部渠道、文件解析和
            Word 导出尚未连接。
          </p>
        </div>
      </Dialog>
    </div>
  )
}

function Conversation({
  messages,
  pending,
  context,
  onOpen,
  onPrompt,
}: {
  messages: Message[]
  pending: boolean
  context: PreviewView
  onOpen: (view: PreviewView) => void
  onPrompt: (text: string) => void
}) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, pending])
  const suggestions =
    context === 'reading'
      ? ['解释一下注意力机制', '帮我梳理这份材料']
      : context === 'writing'
        ? ['帮我完善研究计划', '这份文稿可以怎么组织？']
        : context === 'mastery'
          ? ['用直觉解释线性无关', '我想复习一下']
          : ['带我读懂注意力机制', '帮我写一份研究计划', '我想复习线性代数']
  return (
    <div className="preview-conversation">
      {!messages.length && (
        <div className="preview-conversation-empty">
          <Image src="/logo.png" alt="" width={38} height={38} />
          <h2>{context === 'chat' ? '想从哪里开始？' : '我就在这里'}</h2>
          <p>
            {context === 'chat'
              ? '提一个问题，或告诉我你想完成什么。'
              : '围绕当前内容提问，或一起找找下一步。'}
          </p>
          <div>
            {suggestions.map(prompt => (
              <button key={prompt} onClick={() => onPrompt(prompt)}>
                {prompt}
                <ArrowRight size={13} />
              </button>
            ))}
          </div>
        </div>
      )}
      {messages.map(message => (
        <div key={message.id} className={`preview-message ${message.role}`}>
          <div className="preview-message-label">
            {message.role === 'assistant' ? (
              <>
                <Sparkles size={13} />
                Dito<span>示例回复</span>
              </>
            ) : (
              '你'
            )}
          </div>
          <MarkdownRenderer content={message.text} />
          {message.target && context !== message.target && (
            <button className="preview-result-link" onClick={() => onOpen(message.target!)}>
              <FileText size={17} />
              <span>{message.targetLabel}</span>
              <ArrowRight size={15} />
            </button>
          )}
        </div>
      ))}
      {pending && (
        <div className="preview-thinking" role="status">
          <span />
          Dito 正在整理示例…
        </div>
      )}
      <div ref={end} />
    </div>
  )
}

function ReadingSurface({
  onClose,
  externalJump,
}: {
  onClose: () => void
  externalJump: JumpRequest | null
}) {
  const { openMaterial } = useReading()
  const [jump, setJump] = useState<JumpRequest | null>(() => ({
    locator: readDemo('position', { locator: 1 }).locator,
    nonce: Date.now(),
  }))
  const [locator, setLocator] = useState(() => readDemo('position', { locator: 1 }).locator)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let alive = true
    void openMaterial(material).then(() => {
      if (alive) setReady(true)
    })
    return () => {
      alive = false
    }
  }, [openMaterial])
  return (
    <div className="preview-reading-surface">
      <div className="preview-reading-outline">
        <div className="preview-nav-label">目录</div>
        {material.outline.map(row => (
          <button
            key={row.locator}
            className={locator === row.locator ? 'is-active' : ''}
            onClick={() => setJump({ locator: row.locator, nonce: Date.now() })}
          >
            <span>0{row.locator}</span>
            {row.title}
          </button>
        ))}
      </div>
      <div className="preview-reader">
        {ready ? (
          <ReaderPane
            onClose={onClose}
            ownAnnotationList={false}
            externalJump={
              externalJump && externalJump.nonce > (jump?.nonce || 0) ? externalJump : jump
            }
            onLocatorChange={setLocator}
          />
        ) : (
          <div role="status" className="p-8 text-sm text-muted-foreground">
            正在打开阅读材料…
          </div>
        )}
      </div>
    </div>
  )
}
