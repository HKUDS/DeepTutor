'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowUpRight, Check, LoaderCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import ProviderIcon from '@/components/common/ProviderIcon'
import {
  CHATGPT_PLAN_LABEL,
  CHATGPT_PLAN_MODELS_URL,
  CHATGPT_PLAN_USAGE_URL,
  requestChatGPTPlan as request,
  type PlanStatus,
} from '@/lib/chatgpt-plan'
import { registryButton, registryPrimary } from './RegistryControls'
import { subPanelClass } from './shared'

const signInButton = `${registryPrimary} !bg-[#151515] !text-white dark:!border-white/30`

export function ChatGPTPlanCard({ onStatus }: { onStatus: (status: PlanStatus) => void }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<PlanStatus>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [statusError, setStatusError] = useState<string>()
  const [authorizeUrl, setAuthorizeUrl] = useState<string>()
  const [addingAccount, setAddingAccount] = useState(false)
  const [accountLabel, setAccountLabel] = useState('')
  const welcome = useRef<HTMLDialogElement>(null)

  const showError = (reason: unknown) => {
    setError(reason instanceof Error ? reason.message : 'connection_failed')
  }
  const refresh = useCallback(async () => {
    const next = await request<PlanStatus>('status')
    setStatusError(undefined)
    setStatus(next)
    onStatus(next)
    if (!next.pending) setAuthorizeUrl(undefined)
    return next
  }, [onStatus])
  const refreshStatus = useCallback(() => {
    void refresh().catch((reason: unknown) => {
      setStatusError(reason instanceof Error ? reason.message : 'connection_failed')
    })
  }, [refresh])
  useEffect(() => {
    refreshStatus()
    window.addEventListener('focus', refreshStatus)
    return () => window.removeEventListener('focus', refreshStatus)
  }, [refreshStatus])
  useEffect(() => {
    if (!status?.pending) return
    const timer = setInterval(refreshStatus, 1200)
    return () => clearInterval(timer)
  }, [refreshStatus, status?.pending])
  useEffect(() => {
    if (status?.show_welcome && !welcome.current?.open) {
      welcome.current?.showModal()
    }
  }, [status?.show_welcome])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(undefined)
    try {
      await action()
    } catch (reason) {
      showError(reason)
    } finally {
      setBusy(false)
    }
  }
  const start = async (action: 'start' | 'add', payload?: { account_id?: string; label?: string }) => {
    const result = await request<{ authorize_url: string }>(action, 'POST', undefined, payload)
    setAddingAccount(false)
    setAccountLabel('')
    const url = new URL(result.authorize_url)
    if (url.origin !== 'https://auth.openai.com' || url.pathname !== '/api/accounts/authorize') {
      throw new Error('connection_failed')
    }
    setAuthorizeUrl(url.href)
    // The Desktop shell routes external attempts to the system browser.
    window.open(url.href, '_blank', 'noopener,noreferrer')
    await refresh()
  }
  const disconnect = async (accountId?: string) => {
    const result = await request<{ revoked: boolean }>(
      'disconnect', 'POST', undefined, accountId ? { account_id: accountId } : undefined,
    )
    await refresh()
    if (!result.revoked) setError('revoke_unconfirmed')
  }
  const currentError = error ?? status?.error ?? statusError
  const errorCopy: Record<string, string> = {
    authorization_denied: t('ChatGPT authorization was declined.'),
    authorization_expired: t('The sign-in request expired. Continue with ChatGPT again.'),
    account_changed: t('This saved registration belongs to a different ChatGPT account.'),
    account_unavailable: t('This saved ChatGPT account is unavailable.'),
    desktop_required: t('ChatGPT plan sign-in requires a local Open DeepTutor Desktop profile.'),
    login_required: t('Reconnect your ChatGPT account to continue.'),
    vault_unavailable: t('Unlock the system credential store and reopen DeepTutor.'),
    revoke_unconfirmed: t(
      'Disconnected on this device. Open ChatGPT settings to remove remote access.'
    ),
  }

  return (
    <section aria-label={CHATGPT_PLAN_LABEL} className={`${subPanelClass} overflow-hidden`}>
      <dialog
        ref={welcome}
        aria-labelledby="chatgpt-plan-welcome-title"
        onClose={() => void run(async () => {
          await request('dismiss-welcome', 'POST')
          await refresh()
        })}
        className="m-auto w-[min(26rem,calc(100%-2rem))] rounded-2xl border border-[var(--border)] bg-[var(--popover)] p-6 text-[var(--foreground)] shadow-xl backdrop:bg-black/40"
      >
        <ProviderIcon provider="openai" size={25} />
        <h3 id="chatgpt-plan-welcome-title" className="mt-3 text-base font-semibold">
          {t('You’re using your ChatGPT plan')}
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-[var(--muted-foreground)]">
          {t(
            'Eligible requests with this provider use your ChatGPT plan. You can review usage in ChatGPT settings.'
          )}
        </p>
        <form method="dialog" className="mt-5">
          <button type="submit" className={registryPrimary}>
            {t('Got it')}
          </button>
        </form>
      </dialog>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--border)] p-4 sm:p-5">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[var(--secondary)]">
            <ProviderIcon provider="openai" size={23} />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold">{CHATGPT_PLAN_LABEL}</h3>
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
              {t('Use your ChatGPT plan for text conversations in DeepTutor.')}
            </p>
          </div>
        </div>
        <span
          role="status"
          className="inline-flex items-center gap-1.5 rounded-full bg-[var(--muted)] px-3 py-1 text-[12px]"
        >
          {status?.pending && (
            <LoaderCircle size={13} aria-hidden className="motion-safe:animate-spin" />
          )}
          {status?.sharing && !status.pending && (
            <Check size={14} aria-hidden className="text-[var(--success)]" />
          )}
          {!status
            ? error
              ? t('Not connected')
              : t('Loading…')
            : status.pending
              ? t('Waiting for ChatGPT')
              : status.sharing
                ? t('Connected')
                : status.connected
                  ? t('Plan usage not allowed')
                  : t('Not connected')}
        </span>
      </header>
      <div className="space-y-4 p-4 sm:p-5">
        {status?.account && <p className="break-all text-sm font-medium">{status.account}</p>}
        {currentError && (
          <p
            role="alert"
            className="rounded-lg bg-[var(--warning-surface)] px-3 py-2 text-[13px] text-[var(--warning-foreground)]"
          >
            {errorCopy[currentError] ?? t('Could not connect to ChatGPT. Try again.')}
          </p>
        )}
        <section
          aria-labelledby="chatgpt-plan-privacy-title"
          className="space-y-2 rounded-lg border border-[var(--border)] px-4 py-3 text-[13px] leading-relaxed text-[var(--muted-foreground)]"
        >
          <h4 id="chatgpt-plan-privacy-title" className="font-medium text-[var(--foreground)]">
            {t('Privacy and plan usage')}
          </h4>
          <ul className="list-disc space-y-1.5 pl-4">
            <li>{t('You sign in with OpenAI in your browser. DeepTutor stores your account label and encrypted sign-in credentials on this device.')}</li>
            <li>{t('When you use a ChatGPT Plan model, DeepTutor sends your messages and relevant context, such as chat history or workspace content, to OpenAI. A model test sends a short test message.')}</li>
            <li>{t('Eligible requests count toward your ChatGPT plan limits. DeepTutor does not charge for this connection. Scheduled tasks and automatic titles do not use this plan.')}</li>
            <li>{t('Disconnect in Providers or revoke access in ChatGPT settings. Disconnecting leaves your saved DeepTutor chats intact.')}</li>
          </ul>
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
            <a className="underline underline-offset-2" href="https://openai.com/policies/privacy-policy/" target="_blank" rel="noreferrer">
              {t('OpenAI Privacy Policy')}
            </a>
            <a className="underline underline-offset-2" href="https://openai.com/policies/sign-in-with-chatgpt-terms/" target="_blank" rel="noreferrer">
              {t('Sign in with ChatGPT Terms')}
            </a>
          </div>
          <details className="mt-3 border-t border-[var(--border)] pt-2">
            <summary className="cursor-pointer font-medium text-[var(--foreground)]">
              {t('DeepTutor data notice')}
            </summary>
            <div className="mt-2 max-w-prose space-y-2">
              <p>{t('Open DeepTutor is an open-source project. Each saved ChatGPT registration keeps its own account identifier, label and encrypted credentials in this Desktop profile. DeepTutor uses a system-protected key to unlock them.')}</p>
              <p>{t('Disconnect the active account to stop local use and request revocation. Its local label and registration remain for future sign-ins, along with your DeepTutor chats. Remove the local Desktop profile to erase the remaining local data.')}</p>
              <p>{t('If remote revocation cannot be confirmed, DeepTutor keeps an encrypted token solely to retry revocation. You can retry from the account list.')}</p>
              <p>{t('Only send information you are allowed to share. Do not send personal information about children under 13 or below the applicable age of digital consent.')}</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <a className="underline underline-offset-2" href="https://github.com/HKUDS/DeepTutor" target="_blank" rel="noreferrer">
                  {t('DeepTutor project')}
                </a>
                <a className="underline underline-offset-2" href="https://github.com/HKUDS/DeepTutor/security/advisories/new" target="_blank" rel="noreferrer">
                  {t('Report a security issue')}
                </a>
              </div>
            </div>
          </details>
        </section>
        {status && !status.pending && status.accounts.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">{t('ChatGPT accounts and workspaces')}</h4>
            <ul className="divide-y divide-[var(--border)]">
              {status.accounts.map((account, index) => (
                <li key={account.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span className="min-w-0 break-all">
                    {account.label}
                    {status.accounts.some((other) => other.id !== account.id && other.label === account.label) && (
                      <span className="ml-2 text-[var(--muted-foreground)]">({index + 1})</span>
                    )}
                  </span>
                  {account.revocation_pending ? (
                    <button type="button" className={registryButton} disabled={busy}
                      onClick={() => void run(() => disconnect(account.id))}>
                      {t('Retry revocation')}
                    </button>
                  ) : account.id === status.active_account_id && account.connected ? (
                    <span className="text-[13px] text-[var(--muted-foreground)]">{t('Active account')}</span>
                  ) : (
                    <button type="button" className={registryButton} disabled={busy}
                      aria-label={t('Use {{account}}', { account: account.label })}
                      onClick={() => void run(() => start('start', { account_id: account.id }))}>
                      {t('Use account')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {addingAccount ? (
              <form className="space-y-2" onSubmit={(event) => {
                event.preventDefault()
                void run(() => start('add', { label: accountLabel }))
              }}>
                <label className="block text-[13px]">
                  {t('Account or workspace name (optional)')}
                  <input className="mt-1 block w-full max-w-sm rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2"
                    value={accountLabel} maxLength={80} onChange={(event) => setAccountLabel(event.target.value)} />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="submit" className={signInButton} disabled={busy}>
                    <ProviderIcon provider="openai_siwc" size={21} />
                    {t('Continue with ChatGPT')}
                  </button>
                  <button type="button" className={registryButton} onClick={() => setAddingAccount(false)}>
                    {t('Cancel')}
                  </button>
                </div>
              </form>
            ) : (
              <button type="button" className={registryButton} disabled={busy} onClick={() => setAddingAccount(true)}>
                {t('Add ChatGPT account or workspace')}
              </button>
            )}
          </div>
        )}
        {status && !status.sharing && !status.pending && !addingAccount &&
          !status.accounts.some(account => account.id === status.active_account_id && account.revocation_pending) && (
          <>
            <p className="max-w-prose text-sm leading-relaxed text-[var(--muted-foreground)]">
              {t(
                'Sign in in your browser and allow plan usage. You can choose models in Language models.'
              )}
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => start('start'))}
              className={signInButton}
            >
              <ProviderIcon provider="openai_siwc" size={21} />
              {t('Continue with ChatGPT')}
            </button>
          </>
        )}
        {status?.pending && (
          <div className="flex flex-wrap items-center gap-2">
            {authorizeUrl && (
              <a className={registryPrimary} href={authorizeUrl} target="_blank" rel="noreferrer">
                {t('Continue in browser')} <ArrowUpRight size={14} aria-hidden />
              </a>
            )}
            <button
              type="button"
              className={registryButton}
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await request('cancel', 'POST')
                  await refresh()
                })
              }
            >
              {t('Cancel')}
            </button>
          </div>
        )}
        {status?.sharing && !status.pending && (
          <Link href={CHATGPT_PLAN_MODELS_URL} className={registryPrimary}>
            {t('Choose language models')} <ArrowUpRight size={14} aria-hidden />
          </Link>
        )}
        {status?.connected && !status.pending && (
          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-3">
            <a
              className="inline-flex items-center gap-1 text-[13px] text-[var(--primary)] hover:underline"
              href={CHATGPT_PLAN_USAGE_URL}
              target="_blank"
              rel="noreferrer"
            >
              {t('Manage ChatGPT usage')} <ArrowUpRight size={14} aria-hidden />
            </a>
            <button
              type="button"
              className={registryButton}
              disabled={busy}
              onClick={() => void run(() => disconnect())}
            >
              {t('Disconnect account')}
            </button>
          </footer>
        )}
      </div>
    </section>
  )
}
