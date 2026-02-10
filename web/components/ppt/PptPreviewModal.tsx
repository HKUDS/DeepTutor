"use client"

import React from 'react'
import { X } from 'lucide-react'

import SlidePreview from '@/components/ppt/SlidePreview'
import { PresentationOutline, SlideContent } from '@/types/ppt'

interface ImageProgress {
  current: number
  total: number
}

interface PptPreviewModalProps {
  isOpen: boolean
  outline: PresentationOutline | null
  isExporting: boolean
  imageProgress?: ImageProgress
  generatingSlideIndices?: number[]
  onClose: () => void
  onExport: () => void
  onUpdateSlide: (index: number, updatedSlide: SlideContent) => void
}

export default function PptPreviewModal({
  isOpen,
  outline,
  isExporting,
  imageProgress,
  generatingSlideIndices = [],
  onClose,
  onExport,
  onUpdateSlide,
}: PptPreviewModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <div className="relative w-full max-w-6xl h-[90vh] bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <div className="text-sm font-semibold text-slate-700">PPT 预览</div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onExport}
              disabled={!outline || isExporting}
              className="px-4 py-2 text-sm rounded-lg bg-slate-900 text-white hover:bg-slate-800 transition-colors disabled:opacity-50"
            >
              {isExporting ? '导出中...' : '导出 PPT'}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors"
            >
              <X className="w-4 h-4 text-slate-500" />
            </button>
          </div>
        </div>

        {outline ? (
          <div className="flex-1 overflow-hidden flex flex-col">
            <div className="px-6 pt-4 pb-2 flex items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-3 h-3 rounded"
                    style={{ backgroundColor: outline.themeColor }}
                  />
                  <span
                    className="w-3 h-3 rounded"
                    style={{ backgroundColor: outline.accentColor }}
                  />
                  <span className="text-xs text-slate-400 uppercase tracking-wider">
                    Theme
                  </span>
                </div>
                <h3 className="text-xl font-bold text-slate-900">{outline.title}</h3>
                {outline.subtitle && (
                  <p className="text-sm text-slate-500">{outline.subtitle}</p>
                )}
              </div>

              {imageProgress && imageProgress.total > 0 && (
                <div className="text-xs text-slate-500">
                  图片生成 {Math.min(imageProgress.current, imageProgress.total)}/
                  {imageProgress.total}
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto px-6 pb-6">
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {outline.slides.map((slide, index) => (
                  <SlidePreview
                    key={`${slide.title}-${index}`}
                    slide={slide}
                    index={index}
                    themeColor={outline.themeColor}
                    accentColor={outline.accentColor}
                    isGenerating={generatingSlideIndices.includes(index)}
                    onUpdateSlide={onUpdateSlide}
                  />
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
            正在生成大纲...
          </div>
        )}
      </div>
    </div>
  )
}
