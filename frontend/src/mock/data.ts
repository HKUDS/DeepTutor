/* ---------------- Mock Data ---------------- */

export type TaskStatus = 'todo' | 'active' | 'done' | 'blocked'

export interface TaskNode {
  id: string
  label: string
  status: TaskStatus
  children?: TaskNode[]
}

export const taskTree: TaskNode[] = [
  {
    id: 't-askora',
    label: 'Askora',
    status: 'active',
    children: [
      {
        id: 't-ui-redesign',
        label: 'UI Redesign',
        status: 'active',
        children: [
          { id: 't-audit-ui',   label: 'Audit current interface',  status: 'done' },
          { id: 't-tokens',     label: 'Build design tokens',      status: 'active' },
          { id: 't-composer',   label: 'Composer redesign',        status: 'todo' },
        ],
      },
      {
        id: 't-teaching',
        label: 'Teaching System',
        status: 'todo',
        children: [
          { id: 't-learner',    label: 'Learner Model',            status: 'todo' },
          { id: 't-policy',     label: 'Teaching Policy',          status: 'todo' },
        ],
      },
      {
        id: 't-quality',
        label: 'Quality',
        status: 'todo',
        children: [
          { id: 't-regression', label: 'UI regression',            status: 'todo' },
          { id: 't-component',  label: 'Component tests',          status: 'blocked' },
        ],
      },
    ],
  },
]

export interface MessageBlock {
  type: 'text' | 'code' | 'tool' | 'status'
  content: string
  lang?: string
  title?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  author: string
  time: string
  blocks: MessageBlock[]
  attachments?: string[]
}

export const initialMessages: ChatMessage[] = [
  {
    id: 'm-1',
    role: 'user',
    author: 'Xike',
    time: '18:11',
    blocks: [
      {
        type: 'text',
        content: 'hi',
      },
    ],
  },
  {
    id: 'm-2',
    role: 'assistant',
    author: 'DeepTutor',
    time: '18:12',
    blocks: [
      {
        type: 'text',
        content: 'Hi! What can I help you with?',
      },
    ],
  },
]

export interface FileChange {
  path: string
  type: 'added' | 'modified' | 'deleted'
}

export const fileChanges: FileChange[] = [
  { path: 'src/app/App.tsx',                     type: 'added' },
  { path: 'src/styles/tokens.css',               type: 'added' },
  { path: 'src/styles/themes.css',               type: 'added' },
  { path: 'src/styles/globals.css',              type: 'modified' },
  { path: 'src/styles/reset.css',                type: 'added' },
  { path: 'src/mock/data.ts',                    type: 'added' },
  { path: 'src/main.tsx',                        type: 'added' },
  { path: 'src/vite-env.d.ts',                   type: 'added' },
  { path: 'index.html',                          type: 'modified' },
  { path: 'package.json',                        type: 'added' },
  { path: 'vite.config.ts',                      type: 'added' },
  { path: 'tsconfig.json',                       type: 'added' },
]

/* Mode tabs: Work/Code/Design */
export const modeTabs = [
  { id: 'work',   label: 'Work',   icon: 'work' },
  { id: 'code',   label: 'Code',   icon: 'code' },
  { id: 'design', label: 'Design', icon: 'design' },
] as const

export type ModeTabId = (typeof modeTabs)[number]['id']

/* Primary nav items */
export interface NavItem {
  id: string
  label: string
  icon: string
  shortcut?: string
}

export const navItems: NavItem[] = [
  { id: 'create-task', label: '新建对话', icon: 'chat-new', shortcut: '⌃⌘N' },
  { id: 'automation',  label: '学习空间', icon: 'automation' },
  { id: 'plugin',      label: '资料库',   icon: 'marketplace' },
]

/* Task list items */
export interface TaskItem {
  id: string
  label: string
  time: string
  pinned?: boolean
}

export const taskList: TaskItem[] = [
  { id: 't-greeting', label: 'Greeting', time: '18:12' },
  { id: 't-tokens',   label: 'Build design tokens', time: '15:30' },
]

/* Current session task */
export const currentTask = {
  name: 'Greeting',
  time: '18:12',
}

/* Context status */
export const contextUsage = {
  percent: 6,
  segments: [{ width: 6.35846, color: 'var(--accent-accent-slate)' }],
}
