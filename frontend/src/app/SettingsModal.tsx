import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import closeSvg from '../../design-system/assets/icons/close-medium.svg?raw'
import downSvg from '../../design-system/assets/icons/Down.svg?raw'
import settingsSvg from '../../design-system/assets/icons/settings.svg?raw'
import chatSvg from '../../design-system/assets/icons/chat-session-icon.svg?raw'
import { toolLabel, type ToolItem } from '../api/tools'
import {
  GeneralSettings,
  LanguageId,
  LocalLinkOpenMode,
  ThemeId,
  loadGeneralSettings,
  persistChatTimeout,
  persistInterfaceSettings,
  persistVoiceAutoplay,
  saveGeneralSettings,
  timeoutSelectOptions,
} from './settings'
import { PRODUCT_NAME } from './brand'

const OfficialIcon: React.FC<{ svg: string; size?: number; className?: string }> = ({
  svg, size = 16, className = '',
}) => (
  <span
    className={`trae-icon ${className}`.trim()}
    aria-hidden
    style={{ display: 'inline-flex', width: size, height: size, color: 'currentColor' }}
    dangerouslySetInnerHTML={{
      __html: svg.replace('width="24"', `width="${size}"`).replace('height="24"', `height="${size}"`),
    }}
  />
)

type SettingsPane = 'general' | 'chat'

type Copy = {
  general: string
  chat: string
  basic: string
  prefs: string
  reply: string
  tools: string
  theme: string
  themeHint: string
  language: string
  languageHint: string
  replyLanguage: string
  replyLanguageHint: string
  autoplay: string
  autoplayHint: string
  timeout: string
  timeoutHint: string
  toolsHint: string
  comingSoon: string
  localLink: string
  localLinkHint: string
  artifact: string
  artifactHint: string
  change: string
  light: string
  dark: string
  zh: string
  en: string
  ask: string
  builtin: string
  system: string
}

const COPY: Record<LanguageId, Copy> = {
  zh: {
    general: '通用',
    chat: '对话与工具',
    basic: '基础设置',
    prefs: '偏好设置',
    reply: '回复',
    tools: '可选工具',
    theme: '主题',
    themeHint: '选择主题',
    language: '语言',
    languageHint: '选择您喜欢的按钮标签和应用内其他文本的语言',
    replyLanguage: '模型回复语言',
    replyLanguageHint: '助手默认用哪种语言回答。与界面语言独立，可中文界面、英文作答。',
    autoplay: '回复自动朗读',
    autoplayHint: '每轮回答结束后自动用语音读出。未配置语音服务时会静默跳过。',
    timeout: '对话等待超时',
    timeoutHint: '等待下一轮事件的最长时间。出图、视频等慢工具可调长一些。',
    toolsHint: '关闭后，对话默认不会调用该工具。可随时再打开。',
    comingSoon: '即将推出',
    localLink: '本地链接的默认打开方式',
    localLinkHint: '点击终端中的本地链接时，是否自动使用内置浏览器打开',
    artifact: '自定义产物存储路径',
    artifactHint: '新建任务和工作空间将保存在此（该更改不会修改已有的文件路径）',
    change: '更改',
    light: '亮色',
    dark: '暗色',
    zh: '简体中文',
    en: 'English',
    ask: '始终询问',
    builtin: '内置浏览器',
    system: '系统默认浏览器',
  },
  en: {
    general: 'General',
    chat: 'Chat & tools',
    basic: 'Basics',
    prefs: 'Preferences',
    reply: 'Replies',
    tools: 'Optional tools',
    theme: 'Theme',
    themeHint: 'Choose a theme',
    language: 'Language',
    languageHint: 'Language for button labels and other in-app text',
    replyLanguage: 'Reply language',
    replyLanguageHint: 'Default language for model replies. Independent of the interface language.',
    autoplay: 'Auto-play replies',
    autoplayHint: 'Read each finished reply aloud. Skipped silently if speech is not configured.',
    timeout: 'Reply wait timeout',
    timeoutHint: 'How long to wait for the next turn event. Raise this for slow image or video tools.',
    toolsHint: 'When off, chat will not call this tool by default. You can turn it back on anytime.',
    comingSoon: 'Coming soon',
    localLink: 'Default way to open local links',
    localLinkHint: 'When you click a local link in the terminal, whether to open it in the built-in browser',
    artifact: 'Custom artifact storage path',
    artifactHint: 'New tasks and workspaces will be saved here (this change will not move existing files)',
    change: 'Change',
    light: 'Light',
    dark: 'Dark',
    zh: '简体中文',
    en: 'English',
    ask: 'Always ask',
    builtin: 'Built-in browser',
    system: 'System browser',
  },
}

function useFixedMenu(
  open: boolean,
  anchorRef: React.RefObject<HTMLElement | null>,
  itemCount: number,
) {
  const [pos, setPos] = useState<{ top: number; left: number; minWidth: number } | null>(null)

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setPos(null)
      return
    }
    const place = () => {
      const el = anchorRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const menuH = itemCount * 32 + 12
      const openUp = window.innerHeight - r.bottom < menuH + 8 && r.top > menuH
      const minWidth = Math.max(Math.ceil(r.width), 128)
      const left = Math.min(Math.max(8, r.right - minWidth), window.innerWidth - minWidth - 8)
      setPos({
        top: openUp ? Math.max(8, r.top - menuH - 4) : r.bottom + 4,
        left,
        minWidth,
      })
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [open, itemCount, anchorRef])

  return pos
}

function SettingsSelect<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
  ariaLabel: string
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const pos = useFixedMenu(open, rootRef, options.length)
  const current = options.find((o) => o.value === value)?.label || value

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      const target = e.target
      if (!(target instanceof Node)) return
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopPropagation()
      setOpen(false)
    }
    const onOther = () => setOpen(false)
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('dt-settings-close-menus', onOther)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('dt-settings-close-menus', onOther)
    }
  }, [open])

  return (
    <div className="dtSettingsSelect" ref={rootRef}>
      <button
        type="button"
        className="dtSettingsSelectTrigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => {
          const next = !open
          window.dispatchEvent(new Event('dt-settings-close-menus'))
          setOpen(next)
        }}
      >
        <span>{current}</span>
        <OfficialIcon svg={downSvg} size={14} className="dtSettingsSelectChevron" />
      </button>
      {open && pos && createPortal(
        <div
          ref={menuRef}
          className="dtSettingsSelectMenu"
          role="listbox"
          aria-label={ariaLabel}
          style={{ top: pos.top, left: pos.left, minWidth: pos.minWidth }}
        >
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="option"
              aria-selected={opt.value === value}
              className={`dtSettingsSelectOption${opt.value === value ? ' is-selected' : ''}`}
              onClick={() => { onChange(opt.value); setOpen(false) }}
            >
              {opt.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  )
}

function SettingsSwitch({
  checked,
  label,
  disabled,
  onChange,
}: {
  checked: boolean
  label: string
  disabled?: boolean
  onChange: () => void
}) {
  return (
    <button
      type="button"
      className={`dtSettingsSwitch${checked ? ' is-on' : ''}`}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
    >
      <span className="dtSettingsSwitchThumb" />
    </button>
  )
}

export function SettingsModal({
  open,
  onClose,
  theme,
  onThemeChange,
  language,
  onLanguageChange,
  responseLanguage,
  onResponseLanguageChange,
  voiceAutoplay,
  onVoiceAutoplayChange,
  chatTimeout,
  onChatTimeoutChange,
  tools,
  onToggleTool,
  accountName,
  accountPlan,
}: {
  open: boolean
  onClose: () => void
  theme: ThemeId
  onThemeChange: (theme: ThemeId) => void
  language: LanguageId
  onLanguageChange: (language: LanguageId) => void
  responseLanguage: LanguageId
  onResponseLanguageChange: (language: LanguageId) => void
  voiceAutoplay: boolean
  onVoiceAutoplayChange: (value: boolean) => void
  chatTimeout: number
  onChatTimeoutChange: (seconds: number) => void
  tools: ToolItem[]
  onToggleTool: (name: string) => void
  accountName: string
  accountPlan: string
}) {
  const [pane, setPane] = useState<SettingsPane>('general')
  const [general, setGeneral] = useState<GeneralSettings>(() => loadGeneralSettings())
  const [editingPath, setEditingPath] = useState(false)
  const [pathDraft, setPathDraft] = useState(general.artifactPath)
  const pathInputRef = useRef<HTMLInputElement>(null)
  const copy = COPY[language]
  const timeoutOptions = timeoutSelectOptions(chatTimeout, language)

  useEffect(() => {
    if (!open) {
      setPane('general')
      setEditingPath(false)
      return
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (editingPath) { setEditingPath(false); return }
      onClose()
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [open, editingPath, onClose])

  useEffect(() => {
    if (editingPath) pathInputRef.current?.focus()
  }, [editingPath])

  if (!open) return null

  const commit = (patch: Partial<GeneralSettings>) => {
    const next = { ...general, ...patch }
    setGeneral(next)
    saveGeneralSettings(next)
  }

  const setTheme = (next: ThemeId) => {
    onThemeChange(next)
    persistInterfaceSettings({ theme: next })
  }
  const setLanguage = (next: LanguageId) => {
    onLanguageChange(next)
    persistInterfaceSettings({ language: next })
  }
  const setReplyLanguage = (next: LanguageId) => {
    onResponseLanguageChange(next)
    persistInterfaceSettings({ response_language: next })
  }
  const setAutoplay = (next: boolean) => {
    onVoiceAutoplayChange(next)
    persistVoiceAutoplay(next)
  }
  const setTimeoutSeconds = (next: string) => {
    const seconds = Number(next)
    onChatTimeoutChange(seconds)
    persistChatTimeout(seconds)
  }

  const finishPath = () => {
    const trimmed = pathDraft.trim() || general.artifactPath
    setPathDraft(trimmed)
    commit({ artifactPath: trimmed })
    setEditingPath(false)
  }

  return (
    <div className="dtSettingsMask" onClick={onClose}>
      <div
        className="dtSettings"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dt-settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <aside className="dtSettingsNav">
          <div className="dtSettingsAccount">
            <span className="dtSettingsAvatar" aria-hidden>{accountName.slice(0, 1)}</span>
            <div className="dtSettingsAccountMeta">
              <div className="dtSettingsAccountNameRow">
                <span className="dtSettingsAccountName">{accountName}</span>
                <span className="accountHostTag-Hli3r_">{accountPlan}</span>
              </div>
              <span className="dtSettingsProduct">{PRODUCT_NAME}</span>
            </div>
          </div>
          <button
            type="button"
            className={`dtSettingsNavItem${pane === 'general' ? ' is-active' : ''}`}
            aria-current={pane === 'general' ? 'page' : undefined}
            onClick={() => {
              window.dispatchEvent(new Event('dt-settings-close-menus'))
              setPane('general')
            }}
          >
            <OfficialIcon svg={settingsSvg} size={16} />
            <span>{copy.general}</span>
          </button>
          <button
            type="button"
            className={`dtSettingsNavItem${pane === 'chat' ? ' is-active' : ''}`}
            aria-current={pane === 'chat' ? 'page' : undefined}
            onClick={() => {
              window.dispatchEvent(new Event('dt-settings-close-menus'))
              setPane('chat')
            }}
          >
            <OfficialIcon svg={chatSvg} size={16} />
            <span>{copy.chat}</span>
          </button>
        </aside>

        <section className="dtSettingsMain" data-settings-pane={pane}>
          <button type="button" className="dtSettingsClose" aria-label="Close" onClick={onClose}>
            <OfficialIcon svg={closeSvg} size={16} />
          </button>
          <h1 id="dt-settings-title" className="dtSettingsTitle">
            {pane === 'chat' ? copy.chat : copy.general}
          </h1>

          {pane === 'general' && (
            <>
              <h2 className="dtSettingsSection">{copy.basic}</h2>
              <div className="dtSettingsCard">
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.theme}</div>
                    <div className="dtSettingsRowHint">{copy.themeHint}</div>
                  </div>
                  <SettingsSelect
                    ariaLabel={copy.theme}
                    value={theme}
                    onChange={setTheme}
                    options={[
                      { value: 'light', label: copy.light },
                      { value: 'dark', label: copy.dark },
                    ]}
                  />
                </div>
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.language}</div>
                    <div className="dtSettingsRowHint">{copy.languageHint}</div>
                  </div>
                  <SettingsSelect
                    ariaLabel={copy.language}
                    value={language}
                    onChange={setLanguage}
                    options={[
                      { value: 'zh', label: copy.zh },
                      { value: 'en', label: copy.en },
                    ]}
                  />
                </div>
              </div>

              <h2 className="dtSettingsSection">{copy.prefs}</h2>
              <div className="dtSettingsCard">
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.localLink}</div>
                    <div className="dtSettingsRowHint">{copy.localLinkHint}</div>
                  </div>
                  <SettingsSelect
                    ariaLabel={copy.localLink}
                    value={general.localLinkOpen}
                    onChange={(value: LocalLinkOpenMode) => commit({ localLinkOpen: value })}
                    options={[
                      { value: 'ask', label: copy.ask },
                      { value: 'builtin', label: copy.builtin },
                      { value: 'system', label: copy.system },
                    ]}
                  />
                </div>
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.artifact}</div>
                    <div className="dtSettingsRowHint">{copy.artifactHint}</div>
                  </div>
                  <div className="dtSettingsPath">
                    {editingPath ? (
                      <input
                        ref={pathInputRef}
                        className="dtSettingsPathInput"
                        value={pathDraft}
                        aria-label={copy.artifact}
                        onChange={(e) => setPathDraft(e.target.value)}
                        onBlur={finishPath}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') finishPath()
                          if (e.key === 'Escape') {
                            setPathDraft(general.artifactPath)
                            setEditingPath(false)
                          }
                        }}
                      />
                    ) : (
                      <span className="dtSettingsPathValue" title={general.artifactPath}>{general.artifactPath}</span>
                    )}
                    <button
                      type="button"
                      className="dtSettingsPathBtn"
                      onClick={() => {
                        setPathDraft(general.artifactPath)
                        setEditingPath(true)
                      }}
                    >
                      {copy.change}
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}

          {pane === 'chat' && (
            <>
              <h2 className="dtSettingsSection">{copy.reply}</h2>
              <div className="dtSettingsCard">
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.replyLanguage}</div>
                    <div className="dtSettingsRowHint">{copy.replyLanguageHint}</div>
                  </div>
                  <SettingsSelect
                    ariaLabel={copy.replyLanguage}
                    value={responseLanguage}
                    onChange={setReplyLanguage}
                    options={[
                      { value: 'zh', label: copy.zh },
                      { value: 'en', label: copy.en },
                    ]}
                  />
                </div>
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.autoplay}</div>
                    <div className="dtSettingsRowHint">{copy.autoplayHint}</div>
                  </div>
                  <SettingsSwitch
                    checked={voiceAutoplay}
                    label={copy.autoplay}
                    onChange={() => setAutoplay(!voiceAutoplay)}
                  />
                </div>
                <div className="dtSettingsRow">
                  <div className="dtSettingsRowCopy">
                    <div className="dtSettingsRowTitle">{copy.timeout}</div>
                    <div className="dtSettingsRowHint">{copy.timeoutHint}</div>
                  </div>
                  <SettingsSelect
                    ariaLabel={copy.timeout}
                    value={String(chatTimeout)}
                    onChange={setTimeoutSeconds}
                    options={timeoutOptions}
                  />
                </div>
              </div>

              <h2 className="dtSettingsSection">{copy.tools}</h2>
              <div className="dtSettingsCard">
                {tools.length === 0 ? (
                  <div className="dtSettingsRow">
                    <div className="dtSettingsRowCopy">
                      <div className="dtSettingsRowHint">{copy.toolsHint}</div>
                    </div>
                  </div>
                ) : tools.map((tool) => {
                  const label = toolLabel(tool, language)
                  const hint = tool.descriptions[language] || copy.toolsHint
                  const locked = tool.comingSoon || !tool.toggleable
                  return (
                    <div key={tool.name} className={`dtSettingsRow${locked ? ' is-locked' : ''}`}>
                      <div className="dtSettingsRowCopy">
                        <div className="dtSettingsRowTitle">
                          {label}
                          {tool.comingSoon && <span className="dtSettingsBadge">{copy.comingSoon}</span>}
                        </div>
                        <div className="dtSettingsRowHint">{hint}</div>
                      </div>
                      <SettingsSwitch
                        checked={tool.enabled && !tool.comingSoon}
                        label={label}
                        disabled={locked}
                        onChange={() => onToggleTool(tool.name)}
                      />
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
