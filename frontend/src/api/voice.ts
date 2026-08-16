import { apiFetch } from './http'

let current: HTMLAudioElement | null = null

export function stopSpeech(): void {
  if (!current) return
  current.pause()
  current.src = ''
  current = null
}

export async function speakReply(text: string): Promise<void> {
  const clipped = text.replace(/\s+/g, ' ').trim().slice(0, 4000)
  if (!clipped) return
  stopSpeech()
  try {
    const response = await apiFetch('/api/v1/voice/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clipped }),
    })
    if (!response.ok) return
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    current = audio
    audio.onended = () => {
      URL.revokeObjectURL(url)
      if (current === audio) current = null
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      if (current === audio) current = null
    }
    await audio.play()
  } catch {
    /* TTS not configured or blocked — preference is still saved */
  }
}
