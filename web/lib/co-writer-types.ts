export interface CoWriterDocumentSummary {
  id: string
  title: string
  created_at: number
  updated_at: number
  preview: string
}

export interface CoWriterDocument {
  id: string
  title: string
  content: string
  created_at: number
  updated_at: number
}
