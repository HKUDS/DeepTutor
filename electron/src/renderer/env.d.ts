/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_TITLE: string
  readonly NEXT_PUBLIC_IS_DESKTOP: string
  readonly NEXT_PUBLIC_API_BASE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
