'use client'
import dynamic from 'next/dynamic'
import { installDemoTransport } from '@/features/preview/demo-transport'
import 'katex/dist/katex.min.css'
import './preview.css'

installDemoTransport()
const PreviewWorkspace = dynamic(() => import('@/features/preview/PreviewWorkspace'), {
  ssr: false,
})
export default function PreviewClient() {
  return <PreviewWorkspace />
}
