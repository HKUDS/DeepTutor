import { apiUrl } from '@/lib/api'
import { invalidateClientCache, withClientCache } from '@/lib/client-cache'

const CACHE_PREFIX = 'structure-note:'

export type StructureNoteStatus =
  | 'queued'
  | 'normalizing'
  | 'indexing'
  | 'planning'
  | 'generating'
  | 'processing_images'
  | 'rendering'
  | 'ready'
  | 'failed'

export type StructureNoteDifficulty = 'simple' | 'medium' | 'detailed'
export type StructureNoteLanguage = 'zh' | 'en'
export type StructureNoteStyleLevel = 'low' | 'medium' | 'high'

export interface StructureNoteCitation {
  citation_id: string
  section_path: string[]
  page_start: number
  page_end: number
  source_file: string
  source_kind: 'text' | 'image'
  image_page?: number | null
  image_region?: number[] | null
  excerpt?: string | null
}

export interface StructureNoteSection {
  section_id: string
  title: string
  level: number
  page_start: number
  page_end: number
  summary?: string
  parent_id?: string | null
  child_ids?: string[]
  path?: string[]
}

export interface StructureNoteJob {
  job_id: string
  file_name: string
  status: StructureNoteStatus
  source_format: string
  difficulty_level: StructureNoteDifficulty
  note_language: StructureNoteLanguage
  style_level: StructureNoteStyleLevel
  project_name?: string | null
  note_title?: string | null
  source_kind?: 'upload' | 'knowledge_base'
  source_ref?: Record<string, string>
  final_pdf_url: string | null
  rendered_markdown_url: string | null
  asset_base_url: string | null
  sections: StructureNoteSection[]
  citations: StructureNoteCitation[]
  retry_available: boolean
  error: string | null
  task_id: string | null
  created_at: string
  updated_at: string
}

export interface StructureNoteKbFile {
  file_id: string
  file_name: string
  display_path: string
  size_bytes: number
  updated_at: string
}

export interface StructureNoteKbGroup {
  kb_name: string
  files: StructureNoteKbFile[]
}

export interface StructureNoteProject {
  name: string
  created_at: string
  updated_at: string
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string') {
        detail = payload.detail
      }
    } catch {}
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export async function listStructureNoteProjects(options?: { force?: boolean }) {
  return withClientCache<StructureNoteProject[]>(
    `${CACHE_PREFIX}projects`,
    async () => {
      const response = await fetch(apiUrl('/api/v1/structure-note/projects'), {
        cache: 'no-store',
      })
      const data = await expectJson<{ projects?: StructureNoteProject[] }>(response)
      return Array.isArray(data.projects) ? data.projects : []
    },
    {
      force: options?.force,
      ttlMs: 10_000,
    }
  )
}

export async function createStructureNoteProject(name: string): Promise<StructureNoteProject> {
  const formData = new FormData()
  formData.append('name', name)
  const response = await fetch(apiUrl('/api/v1/structure-note/projects'), {
    method: 'POST',
    body: formData,
  })
  const data = await expectJson<StructureNoteProject>(response)
  invalidateClientCache(CACHE_PREFIX)
  return data
}

export async function renameStructureNoteProject(
  projectName: string,
  newName: string
): Promise<StructureNoteProject> {
  const formData = new FormData()
  formData.append('new_name', newName)
  const response = await fetch(
    apiUrl(`/api/v1/structure-note/projects/${encodeURIComponent(projectName)}/rename`),
    {
      method: 'POST',
      body: formData,
    }
  )
  const data = await expectJson<StructureNoteProject>(response)
  invalidateClientCache(CACHE_PREFIX)
  return data
}

export async function deleteStructureNoteProject(
  projectName: string
): Promise<{ deleted_job_ids: string[] }> {
  const response = await fetch(
    apiUrl(`/api/v1/structure-note/projects/${encodeURIComponent(projectName)}`),
    {
      method: 'DELETE',
    }
  )
  const data = await expectJson<{ deleted_job_ids: string[] }>(response)
  invalidateClientCache(CACHE_PREFIX)
  return data
}

export async function listStructureNoteKnowledgeBaseFiles(options?: { force?: boolean }) {
  return withClientCache<StructureNoteKbGroup[]>(
    `${CACHE_PREFIX}kb-files`,
    async () => {
      const response = await fetch(apiUrl('/api/v1/structure-note/kb/files'), {
        cache: 'no-store',
      })
      const data = await expectJson<{ knowledge_bases?: StructureNoteKbGroup[] }>(response)
      return Array.isArray(data.knowledge_bases) ? data.knowledge_bases : []
    },
    {
      force: options?.force,
      ttlMs: 10_000,
    }
  )
}

export async function listStructureNoteJobs(options?: { force?: boolean }) {
  return withClientCache<StructureNoteJob[]>(
    `${CACHE_PREFIX}jobs`,
    async () => {
      const response = await fetch(apiUrl('/api/v1/structure-note/jobs'), {
        cache: 'no-store',
      })
      const data = await expectJson<{ jobs?: StructureNoteJob[] }>(response)
      return Array.isArray(data.jobs) ? data.jobs : []
    },
    {
      force: options?.force,
      ttlMs: 10_000,
    }
  )
}

export async function getStructureNoteJob(jobId: string): Promise<StructureNoteJob> {
  const response = await fetch(apiUrl(`/api/v1/structure-note/jobs/${jobId}`), {
    cache: 'no-store',
  })
  return expectJson<StructureNoteJob>(response)
}

export async function createStructureNoteJob(
  file: File,
  difficultyLevel: StructureNoteDifficulty,
  noteLanguage: StructureNoteLanguage,
  styleLevel: StructureNoteStyleLevel,
  projectName?: string | null
): Promise<StructureNoteJob> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('difficulty_level', difficultyLevel)
  formData.append('note_language', noteLanguage)
  formData.append('style_level', styleLevel)
  if (projectName) {
    formData.append('project_name', projectName)
  }
  const response = await fetch(apiUrl('/api/v1/structure-note/jobs'), {
    method: 'POST',
    body: formData,
  })
  const data = await expectJson<StructureNoteJob>(response)
  invalidateClientCache(CACHE_PREFIX)
  return data
}

export async function createStructureNoteJobFromKnowledgeBase(
  kbName: string,
  fileId: string,
  difficultyLevel: StructureNoteDifficulty,
  noteLanguage: StructureNoteLanguage,
  styleLevel: StructureNoteStyleLevel,
  projectName?: string | null
): Promise<StructureNoteJob> {
  const formData = new FormData()
  formData.append('kb_name', kbName)
  formData.append('file_id', fileId)
  formData.append('difficulty_level', difficultyLevel)
  formData.append('note_language', noteLanguage)
  formData.append('style_level', styleLevel)
  if (projectName) {
    formData.append('project_name', projectName)
  }
  const response = await fetch(apiUrl('/api/v1/structure-note/jobs/from-kb'), {
    method: 'POST',
    body: formData,
  })
  const data = await expectJson<StructureNoteJob>(response)
  invalidateClientCache(CACHE_PREFIX)
  return data
}

export async function retryStructureNoteJob(jobId: string): Promise<StructureNoteJob> {
  const response = await fetch(apiUrl(`/api/v1/structure-note/jobs/${jobId}/retry`), {
    method: 'POST',
  })
  const data = await expectJson<StructureNoteJob>(response)
  invalidateClientCache(CACHE_PREFIX)
  return data
}

export async function fetchStructureNoteMarkdown(markdownUrl: string): Promise<string> {
  const response = await fetch(apiUrl(markdownUrl), {
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Markdown download failed: ${response.status}`)
  }
  return response.text()
}

export function invalidateStructureNoteCaches() {
  invalidateClientCache(CACHE_PREFIX)
}
