import { PresentationOutline, SlideContent } from '@/types/ppt'

export const exportToPptx = async (outline: PresentationOutline) => {
  const { default: PptxGenJS } = await import('pptxgenjs')
  const pptx = new PptxGenJS()
  pptx.layout = 'LAYOUT_16x9'

  const themeColor = outline.themeColor.replace('#', '')
  const accentColor = outline.accentColor.replace('#', '')

  const titleSlide = pptx.addSlide()
  titleSlide.background = { color: 'FFFFFF' }

  titleSlide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: '40%',
    h: '100%',
    fill: { color: themeColor },
  })

  titleSlide.addText(outline.title, {
    x: '45%',
    y: 1.5,
    w: '50%',
    h: 1.5,
    fontSize: 44,
    bold: true,
    color: '1A1A1A',
    align: 'left',
    fontFace: 'Microsoft YaHei',
  })

  titleSlide.addShape(pptx.ShapeType.rect, {
    x: '45%',
    y: 3.0,
    w: 2.0,
    h: 0.05,
    fill: { color: accentColor },
  })

  titleSlide.addText(outline.subtitle, {
    x: '45%',
    y: 3.3,
    w: '50%',
    h: 0.5,
    fontSize: 22,
    color: '666666',
    align: 'left',
  })

  outline.slides.forEach((slideData: SlideContent) => {
    const slide = pptx.addSlide()
    const hasImage = !!slideData.generatedImageUrl
    const layout = slideData.layout

    const bulletPoints = slideData.points.map((point) => ({
      text: point,
      options: {
        bullet: true,
        margin: 10,
        color: '333333',
        fontFace: 'Microsoft YaHei',
        paraSpaceAfter: 8,
        paraSpaceBefore: 2,
      },
    }))

    slide.addText(outline.title, {
      x: 0.5,
      y: 5.3,
      w: '40%',
      h: 0.3,
      fontSize: 9,
      color: 'AAAAAA',
    })

    if (layout === 'SECTION_HEADER') {
      slide.background = { color: themeColor }
      slide.addText(slideData.title, {
        x: 1,
        y: 2,
        w: 8,
        h: 1.5,
        fontSize: 54,
        bold: true,
        color: 'FFFFFF',
        align: 'center',
        fontFace: 'Microsoft YaHei',
      })
      slide.addShape(pptx.ShapeType.rect, {
        x: 4,
        y: 3.5,
        w: 2,
        h: 0.08,
        fill: { color: 'FFFFFF' },
      })
    } else if (layout === 'QUOTE') {
      slide.addText('“', {
        x: 0.5,
        y: 1.0,
        w: 1,
        h: 1,
        fontSize: 80,
        color: accentColor,
        bold: true,
      })
      slide.addText(slideData.points[0] || slideData.title, {
        x: 1.5,
        y: 1.5,
        w: 7,
        h: 2.5,
        fontSize: 32,
        italic: true,
        color: '222222',
        align: 'center',
        fontFace: 'Microsoft YaHei',
      })
      slide.addText('”', {
        x: 8.5,
        y: 3.5,
        w: 1,
        h: 1,
        fontSize: 80,
        color: accentColor,
        bold: true,
      })
    } else if (layout === 'OVERVIEW') {
      slide.addText(slideData.title, {
        x: 0.5,
        y: 0.3,
        w: 9,
        h: 0.7,
        fontSize: 32,
        bold: true,
        color: themeColor,
        fontFace: 'Microsoft YaHei',
      })
      const gridPoints = slideData.points.slice(0, 4)
      gridPoints.forEach((point, idx) => {
        const xPos = idx % 2 === 0 ? 0.5 : 5.1
        const yPos = idx < 2 ? 1.2 : 3.2
        slide.addShape(pptx.ShapeType.rect, {
          x: xPos,
          y: yPos,
          w: 4.4,
          h: 1.8,
          line: { color: accentColor, width: 2 },
          fill: { color: 'F9F9F9' },
        })
        slide.addText(point, {
          x: xPos + 0.2,
          y: yPos + 0.2,
          w: 4,
          h: 1.4,
          fontSize: 18,
          color: '333333',
          valign: 'middle',
          fontFace: 'Microsoft YaHei',
        })
      })
    } else if (
      (layout === 'SPLIT_RIGHT' || layout === 'SPLIT_IMAGE_RIGHT') &&
      hasImage
    ) {
      slide.addText(slideData.title, {
        x: 0.5,
        y: 0.4,
        w: 4.5,
        h: 0.8,
        fontSize: 28,
        bold: true,
        color: themeColor,
        fontFace: 'Microsoft YaHei',
      })
      slide.addText(bulletPoints, {
        x: 0.5,
        y: 1.2,
        w: 4.5,
        h: 4,
        fontSize: 16,
        valign: 'top',
      })
      slide.addImage({
        data: slideData.generatedImageUrl,
        x: 5,
        y: 0,
        w: 5,
        h: 5.625,
        sizing: { type: 'cover', w: 5, h: 5.625 },
      })
    } else if (
      (layout === 'SPLIT_LEFT' || layout === 'SPLIT_IMAGE_LEFT') &&
      hasImage
    ) {
      slide.addText(slideData.title, {
        x: 5.2,
        y: 0.4,
        w: 4.5,
        h: 0.8,
        fontSize: 28,
        bold: true,
        color: themeColor,
        fontFace: 'Microsoft YaHei',
      })
      slide.addText(bulletPoints, {
        x: 5.2,
        y: 1.2,
        w: 4.5,
        h: 4,
        fontSize: 16,
        valign: 'top',
      })
      slide.addImage({
        data: slideData.generatedImageUrl,
        x: 0,
        y: 0,
        w: 5,
        h: 5.625,
        sizing: { type: 'cover', w: 5, h: 5.625 },
      })
    } else if (layout === 'TOP_IMAGE' && hasImage) {
      slide.addImage({
        data: slideData.generatedImageUrl,
        x: 0,
        y: 0,
        w: '100%',
        h: 2.8,
        sizing: { type: 'cover', w: 10, h: 2.8 },
      })
      slide.addShape(pptx.ShapeType.rect, {
        x: 0,
        y: 2.8,
        w: '100%',
        h: 0.05,
        fill: { color: accentColor },
      })
      slide.addText(slideData.title, {
        x: 0.5,
        y: 3.0,
        w: '90%',
        h: 0.6,
        fontSize: 26,
        bold: true,
        color: themeColor,
        fontFace: 'Microsoft YaHei',
      })
      slide.addText(bulletPoints, {
        x: 0.5,
        y: 3.7,
        w: '90%',
        h: 1.5,
        fontSize: 16,
        valign: 'top',
      })
    } else if (layout === 'TYPOGRAPHIC_WITH_IMAGE' && hasImage) {
      slide.addText(slideData.title, {
        x: 0.5,
        y: 0.5,
        w: 6,
        h: 1,
        fontSize: 36,
        bold: true,
        color: themeColor,
        fontFace: 'Microsoft YaHei',
      })
      slide.addText(bulletPoints, {
        x: 0.5,
        y: 1.8,
        w: 6,
        h: 3,
        fontSize: 18,
        valign: 'top',
      })
      slide.addImage({
        data: slideData.generatedImageUrl,
        x: 6.8,
        y: 1.5,
        w: 2.8,
        h: 2.8,
        sizing: { type: 'cover', w: 2.8, h: 2.8 },
      })
      slide.addShape(pptx.ShapeType.rect, {
        x: 6.6,
        y: 1.3,
        w: 3.2,
        h: 3.2,
        line: { color: accentColor, width: 3 },
      })
    } else {
      slide.addShape(pptx.ShapeType.rect, {
        x: 0,
        y: 0,
        w: '100%',
        h: 0.1,
        fill: { color: themeColor },
      })
      slide.addText(slideData.title, {
        x: 0.5,
        y: 0.5,
        w: 9,
        h: 1,
        fontSize: 36,
        bold: true,
        color: themeColor,
        align: 'center',
        fontFace: 'Microsoft YaHei',
      })
      slide.addText(bulletPoints, {
        x: 1.5,
        y: 1.8,
        w: 7,
        h: 3,
        fontSize: 20,
        valign: 'top',
        align: 'left',
      })
    }
  })

  const safeTitle = outline.title.replace(/\s+/g, '_')
  await pptx.writeFile({ fileName: `${safeTitle}.pptx` })
}
