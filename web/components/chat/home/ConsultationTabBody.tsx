'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import PartnerGroupChat from '@/components/partners/group/PartnerGroupChat'
import { getPartnerGroup, type PartnerGroup } from '@/lib/partner-groups-api'
import type { StreamEvent } from '@/features/chat/model/protocol'
import SubagentTabBody from './SubagentTabBody'
import SubagentRunTranscript from './SubagentRunTranscript'
import PartnerChat from '@/components/partners/PartnerChat'
import { getPartner, getPartnerConsultationSession, type PartnerInfo } from '@/lib/partners-api'

export default function ConsultationTabBody({
  tabEvents,
  sessionId,
}: {
  tabEvents: StreamEvent[]
  sessionId: string | null
}) {
  const { t } = useTranslation()
  const meta = [...tabEvents].reverse().map(event => event.metadata ?? {}).find(meta => meta.partner_group_id)
  if (meta)
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        {typeof meta.partner_group_idle_seconds === 'number' && meta.partner_group_idle_seconds > 0 && (
          <p role="status" className="shrink-0 border-b border-[var(--border)] px-4 py-2 text-xs text-[var(--muted-foreground)]">
            {t('DeepTutor will respond in {{count}}s. Continue here to keep discussing.', { count: meta.partner_group_idle_seconds })}
          </p>
        )}
        <GroupDiscussionBody
          consultationActive={meta.partner_group_consultation_status !== "completed"}
          groupId={String(meta.partner_group_id)}
          sessionKey={String(meta.partner_group_session_key)}
        />
      </div>
    )
  if (tabEvents.some(event => event.metadata?.subagent_kind === 'partner')) {
    const partnerMeta = [...tabEvents].reverse().find(event => event.metadata?.partner_session_key)?.metadata
    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        {partnerMeta ? (
          <PartnerConsultationBody
            key={`${partnerMeta.partner_session_key}:${partnerMeta.consult_index}`}
            partnerId={String(partnerMeta.partner_id)}
            sessionKey={String(partnerMeta.partner_session_key)}
          />
        ) : <LegacyPartnerConsultation events={tabEvents} sessionId={sessionId} />}
      </div>
    )
  }
  return <SubagentTabBody tabEvents={tabEvents} sessionId={sessionId} />
}

function GroupDiscussionBody({ groupId, sessionKey, consultationActive }: { groupId: string; sessionKey: string; consultationActive: boolean }) {
  const { t } = useTranslation()
  const [group, setGroup] = useState<PartnerGroup | null>(null)
  const [error, setError] = useState('')
  const [panelOpen, setPanelOpen] = useState(false)
  useEffect(() => {
    let active = true
    void getPartnerGroup(groupId)
      .then(value => {
        if (active) setGroup(value)
      })
      .catch(error => {
        if (active) setError(String(error))
      })
    return () => {
      active = false
    }
  }, [groupId])
  if (error)
    return (
      <p role="alert" className="p-4 text-sm">
        {t('Could not load partner groups')}: {error}
      </p>
    )
  if (!group)
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="animate-spin" size={18} />
      </div>
    )
  return (
    <PartnerGroupChat
      embedded
      consultationActive={consultationActive}
      group={group}
      sessionKey={sessionKey}
      panelOpen={panelOpen}
      onOpenPanel={() => setPanelOpen(true)}
      onClosePanel={() => setPanelOpen(false)}
    />
  )
}

function PartnerConsultationPending({ events }: { events: StreamEvent[] }) {
  // Older saved traces predate native session identities. Keep them readable.
  if (events.some(event => ['text', 'result', 'reasoning'].includes(String(event.metadata?.subagent_channel)))) {
    return <div className="h-full min-h-0 overflow-y-auto overscroll-contain"><SubagentRunTranscript events={events} /></div>
  }
  const error = events.find(event => event.metadata?.subagent_channel === 'error')
  return error ? (
    <p role="alert" className="p-4 text-sm text-[var(--destructive)]">{error.content}</p>
  ) : (
    <div className="flex flex-1 items-center justify-center"><Loader2 className="animate-spin" size={18} /></div>
  )
}

function PartnerConsultationBody({ partnerId, sessionKey }: { partnerId: string; sessionKey: string }) {
  const [partner, setPartner] = useState<PartnerInfo | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    void getPartner(partnerId).then(value => {
      if (active) setPartner(value)
    }).catch(error => {
      if (active) setError(String(error))
    })
    return () => { active = false }
  }, [partnerId])
  if (error) return <p role="alert" className="p-4 text-sm">{error}</p>
  if (!partner) return <PartnerConsultationPending events={[]} />
  return (
    <>
      {notice && <p role="status" className="px-4 pt-2 text-xs text-[var(--muted-foreground)]">{notice}</p>}
      <div className="min-h-0 flex-1">
        <PartnerChat
          embedded
          partnerId={partnerId}
          partnerName={partner.name}
          emoji={partner.emoji}
          color={partner.color}
          avatar={partner.avatar}
          sessionKey={sessionKey}
          onToast={setNotice}
        />
      </div>
    </>
  )
}

function LegacyPartnerConsultation({ events, sessionId }: { events: StreamEvent[]; sessionId: string | null }) {
  const name = String(events.find(event => event.metadata?.subagent_name)?.metadata?.subagent_name || '')
  const [identity, setIdentity] = useState<{ partner_id: string; session_key: string } | null>(null)
  useEffect(() => {
    if (!sessionId || !name) return
    let active = true
    void getPartnerConsultationSession(sessionId, name).then(value => {
      if (active) setIdentity(value)
    }).catch(() => {})
    return () => { active = false }
  }, [sessionId, name])
  return identity ? <PartnerConsultationBody partnerId={identity.partner_id} sessionKey={identity.session_key} /> : <PartnerConsultationPending events={events} />
}
