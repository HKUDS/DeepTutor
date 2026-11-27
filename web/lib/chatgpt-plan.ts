import { apiFetch, apiUrl } from '@/shared/api/client'

export const CHATGPT_PLAN_PROVIDER = 'openai_chatgpt_plan'
export const CHATGPT_PLAN_LABEL = 'ChatGPT Plan'
export const CHATGPT_PLAN_USAGE_URL = 'https://chatgpt.com/settings/usage'
export const CHATGPT_PLAN_ACCOUNT_URL = '/settings/connections?chatgpt-plan=1'
export const CHATGPT_PLAN_MODELS_URL = '/settings/llm?add=1&provider=openai_chatgpt_plan'
export const CHATGPT_PLAN_USAGE_LIMIT = 'chatgpt_plan_usage_limit'
export const CHATGPT_PLAN_LOGIN_REQUIRED = 'chatgpt_plan_login_required'

export type PlanModel = { id: string; label: string }
export type PlanStatus = {
  connected: boolean
  sharing: boolean
  pending: boolean
  account: string | null
  active_account_id: string | null
  accounts: { id: string; label: string; connected: boolean; revocation_pending: boolean }[]
  show_welcome: boolean
  error: string | null
}

export async function requestChatGPTPlan<T>(
  action: string,
  method = 'GET',
  signal?: AbortSignal,
  payload?: { account_id?: string; label?: string }
): Promise<T> {
  const response = await apiFetch(apiUrl(`/api/settings/providers/chatgpt-plan/${action}`), {
    method,
    signal,
    ...(payload && { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  })
  const result = await response.json()
  if (!response.ok) {
    throw new Error(typeof result.detail === 'string' ? result.detail : 'connection_failed')
  }
  return result as T
}
