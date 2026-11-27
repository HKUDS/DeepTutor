import { apiFetch } from '@/shared/api/client'
import { CalendarRequestError } from './api'

/**
 * Calendar-page download helper. Keep this out of `api.ts` so the workspace
 * reminder runtime does not pull blob-saving code into every layout.
 */

const endpoint = '/api/calendar'

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1].trim())
    } catch {
      /* malformed percent-encoding — use the quoted form */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain?.[1]?.trim() || fallback
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function exportIcs(calendarId?: string): Promise<void> {
  const search = calendarId ? `?calendar_id=${encodeURIComponent(calendarId)}` : ''
  const response = await apiFetch(`${endpoint}/export.ics${search}`, {
    cache: 'no-store',
  })
  if (!response.ok) {
    let detail = ''
    try {
      detail = String((await response.json())?.detail ?? '')
    } catch {
      /* no body */
    }
    throw new CalendarRequestError(response.status, detail)
  }
  saveBlob(
    await response.blob(),
    filenameFromDisposition(response.headers.get('content-disposition'), 'calendar.ics')
  )
}
