'use client'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import './note-library.css'
import { Layers, X } from 'lucide-react'
import { noteRequest } from '@/lib/notes-api'
import PickerShell from '@/components/common/PickerShell'
interface Card {
  page_id: string
  page_title: string
  block_id: string
  card_id: string
  front: string
  back: string
}
export default function NoteReview() {
  const { t } = useTranslation()
  const [cards, setCards] = useState<Card[]>([])
  const [open, setOpen] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    void noteRequest<{ cards: Card[] }>('/review/due')
      .then(r => setCards(r.cards))
      .catch(e => setError(String(e)))
  }, [])
  const card = cards[0]
  const grade = async (remembered: boolean) => {
    setBusy(true)
    try {
      await noteRequest(`/${card.page_id}/review`, { card_id: card.card_id, remembered })
      setCards(c => c.slice(1))
      setRevealed(false)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  if (!cards.length && !open) return null
  return (
    <>
      <button
        className="dt-notes-review-trigger"
        onClick={() => {
          setRevealed(false)
          setOpen(true)
        }}
      >
        <Layers size={14} strokeWidth={1.7} />
        {t('Review flashcards')}
        <span className="dt-notes-review-count">{cards.length}</span>
      </button>
      <PickerShell open={open} onClose={() => setOpen(false)} ariaLabel={t('Review flashcards')}>
        <div className="dt-notes-review">
          <header>
            <span>{t('Review flashcards')}</span>
            {card && <span>{t('{{count}} left', { count: cards.length })}</span>}
            <button className="dt-note-icon-button" aria-label={t('Close')} onClick={() => setOpen(false)}>
              <X size={15} />
            </button>
          </header>
          {card ? (
            <>
              <div className="dt-notes-review-card">
                <p className="is-front">{card.front}</p>
                {revealed && <p className="is-back">{card.back}</p>}
              </div>
              <Link href={`/co-writer/${card.page_id}#${card.block_id}`} className="dt-notes-review-source">
                {t('From “{{page}}”', { page: card.page_title || t('Untitled') })} ↗
              </Link>
              <div className="dt-notes-review-actions">
                {revealed ? (
                  <>
                    <button disabled={busy} onClick={() => void grade(false)}>
                      {t('Again')}
                    </button>
                    <button disabled={busy} className="is-primary" onClick={() => void grade(true)}>
                      {t('Remembered')}
                    </button>
                  </>
                ) : (
                  <button className="is-primary" onClick={() => setRevealed(true)}>
                    {t('Show answer')}
                  </button>
                )}
              </div>
            </>
          ) : (
            <div className="dt-notes-review-done">
              <span aria-hidden>🎉</span>
              <p>{t('All caught up')}</p>
            </div>
          )}
          {error && (
            <p role="alert" className="dt-notes-review-error">
              {error}
            </p>
          )}
        </div>
      </PickerShell>
    </>
  )
}
