import { createLucideIcon } from 'lucide-react'

/**
 * The five shelves' own marks, drawn as one family: the same 24px grid,
 * rounded joins and optical weight, so the bar reads as a set rather than
 * five icons borrowed from different places. Each has a body
 * (`dt-shelf-fill`) the selected tab tints, so selection shows in the glyph
 * itself and not only in the pill behind it.
 */
const fill = 'dt-shelf-fill'

export const HomeShelfIcon = createLucideIcon('home-shelf', [
  [
    'path',
    {
      d: 'M4 10.4a2 2 0 0 1 .74-1.55l6-4.9a2 2 0 0 1 2.52 0l6 4.9A2 2 0 0 1 20 10.4V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z',
      className: fill,
      key: 'house',
    },
  ],
  ['path', { d: 'M9.75 20v-4.25a2.25 2.25 0 0 1 4.5 0V20', key: 'door' }],
])

export const LearningShelfIcon = createLucideIcon('learning-shelf', [
  [
    'path',
    {
      d: 'M12 7.4C10.3 5.8 7.8 5.15 4.9 5.3a.95.95 0 0 0-.9.95v11.4c0 .55.46.98 1 .95 2.6-.15 4.95.5 7 2',
      className: fill,
      key: 'left',
    },
  ],
  [
    'path',
    {
      d: 'M12 7.4c1.7-1.6 4.2-2.25 7.1-2.1a.95.95 0 0 1 .9.95v11.4c0 .55-.46.98-1 .95-2.6-.15-4.95.5-7 2',
      className: fill,
      key: 'right',
    },
  ],
  ['path', { d: 'M12 7.4v13.2', key: 'spine' }],
])

export const ResourcesShelfIcon = createLucideIcon('resources-shelf', [
  [
    'path',
    {
      d: 'M3.75 7.25a2 2 0 0 1 2-2h3.2a2 2 0 0 1 1.52.7l1.06 1.25a2 2 0 0 0 1.52.7h5.2a2 2 0 0 1 2 2v7.85a2 2 0 0 1-2 2H5.75a2 2 0 0 1-2-2z',
      className: fill,
      key: 'folder',
    },
  ],
  ['path', { d: 'M3.75 10.4h16.5', key: 'lip' }],
])

export const PartnersShelfIcon = createLucideIcon('partners-shelf', [
  [
    'path',
    {
      d: 'M12 4c4.56 0 8.25 3.25 8.25 7.25S16.56 18.5 12 18.5c-.98 0-1.92-.15-2.8-.43L5.1 19.6l1.18-3.38C4.84 14.92 3.75 13.18 3.75 11.25 3.75 7.25 7.44 4 12 4z',
      className: fill,
      key: 'bubble',
    },
  ],
  ['path', { d: 'M9 12.1c.75.95 1.75 1.45 3 1.45s2.25-.5 3-1.45', key: 'smile' }],
])

export const PersonalizationShelfIcon = createLucideIcon('personalization-shelf', [
  ['circle', { cx: '10', cy: '8.25', r: '3.5', className: fill, key: 'head' }],
  ['path', { d: 'M3.75 19.75c.55-3.35 3.15-5.6 6.25-5.6 1.2 0 2.32.33 3.27.92', key: 'shoulders' }],
  [
    'path',
    {
      d: 'M17.75 12.75c.3 1.65 1.35 2.7 3 3-1.65.3-2.7 1.35-3 3-.3-1.65-1.35-2.7-3-3 1.65-.3 2.7-1.35 3-3z',
      className: fill,
      key: 'spark',
    },
  ],
])
