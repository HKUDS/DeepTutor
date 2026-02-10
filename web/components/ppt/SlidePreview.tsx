"use client"

import React from 'react'

import { SlideContent } from '@/types/ppt'

interface SlidePreviewProps {
  slide: SlideContent
  index: number
  themeColor?: string
  accentColor?: string
  isGenerating?: boolean
  onUpdateSlide: (index: number, updatedSlide: SlideContent) => void
}

const SlidePreview: React.FC<SlidePreviewProps> = ({
  slide,
  index,
  themeColor = '#3b82f6',
  accentColor = '#f59e0b',
  isGenerating,
  onUpdateSlide,
}) => {
  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onUpdateSlide(index, { ...slide, title: e.target.value })
  }

  const handlePointChange = (pointIndex: number, newValue: string) => {
    const updatedPoints = [...slide.points]
    updatedPoints[pointIndex] = newValue
    onUpdateSlide(index, { ...slide, points: updatedPoints })
  }

  const layout = slide.layout

  const TextSection = ({
    className = '',
    centered = false,
    dark = false,
  }: {
    className?: string
    centered?: boolean
    dark?: boolean
  }) => (
    <div
      className={`p-5 overflow-y-auto flex flex-col ${centered ? 'items-center justify-center text-center' : ''
        } ${className}`}
    >
      <div className="mb-3 w-full">
        <input
          type="text"
          value={slide.title}
          onChange={handleTitleChange}
          className={`w-full bg-transparent border-none font-bold text-sm outline-none focus:ring-1 focus:ring-blue-100 rounded ${centered ? 'text-center' : ''
            }`}
          style={{ color: dark ? '#FFFFFF' : themeColor }}
          placeholder="Slide Title"
        />
      </div>
      <div className="space-y-1 w-full">
        {slide.points.map((point, i) => (
          <div
            key={`${index}-${i}`}
            className={`flex items-start text-[11px] group/point ${centered ? 'justify-center' : ''
              }`}
          >
            {!centered && (
              <span
                className="mr-2 font-bold shrink-0 mt-0.5"
                style={{ color: dark ? '#FFFFFF' : accentColor }}
              >
                •
              </span>
            )}
            <textarea
              rows={1}
              value={point}
              onChange={(e) => handlePointChange(i, e.target.value)}
              className={`w-full bg-transparent border-none resize-none focus:ring-1 focus:ring-blue-50 rounded px-1 py-0.5 leading-tight outline-none ${centered ? 'text-center italic' : ''
                }`}
              style={{ color: dark ? '#FFFFFF' : '#4b5563' }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement
                target.style.height = 'auto'
                target.style.height = `${target.scrollHeight}px`
              }}
            />
          </div>
        ))}
      </div>
    </div>
  )

  const ImageSection = ({ className = '' }: { className?: string }) => (
    <div className={`relative bg-gray-50 flex-shrink-0 ${className}`}>
      {isGenerating ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-50/80">
          <div className="w-6 h-6 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-2" />
          <span className="text-[9px] text-gray-400 font-medium">Painting...</span>
        </div>
      ) : slide.generatedImageUrl ? (
        <img
          src={slide.generatedImageUrl}
          alt=""
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-gray-300">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-8 w-8"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1}
              d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
            />
          </svg>
        </div>
      )}
    </div>
  )

  let content: React.ReactNode
  switch (layout) {
    case 'SECTION_HEADER':
      content = (
        <div
          className="w-full h-full flex items-center justify-center p-8"
          style={{ backgroundColor: themeColor }}
        >
          <input
            type="text"
            value={slide.title}
            onChange={handleTitleChange}
            className="w-full bg-transparent border-none font-black text-2xl text-white text-center outline-none focus:ring-1 focus:ring-white/30 rounded"
          />
        </div>
      )
      break
    case 'QUOTE':
      content = (
        <div className="w-full h-full flex flex-col items-center justify-center p-10 relative">
          <span
            className="absolute top-4 left-4 text-4xl font-serif opacity-30"
            style={{ color: accentColor }}
          >
            “
          </span>
          <TextSection centered className="w-full" />
          <span
            className="absolute bottom-4 right-4 text-4xl font-serif opacity-30"
            style={{ color: accentColor }}
          >
            ”
          </span>
        </div>
      )
      break
    case 'OVERVIEW':
      content = (
        <div className="w-full h-full p-4 flex flex-col">
          <div className="mb-2 border-b pb-1" style={{ borderColor: accentColor }}>
            <input
              type="text"
              value={slide.title}
              onChange={handleTitleChange}
              className="w-full bg-transparent border-none font-bold text-sm outline-none"
              style={{ color: themeColor }}
            />
          </div>
          <div className="grid grid-cols-2 gap-2 flex-1">
            {slide.points.slice(0, 4).map((point, i) => (
              <div
                key={`${index}-grid-${i}`}
                className="border p-2 rounded bg-slate-50 flex items-center text-[10px]"
                style={{ borderColor: `${accentColor}44` }}
              >
                <textarea
                  rows={2}
                  value={point}
                  onChange={(e) => handlePointChange(i, e.target.value)}
                  className="w-full bg-transparent border-none resize-none outline-none text-gray-600"
                />
              </div>
            ))}
          </div>
        </div>
      )
      break
    case 'SPLIT_RIGHT':
    case 'SPLIT_IMAGE_RIGHT':
      content = (
        <>
          <TextSection className="w-3/5" />
          <ImageSection className="w-2/5 border-l" />
        </>
      )
      break
    case 'SPLIT_LEFT':
    case 'SPLIT_IMAGE_LEFT':
      content = (
        <>
          <ImageSection className="w-2/5 border-r" />
          <TextSection className="w-3/5" />
        </>
      )
      break
    case 'TOP_IMAGE':
      content = (
        <div className="flex flex-col w-full">
          <ImageSection className="h-2/5 w-full border-b" />
          <TextSection className="h-3/5 w-full" />
        </div>
      )
      break
    case 'TYPOGRAPHIC_WITH_IMAGE':
      content = (
        <div className="w-full h-full p-4 flex gap-4">
          <TextSection className="flex-1" />
          <div className="w-1/3 relative flex items-center justify-center">
            <div
              className="absolute inset-0 border-2"
              style={{ borderColor: accentColor, margin: '10%' }}
            />
            <ImageSection className="w-4/5 h-4/5 shadow-md relative z-10" />
          </div>
        </div>
      )
      break
    default:
      content = (
        <div className="flex w-full items-center justify-center">
          <div className="w-2 h-full shrink-0" style={{ backgroundColor: themeColor }} />
          <TextSection className="flex-1" />
        </div>
      )
  }

  return (
    <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden flex flex-col aspect-[16/9] transition-all hover:shadow-xl group relative">
      <div className="absolute top-2 right-2 z-20">
        <span className="text-[7px] bg-slate-800/80 text-white px-1.5 py-0.5 rounded backdrop-blur-sm opacity-60 group-hover:opacity-100 transition-opacity uppercase font-bold">
          {layout.replace(/_/g, ' ')}
        </span>
      </div>

      <div className="flex-1 flex overflow-hidden">{content}</div>

      {slide.imagePrompt && (
        <div className="px-4 py-1.5 bg-gray-50 border-t border-gray-100 italic text-[7px] text-gray-400 truncate opacity-0 group-hover:opacity-100 transition-opacity">
          AI Design: {slide.imagePrompt}
        </div>
      )}
    </div>
  )
}

export default SlidePreview
