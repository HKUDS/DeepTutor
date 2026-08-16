import React, { useEffect, useRef, useState } from 'react'
import closeSvg from '../../design-system/assets/icons/close-medium.svg?raw'
import downSvg from '../../design-system/assets/icons/Down.svg?raw'
import settingsSvg from '../../design-system/assets/icons/settings.svg?raw'
import {
  DEFAULT_VOICE_SHORTCUT,
  GeneralSettings,
  LanguageId,
  LocalLinkOpenMode,
  ThemeId,
  formatShortcut,
  loadGeneralSettings,
  persistInterfaceSettings,
  saveGeneralSettings,
  shortcutFromKeyboardEvent,
} from './settings'

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

type Copy = {
  general: string
  basic: string
  prefs: string
  theme: string
  themeHint: string
  language: string
  languageHint: string
  voice: string
  voiceHint: string
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
  record: string
  restore: string
  recording: string
}

const COPY: Record<LanguageId, Copy> = {
  zh: {
    general: '通用',
    basic: '基础设置',
    prefs: '偏好设置',
    theme: '主题',
    themeHint: '选择主题',
    language: '语言',
    languageHint: '选择您喜欢的按钮标签和应用内其他文本的语言',
    voice: '语音转录快捷键',
    voiceHint: '开启或关闭语音转录快捷键，录制自定义组合键，或恢复默认值。',
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
    record: '录制快捷键',
    restore: '恢复默认值',
    recording: '按下组合键',
  },
  en: {
    general: 'General',
    basic: 'Basics',
    prefs: 'Preferences',
    theme: 'Theme',
    themeHint: 'Choose a theme',
    language: 'Language',
    languageHint: 'Language for button labels and other in-app text',
    voice: 'Speech-to-text shortcut',
    voiceHint: 'Turn the speech-to-text shortcut on or off, record a custom combo, or restore the default.',
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
    record: 'Record shortcut',
    restore: 'Restore default',
    recording: 'Press a combo',
  },
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
  const current = options.find((o) => o.value === value)?.label || value

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && e.target instanceof Node && rootRef.current.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])

  return (
    <div className="dtSettingsSelect" ref={rootRef}>
      <button
        type="button"
        className="dtSettingsSelectTrigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{current}</span>
        <OfficialIcon svg={downSvg} size={14} className="dtSettingsSelectChevron" />
      </button>
      {open && (
        <div className="dtSettingsSelectMenu" role="listbox" aria-label={ariaLabel}>
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
        </div>
      )}
    </div>
  )
}

export function SettingsModal({
  open,
  onClose,
  theme,
  onThemeChange,
  language,
  onLanguageChange,
  accountName,
  accountPlan,
}: {
  open: boolean
  onClose: () => void
  theme: ThemeId
  onThemeChange: (theme: ThemeId) => void
  language: LanguageId
  onLanguageChange: (language: LanguageId) => void
  accountName: string
  accountPlan: string
}) {
  const [general, setGeneral] = useState<GeneralSettings>(() => loadGeneralSettings())
  const [gearOpen, setGearOpen] = useState(false)
  const [recording, setRecording] = useState(false)
  const [editingPath, setEditingPath] = useState(false)
  const [pathDraft, setPathDraft] = useState(general.artifactPath)
  const gearRef = useRef<HTMLDivElement>(null)
  const pathInputRef = useRef<HTMLInputElement>(null)
  const copy = COPY[language]

  useEffect(() => {
    if (!open) {
      setGearOpen(false)
      setRecording(false)
      setEditingPath(false)
      return
    }
    const onKey = (e: KeyboardEvent) => {
      if (recording) {
        e.preventDefault()
        e.stopPropagation()
        if (e.key === 'Escape') {
          setRecording(false)
          return
        }
        const next = shortcutFromKeyboardEvent(e)
        if (!next) return
        commit({ voiceShortcut: { ...next, enabled: general.voiceShortcut.enabled } })
        setRecording(false)
        return
      }
      if (e.key === 'Escape') {
        if (gearOpen) { setGearOpen(false); return }
        if (editingPath) { setEditingPath(false); return }
        onClose()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [open, recording, gearOpen, editingPath, general.voiceShortcut.enabled, onClose])

  useEffect(() => {
    if (!gearOpen) return
    const onPointer = (e: PointerEvent) => {
      if (gearRef.current && e.target instanceof Node && gearRef.current.contains(e.target)) return
      setGearOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [gearOpen])

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
              <span className="dtSettingsProduct">DeepTutor</span>
            </div>
          </div>
          <button type="button" className="dtSettingsNavItem is-active" aria-current="page">
            <OfficialIcon svg={settingsSvg} size={16} />
            <span>{copy.general}</span>
          </button>
        </aside>

        <section className="dtSettingsMain">
          <button type="button" className="dtSettingsClose" aria-label="Close" onClick={onClose}>
            <OfficialIcon svg={closeSvg} size={16} />
          </button>
          <h1 id="dt-settings-title" className="dtSettingsTitle">{copy.general}</h1>

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
                <div className="dtSettingsRowTitle">{copy.voice}</div>
                <div className="dtSettingsRowHint">{copy.voiceHint}</div>
              </div>
              <div className="dtSettingsShortcut">
                <button
                  type="button"
                  className={`dtSettingsSwitch${general.voiceShortcut.enabled ? ' is-on' : ''}`}
                  role="switch"
                  aria-checked={general.voiceShortcut.enabled}
                  aria-label={copy.voice}
                  onClick={() => commit({
                    voiceShortcut: { ...general.voiceShortcut, enabled: !general.voiceShortcut.enabled },
                  })}
                >
                  <span className="dtSettingsSwitchThumb" />
                </button>
                <div className={`dtSettingsKeys${recording ? ' is-recording' : ''}`}>
                  {recording ? (
                    <span className="dtSettingsKey dtSettingsKeyWide">{copy.recording}</span>
                  ) : (
                    formatShortcut(general.voiceShortcut).map((part, i) => (
                      <React.Fragment key={`${part}-${i}`}>
                        {i > 0 && <span className="dtSettingsKeyPlus">+</span>}
                        <span className="dtSettingsKey">{part}</span>
                      </React.Fragment>
                    ))
                  )}
                </div>
                <div className="dtSettingsGearWrap" ref={gearRef}>
                  <button
                    type="button"
                    className="dtSettingsGear"
                    aria-label={copy.record}
                    aria-expanded={gearOpen}
                    onClick={() => setGearOpen((v) => !v)}
                  >
                    <OfficialIcon svg={settingsSvg} size={14} />
                  </button>
                  {gearOpen && (
                    <div className="dtSettingsGearMenu" role="menu">
                      <button
                        type="button"
                        role="menuitem"
                        className="dtSettingsGearItem"
                        onClick={() => { setGearOpen(false); setRecording(true) }}
                      >
                        {copy.record}
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="dtSettingsGearItem"
                        onClick={() => {
                          setGearOpen(false)
                          commit({ voiceShortcut: { ...DEFAULT_VOICE_SHORTCUT, enabled: general.voiceShortcut.enabled } })
                        }}
                      >
                        {copy.restore}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

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
        </section>
      </div>
    </div>
  )
}
