/** Same-origin routes that serve a file already referenced by a conversation. */
export function isChatFileLink(href: string): boolean {
  if (!href.startsWith('/files/') || /[\\\r\n\t]/.test(href)) return false
  const { pathname } = new URL(href, 'http://deeptutor.local')
  return /^\/files\/(?:workspace-items\/ws_[a-f\d]{32}\/wsi_[a-f\d]{32}|(?:outputs|attachments)\/.+)$/.test(
    pathname
  )
}

/** Published lesson pages render model-written scripts in the lesson sandbox. */
export function isChatVideoLessonLink(href: string): boolean {
  if (!isChatFileLink(href)) return false
  const { pathname } = new URL(href, 'http://deeptutor.local')
  return /^\/files\/outputs\/(?:[^/]+\/)*video_lesson\/(?:[^/]+\/)*[^/]+\.html$/.test(pathname)
}
