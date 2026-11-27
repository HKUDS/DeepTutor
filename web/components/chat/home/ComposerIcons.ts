import { createLucideIcon, type LucideIcon } from 'lucide-react'

/**
 * The composer's own marks for the choices that mean "let Dito decide".
 *
 * Drawn on the same 24px grid and weight as the shelf icons, two-tone: the
 * body (`dt-duo`) carries a light wash of the line colour, so a mark reads as
 * a shape and not a scribble at 14–16px, and it picks up the accent with the
 * row around it.
 */
const duo = 'dt-duo'
const solid = 'dt-duo-solid'

/** Skills as Dito needs them: a hand of cards, the front one lit. */
export const SkillDeckIcon = createLucideIcon('skill-deck', [
  ['path', { d: 'M8.75 6.5V5.25a2 2 0 0 1 2-2h7.5a2 2 0 0 1 2 2V15.5a2 2 0 0 1-2 2h-1.5', key: 'back' }],
  ['rect', { x: '3.75', y: '6.5', width: '12.75', height: '14.25', rx: '2.25', className: duo, key: 'front' }],
  [
    'path',
    {
      d: 'M10.1 10.6c.3 1.6 1.25 2.55 2.85 2.85-1.6.3-2.55 1.25-2.85 2.85-.3-1.6-1.25-2.55-2.85-2.85 1.6-.3 2.55-1.25 2.85-2.85z',
      className: solid,
      key: 'spark',
    },
  ],
])

/** Every connected service: Dito at the hub, each service on its own branch. */
export const ConnectorHubIcon = createLucideIcon('connector-hub', [
  ['circle', { cx: '12', cy: '12.6', r: '2.1', className: solid, key: 'hub' }],
  ['circle', { cx: '12', cy: '4.2', r: '2.3', className: duo, key: 'a' }],
  ['circle', { cx: '4.7', cy: '16.8', r: '2.3', className: duo, key: 'b' }],
  ['circle', { cx: '19.3', cy: '16.8', r: '2.3', className: duo, key: 'c' }],
  ['path', { d: 'M12 10.1V6.9M9.85 13.85l-3.1 1.8M14.15 13.85l3.1 1.8', key: 'spokes' }],
])

/** Dito's usual voice: a plain reply, nothing put on. */
export const PlainVoiceIcon = createLucideIcon('plain-voice', [
  [
    'path',
    {
      d: 'M12 4c4.42 0 8 2.95 8 6.6s-3.58 6.6-8 6.6c-.93 0-1.82-.13-2.65-.37L5.1 18.75l1.05-3.35C4.8 14.2 4 12.5 4 10.6 4 6.95 7.58 4 12 4z',
      className: duo,
      key: 'bubble',
    },
  ],
  ['path', { d: 'M8.75 9.35h6.5M8.75 12.35h3.75', key: 'lines' }],
])

/*
 * The modes, drawn as one family: a washed body that says what the mode
 * works on, and a single solid accent for what it brings to it.
 */

/** Ask Questions: Dito turns the question around. */
const AskBackIcon = createLucideIcon('mode-ask', [
  [
    'path',
    {
      d: 'M5.5 3h13A2.5 2.5 0 0 1 21 5.5V15a2.5 2.5 0 0 1-2.5 2.5H12l-4.5 3.5v-3.5h-2A2.5 2.5 0 0 1 3 15V5.5A2.5 2.5 0 0 1 5.5 3z',
      className: duo,
      key: 'bubble',
    },
  ],
  ['path', { d: 'M9.65 8.35a2.35 2.35 0 1 1 3.525 2.035c-.72.42-1.175.9-1.175 1.6', strokeWidth: '1.8', key: 'hook' }],
  ['circle', { cx: '12', cy: '14.45', r: '.95', className: solid, stroke: 'none', key: 'dot' }],
])

/** Quiz: a sheet checked as it is answered — one mark right, one still open. */
const QuizSheetIcon = createLucideIcon('mode-quiz', [
  ['rect', { x: '4', y: '2.75', width: '16', height: '18.5', rx: '3', className: duo, key: 'sheet' }],
  ['path', { d: 'm7.25 9 1.6 1.6 3.15-3.35', strokeWidth: '1.9', key: 'right' }],
  ['path', { d: 'M14.25 9h2.5', key: 'a' }],
  ['circle', { cx: '9.4', cy: '15.25', r: '1.75', key: 'open' }],
  ['path', { d: 'M14.25 15.25h2.5', key: 'b' }],
])

/** Visualize: a pie with one share drawn out and lit. */
const VisualizeRingIcon = createLucideIcon('mode-visualize', [
  ['path', { d: 'M11 5a8 8 0 1 0 8 8h-8z', className: duo, key: 'rest' }],
  ['path', { d: 'M13 3v8h8a8 8 0 0 0-8-8z', className: solid, key: 'share' }],
])

/** Solve: a stair climbed one step at a time, the answer flagged at the top. */
const SolveStepsIcon = createLucideIcon('mode-solve', [
  ['path', { d: 'M3 21v-4h6v-4h6V9h6v12z', className: duo, key: 'stairs' }],
  ['path', { d: 'M17.25 9V3.5', key: 'pole' }],
  ['path', { d: 'M17.25 3.5 21.5 5.4l-4.25 1.9z', className: solid, key: 'flag' }],
])

/** Research: a lens, and what it turns up. */
const ResearchLensIcon = createLucideIcon('mode-research', [
  ['circle', { cx: '10.5', cy: '10.5', r: '7.25', className: duo, key: 'lens' }],
  ['path', { d: 'm15.75 15.75 5 5', strokeWidth: '2', key: 'handle' }],
  [
    'path',
    {
      d: 'M10.5 6.4c.4 2.15 1.55 3.3 3.7 3.7-2.15.4-3.3 1.55-3.7 3.7-.4-2.15-1.55-3.3-3.7-3.7 2.15-.4 3.3-1.55 3.7-3.7z',
      className: solid,
      strokeLinejoin: 'round',
      key: 'find',
    },
  ],
])

/** Audio Overview: a recording, voices rising and falling. */
const AudioVoicesIcon = createLucideIcon('mode-audio', [
  ['rect', { x: '2.5', y: '4.75', width: '19', height: '14.5', rx: '7.25', className: duo, key: 'tape' }],
  ['path', { d: 'M7 10.75v2.5M9.5 8.5v7M12 9.75v4.5M14.5 8v8M17 10.5v3', strokeWidth: '1.8', key: 'wave' }],
])

/** Math animation: a curve set going. */
const MathMotionIcon = createLucideIcon('mode-math-animator', [
  ['rect', { x: '2.75', y: '4.5', width: '18.5', height: '15', rx: '3', className: duo, key: 'frame' }],
  ['path', { d: 'M5.75 12c1.25-3.5 2.5-3.5 3.75 0s2.5 3.5 3.75 0', key: 'curve' }],
  ['path', { d: 'M15.75 9.6v4.8l3.75-2.4z', className: solid, strokeLinejoin: 'round', key: 'play' }],
])

/** The tray's own marks for each mode; anything else keeps the icon it came with. */
export const MODE_ICONS: Record<string, LucideIcon> = {
  ask_questions: AskBackIcon,
  deep_question: QuizSheetIcon,
  visualize: VisualizeRingIcon,
  deep_solve: SolveStepsIcon,
  deep_research: ResearchLensIcon,
  audio_overview: AudioVoicesIcon,
  math_animator: MathMotionIcon,
}

export function modeIcon(capability: { value: string; icon: LucideIcon }): LucideIcon {
  return MODE_ICONS[capability.value] ?? capability.icon
}
