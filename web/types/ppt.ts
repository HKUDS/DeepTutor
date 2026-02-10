export type SlideLayout =
  | 'SPLIT_RIGHT'
  | 'SPLIT_LEFT'
  | 'TOP_IMAGE'
  | 'TYPOGRAPHIC'
  | 'SECTION_HEADER'
  | 'QUOTE'
  | 'OVERVIEW'
  | 'SPLIT_IMAGE_LEFT'
  | 'SPLIT_IMAGE_RIGHT'
  | 'TYPOGRAPHIC_WITH_IMAGE'

export interface SlideContent {
  title: string
  points: string[]
  imagePrompt?: string
  generatedImageUrl?: string
  layout: SlideLayout
  iconName?: string
}

export interface PresentationOutline {
  title: string
  subtitle: string
  themeColor: string
  accentColor: string
  slides: SlideContent[]
}

export enum AppState {
  IDLE = 'IDLE',
  GENERATING_OUTLINE = 'GENERATING_OUTLINE',
  GENERATING_IMAGES = 'GENERATING_IMAGES',
  REVIEWING = 'REVIEWING',
  EXPORTING = 'EXPORTING',
}
