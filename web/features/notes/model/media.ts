export const noteMediaAccept =
  'image/png,image/jpeg,image/gif,image/webp,audio/mpeg,audio/wav,video/mp4,application/pdf'
export function noteMediaType(file: Pick<File, 'type' | 'size'>) {
  if (!noteMediaAccept.split(',').includes(file.type))
    throw new Error('Unsupported attachment type')
  if (!file.size || file.size > 25 * 1024 * 1024)
    throw new Error('Attachments must be between 1 byte and 25 MB')
  return file.type.startsWith('image/')
    ? 'image'
    : file.type.startsWith('audio/')
      ? 'audio'
      : file.type.startsWith('video/')
        ? 'video'
        : 'file'
}
