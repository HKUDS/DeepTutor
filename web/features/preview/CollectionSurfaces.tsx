'use client'
import { useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Plus,
  Settings2,
  Users,
  MessageCircle,
  Sparkles,
} from 'lucide-react'
import { FeaturePage, PageHeader, pageActionClass } from '@/components/layout/FeaturePage'
import { LearningShell } from '@/components/learning/LearningShell'
import { LearningCardContent } from '@/components/learning/LearningCard'
import PartnerAvatar from '@/components/partners/PartnerAvatar'
import { Dialog } from '@/shared/ui/Dialog'
import MarkdownRenderer from '@/components/common/MarkdownRenderer'
import { MasteryQuestionCard } from '@/components/chat/home/MasteryQuestionCard'
import type { MasteryGradeResult } from '@/lib/mastery-question'
import { DASHBOARD_GROUPS } from '@/components/space/dashboard-groups'
import {
  learningKinds,
  type Collections,
  type LearningKind,
  type LearningRecord,
} from './collections'
import { question } from './fixtures'
import { readDemo, writeDemo } from './demo-transport'

export function LearningOverview({
  collections,
  onOpen,
}: {
  collections: Collections
  onOpen: (r: LearningRecord) => void
}) {
  const [kind, setKind] = useState('all')
  return (
    <LearningShell
      back={false}
      title="学习"
      subtitle="你的书籍、精通之路、练习和阅读，都在这里。"
      tabs={
        <div className="preview-filter-bar">
          {[{ id: 'all', label: '全部' }, ...learningKinds].map(k => (
            <button
              key={k.id}
              aria-pressed={kind === k.id}
              className={kind === k.id ? 'is-active' : ''}
              onClick={() => setKind(k.id)}
            >
              {k.label}
            </button>
          ))}
        </div>
      }
    >
      <div className="preview-learning-grid">
        {collections.learning
          .filter(r => kind === 'all' || r.kind === kind)
          .map(r => {
            const type = learningKinds.find(k => k.id === r.kind)!
            return (
              <button key={r.id} className="preview-learning-card" onClick={() => onOpen(r)}>
                <div className="preview-card-meta">
                  <span>{type.label}</span>
                  <ArrowRight size={15} />
                </div>
                <LearningCardContent
                  title={r.title}
                  subtitle={r.detail}
                  icon={<type.icon size={23} strokeWidth={1.5} />}
                />
              </button>
            )
          })}
      </div>
    </LearningShell>
  )
}
export function CreateLearningPage({
  onBack,
  onCreate,
}: {
  onBack: () => void
  onCreate: (r: LearningRecord) => void
}) {
  const [kind, setKind] = useState<LearningKind>('book')
  const [title, setTitle] = useState('')
  const [goal, setGoal] = useState('')
  return (
    <FeaturePage className="preview-create-learning-page">
      <button className="preview-back-link" onClick={onBack}>
        <ArrowLeft size={14} />
        返回所有学习
      </button>
      <PageHeader
        title="新建学习"
        description="选一种适合你的方式，之后都可以从学习记录里继续。"
      />
      <form
        className="preview-create-form preview-create-learning-form"
        onSubmit={e => {
          e.preventDefault()
          if (!title.trim()) return
          onCreate({
            id: crypto.randomUUID(),
            title: title.trim(),
            kind,
            detail: '刚刚创建 · 草稿',
            notes: goal,
          })
          setTitle('')
          setGoal('')
        }}
      >
        <div className="preview-kind-picker">
          {learningKinds.map(k => (
            <button
              type="button"
              key={k.id}
              aria-pressed={kind === k.id}
              onClick={() => setKind(k.id)}
              className={kind === k.id ? 'is-active' : ''}
            >
              <k.icon size={22} strokeWidth={1.5} />
              <span>
                {k.label}
                <small>{k.description}</small>
              </span>
              {kind === k.id && <Check size={15} />}
            </button>
          ))}
        </div>
        <label>
          名称
          <input
            data-autofocus
            required
            maxLength={100}
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="例如：从直觉理解概率论"
          />
        </label>
        <label>
          {kind === 'reading' ? '阅读材料或笔记' : '你想学会什么？'}
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder={
              kind === 'reading'
                ? '粘贴想阅读的内容，也可以稍后添加…'
                : '写下你的目标，或留给之后慢慢补充…'
            }
            rows={3}
          />
        </label>
        <div className="preview-form-footer">
          <span>预览中创建本地草稿，保存在此浏览器。</span>
          <button className={pageActionClass()} type="submit" disabled={!title.trim()}>
            创建{learningKinds.find(k => k.id === kind)?.label}
            <ArrowRight size={14} />
          </button>
        </div>
      </form>
    </FeaturePage>
  )
}
const bookChapters = [
  {
    title: '从不确定性开始',
    text: '# 从不确定性开始\n\n概率是我们描述不确定性的一种语言。\n\n想象抛一枚均匀的硬币：下一次的结果未知，但我们可以描述长期重复后，正面大约会占一半。\n\n## 一个事件，一种可能\n\n样本空间包含所有可能的结果。事件则是其中的一部分。\n\n- 抛硬币：样本空间是正面与反面。\n- 掷骰子：样本空间包含 1 到 6。\n- 掷出偶数：事件包含 2、4、6。\n\n> 先把所有可能列清楚，再讨论其中哪些结果满足条件。',
  },
  {
    title: '条件改变了什么',
    text: '# 条件改变了什么\n\n已知骰子掷出的点数是偶数，它等于 6 的概率是多少？\n\n原来的六种可能，现在只剩下 2、4、6。我们把讨论的范围缩小到了已知条件之内。\n\n$$P(A\\mid B)=\\frac{P(A\\cap B)}{P(B)}$$\n\n条件概率关心的是：在 B 已经发生的世界里，A 出现的比例。',
  },
  {
    title: '用新证据更新判断',
    text: '# 用新证据更新判断\n\n贝叶斯公式让我们在看到新证据后更新判断。\n\n$$P(A\\mid B)=\\frac{P(B\\mid A)P(A)}{P(B)}$$\n\n先验表达看到证据之前的判断。似然表达假设成立时，看到当前证据有多自然。两者一起帮助我们形成新的判断。\n\n## 试着思考\n\n当一种疾病非常罕见时，为什么阳性的检测结果仍然需要进一步确认？',
  },
]
export function LearningRecordSurface({
  record,
  onChange,
  onBack,
}: {
  record: LearningRecord
  onChange: (r: LearningRecord) => void
  onBack: () => void
}) {
  const [chapter, setChapter] = useState(() => readDemo(`chapter-${record.id}`, 0))
  const [grade, setGrade] = useState<MasteryGradeResult | null>(() =>
    readDemo(`practice-${record.id}`, null)
  )
  const kind = learningKinds.find(k => k.id === record.kind)!
  return (
    <FeaturePage>
      <button className="preview-back-link" onClick={onBack}>
        <ArrowLeft size={14} />
        所有学习
      </button>
      <PageHeader
        title={record.title}
        description={`${kind.label} · ${record.sample ? '示例内容' : '草稿已保存在此浏览器'}`}
      />
      {record.sample && record.kind === 'book' ? (
        <div className="preview-mastery-layout">
          <nav className="preview-objectives" aria-label="书籍章节">
            <div className="preview-nav-label">目录</div>
            {bookChapters.map((c, i) => (
              <button
                key={c.title}
                className={chapter === i ? 'is-active' : ''}
                onClick={() => {
                  setChapter(i)
                  writeDemo(`chapter-${record.id}`, i)
                }}
              >
                <span>{String(i + 1).padStart(2, '0')}</span>
                {c.title}
              </button>
            ))}
          </nav>
          <article className="preview-lesson">
            <MarkdownRenderer content={bookChapters[chapter].text} />
          </article>
        </div>
      ) : record.sample && record.kind === 'practice' ? (
        <div className="preview-record-practice">
          <div className="preview-section-title">
            <span>巩固练习</span>
            <small>{grade ? '已完成 1 / 1' : '第 1 / 1 题'}</small>
          </div>
          <MasteryQuestionCard
            question={question}
            grade={grade}
            answered={!!grade}
            submittedAnswer={grade?.learnerAnswer || ''}
            onSubmit={p => {
              const answer = p.answers?.[0]?.text || p.text || ''
              const result: MasteryGradeResult = {
                questionId: question.questionId,
                learnerAnswer: answer,
                isCorrect: answer === 'B',
                correctLabel: 'B',
                correctBody: '(1, 0) 和 (0, 1)',
                explanation: '两个向量线性无关，且能够张成二维空间。',
                result: answer === 'B' ? 'correct' : 'incorrect',
              }
              setGrade(result)
              writeDemo(`practice-${record.id}`, result)
              return true
            }}
          />
          {grade && (
            <button
              className={pageActionClass('secondary')}
              onClick={() => {
                setGrade(null)
                writeDemo(`practice-${record.id}`, null)
              }}
            >
              再练一次
            </button>
          )}
        </div>
      ) : (
        <div className="preview-record-draft">
          <div className="preview-draft-status">
            <kind.icon size={20} />
            <div>
              <strong>你的{kind.label}已创建</strong>
              <p>可以先整理目标和材料。自动生成内容需要接入模型。</p>
            </div>
          </div>
          <label className="preview-field">
            名称
            <input
              value={record.title}
              onChange={e => onChange({ ...record, title: e.target.value })}
            />
          </label>
          <label className="preview-field">
            {record.kind === 'reading' ? '阅读材料' : '目标与笔记'}
            <textarea
              rows={10}
              value={record.notes}
              onChange={e => onChange({ ...record, notes: e.target.value })}
              placeholder="在这里补充内容…"
            />
          </label>
          {record.notes && (
            <div className="preview-note-render">
              <MarkdownRenderer content={record.notes} />
            </div>
          )}
          <p className="preview-local-note">
            <Check size={12} />
            修改自动保存在此浏览器
          </p>
        </div>
      )}
    </FeaturePage>
  )
}

export type PartnerModal = 'partner' | 'group' | null
export function PartnerSurface({
  collections: c,
  selected,
  onSelect,
  modal,
  setModal,
}: {
  collections: Collections
  selected: string
  onSelect: (id: string) => void
  modal: PartnerModal
  setModal: (m: PartnerModal) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [members, setMembers] = useState<string[]>([])
  const [editing, setEditing] = useState(false)
  const [input, setInput] = useState('')
  const session = c.sessions.find(s => s.id === selected)
  const owner = session?.owner || selected
  const partner = c.partners.find(p => p.id === owner)
  const group = c.groups.find(g => g.id === owner)
  const title = session?.title || partner?.name || group?.name || '伙伴'
  function createSession() {
    const id = crypto.randomUUID()
    c.setSessions(s => [
      { id, title: `与 ${partner?.name || group?.name} 的新会话`, owner, messages: [] },
      ...s,
    ])
    onSelect(id)
  }
  function configure() {
    setName(partner?.name || group?.name || '')
    setDescription(partner?.description || '')
    setMembers(group?.members || [])
    setEditing(true)
    setModal(partner ? 'partner' : 'group')
  }
  return (
    <>
      <FeaturePage>
        <PageHeader
          title={title}
          description={
            session
              ? `${partner?.name || group?.name} · 会话记录`
              : partner?.description ||
                (group ? '让不同的伙伴，一起参与同一个问题。' : '选择一位伙伴，或让他们一起讨论。')
          }
          action={
            selected ? (
              <div className="flex gap-2">
                <button className={pageActionClass('secondary')} onClick={() => onSelect('')}>
                  <ArrowLeft size={14} />
                  所有伙伴
                </button>
                <button className={pageActionClass('secondary')} onClick={configure}>
                  <Settings2 size={14} />
                  配置
                </button>
                {!session && (
                  <button className={pageActionClass()} onClick={createSession}>
                    <Plus size={14} />
                    新会话
                  </button>
                )}
              </div>
            ) : (
              <button
                className={pageActionClass()}
                onClick={() => {
                  setEditing(false)
                  setName('')
                  setDescription('')
                  setModal('partner')
                }}
              >
                <Plus size={14} />
                新建伙伴
              </button>
            )
          }
        />
        {!selected ? (
          <>
            <div className="preview-section-title">
              <h2>我的伙伴</h2>
              <span>{c.partners.length} 位</span>
            </div>
            <div className="preview-partner-cards">
              {c.partners.map(p => (
                <button key={p.id} onClick={() => onSelect(p.id)}>
                  <PartnerAvatar name={p.name} color={p.color} size={50} />
                  <div>
                    <h3>{p.name}</h3>
                    <p>{p.description}</p>
                    <small>本地预览</small>
                  </div>
                  <ArrowRight size={16} />
                </button>
              ))}
            </div>
            <div className="preview-section-title mt-9">
              <h2>群组</h2>
              <button
                onClick={() => {
                  setEditing(false)
                  setName('')
                  setModal('group')
                }}
              >
                <Plus size={14} />
                新建群组
              </button>
            </div>
            {c.groups.map(g => (
              <button key={g.id} className="preview-group-row" onClick={() => onSelect(g.id)}>
                <Users size={23} strokeWidth={1.5} />
                <span>
                  <strong>{g.name}</strong>
                  <small>
                    {g.members.map(id => c.partners.find(p => p.id === id)?.name).join('、')}
                  </small>
                </span>
                <ArrowRight size={15} />
              </button>
            ))}
            <div className="preview-section-title mt-9">
              <h2>最近会话</h2>
            </div>
            {c.sessions.map(s => (
              <button className="preview-session-row" key={s.id} onClick={() => onSelect(s.id)}>
                <MessageIcon />
                <span>{s.title}</span>
                <small>
                  {c.partners.find(p => p.id === s.owner)?.name ||
                    c.groups.find(g => g.id === s.owner)?.name}
                </small>
                <ArrowRight size={14} />
              </button>
            ))}
          </>
        ) : session ? (
          <div className="preview-partner-chat">
            {session.messages.length ? (
              session.messages.map((m, i) => (
                <div key={i} className={`preview-partner-message ${m.role}`}>
                  <small>{m.role === 'user' ? '你' : partner?.name || group?.name}</small>
                  <MarkdownRenderer content={m.text} />
                </div>
              ))
            ) : (
              <div className="preview-partner-empty">
                <Sparkles size={27} strokeWidth={1.4} />
                <h2>从一个问题开始</h2>
                <p>这段会话会保留在伙伴栏，随时可以继续。</p>
              </div>
            )}
            <form
              onSubmit={e => {
                e.preventDefault()
                if (!input.trim()) return
                const text = input.trim()
                c.setSessions(all =>
                  all.map(s =>
                    s.id !== session.id
                      ? s
                      : {
                          ...s,
                          title: s.messages.length ? s.title : text.slice(0, 30),
                          messages: [
                            ...s.messages,
                            { role: 'user', text },
                            {
                              role: 'assistant',
                              text: `已收到「${text}」。这是会话交互示例；接入模型后，${partner?.name || '群组成员'}会在这里继续回应。`,
                            },
                          ],
                        }
                  )
                )
                setInput('')
              }}
            >
              <input
                aria-label="发送给伙伴"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder={`与 ${partner?.name || group?.name} 聊聊…`}
              />
              <button disabled={!input.trim()} aria-label="发送" className={pageActionClass()}>
                <ArrowRight size={17} />
              </button>
            </form>
            <p className="preview-local-note">示例对话 · 未连接模型或外部渠道</p>
          </div>
        ) : (
          <>
            <div className="preview-partner-detail">
              {partner ? (
                <PartnerAvatar name={partner.name} color={partner.color} size={70} />
              ) : (
                <Users size={50} strokeWidth={1.2} />
              )}
              <h2>{partner?.name || group?.name}</h2>
              <p>
                {partner?.description ||
                  group?.members.map(id => c.partners.find(p => p.id === id)?.name).join(' · ')}
              </p>
              <button className={pageActionClass()} onClick={createSession}>
                <Plus size={14} />
                开始新会话
              </button>
            </div>
            <div className="preview-section-title">
              <h2>会话记录</h2>
            </div>
            {c.sessions
              .filter(s => s.owner === owner)
              .map(s => (
                <button className="preview-session-row" key={s.id} onClick={() => onSelect(s.id)}>
                  <MessageIcon />
                  <span>{s.title}</span>
                  <ArrowRight size={14} />
                </button>
              ))}
          </>
        )}
      </FeaturePage>
      <Dialog
        open={!!modal}
        onClose={() => {
          setModal(null)
          setEditing(false)
          setName('')
          setDescription('')
          setMembers([])
        }}
        title={`${editing ? '配置' : '新建'}${modal === 'group' ? '群组' : '伙伴'}`}
        closeLabel="关闭"
      >
        <form
          className="preview-create-form"
          onSubmit={e => {
            e.preventDefault()
            if (!name.trim()) return
            const id = editing ? owner : crypto.randomUUID()
            if (modal === 'partner') {
              const p = { id, name: name.trim(), description, color: partner?.color || '#7a8d75' }
              c.setPartners(all =>
                editing ? all.map(old => (old.id === id ? p : old)) : [...all, p]
              )
            } else {
              const g = { id, name: name.trim(), members }
              c.setGroups(all =>
                editing ? all.map(old => (old.id === id ? g : old)) : [...all, g]
              )
            }
            setModal(null)
            setEditing(false)
            setName('')
            setDescription('')
            setMembers([])
            onSelect(id)
          }}
        >
          <label>
            名称
            <input
              required
              maxLength={70}
              value={name}
              onChange={e => setName(e.target.value)}
              data-autofocus
            />
          </label>
          {modal === 'partner' ? (
            <label>
              伙伴的角色
              <textarea
                rows={4}
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="这位伙伴擅长什么，怎样与你交流？"
              />
            </label>
          ) : (
            <fieldset>
              <legend>选择成员（至少 2 位）</legend>
              {c.partners.map(p => (
                <label className="preview-member-choice" key={p.id}>
                  <input
                    type="checkbox"
                    checked={members.includes(p.id)}
                    onChange={() =>
                      setMembers(all =>
                        all.includes(p.id) ? all.filter(id => id !== p.id) : [...all, p.id]
                      )
                    }
                  />
                  <PartnerAvatar name={p.name} color={p.color} size={24} />
                  {p.name}
                </label>
              ))}
            </fieldset>
          )}
          <div className="preview-form-footer">
            <span>配置保存在本地预览中</span>
            <button
              className={pageActionClass()}
              disabled={!name.trim() || (modal === 'group' && members.length < 2)}
            >
              保存
            </button>
          </div>
        </form>
      </Dialog>
    </>
  )
}
function MessageIcon() {
  return <MessageCircle size={17} strokeWidth={1.5} />
}

export function ResourceSurface({ href, onBack }: { href: string; onBack: () => void }) {
  const item = DASHBOARD_GROUPS.flatMap(g => g.items).find(i => i.href === href)!
  const [rows, setRows] = useState<{ id: string; name: string; text: string }[]>(() =>
    readDemo(`resources-${href}`, [])
  )
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  function save(next: typeof rows) {
    setRows(next)
    writeDemo(`resources-${href}`, next)
  }
  return (
    <FeaturePage>
      <button className="preview-back-link" onClick={onBack}>
        <ArrowLeft size={14} />
        资料总览
      </button>
      <PageHeader
        title={item.title.zh}
        description={item.blurb.zh}
        action={
          <button className={pageActionClass('secondary')} onClick={() => setAdding(true)}>
            <Plus size={14} />
            添加示例条目
          </button>
        }
      />
      {rows.length ? (
        rows.map(r => (
          <div className="preview-resource-entry" key={r.id}>
            <button
              className="preview-session-row"
              onClick={() => setSelected(selected === r.id ? null : r.id)}
            >
              <item.icon size={18} />
              <span>{r.name}</span>
              <ArrowRight size={14} />
            </button>
            {selected === r.id && (
              <div className="p-5">
                <MarkdownRenderer content={r.text || '尚未添加说明。'} />
              </div>
            )}
          </div>
        ))
      ) : (
        <div className="preview-resource-empty">
          <item.icon size={32} strokeWidth={1.2} />
          <h2>{item.title.zh}</h2>
          <p>{item.blurb.zh}</p>
          <small>这里继承学习空间的资源分类。预览使用独立的本地示例，不读取你的实际资料。</small>
        </div>
      )}
      <Dialog
        open={adding}
        title={`添加${item.title.zh}示例`}
        closeLabel="关闭"
        onClose={() => setAdding(false)}
      >
        <form
          className="preview-create-form"
          onSubmit={e => {
            e.preventDefault()
            const id = crypto.randomUUID()
            save([...rows, { id, name: name.trim(), text }])
            setSelected(id)
            setAdding(false)
            setName('')
            setText('')
          }}
        >
          <label>
            名称
            <input required value={name} onChange={e => setName(e.target.value)} />
          </label>
          <label>
            说明
            <textarea rows={4} value={text} onChange={e => setText(e.target.value)} />
          </label>
          <p className="preview-local-note">用于体验资源的组织方式，不创建真实服务或连接。</p>
          <button className={pageActionClass()} disabled={!name.trim()}>
            添加
          </button>
        </form>
      </Dialog>
    </FeaturePage>
  )
}
