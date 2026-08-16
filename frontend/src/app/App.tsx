import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import {
  ChatMessage,
  MessageBlock,
  ModeTabId,
  TaskItem,
  TaskNode,
  contextUsage,
  modeTabs,
  navItemsByMode,
  taskTree,
} from '../mock/data'
import {
  NewTaskPage,
  WorkHomePage,
  DesignHomePage,
  ModeShellPage,
  AutomationPage,
  MarketplacePage,
  PluginDetailModal,
  SkillDetailModal,
} from './pages'
import { listToggleableTools, setEnabledOptionalTools, type ToolItem } from '../api/tools'
import { speakReply, stopSpeech } from '../api/voice'
import { UnifiedWSClient, type StreamEvent } from '../api/ws'
import { AssistantMarkdown } from './AssistantMarkdown'
import { PRODUCT_NAME } from './brand'
import { SettingsModal } from './SettingsModal'
import {
  DEFAULT_CHAT_TIMEOUT,
  LS_CHAT_TIMEOUT,
  LS_LANGUAGE,
  LS_RESPONSE_LANGUAGE,
  LS_VOICE_AUTOPLAY,
  LanguageId,
  clampChatTimeout,
  loadRuntimeUiSettings,
  persistInterfaceSettings,
} from './settings'
import { deleteSession as deleteSessionApi, renameSession as renameSessionApi } from '../api/sessions'
import copySvg from '../assets/icons/Copy.svg?raw'
import moreSvg from '../../design-system/assets/icons/More.svg?raw'
import moreActionSvg from '../../design-system/assets/icons/more-action.svg?raw'
import arrowLeftSvg from '../../design-system/assets/icons/ArrowLeft.svg?raw'
import treeSvg from '../../design-system/assets/icons/tree.svg?raw'
import downSvg from '../../design-system/assets/icons/Down.svg?raw'
import fileUploadSvg from '../../design-system/assets/icons/file-upload.svg?raw'
import profileSvg from '../../design-system/assets/icons/profile.svg?raw'
import notificationSvg from '../../design-system/assets/icons/Notification.svg?raw'
import domainSvg from '../../design-system/assets/icons/domain.svg?raw'
import moonSvg from '../../design-system/assets/icons/Moon.svg?raw'
import settingsSvg from '../../design-system/assets/icons/settings.svg?raw'
import feedbackSvg from '../../design-system/assets/icons/feedback.svg?raw'
import downloadSvg from '../../design-system/assets/icons/download.svg?raw'
import mobileSvg from '../../design-system/assets/icons/mobile.svg?raw'
import rightSvg from '../../design-system/assets/icons/Right.svg?raw'
import {
  CAPABILITIES,
  ChassisSession,
  CREATE_SESSION_ERROR,
  FileAttachment,
  NEW_SESSION_TITLE,
  STREAM_CONNECT_ERROR,
  ViewId,
  eventsToBlocks,
  studentVisibleBlocks,
  visibleAnswerFromEvents,
  deriveSessionTitle,
  fileToAttachment,
  formatClock,
  hashFor,
  isPendingSessionId,
  loadServerSessions,
  loadSessionMessages,
  mergeSessions,
  parseHash,
  readSelectedId,
  readSessions,
  sessionIdFromEvent,
  sortSessions,
  writeSelectedId,
  writeSessions,
} from './sessions'

/* =============================================================
   Icons – 16×16 trae-icon style paths
   ============================================================= */
type IconProps = {
  name: string
  size?: number
  className?: string
  onClick?: (e: React.MouseEvent<SVGElement>) => void
  style?: React.CSSProperties
}
const OfficialIcon: React.FC<{
  svg: string
  size?: number
  className?: string
  style?: React.CSSProperties
}> = ({ svg, size = 16, className = '', style }) => (
  <span
    className={`trae-icon ${className}`.trim()}
    aria-hidden
    style={{ display: 'inline-flex', width: size, height: size, color: 'currentColor', ...style }}
    dangerouslySetInnerHTML={{
      __html: svg
        .replace('width="24"', `width="${size}"`)
        .replace('height="24"', `height="${size}"`),
    }}
  />
)

const Icon: React.FC<IconProps> = ({
  name, size = 16, className = '', onClick, style,
}) => {
  const common: React.SVGProps<SVGSVGElement> = {
    width: size, height: size, viewBox: '0 0 16 16',
    fill: 'none', stroke: 'currentColor', strokeWidth: 1.2,
    strokeLinecap: 'round', strokeLinejoin: 'round',
    onClick, style, className,
  }
  switch (name) {
    case 'chat-new':
    case 'chat':
    case 'view-left':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          {name === 'chat-new' ? (
            <path d="M13.4075 8C13.4075 5.03147 11.001 2.625 8.03247 2.625C5.06394 2.625 2.65747 5.03147 2.65747 8C2.65747 8.80228 2.83281 9.56195 3.14673 10.2441C3.27815 10.5296 3.31735 10.8695 3.21509 11.1982L2.68384 12.9043C2.59508 13.19 2.86044 13.4592 3.14771 13.375L4.9397 12.8496C5.25595 12.757 5.58045 12.7939 5.85571 12.916L6.10767 13.0205C6.70456 13.2495 7.35325 13.375 8.03247 13.375C11.001 13.375 13.4075 10.9686 13.4075 8ZM14.6575 8C14.6575 11.6589 11.6914 14.625 8.03247 14.625C7.07843 14.625 6.17002 14.4228 5.34888 14.0586C5.31747 14.0447 5.29702 14.0481 5.29126 14.0498L3.49927 14.5752C2.25469 14.9399 1.10501 13.7708 1.49048 12.5322L2.02075 10.8271L2.02271 10.8066C2.02189 10.7965 2.01843 10.7828 2.01099 10.7666C1.62323 9.9239 1.40747 8.98625 1.40747 8C1.40747 4.34112 4.37359 1.375 8.03247 1.375C11.6914 1.375 14.6575 4.34112 14.6575 8ZM8.02539 5.25C8.37034 5.25026 8.64941 5.52998 8.64941 5.875V7.40039H10.125C10.4702 7.40039 10.75 7.68021 10.75 8.02539C10.7498 8.3704 10.4701 8.65039 10.125 8.65039H8.64941V10.125C8.64941 10.4702 8.36959 10.75 8.02441 10.75C7.67946 10.7497 7.39941 10.47 7.39941 10.125V8.65039H5.875C5.52994 8.65039 5.2502 8.3704 5.25 8.02539C5.25 7.68021 5.52982 7.40039 5.875 7.40039H7.39941V5.875C7.39941 5.52982 7.68021 5.25 8.02539 5.25Z" />
          ) : name === 'view-left' ? (
            <path fillRule="evenodd" clipRule="evenodd" d="M6 3.33333V12.6667H11.3333C12.0697 12.6667 12.6667 12.0697 12.6667 11.3333V4.66667C12.6667 3.93029 12.0697 3.33333 11.3333 3.33333H6ZM2 4.66667C2 3.19391 3.19391 2 4.66667 2H11.3333C12.8061 2 14 3.19391 14 4.66667V11.3333C14 12.8061 12.8061 14 11.3333 14H4.66667C3.19391 14 2 12.8061 2 11.3333V4.66667Z" />
          ) : (
            <path d="M7.334 2.042a5.292 5.292 0 1 1 0 10.583 5.292 5.292 0 0 1 0-10.583Zm0 1.25a4.042 4.042 0 1 0 0 8.083 4.042 4.042 0 0 0 0-8.083Zm5.613 8.313a.625.625 0 0 1 .883-.884l2.286 2.286a.625.625 0 1 1-.884.884l-2.285-2.286Z" />
          )}
        </svg>
      )
    case 'plus':
      return <svg {...common} className={className}><path d="M8 3.2v9.6M3.2 8h9.6" /></svg>
    case 'close':
      return <svg {...common} className={className}><path d="M12 4 4 12M4 4l8 8" /></svg>
    case 'cloud':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M4.583 12.25A3.083 3.083 0 0 1 4.74 6.09a4.167 4.167 0 0 1 8.105 1.064 2.917 2.917 0 0 1-.34 5.096H4.583Z" />
        </svg>
      )
    case 'more-action':
      return (
        <OfficialIcon svg={moreActionSvg} size={size} className={`trae-icon-more-action ${className}`.trim()} style={style} />
      )
    case 'chevron-right':
      return <svg {...common} className={className}><path d="m6 12 4-4-4-4" /></svg>
    case 'chevron-down':
      return <svg {...common} className={className}><path d="m4 6 4 4 4-4" /></svg>
    case 'chevron-up':
      return <svg {...common} className={className}><path d="m4 10 4-4 4 4" /></svg>
    case 'pin':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M9.45 1.692a.8.8 0 0 1 .388.154c.154.107.267.26.322.44l.86 2.785 2.63 1.226a.8.8 0 0 1 .008 1.444l-2.6 1.183.65 3.624a.8.8 0 0 1-.309.785l-.004.003a.8.8 0 0 1-.846.076l-2.596-1.225-1.943 1.905a.8.8 0 0 1-.856.173.8.8 0 0 1-.517-.717l-.155-3.71-2.45-1.34a.8.8 0 0 1-.11-1.354l2.246-1.78.697-2.885a.8.8 0 0 1 .352-.486.8.8 0 0 1 .402-.1h4.396Z" />
        </svg>
      )
    case 'tree':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M3.33301 2.04199C4.41446 2.04199 5.29182 2.91859 5.29199 4C5.29189 4.86234 4.73338 5.59307 3.95898 5.85449V8.04102H6.00098C6.34559 8.04145 6.62567 8.32137 6.62598 8.66602C6.62598 9.01092 6.34578 9.29058 6.00098 9.29102H3.95898V11.833C3.95898 12.3163 4.35074 12.708 4.83398 12.708H6.00098C6.3457 12.7084 6.62584 12.9882 6.62598 13.333C6.62598 13.6779 6.34578 13.9576 6.00098 13.958H4.83398C3.66038 13.958 2.70898 13.0066 2.70898 11.833V5.85449C1.93403 5.59348 1.37511 4.86286 1.375 4C1.37518 2.9187 2.25171 2.04217 3.33301 2.04199ZM14 12.708C14.3451 12.708 14.6248 12.988 14.625 13.333C14.625 13.6782 14.3452 13.958 14 13.958H9.33301C8.98798 13.9578 8.70801 13.6781 8.70801 13.333C8.70818 12.9881 8.98809 12.7082 9.33301 12.708H14ZM14 8.04199C14.3452 8.04199 14.625 8.32181 14.625 8.66699C14.6248 9.01202 14.3451 9.29199 14 9.29199H9.33301C8.98809 9.29182 8.70818 9.01191 8.70801 8.66699C8.70801 8.32192 8.98798 8.04217 9.33301 8.04199H14ZM3.33301 3.29199C2.94206 3.29217 2.62518 3.60906 2.625 4C2.62513 4.38935 2.9394 4.7052 3.32812 4.70801H3.33789C3.72677 4.70537 4.04186 4.38946 4.04199 4C4.04182 3.60895 3.7241 3.29199 3.33301 3.29199ZM14 3.375C14.3452 3.375 14.625 3.65482 14.625 4C14.625 4.34518 14.3452 4.625 14 4.625H8C7.65482 4.625 7.375 4.34518 7.375 4C7.375 3.65482 7.65482 3.375 8 3.375H14Z" />
        </svg>
      )
    case 'copy':
      return (
        <span
          className={`trae-icon trae-icon-Copy ${className}`.trim()}
          aria-hidden
          style={{ display: 'inline-flex', width: size, height: size, color: 'currentColor', ...style }}
          dangerouslySetInnerHTML={{
            __html: copySvg
              .replace('width="24"', `width="${size}"`)
              .replace('height="24"', `height="${size}"`),
          }}
        />
      )
    case 'copy-check':
      return (
        <svg {...common} className={`trae-icon trae-icon-check ${className}`.trim()} fill="currentColor" stroke="none">
          <path d="M13.7117 2.90824C13.9472 2.656 14.3432 2.64248 14.5955 2.87797C14.8477 3.1135 14.8612 3.50945 14.6257 3.76176L6.38551 12.5909C6.06158 12.9379 5.51701 12.9556 5.17067 12.6309L1.74098 9.41606C1.48925 9.17996 1.47661 8.78405 1.71266 8.53227C1.94875 8.28054 2.34466 8.2679 2.59645 8.50395L5.73903 11.4502L13.7117 2.90824Z" fill="currentColor" />
        </svg>
      )
    case 'like-fill':
      return (
        <svg {...common} className={`trae-icon trae-icon-Like_fill ${className}`.trim()} fill="currentColor" stroke="none">
          <path fillRule="evenodd" clipRule="evenodd" d="M7.33325 1.33337C7.08072 1.33337 6.84992 1.47604 6.73699 1.7019L4.25457 6.66671H2.66659C1.93021 6.66671 1.33325 7.26364 1.33325 8.00004V12.6667C1.33325 13.4031 1.93021 14 2.66659 14H11.5875C12.921 14 14.0495 13.015 14.2297 11.6937L14.6843 8.36037C14.9026 6.75917 13.658 5.33337 12.042 5.33337H9.45599L9.71978 3.64148C9.90885 2.42873 8.97105 1.33337 7.74365 1.33337H7.33325ZM3.99992 12.6667V8.00004H2.66659V12.6667H3.99992Z" />
        </svg>
      )
    case 'unlike-fill':
      return (
        <svg {...common} className={`trae-icon trae-icon-Unlike_fill ${className}`.trim()} fill="currentColor" stroke="none">
          <path fillRule="evenodd" clipRule="evenodd" d="M9.46448 13.9301C9.24048 14.3813 8.78021 14.6667 8.27648 14.6667C7.04941 14.6667 6.11699 13.5689 6.30497 12.3589L6.56788 10.6667H3.9933C2.37906 10.6667 1.14084 9.2384 1.35803 7.64L1.81098 4.30667C1.9903 2.98701 3.11435 2 4.44625 2H13.3333C14.0697 2 14.6667 2.59695 14.6667 3.33333V8C14.6667 8.7364 14.0697 9.33333 13.3333 9.33333H11.7467L9.46448 13.9301ZM12 8H13.3333V3.33333H12V8Z" />
        </svg>
      )
    case 'delete':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M6.5 1.75a.75.75 0 0 0-.75.75v1h-2.5a.75.75 0 0 0 0 1.5h9a.75.75 0 0 0 0-1.5h-2.5v-1a.75.75 0 0 0-.75-.75h-2.5Zm-3 4.5v6.5a1.5 1.5 0 0 0 1.5 1.5h6a1.5 1.5 0 0 0 1.5-1.5v-6.5h-1.5v6.5a.75.75 0 0 1-.75.75h-4.5a.75.75 0 0 1-.75-.75v-6.5H3.5Z" />
        </svg>
      )
    case 'revert':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M8 1.25a6.75 6.75 0 1 0 6.569 5.443.75.75 0 1 0-1.48.242A5.25 5.25 0 1 1 12.6 4H10.5a.75.75 0 0 0 0 1.5H14A.75.75 0 0 0 14.75 4.75v-3.5A.75.75 0 0 0 13.25 1.25h-.5a.75.75 0 0 0-.75.75v1.078A6.741 6.741 0 0 0 8 1.25Z" />
        </svg>
      )
    case 'like':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M7.74414 1.375C8.94568 1.37524 9.86368 2.44751 9.67871 3.63477L9.40723 5.375H12.042C13.6327 5.375 14.8575 6.77843 14.6426 8.35449L14.1885 11.6875C14.0111 12.9881 12.9004 13.9578 11.5879 13.958H2.66699C1.95374 13.958 1.37518 13.3802 1.375 12.667V8C1.375 7.28661 1.95364 6.70801 2.66699 6.70801H4.28027L6.77441 1.7207L6.81934 1.64453C6.93489 1.47738 7.12614 1.37511 7.33301 1.375H7.74414ZM5.29199 7.48047V12.708H11.5879C12.2752 12.7078 12.8571 12.2005 12.9502 11.5195L13.4043 8.18555C13.5168 7.36012 12.8752 6.625 12.042 6.625H8.67773C8.49521 6.625 8.32186 6.54487 8.20312 6.40625C8.08438 6.26756 8.03145 6.08372 8.05957 5.90332L8.44336 3.44238C8.51029 3.01302 8.17864 2.62524 7.74414 2.625H7.71973L5.29199 7.48047ZM2.625 12.667C2.62518 12.6899 2.64408 12.708 2.66699 12.708H4.04199V7.95801H2.66699C2.64398 7.95801 2.625 7.97699 2.625 8V12.667Z" />
        </svg>
      )
    case 'unlike':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M13.375 3.33362C13.375 3.3106 13.356 3.29163 13.333 3.29163H11.958V8.04163H13.333C13.356 8.04163 13.375 8.02266 13.375 7.99963V3.33362ZM4.44627 3.29163C3.76412 3.29163 3.18377 3.7975 3.0908 4.4801L2.63768 7.81409C2.52528 8.64208 3.16671 9.37456 3.99315 9.37463H7.34568C7.52811 9.37463 7.70156 9.45491 7.82029 9.59338C7.93903 9.732 7.99187 9.91596 7.96385 10.0963L7.58104 12.5573C7.51398 12.9893 7.84713 13.3746 8.27635 13.3746C8.28943 13.3746 8.30171 13.3677 8.3076 13.3561L10.708 8.51917V3.29163H4.44627ZM14.625 7.99963C14.625 8.71301 14.0464 9.29163 13.333 9.29163H11.7217L9.42674 13.9117C9.20972 14.3486 8.76412 14.6246 8.27635 14.6246C7.07504 14.6246 6.16163 13.5496 6.34568 12.3649L6.61619 10.6246H3.99315C2.40438 10.6246 1.18558 9.21859 1.3994 7.64514L1.85252 4.31213C2.02911 3.01308 3.13537 2.04163 4.44627 2.04163H13.333C14.0464 2.04163 14.625 2.62026 14.625 3.33362V7.99963Z" />
        </svg>
      )
    case 'retry':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M13.3337 7.37463C13.6786 7.37481 13.9585 7.65473 13.9587 7.99963C13.9587 11.2903 11.2905 13.9576 7.99976 13.9576C6.45541 13.9575 5.0246 13.3676 3.95093 12.401V13.3336C3.95075 13.6785 3.67077 13.9584 3.32593 13.9586C2.98086 13.9586 2.7011 13.6786 2.70093 13.3336V10.6666C2.70093 10.3214 2.98075 10.0416 3.32593 10.0416H5.99292C6.33772 10.0421 6.61792 10.3217 6.61792 10.6666C6.61792 11.0115 6.33772 11.2912 5.99292 11.2916H4.59644C5.46314 12.1639 6.67927 12.7075 7.99976 12.7076C10.6001 12.7076 12.7087 10.6 12.7087 7.99963C12.7089 7.65466 12.9887 7.3747 13.3337 7.37463ZM12.6667 2.04163C13.0118 2.0418 13.2917 2.32156 13.2917 2.66663V5.33362C13.2916 5.67854 13.0117 5.95844 12.6667 5.95862H9.99976C9.6548 5.95849 9.37493 5.67857 9.37476 5.33362C9.37476 4.98852 9.65469 4.70875 9.99976 4.70862H11.405C10.538 3.83572 9.32065 3.29163 7.99976 3.29163C5.39967 3.2918 3.29192 5.39955 3.29175 7.99963C3.29175 8.34481 3.01193 8.62463 2.66675 8.62463C2.32157 8.62463 2.04175 8.34481 2.04175 7.99963C2.04192 4.70919 4.70932 2.0418 7.99976 2.04163C9.54043 2.04163 10.969 2.62813 12.0417 3.59045V2.66663C12.0417 2.32153 12.3217 2.04176 12.6667 2.04163Z" />
        </svg>
      )
    case 'attachment':
      return <svg {...common} className={className}><path d="m8.6 12.8-3.2 3.2a3 3 0 0 1-4.2-4.2l6.3-6.3a4.1 4.1 0 0 1 5.8 5.8l-5.9 5.9" /></svg>
    case 'plugin':
      return <svg {...common} className={className}><path d="M4 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" /><path d="M8 4v8M4 8h8" /></svg>
    case 'mic':
      return <svg {...common} className={className}><path d="M5 3.5a3 3 0 0 1 6 0v4a3 3 0 0 1-6 0v-4Z" /><path d="M2.5 8.5a5.5 5.5 0 0 0 11 0M8 14v1.5" /></svg>
    case 'expand':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M8.89038 8.89127C9.13443 8.64721 9.53106 8.64726 9.77515 8.89127L12.7087 11.8249V9.33365C12.7087 8.98847 12.9886 8.70865 13.3337 8.70865C13.6787 8.70891 13.9587 8.98863 13.9587 9.33365V13.3336C13.9586 13.6785 13.6786 13.9584 13.3337 13.9586H9.33374C8.98866 13.9586 8.70891 13.6787 8.70874 13.3336C8.70874 12.9885 8.98856 12.7086 9.33374 12.7086H11.823L8.89038 9.77603C8.6465 9.53207 8.64669 9.13535 8.89038 8.89127ZM6.66675 2.04166C7.01193 2.04166 7.29175 2.32148 7.29175 2.66666C7.29175 3.01183 7.01193 3.29166 6.66675 3.29166H4.17651L7.10913 6.22427C7.35318 6.46834 7.35317 6.86496 7.10913 7.10904C6.86506 7.35311 6.46844 7.3531 6.22437 7.10904L3.29175 4.17642V6.66666C3.29175 7.01183 3.01193 7.29166 2.66675 7.29166C2.32157 7.29166 2.04175 7.01183 2.04175 6.66666V2.66666C2.04175 2.32148 2.32157 2.04166 2.66675 2.04166H6.66675Z" />
        </svg>
      )
    case 'task':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M4.167 2.333a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm0 4.167a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm0 4.167a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM7 4.5h6.5v1.25H7V4.5Zm0 4.166h6.5v1.25H7v-1.25ZM7 13h6.5v1.25H7V13Z" />
        </svg>
      )
    case 'context':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M4.5 3h7A1.5 1.5 0 0 1 13 4.5v7a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 3 11.5v-7A1.5 1.5 0 0 1 4.5 3Zm.5 2v6h6V5H5Z" />
        </svg>
      )
    case 'info':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M8 1.75a6.25 6.25 0 1 1 0 12.5 6.25 6.25 0 0 1 0-12.5Zm0 5.5a.75.75 0 0 0-.75.75v3.5a.75.75 0 0 0 1.5 0V8a.75.75 0 0 0-.75-.75ZM8 5.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z" />
        </svg>
      )
    case 'filter':
      return <svg {...common} className={className}><path d="M2.5 4h11M5 8h6M7 12h2" /></svg>
    case 'theme-dark':
      return <svg {...common} className={className}><path d="M14 9.2A5.75 5.75 0 1 1 6.8 2a4.625 4.625 0 0 0 7.2 7.2Z" /></svg>
    case 'theme-light':
      return (
        <svg {...common} className={className}>
          <circle cx="8" cy="8" r="3.2" /><path d="M8 1.5v1.4M8 13.1v1.4M1.5 8h1.4M13.1 8h1.4M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" />
        </svg>
      )
    case 'time':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M13.375 8C13.375 5.03147 10.9686 2.625 8 2.625C5.03147 2.625 2.625 5.03147 2.625 8C2.625 10.9686 5.03147 13.375 8 13.375C10.9686 13.375 13.375 10.9686 13.375 8ZM7.375 5.33301C7.37518 4.98798 7.65493 4.70801 8 4.70801C8.34507 4.70801 8.62482 4.98798 8.625 5.33301V7.74023L10.1084 9.22461C10.3525 9.46869 10.3525 9.86432 10.1084 10.1084C9.86432 10.3525 9.46869 10.3525 9.22461 10.1084L7.55762 8.44238C7.44041 8.32517 7.375 8.16576 7.375 8V5.33301ZM14.625 8C14.625 11.6589 11.6589 14.625 8 14.625C4.34112 14.625 1.375 11.6589 1.375 8C1.375 4.34112 4.34112 1.375 8 1.375C11.6589 1.375 14.625 4.34112 14.625 8Z" />
        </svg>
      )
    case 'edit':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M10.8906 3.55786C11.871 2.57751 13.4609 2.5777 14.4414 3.55786C15.4219 4.53832 15.4219 6.12816 14.4414 7.10864L9.02734 12.5227C8.53509 13.0149 7.86701 13.2913 7.1709 13.2913H5.33301C4.98794 13.2911 4.70801 13.0114 4.70801 12.6663V10.8284C4.70805 10.1322 4.98439 9.46415 5.47656 8.97192L10.8906 3.55786ZM13.5576 4.44165C13.0654 3.94973 12.2676 3.94971 11.7754 4.44165L6.36035 9.85571C6.10259 10.1135 5.95805 10.4638 5.95801 10.8284V12.0413H7.1709C7.53547 12.0413 7.8857 11.8967 8.14355 11.6389L13.5576 6.22485C14.0499 5.73252 14.0499 4.93395 13.5576 4.44165Z" />
        </svg>
      )
    case 'image':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M3.333 2.375h9.334A2.958 2.958 0 0 1 15.625 5.333v5.334A2.958 2.958 0 0 1 12.667 13.625H3.333A2.958 2.958 0 0 1 .375 10.667V5.333A2.958 2.958 0 0 1 3.333 2.375Zm0 1.25A1.708 1.708 0 0 0 1.625 5.333v5.334c0 .172.026.338.074.495L5.2 8.66a1.25 1.25 0 0 1 1.68-.04l1.94 1.668 2.36-2.655a1.25 1.25 0 0 1 1.9.04l1.67 2.004V5.333A1.708 1.708 0 0 0 12.667 3.625H3.333ZM5.25 6.25a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5Z" />
        </svg>
      )
    case 'folder':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M2.667 3.375h3.2l1.2 1.5h6.266A1.958 1.958 0 0 1 15.292 6.833v5.334A1.958 1.958 0 0 1 13.333 14.125H2.667A1.958 1.958 0 0 1 .708 12.167V5.333A1.958 1.958 0 0 1 2.667 3.375Zm0 1.25A.708.708 0 0 0 1.958 5.333v6.834c0 .39.317.708.709.708h10.666a.708.708 0 0 0 .709-.708V6.833a.708.708 0 0 0-.709-.708H6.667l-1.2-1.5H2.667Z" />
        </svg>
      )
    case 'command':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M3.333 2.375h9.334A1.958 1.958 0 0 1 14.625 4.333v7.334A1.958 1.958 0 0 1 12.667 13.625H3.333A1.958 1.958 0 0 1 1.375 11.667V4.333A1.958 1.958 0 0 1 3.333 2.375Zm0 1.25A.708.708 0 0 0 2.625 4.333v7.334c0 .39.317.708.708.708h9.334a.708.708 0 0 0 .708-.708V4.333a.708.708 0 0 0-.708-.708H3.333ZM4.5 6.125h7a.625.625 0 1 1 0 1.25h-7a.625.625 0 1 1 0-1.25Zm0 2.5h4.5a.625.625 0 1 1 0 1.25H4.5a.625.625 0 1 1 0-1.25Z" />
        </svg>
      )
    case 'skill':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M8 1.375a6.625 6.625 0 1 1 0 13.25 6.625 6.625 0 0 1 0-13.25Zm0 1.25a5.375 5.375 0 1 0 0 10.75 5.375 5.375 0 0 0 0-10.75ZM8 7.125a.75.75 0 0 1 .75.75v2.5a.75.75 0 1 1-1.5 0v-2.5A.75.75 0 0 1 8 7.125Zm0-2.25a.75.75 0 1 1 0 1.5.75.75 0 0 1 0-1.5Z" />
        </svg>
      )
    case 'check':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path fillRule="evenodd" clipRule="evenodd" d="M11.7723 4.83163C12.0494 5.07408 12.0775 5.49525 11.8351 5.77235L7.1684 11.1057C7.04687 11.2445 6.87327 11.3268 6.68887 11.333C6.50444 11.3391 6.32573 11.2685 6.19526 11.1381L4.19526 9.13807C3.93491 8.87773 3.93491 8.4556 4.19526 8.19527C4.45561 7.93493 4.87772 7.93493 5.13807 8.19527L6.63419 9.6914L10.8316 4.89434C11.0741 4.61725 11.4953 4.58917 11.7723 4.83163Z" />
        </svg>
      )
    case 'send':
      return <svg {...common} className={className}><path d="M14.5 1.5 7.4 8.6M14.5 1.5 10 14.5l-2.6-5.9-5.9-2.6L14.5 1.5Z" /></svg>
    case 'work':
      return (
        <svg {...common} className={className} fill="none" strokeWidth={1.33}>
          <path d="M8 5.33C8 4.23 8.9 3.33 10 3.33h3.33c.74 0 1.34.6 1.34 1.34v6.66c0 .74-.6 1.34-1.34 1.34h-3.15c-.9 0-1.73.5-2.18 1.33m0-8.67c0-1.1-.9-2-2-2H2.67c-.74 0-1.34.6-1.34 1.34v6.66c0 .74.6 1.34 1.34 1.34h3.15c.9 0 1.73.5 2.18 1.33m0-8.67V14" />
        </svg>
      )
    case 'code':
      return (
        <svg {...common} className={className} fill="none" strokeWidth={1.33}>
          <path d="M6.67 13.33 9.33 2.67M12 5.33l1.32 1.18c.9.79.9 2.19 0 2.98L12 10.67M4 10.67 2.68 9.49c-.9-.79-.9-2.19 0-2.98L4 5.33" />
        </svg>
      )
    case 'design':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M8 1.37305C11.6598 1.37305 14.627 4.3402 14.627 8C14.627 8.4108 14.5886 8.81354 14.5166 9.2041C14.3485 10.1146 13.519 10.6269 12.7148 10.627H9.33301C8.94296 10.6271 8.62713 10.943 8.62695 11.333V12.667C8.62677 13.6998 7.74555 14.7363 6.53906 14.4648C3.58235 13.7993 1.37305 11.1584 1.37305 8C1.37305 4.3402 4.34019 1.37305 8 1.37305ZM8 2.62695C5.03239 2.62695 2.62695 5.03239 2.62695 8C2.62695 10.5596 4.41708 12.7026 6.81445 13.2422C6.95341 13.2735 7.07713 13.2353 7.18066 13.1387C7.29113 13.0354 7.37296 12.8658 7.37305 12.667V11.333C7.37322 10.2508 8.25077 9.37322 9.33301 9.37305H12.7148C13.0405 9.373 13.2472 9.17696 13.2842 8.97656C13.3425 8.66019 13.373 8.33387 13.373 8C13.373 5.03239 10.9676 2.62695 8 2.62695ZM4.69922 7.93359C5.19624 7.93359 5.59956 8.336 5.59961 8.83301C5.59961 9.33006 5.19627 9.7334 4.69922 9.7334C4.20232 9.73321 3.7998 9.32995 3.7998 8.83301C3.79986 8.33611 4.20235 7.93378 4.69922 7.93359ZM11.5 6.2002C11.997 6.2002 12.4003 6.6026 12.4004 7.09961C12.4004 7.59667 11.9971 8 11.5 8C11.0031 7.99982 10.6006 7.59655 10.6006 7.09961C10.6006 6.60271 11.0031 6.20038 11.5 6.2002ZM5.5 4.5332C5.99706 4.5332 6.40039 4.93654 6.40039 5.43359C6.40018 5.93047 5.99693 6.33301 5.5 6.33301C5.00323 6.33282 4.6008 5.93036 4.60059 5.43359C4.60059 4.93665 5.0031 4.53339 5.5 4.5332ZM8.90039 3.7334C9.39727 3.73361 9.7998 4.13686 9.7998 4.63379C9.79959 5.13054 9.39714 5.53299 8.90039 5.5332C8.40346 5.5332 8.00021 5.13067 8 4.63379C8 4.13673 8.40333 3.7334 8.90039 3.7334Z" />
        </svg>
      )
    case 'marketplace':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M11.5314 8.57031C11.8771 8.57077 12.1574 8.85145 12.1574 9.19727V11.0107H13.9689C14.3148 11.011 14.5959 11.2918 14.5959 11.6377C14.5955 11.90833 14.3145 12.2634 13.9689 12.2637H12.1574V14.0771C12.1572 14.4228 11.877 14.7036 11.5314 14.7041C11.1854 14.7041 10.9046 14.4231 10.9044 14.0771V12.2637H9.09293C8.74707 12.2637 8.46637 11.9835 8.46597 11.6377C8.46597 11.2916 8.74683 11.0107 9.09293 11.0107H10.9044V9.19727C10.9044 8.85117 11.1853 8.57031 11.5314 8.57031ZM3.02847 9.37891C3.62998 8.30359 5.17801 8.30351 5.707945 9.37891L7.28921 12.0801C7.87639 13.1304 7.11753 14.4248 5.91421 14.4248H2.89371C1.69036 14.4248 0.930526 13.1304 1.51773 12.0801L3.02847 9.37891ZM4.68765 9.98926C4.56323 9.76715 4.24357 9.76699 4.11929 9.98926L2.60953 12.6904C2.48821 12.9075 2.64498 13.1748 2.89371 13.1748H5.91421C6.16291 13.1748 6.31968 12.9075 6.19839 12.6904L4.68765 9.98926ZM11.5314 1.57324C13.2233 1.57368 14.5958 2.94487 14.5959 4.63672C14.5959 6.32863 13.2233 7.69976 11.5314 7.7002C9.83912 7.7002 8.46597 6.3289 8.46597 4.63672C8.46605 2.9446 9.83917 1.57324 11.5314 1.57324ZM5.65347 1.54785C6.67607 1.5482 7.50406 2.37815 7.50406 3.40039V5.7998C7.50406 6.82205 6.67607 7.652 5.65347 7.65234H3.25503C2.23214 7.65234 1.40347 6.82226 1.40347 5.7998V3.40039C1.40347 2.37794 2.23214 1.54785 3.25503 1.54785H5.65347ZM11.5314 2.82715C10.5307 2.82715 9.71996 3.6375 9.71988 4.63672C9.71988 5.636 10.5306 6.44727 11.5314 6.44727C12.5318 6.44683 13.3429 5.63573 13.3429 4.63672C13.3428 3.63777 12.5318 2.82759 11.5314 2.82715ZM3.25503 2.85254C2.95346 2.85254 2.70816 3.09736 2.70816 3.40039V5.7998C2.70816 6.10283 2.95346 6.34766 3.25503 6.34766H5.65347C5.95476 6.34731 6.20035 6.10262 6.20035 5.7998V3.40039C6.20035 3.09758 5.95476 2.85288 5.65347 2.85254H3.25503Z" />
        </svg>
      )
    case 'automation':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M13.373 8C13.373 5.03239 10.9676 2.62695 8 2.62695C5.03239 2.62695 2.62695 5.03239 2.62695 8C2.62695 10.9676 5.03239 13.373 8 13.373C10.9676 13.373 13.373 10.9676 13.373 8ZM7.37305 5.33333C7.37305 4.98723 7.6539 4.70638 8 4.70638C8.3461 4.70638 8.62695 4.98723 8.62695 5.33333V7.74023L10.11 9.22331C10.3548 9.46804 10.3548 9.8653 10.11 10.11C9.8653 10.3548 9.46804 10.3548 9.22331 10.11L7.55664 8.44336C7.43912 8.32584 7.37305 8.1662 7.37305 8V5.33333ZM14.627 8C14.627 11.6598 11.6598 14.627 8 14.627C4.3402 14.627 1.37305 11.6598 1.37305 8C1.37305 4.34019 4.34019 1.37305 8 1.37305C11.6598 1.37305 14.627 4.3402 14.627 8ZM2.99887 1.05728C3.24354.812617 3.64031.812292 3.88506 1.05682C4.12979 1.30155 4.12979 1.69874 3.88506 1.94346L1.94328 3.88525C1.69855 4.12997 1.30136 4.12997 1.05663 3.88525.812106 3.6405.812431 3.24372 1.05709 2.99906L2.99887 1.05728ZM13.163 1.05728C12.9183.812617 12.5216.812292 12.2768 1.05682C12.0321 1.30155 12.0321 1.69874 12.2768 1.94346L14.2186 3.88525C14.4633 4.12997 14.8605 4.12997 15.1052 3.88525 15.3498 3.6405 15.3494 3.24372 15.1048 2.99906L13.163 1.05728z" />
        </svg>
      )
    case 'download':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M13.375 8C13.375 5.03147 10.9686 2.625 8 2.625C5.03147 2.625 2.625 5.03147 2.625 8C2.625 10.9686 5.03147 13.375 8 13.375C10.9686 13.375 13.375 10.9686 13.375 8ZM10 10.042C10.3452 10.042 10.625 10.3218 10.625 10.667C10.6248 11.012 10.3451 11.292 10 11.292H6C5.65493 11.292 5.37518 11.012 5.375 10.667C5.375 10.3218 5.65482 10.042 6 10.042H10ZM7.375 5.33301C7.37518 4.98798 7.65493 4.70801 8 4.70801C8.34507 4.70801 8.62482 4.98798 8.625 5.33301V7.15723L8.8916 6.8916C9.13568 6.64752 9.53131 6.64752 9.77539 6.8916C10.0193 7.13569 10.0194 7.53137 9.77539 7.77539L8.44238 9.1084C8.19831 9.35248 7.80169 9.35248 7.55762 9.1084L6.22461 7.77539C5.98059 7.53137 5.98069 7.13569 6.22461 6.8916C6.46869 6.64752 6.86432 6.64752 7.1084 6.8916L7.375 7.15723V5.33301ZM14.625 8C14.625 11.6589 11.6589 14.625 8 14.625C4.34112 14.625 1.375 11.6589 1.375 8C1.375 4.34112 4.34112 1.375 8 1.375C11.6589 1.375 14.625 4.34112 14.625 8Z" />
        </svg>
      )
    case 'pin-line':
      return (
        <svg
          className={`trae-icon trae-icon-pin-line pinIcon ${className}`.trim()}
          width="1em"
          height="1em"
          viewBox="0 0 16 16"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          style={{ width: size, height: size, ...style }}
        >
          <path d="M10.3752 4C10.3752 3.24071 9.75951 2.62518 9.00024 2.625H7.00024C6.24086 2.625 5.62524 3.24061 5.62524 4V4.99902C5.62524 6.23217 5.13487 7.41511 4.26294 8.28711C4.06781 8.48223 3.95825 8.74747 3.95825 9.02344V9.375H12.0413V9.02344C12.0413 8.74747 11.9317 8.48223 11.7366 8.28711C10.8648 7.41513 10.3752 6.2321 10.3752 4.99902V4ZM11.6252 4.99902C11.6252 5.90058 11.983 6.76576 12.6204 7.40332C13.0499 7.83286 13.2913 8.41594 13.2913 9.02344V10C13.2913 10.3452 13.0114 10.625 12.6663 10.625H8.62524V14C8.62524 14.3451 8.34527 14.6248 8.00024 14.625C7.65507 14.625 7.37524 14.3452 7.37524 14V10.625H3.33325C2.98807 10.625 2.70825 10.3452 2.70825 10V9.02344C2.70825 8.41594 2.9496 7.83287 3.37915 7.40332C4.01665 6.76575 4.37524 5.90066 4.37524 4.99902V4C4.37524 2.55026 5.5505 1.375 7.00024 1.375H9.00024C10.4499 1.37518 11.6252 2.55037 11.6252 4V4.99902Z" fill="currentColor" />
        </svg>
      )
    case 'right-off':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M11.334 2.04199C12.7835 2.04237 13.959 3.21748 13.959 4.66699V11.334C13.9586 12.7832 12.7832 13.9586 11.334 13.959H4.66699C3.21748 13.959 2.04237 12.7835 2.04199 11.334V4.66699C2.04199 3.21725 3.21725 2.04199 4.66699 2.04199H11.334ZM6.625 3.33301V12.666C6.625 12.6804 6.62205 12.6949 6.62109 12.709H11.334C12.0929 12.7086 12.7086 12.0929 12.709 11.334V4.66699C12.709 3.90783 12.0931 3.29237 11.334 3.29199H6.62109C6.62199 3.30561 6.62499 3.31917 6.625 3.33301ZM4.66699 3.29199C3.9076 3.29199 3.29199 3.9076 3.29199 4.66699V11.334C3.29237 12.0931 3.90783 12.709 4.66699 12.709H5.37891C5.37795 12.6949 5.375 12.6804 5.375 12.666V3.33301C5.37501 3.31917 5.37801 3.30561 5.37891 3.29199H4.66699Z" />
        </svg>
      )
    case 'phone':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M2.37305 10V6C2.37305 5.6539 2.6539 5.37305 3 5.37305C3.3461 5.37305 3.62695 5.6539 3.62695 6V10C3.62695 10.3461 3.3461 10.627 3 10.627C2.6539 10.627 2.37305 10.3461 2.37305 10ZM12.373 8.66659V7.33325C12.373 6.98715 12.6539 6.7063 13 6.7063C13.3461 6.7063 13.627 6.98715 13.627 7.33325V8.66659C13.627 9.01268 13.3461 9.29354 13 9.29354C12.6539 9.29354 12.373 9.01268 12.373 8.66659ZM9.03979 10.6666V5.33325C9.03979 4.98715 9.32065 4.7063 9.66675 4.7063C10.0128 4.7063 10.2937 4.98715 10.2937 5.33325V10.6666C10.2937 11.0127 10.0128 11.2935 9.66675 11.2935C9.32065 11.2935 9.03979 11.0127 9.03979 10.6666ZM5.7063 13.3334V2.66675C5.7063 2.32065 5.98715 2.03979 6.33325 2.03979C6.67935 2.03979 6.96021 2.32065 6.96021 2.66675V13.3334C6.96021 13.6795 6.67935 13.9604 6.33325 13.9604C5.98715 13.9604 5.7063 13.6795 5.7063 13.3334Z" />
        </svg>
      )
    case 'search':
      return (
        <svg {...common} className={className} fill="currentColor" stroke="none">
          <path d="M7.33398 2.04199C10.2562 2.0423 12.625 4.41167 12.625 7.33398C12.6248 8.5697 12.1992 9.70502 11.4893 10.6055L13.7754 12.8916C14.0192 13.1357 14.0193 13.5314 13.7754 13.7754C13.5314 14.0194 13.1357 14.0192 12.8916 13.7754L10.6045 11.4893C9.70413 12.1989 8.56941 12.6249 7.33398 12.625C4.4117 12.625 2.04235 10.2562 2.04199 7.33398C2.04199 4.41148 4.41148 2.04199 7.33398 2.04199ZM7.33398 3.29199C5.10184 3.29199 3.29199 5.10184 3.29199 7.33398C3.29235 9.56583 5.10206 11.375 7.33398 11.375C9.56566 11.3747 11.3746 9.56565 11.375 7.33398C11.375 5.10203 9.56588 3.2923 7.33398 3.29199Z" fill="currentColor" />
        </svg>
      )
    default:
      return <svg {...common} className={className}><circle cx="8" cy="8" r="3.4" /></svg>
  }
}

/* =============================================================
   Icon Button – real TraeWork .iconButton pattern
   ============================================================= */
function IconBtn({
  icon, size = 'xlarge', variant = 'tertiary', className = '',
  label, title, tooltip, testId, onClick, disabled, style,
}: {
  icon: string
  size?: 'small' | 'default' | 'xlarge' | 'large'
  variant?: 'tertiary' | 'quaternary'
  className?: string
  label?: string
  title?: string
  tooltip?: string
  testId?: string
  onClick?: (e: React.MouseEvent) => void
  disabled?: boolean
  style?: React.CSSProperties
}) {
  const sizeCls = size === 'small' ? 'small-MVjdue' : size === 'large' ? 'large-tX8f7h' : size === 'default' ? 'default-yRVfZ2' : 'xlarge-sQMlYy'
  const button = (
    <button
      type="button"
      aria-label={label}
      title={tooltip ? undefined : title}
      onClick={(e) => {
        onClick?.(e)
        ;(e.currentTarget as HTMLButtonElement).blur()
      }}
      disabled={disabled}
      className={`iconButton-abHesq ${variant === 'tertiary' ? 'tertiary-J9WelI' : 'quaternary-bkmm6w'} ${sizeCls} ${className}`}
      style={style}
    >
      <span className="icon-V7eOa6">
        <span
          data-testid={testId}
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <Icon name={icon} size={size === 'small' ? 14 : 16} />
        </span>
      </span>
    </button>
  )
  if (tooltip) return <HoverTooltip text={tooltip}>{button}</HoverTooltip>
  return <span className="trigger-jIoLhZ">{button}</span>
}

function useDismiss(open: boolean, onClose: () => void, rootRef: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      const root = rootRef.current
      if (root && e.target instanceof Node && root.contains(e.target)) return
      onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, rootRef])
}

function HoverTooltip({
  text,
  side = 'top',
  delay = 280,
  variant = 'normal',
  disabled = false,
  children,
  content,
}: {
  text?: string
  side?: 'top' | 'right'
  delay?: number
  variant?: 'normal' | 'mini'
  disabled?: boolean
  children: React.ReactNode
  content?: React.ReactNode
}) {
  const triggerRef = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const anchorRef = useRef<DOMRect | null>(null)
  const timerRef = useRef<number | null>(null)

  const hide = () => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = null
    setVisible(false)
  }

  const show = () => {
    if (disabled) return
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => {
      const trigger = triggerRef.current
      const box = (trigger?.firstElementChild as HTMLElement | null) || trigger
      if (!box) return
      const r = box.getBoundingClientRect()
      if (r.width === 0 && r.height === 0) return
      anchorRef.current = r
      setVisible(true)
    }, delay)
  }

  useLayoutEffect(() => {
    if (!visible) return
    const r = anchorRef.current
    const tip = tipRef.current
    if (!r) return
    const tw = tip?.offsetWidth || 96
    const th = tip?.offsetHeight || 28
    if (side === 'right') {
      const sidebar = document.querySelector('.sidebar-IlIa2h')
      const edge = sidebar?.getBoundingClientRect().right ?? r.right
      setPos({ top: Math.max(8, r.top + r.height / 2 - th / 2), left: Math.round(edge + 12) })
    } else {
      setPos({ top: Math.max(8, r.top - th - 8), left: Math.max(8, r.left + r.width / 2 - tw / 2) })
    }
  }, [visible, side])

  useEffect(() => () => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
  }, [])

  return (
    <>
      <span
        ref={triggerRef}
        className="trigger-jIoLhZ"
        onMouseEnter={show}
        onMouseLeave={hide}
        onPointerDown={hide}
        onFocus={show}
        onBlur={hide}
      >
        {children}
      </span>
      {visible && !disabled && (
        <div
          ref={tipRef}
          className={`tooltip-xBfphh portal-OhWUfM ${variant === 'mini' ? 'mini-f97uEc' : 'normal-vAwSUT'} visible-EcjNhM`}
          data-side={side}
          role="tooltip"
          style={{ top: pos.top, left: pos.left, visibility: 'visible' }}
        >
          <div className="customScrollbar-ASDCqc container-JNIqwG tooltipContainer">
            <span className="text-CPZ58r">
              {content || <span className="tooltipPlainText">{text}</span>}
            </span>
          </div>
          <div className="arrow-dWN5mu" />
        </div>
      )}
    </>
  )
}

/* =============================================================
   Segmented Control (Mode tabs: Work / Code / Design)
   ============================================================= */
interface SegmentedControlProps<T extends string> {
  tabs: readonly { id: T; label: string; icon: string }[]
  value: T
  onChange: (next: T) => void
}
function SegmentedControl<T extends string>({ tabs, value, onChange }: SegmentedControlProps<T>) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const btnRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [btnWidths, setBtnWidths] = useState<Record<string, number>>({})
  const [state, setState] = useState({ left: 2, width: 0 })

  useLayoutEffect(() => {
    const measureBtnWidths = () => {
      const widths: Record<string, number> = {}
      // Temporarily show all icons to measure max width
      tabs.forEach((t) => {
        const btn = btnRefs.current[t.id]
        if (btn) {
          const iconSpan = btn.querySelector('.tabIcon-sSy5GA') as HTMLElement
          if (iconSpan) {
            iconSpan.classList.add('tabIconVisible-Kd2JTX')
          }
        }
      })
      // Force reflow then measure
      requestAnimationFrame(() => {
        tabs.forEach((t) => {
          const btn = btnRefs.current[t.id]
          if (btn) {
            widths[t.id] = btn.getBoundingClientRect().width
          }
        })
        setBtnWidths(widths)

        // Now recalc indicator position
        const btn = btnRefs.current[value]
        const wrap = wrapRef.current
        if (btn && wrap) {
          const wRect = wrap.getBoundingClientRect()
          const bRect = btn.getBoundingClientRect()
          setState({
            left: bRect.left - wRect.left,
            width: bRect.width,
          })
        }
      })
    }
    measureBtnWidths()
    window.addEventListener('resize', measureBtnWidths)
    return () => window.removeEventListener('resize', measureBtnWidths)
  }, [tabs.length])

  useLayoutEffect(() => {
    const recalc = () => {
      const btn = btnRefs.current[value]
      const wrap = wrapRef.current
      if (!btn || !wrap) return
      const wRect = wrap.getBoundingClientRect()
      const bRect = btn.getBoundingClientRect()
      setState({
        left: bRect.left - wRect.left,
        width: bRect.width,
      })
    }
    // Use rAF to ensure DOM has settled after state change
    requestAnimationFrame(recalc)
  }, [value, btnWidths])

  return (
    <div
      ref={wrapRef}
      role="tablist"
      className="container-_1k5WQ"
      style={{
        // @ts-expect-error custom props
        '--indicator-left': `${state.left}px`,
        '--indicator-width': `${state.width}px`,
      }}
    >
      <div className="indicator-k1zg06" aria-hidden />
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          tabIndex={0}
          ref={(el) => (btnRefs.current[t.id] = el)}
          className={`tab-dN86Xu ${value === t.id ? 'tabActive-GMPLPw' : ''}`}
          style={btnWidths[t.id] ? { width: `${btnWidths[t.id]}px` } : undefined}
          onClick={() => onChange(t.id)}
        >
          <span className={`tabIcon-sSy5GA ${value === t.id ? 'tabIconVisible-Kd2JTX' : ''}`}>
            <Icon name={t.icon} size={14} />
          </span>
          <span>{t.label}</span>
        </button>
      ))}
    </div>
  )
}

/* =============================================================
   Sidebar Task List
   ============================================================= */
function TaskList({
  items, selectedId, onSelect,
  expandedTreeId, onToggleTree,
  onPin, onRename, onDelete,
  listClassName = 'taskList-TYOoT1',
}: {
  items: TaskItem[]
  selectedId: string
  onSelect: (id: string) => void
  expandedTreeId: string | null
  onToggleTree: (id: string) => void
  onPin: (id: string) => void
  onRename: (id: string, label: string) => void
  onDelete: (id: string) => void
  listClassName?: string
}) {
  const [menuId, setMenuId] = useState<string | null>(null)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [renamePos, setRenamePos] = useState({ top: 0, left: 0 })
  const renameRef = useRef<HTMLTextAreaElement>(null)
  const renamePopRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const closeMenu = useCallback(() => setMenuId(null), [])
  const closeRename = useCallback(() => setRenamingId(null), [])
  useDismiss(!!menuId, closeMenu, menuRef)
  useDismiss(!!renamingId, closeRename, renamePopRef)

  const openMore = (id: string, btn: HTMLElement) => {
    const r = btn.getBoundingClientRect()
    setMenuPos({ top: r.bottom + 4, left: Math.max(8, r.right - 160) })
    setMenuId(id)
  }

  const startRename = (item: TaskItem, row?: HTMLElement | null) => {
    closeMenu()
    const host = row || document.querySelector(`[data-session-id="${item.id}"] .taskItem`) as HTMLElement | null
    const r = host?.getBoundingClientRect()
    if (r) setRenamePos({ top: r.bottom, left: r.left + 32 })
    setRenamingId(item.id)
    setRenameDraft(item.label)
    window.requestAnimationFrame(() => {
      renameRef.current?.focus()
      renameRef.current?.select()
    })
  }

  const commitRename = () => {
    if (!renamingId) return
    const next = renameDraft.replace(/\s+/g, ' ').trim()
    if (next) onRename(renamingId, next)
    setRenamingId(null)
  }

  const menuItem = items.find((t) => t.id === menuId)

  return (
    <div className={listClassName}>
      {items.map((t) => {
        const selected = t.id === selectedId
        const menuOpen = menuId === t.id
        const renaming = renamingId === t.id
        return (
          <div key={t.id} data-session-id={t.id}>
            <div className="taskItemWrapper">
              <div
                className={`taskItem ${selected ? 'taskItemSelected' : ''} ${expandedTreeId === t.id || menuOpen || renaming ? 'taskItemActive' : ''} ${t.pinned ? 'pinnedTaskItem' : ''}`}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(t.id)}
                onKeyDown={(e) => { if (e.key === 'Enter') onSelect(t.id) }}
              >
                <div className={`taskPinArea ${t.pinned ? '' : 'pinAreaHidden'}`}>
                  <HoverTooltip text={t.pinned ? '取消置顶' : '置顶'} disabled={menuOpen || renaming}>
                    <button
                      type="button"
                      aria-label={t.pinned ? '取消置顶' : '置顶'}
                      aria-pressed={!!t.pinned}
                      className={`iconButton-abHesq tertiary-J9WelI small-MVjdue pinIconDefault${t.pinned ? ' pinIconAlways' : ''}`}
                      onClick={(e) => { e.stopPropagation(); closeMenu(); onPin(t.id) }}
                    >
                      <span className="icon-V7eOa6">
                        <span data-testid="chat-icon-pin-line" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Icon name="pin-line" size={14} />
                        </span>
                      </span>
                    </button>
                  </HoverTooltip>
                </div>
                <HoverTooltip
                  side="right"
                  variant="mini"
                  disabled={menuOpen || renaming}
                  content={(
                    <div className="tooltip">
                      <div className="tooltipTitleRow">
                        <span className="tooltipTitle">{t.label}</span>
                      </div>
                      <div className="tooltipMetaRow">
                        <span className="icon-ot1yE3 default-n2KhWI tooltipMetaIcon">
                          <Icon name="cloud" size={12} />
                        </span>
                        <span className="tooltipMetaText">云端任务</span>
                      </div>
                      <div className="tooltipMetaRow">
                        <span className="icon-ot1yE3 default-n2KhWI tooltipMetaIcon">
                          <Icon name="time" size={12} />
                        </span>
                        <span className="tooltipMetaText">{t.time ? `更新于 ${t.time}` : '更新于 —'}</span>
                      </div>
                    </div>
                  )}
                >
                  <span className="taskText">{t.label}</span>
                </HoverTooltip>
                <div className="taskRight">
                  <div className="taskActions">
                    <HoverTooltip text="更多" disabled={menuOpen || renaming}>
                      <button
                        type="button"
                        aria-label="更多"
                        aria-haspopup="menu"
                        aria-expanded={menuOpen}
                        className="iconButton-abHesq tertiary-J9WelI default-yRVfZ2 taskIconBtn taskMoreBtn"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (menuOpen) closeMenu()
                          else openMore(t.id, e.currentTarget)
                        }}
                      >
                        <span className="icon-V7eOa6">
                          <span data-testid="chat-icon-more" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                            <OfficialIcon svg={moreSvg} size={16} className="trae-icon-More" style={{ transform: 'rotate(90deg)' }} />
                          </span>
                        </span>
                      </button>
                    </HoverTooltip>
                  </div>
                  <span className={`taskTreeWrap${selected || menuOpen ? ' taskTreeWrapVisible' : ''}`}>
                    <button
                      type="button"
                      aria-label="任务树"
                      className="iconButton-abHesq tertiary-J9WelI default-yRVfZ2 taskIconBtn taskTreeBtn taskTreeBtnCode"
                      style={{ border: '0.5px solid var(--border-border-neutral-l3, rgba(115, 115, 115, 0.36))', backgroundColor: 'var(--bg-bg-base-default)' }}
                      onClick={(e) => { e.stopPropagation(); closeMenu(); onToggleTree(t.id) }}
                    >
                      <span className="icon-V7eOa6">
                        <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Icon name="tree" size={14} />
                        </span>
                      </span>
                    </button>
                  </span>
                </div>
              </div>
            </div>
          </div>
        )
      })}
      {menuItem && (
        <div
          ref={menuRef}
          className="taskMenu"
          role="menu"
          style={{ top: menuPos.top, left: menuPos.left, visibility: 'visible' }}
        >
          <button
            type="button"
            className="taskMenuItem"
            role="menuitem"
            onClick={() => { onPin(menuItem.id); closeMenu() }}
          >
            <Icon name="pin-line" size={16} className="taskMenuIcon" />
            <span>{menuItem.pinned ? '取消置顶' : '置顶任务'}</span>
          </button>
          <button
            type="button"
            className="taskMenuItem"
            role="menuitem"
            onClick={() => {
              const row = document.querySelector(`[data-session-id="${menuItem.id}"] .taskItem`) as HTMLElement | null
              startRename(menuItem, row)
            }}
          >
            <Icon name="edit" size={16} className="taskMenuIcon" />
            <span>重命名</span>
          </button>
          <button
            type="button"
            className="taskMenuItem taskMenuItemDelete"
            role="menuitem"
            onClick={() => { onDelete(menuItem.id); closeMenu() }}
          >
            <Icon name="delete" size={16} className="taskMenuIconDelete" />
            <span>删除任务</span>
          </button>
        </div>
      )}
      {renamingId && (
        <div
          ref={renamePopRef}
          className="renamePopover-bnrET0"
          style={{ top: renamePos.top, left: renamePos.left, visibility: 'visible' }}
        >
          <div className="renameInputWrapper-eqbkpZ">
            <textarea
              ref={renameRef}
              className="renameInput-q2DQZg"
              placeholder="输入新的任务名称"
              rows={2}
              maxLength={50}
              value={renameDraft}
              aria-label="重命名对话"
              onChange={(e) => setRenameDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  commitRename()
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setRenamingId(null)
                }
              }}
            />
          </div>
          <div className="renameActions-h9G6za">
            <button type="button" className="button-muTeiY secondary-J0eGRO small-g_CYf2" style={{ padding: '0 6px' }} onClick={() => setRenamingId(null)}>
              <span className="label-RSUjZl">取消</span>
            </button>
            <button type="button" className="button-muTeiY primary-ZG2S1H small-g_CYf2" style={{ padding: '0 6px' }} onClick={commitRename}>
              <span className="label-RSUjZl">确认</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* =============================================================
   Task Tree View – renders hierarchical task nodes
   ============================================================= */
function TaskTreeView({
  nodes, selectedId, onSelect, depth = 0,
}: {
  nodes: TaskNode[]
  selectedId: string
  onSelect: (id: string) => void
  depth?: number
}) {
  return (
    <div className="fileTreeWrapper-mW1q5_">
      {nodes.map((node) => (
        <TaskTreeItem
          key={node.id}
          node={node}
          selectedId={selectedId}
          onSelect={onSelect}
          depth={depth}
        />
      ))}
    </div>
  )
}

function TaskTreeItem({
  node, selectedId, onSelect, depth,
}: {
  node: TaskNode
  selectedId: string
  onSelect: (id: string) => void
  depth: number
}) {
  const [open, setOpen] = useState(depth === 0)
  const hasChildren = node.children && node.children.length > 0
  const selected = node.id === selectedId
  const statusColor = {
    active: 'var(--bg-bg-brand)',
    done: 'var(--icon-icon-tertiary)',
    blocked: '#f59e0b',
    todo: 'var(--border-border-neutral-l3)',
  }[node.status]

  return (
    <div className="taskTreeNode">
      <div
        className={`taskTreeNodeRow ${selected ? 'taskTreeNodeSelected' : ''}`}
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
        role="button"
        tabIndex={0}
        onClick={() => onSelect(node.id)}
        onKeyDown={(e) => { if (e.key === 'Enter') onSelect(node.id) }}
      >
        {hasChildren ? (
          <button
            type="button"
            className="taskTreeToggle"
            onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
            aria-label={open ? '折叠' : '展开'}
          >
            <Icon name={open ? 'chevron-down' : 'chevron-right'} size={10} />
          </button>
        ) : (
          <span className="taskTreeLeafMarker" />
        )}
        <span className="taskTreeStatusDot" style={{ backgroundColor: statusColor }} />
        <span className="taskTreeLabel">{node.label}</span>
      </div>
      {hasChildren && open && (
        <TaskTreeView nodes={node.children!} selectedId={selectedId} onSelect={onSelect} depth={depth + 1} />
      )}
    </div>
  )
}

/* =============================================================
   Sidebar
   ============================================================= */
function Sidebar({
  mode, onModeChange, collapsed, onToggleCollapse,
  items, selectedTask, onSelectTask,
  expandedTreeId, onToggleTree,
  onPinTask, onRenameTask, onDeleteTask,
  activeNavItem, onNavigate,
  theme, onToggleTheme,
  language,
  onOpenSettings,
  searchDocs = [],
  hideSessions = false,
}: {
  mode: ModeTabId
  onModeChange: (m: ModeTabId) => void
  collapsed: boolean
  onToggleCollapse: () => void
  items: TaskItem[]
  selectedTask: string
  onSelectTask: (id: string) => void
  expandedTreeId: string | null
  onToggleTree: (id: string) => void
  onPinTask: (id: string) => void
  onRenameTask: (id: string, label: string) => void
  onDeleteTask: (id: string) => void
  activeNavItem?: string
  onNavigate?: (id: string) => void
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  language: LanguageId
  onOpenSettings: () => void
  searchDocs?: { id: string; title: string; snippet: string }[]
  hideSessions?: boolean
}) {
  const [pinnedOpen, setPinnedOpen] = useState(true)
  const [listOpen, setListOpen] = useState(true)
  const [viewMode, setViewMode] = useState<'list' | 'group'>('list')
  const [groupOpen, setGroupOpen] = useState(true)
  const [viewMenuOpen, setViewMenuOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [accountOpen, setAccountOpen] = useState(false)
  const viewMenuRef = useRef<HTMLDivElement>(null)
  const accountRef = useRef<HTMLDivElement>(null)
  useDismiss(viewMenuOpen, () => setViewMenuOpen(false), viewMenuRef)
  useDismiss(accountOpen, () => setAccountOpen(false), accountRef)
  const pinnedItems = hideSessions ? [] : items.filter((item) => item.pinned)
  const restItems = hideSessions ? [] : items.filter((item) => !item.pinned)
  const nav = navItemsByMode[mode] || navItemsByMode.code
  const q = searchQuery.trim()
  const searchHits = !q ? searchDocs : searchDocs.filter((doc) => {
    const hay = `${doc.title}\n${doc.snippet}`.toLowerCase()
    return hay.includes(q.toLowerCase())
  })
  return (
    <aside className={`sidebar-IlIa2h ${collapsed ? 'sidebarCollapsed-uQ9tUw' : ''}`} aria-label="Primary sidebar">
      <div className="header-WLyHO4">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
          <div style={{ display: 'inline-flex' }}>
            <IconBtn icon="view-left" label="收起侧边栏" title="收起侧边栏" onClick={onToggleCollapse} />
          </div>
          <IconBtn icon="search" label="搜索" title="搜索" onClick={() => setSearchOpen(true)} />
        </div>
        <div className="headerRight-zKtKVX" />
      </div>

      <div className="content-ltxS9m">
        {/* Mode segmented control */}
        <div className="modeContainer-S9Kdmj">
          <SegmentedControl
            tabs={modeTabs}
            value={mode}
            onChange={onModeChange}
          />
        </div>

        {/* Primary nav */}
        <div className="primarySection-RxL7j6">
          {nav.map((item) => (
            <div
              key={item.id}
              className={`navItem-r4wswG${activeNavItem === item.id ? ' navItemActive-FMVRXn' : ''}`}
              role="button"
              tabIndex={0}
              data-tea-param-action={item.id}
              onClick={() => onNavigate?.(item.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onNavigate?.(item.id) }}
            >
              <span className="icon-ot1yE3 default-n2KhWI primaryIcon-nFVwdl">
                <Icon name={item.icon} size={16} />
              </span>
              <span className="primaryText-o42Vkv">{item.label}</span>
              {item.shortcut && (
                <span className="hotkey-AugyC9 hotkey-SxnlGj">
                  {item.shortcut.split('').map((ch, i) => (
                    <span key={i} className="key-yn14uH">{ch}</span>
                  ))}
                </span>
              )}
            </div>
          ))}
        </div>

        {/* Task list */}
        <div className="projectsSection-NbGP3T">
          <div className={`projectsSectionInner-SNZ8_p${expandedTreeId ? ' showFileTree-jePiGe' : ''}`}>
            <div className="projectsContent-JKZ_CZ">
              {pinnedItems.length > 0 && (
                <div className="pinnedSection pinnedSectionWrapper-Y0D1fl">
                  <div
                    className="pinnedSectionHeading"
                    role="button"
                    tabIndex={0}
                    onClick={() => setPinnedOpen((v) => !v)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPinnedOpen((v) => !v) } }}
                  >
                    <span className="pinnedSectionHeadingText">置顶</span>
                    <span className="pinnedSectionCollapseIcon">
                      <span data-testid="chat-icon-down" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Icon name="chevron-down" size={16} />
                      </span>
                    </span>
                  </div>
                  <div className={`pinnedSectionCollapsible${pinnedOpen ? ' pinnedSectionExpanded' : ''}`}>
                    <div className="pinnedSectionCollapsibleInner">
                      <TaskList
                        listClassName="pinnedSectionList"
                        items={pinnedItems}
                        selectedId={selectedTask}
                        onSelect={onSelectTask}
                        expandedTreeId={expandedTreeId}
                        onToggleTree={onToggleTree}
                        onPin={onPinTask}
                        onRename={onRenameTask}
                        onDelete={onDeleteTask}
                      />
                    </div>
                  </div>
                </div>
              )}
              <div className="projectsHeader-Zw_C6i">
                <span
                  className={`projectsHeading-UVr4Aj${pinnedItems.length > 0 || restItems.length > 0 ? ' headingClickable-jMWykt' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setListOpen((v) => !v)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setListOpen((v) => !v) } }}
                >
                  <span> 任务列表</span>
                  {(pinnedItems.length > 0 || restItems.length > 0) && (
                    <span className={`pinnedSectionCollapseIcon${listOpen ? '' : ' isCollapsed'}`}>
                      <Icon name="chevron-down" size={16} />
                    </span>
                  )}
                </span>
                <div className="headerActions-cWB0ey" ref={viewMenuRef}>
                  <HoverTooltip text="视图" disabled={viewMenuOpen}>
                    <IconBtn
                      icon="filter"
                      size="default"
                      label="视图"
                      title="视图"
                      onClick={() => setViewMenuOpen((v) => !v)}
                    />
                  </HoverTooltip>
                  {viewMenuOpen && (
                    <div className="popover-HaNsn7 portal-ThLRPV visible-Uwmjga viewMenuPopover" role="dialog">
                      <div className="viewMenuLabel">视图</div>
                      <button
                        type="button"
                        className={`headerViewMenu__item${viewMode === 'group' ? ' headerViewMenu__item--active' : ''}`}
                        onClick={() => { setViewMode('group'); setViewMenuOpen(false); setGroupOpen(true) }}
                      >
                        <Icon name="tree" size={16} />
                        <span>分组视图</span>
                        {viewMode === 'group' && <span className="viewMenuCheck">✓</span>}
                      </button>
                      <button
                        type="button"
                        className={`headerViewMenu__item${viewMode === 'list' ? ' headerViewMenu__item--active' : ''}`}
                        onClick={() => { setViewMode('list'); setViewMenuOpen(false) }}
                      >
                        <Icon name="filter" size={16} />
                        <span>列表视图</span>
                        {viewMode === 'list' && <span className="viewMenuCheck">✓</span>}
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <div className="taskListCollapsible-Pi1Ab7">
                <div className="taskListCollapsibleInner-B5Kefm">
                  <div className="scrollbarContainer-RAntmd projectsList-_cGMQr">
                    <div className="shadowTop-ytqHYT" />
                    <div className="scrollbarContent-qrtDFj scrollY-I6nZoQ projectsListContent-n9sJMQ">
                      {hideSessions || (restItems.length === 0 && pinnedItems.length === 0) ? (
                        <div className="taskListEmpty">
                          <Icon name="chat" size={20} />
                          <span>暂无任务</span>
                        </div>
                      ) : listOpen && viewMode === 'group' ? (
                        <div className="repoGroup-WLCKPf">
                          <div
                            className="repoGroupHeader-koHGc6"
                            role="button"
                            tabIndex={0}
                            onClick={() => setGroupOpen((v) => !v)}
                          >
                            <span className="icon-ot1yE3 default-n2KhWI repoGroupIconCloud-CWvMTN">
                              <Icon name="cloud" size={14} />
                            </span>
                            <span className="repoGroupName-XgnRBs">默认</span>
                          </div>
                          {groupOpen && (
                            <div className="repoGroupCollapsible-iarCwm repoGroupExpanded-kkme7z">
                              <div className="repoGroupSessions-D58HUE">
                                <TaskList
                                  listClassName="pinnedSectionList"
                                  items={restItems.map((item) => ({ ...item }))}
                                  selectedId={selectedTask}
                                  onSelect={onSelectTask}
                                  expandedTreeId={expandedTreeId}
                                  onToggleTree={onToggleTree}
                                  onPin={onPinTask}
                                  onRename={onRenameTask}
                                  onDelete={onDeleteTask}
                                />
                              </div>
                            </div>
                          )}
                        </div>
                      ) : listOpen ? (
                        <TaskList
                          items={restItems}
                          selectedId={selectedTask}
                          onSelect={onSelectTask}
                          expandedTreeId={expandedTreeId}
                          onToggleTree={onToggleTree}
                          onPin={onPinTask}
                          onRename={onRenameTask}
                          onDelete={onDeleteTask}
                        />
                      ) : null}
                    </div>
                    <div className="shadowBottom-RqEvWr" />
                  </div>
                </div>
              </div>
            </div>
            <div className="fileTreePane-trae">
              <div className="fileTreeHeader-mzolDr">
                <button
                  type="button"
                  className="backButton-I05EhZ"
                  onClick={() => expandedTreeId && onToggleTree(expandedTreeId)}
                >
                  <span className="icon-ot1yE3 default-n2KhWI">
                    <OfficialIcon svg={arrowLeftSvg} size={16} className="trae-icon-ArrowLeft" />
                  </span>
                  <span className="backText-h7H9t6">返回任务列表</span>
                </button>
                <div className="headerRight-WE7XKb">
                  <div className="headerRightContainer-RfZbks">
                    <button type="button" className="modeDropdownTrigger-fdfYvV" aria-haspopup="menu" aria-expanded="false">
                      <OfficialIcon svg={treeSvg} size={16} className="trae-icon-tree" />
                      <OfficialIcon svg={downSvg} size={16} className="trae-icon-Down modeDropdownArrow-maSp63" />
                    </button>
                    <div className="headerDivider-rQ8pED" />
                    <button
                      type="button"
                      className="iconButton-abHesq secondary-KGAeS8 default-yRVfZ2 addButton-v7P7th"
                      title="更多操作"
                    >
                      <span className="icon-V7eOa6">
                        <OfficialIcon svg={moreActionSvg} size={16} className="trae-icon-more-action" />
                      </span>
                    </button>
                  </div>
                </div>
              </div>
              <div className="emptyState-U4vZr4">
                <div className="emptyStateInner-PPJcjY">
                  <OfficialIcon svg={fileUploadSvg} size={24} className="trae-icon-file-upload emptyStateIcon-IhwRgG" />
                  <div className="emptyStateText-c88itD">
                    <pre>{`工作区为空
点击上传或拖拽文件到面板`}</pre>
                  </div>
                  <button type="button" className="button-muTeiY secondary-J0eGRO default-siL9wr">
                    <span className="label-RSUjZl">上传文件</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="footer-XkUaYe">
        <div className="footerContent-HUuOfB">
          <div className="accountRoot-ZwG0Il accountVariantSidebar-zK2D0X" ref={accountRef}>
            <span className="wrapper-RV5xqM">
              <button type="button" className="accountTrigger-y5IeNi" onClick={() => setAccountOpen((v) => !v)}>
                <span className="accountTriggerAvatar-S_uGoG">
                  <span className="avatar-fallback">X</span>
                </span>
                <span className="accountTriggerName-u99673">Xike</span>
                <span className="accountTriggerMembership-NGv617">
                  <span className="accountHostTag-Hli3r_">Free</span>
                </span>
              </button>
            </span>
            <span className="downloadChip-trae footerDownloadChip">下载桌面端</span>
            {accountOpen && (
              <div className="popover-HaNsn7 portal-ThLRPV visible-Uwmjga accountPopover-FbNGEo" data-side="top" role="dialog">
                <div className="content-NiU62c accountPopoverContent-LrhkkF">
                  <div className="accountCard-nHQV96">
                    <div className="accountHeader-qkAtYX">
                      <div className="accountHeaderAvatar-exbsGo">
                        <span className="avatar-fallback">X</span>
                      </div>
                      <div className="accountIdentity-s6_M5c">
                        <div className="accountIdentityNameRow-CclHxH">
                          <span className="accountIdentityName-czXO_D" title="Xike">Xike</span>
                          <span className="accountHostTag-Hli3r_">Free</span>
                        </div>
                      </div>
                    </div>
                    <button type="button" className="accountUpgradeButton-Bwlmtr">升级会员</button>
                    <div className="accountSections-bHnP71">
                      <section className="accountSection-gqAsGh">
                        <button type="button" className="accountMenuItem-NXEKcd">
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={profileSvg} size={16} className="trae-icon-profile accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">管理账户</span>
                          <OfficialIcon svg={rightSvg} size={14} className="trae-icon-Right accountMenuArrow-fbYuZj" />
                        </button>
                        <button type="button" className="accountMenuItem-NXEKcd">
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={notificationSvg} size={16} className="trae-icon-Notification accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">消息</span>
                        </button>
                      </section>
                      <section className="accountSection-gqAsGh">
                        <button type="button" className="accountMenuItem-NXEKcd">
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={domainSvg} size={16} className="trae-icon-domain accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">语言</span>
                          <span className="accountMenuValue-iTOf2H">{language === 'en' ? 'English' : '中文'}</span>
                          <OfficialIcon svg={rightSvg} size={14} className="trae-icon-Right accountMenuArrow-fbYuZj" />
                        </button>
                        <button type="button" className="accountMenuItem-NXEKcd" onClick={onToggleTheme}>
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={moonSvg} size={16} className="trae-icon-Moon accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">主题</span>
                          <span className="accountMenuValue-iTOf2H">{theme === 'dark' ? '暗色' : '浅色'}</span>
                          <OfficialIcon svg={rightSvg} size={14} className="trae-icon-Right accountMenuArrow-fbYuZj" />
                        </button>
                      </section>
                      <section className="accountSection-gqAsGh">
                        <button
                          type="button"
                          className="accountMenuItem-NXEKcd"
                          onClick={() => { setAccountOpen(false); onOpenSettings() }}
                        >
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={settingsSvg} size={16} className="trae-icon-settings accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">设置</span>
                        </button>
                        <button type="button" className="accountMenuItem-NXEKcd">
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={feedbackSvg} size={16} className="trae-icon-feedback accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">报告问题</span>
                        </button>
                        <button type="button" className="accountMenuItem-NXEKcd">
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={downloadSvg} size={16} className="trae-icon-download accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">下载 TraeWork 桌面版</span>
                        </button>
                        <button type="button" className="accountMenuItem-NXEKcd">
                          <span className="accountMenuIcon-mCju4M"><OfficialIcon svg={mobileSvg} size={16} className="trae-icon-mobile accountMenuIconSvg-Y56ze8" /></span>
                          <span className="accountMenuLabel-VsH45r">下载 TRAE 移动端</span>
                          <OfficialIcon svg={rightSvg} size={14} className="trae-icon-Right accountMenuArrow-fbYuZj" />
                        </button>
                      </section>
                    </div>
                    <button type="button" className="accountLogoutButton-MqoPgT"><span>退出登录</span></button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      {searchOpen && (
        <div className="searchModalMask" onClick={() => setSearchOpen(false)}>
          <div className="dialog-W20BR0 modal-E7v43t searchDialog" role="dialog" onClick={(e) => e.stopPropagation()}>
            <div className="searchDialogHead">
              <Icon name="search" size={16} />
              <input
                className="searchInput-B4HMSr"
                placeholder="搜索任务名称及内容"
                value={searchQuery}
                autoFocus
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Escape') setSearchOpen(false) }}
              />
              {q && (
                <button type="button" className="searchClearBtn" aria-label="清除" onClick={() => setSearchQuery('')}>×</button>
              )}
            </div>
            <div className="searchDialogBody">
              {searchHits.length === 0 ? (
                <div className="searchEmpty">
                  <Icon name="search" size={20} />
                  <div>无匹配结果</div>
                  <div className="searchEmptyHint">试试其他关键词，或清除搜索内容</div>
                </div>
              ) : searchHits.map((hit) => {
                const snippet = q && hit.snippet ? hit.snippet : ''
                return (
                  <button
                    key={hit.id}
                    type="button"
                    className="searchHitRow"
                    onClick={() => { setSearchOpen(false); onSelectTask(hit.id) }}
                  >
                    <Icon name="code" size={16} />
                    <span className="searchHitMain">
                      <span className="searchHitTitle">{hit.title}</span>
                      {snippet && (
                        <span className="searchHitSnippet">{highlightQuery(snippet, q)}</span>
                      )}
                    </span>
                    <span className="searchHitBadge">Default</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}

function highlightQuery(text: string, query: string) {
  if (!query) return text
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx < 0) return text.slice(0, 80)
  const start = Math.max(0, idx - 12)
  const end = Math.min(text.length, idx + query.length + 36)
  const before = text.slice(start, idx)
  const match = text.slice(idx, idx + query.length)
  const after = text.slice(idx + query.length, end)
  return (
    <>
      {start > 0 ? '…' : ''}{before}
      <mark className="searchHitMark">{match}</mark>
      {after}
    </>
  )
}

/* =============================================================
   Message Renderer
   ============================================================= */
function renderBlock(block: MessageBlock, idx: number) {
  switch (block.type) {
    case 'text':
      return <AssistantMarkdown key={idx} content={block.content} />
    case 'code':
      return (
        <pre key={idx}><code className={`lang-${block.lang || 'text'}`}>{block.content}</code></pre>
      )
    case 'tool':
      return (
        <div key={idx} className="message-tool-result">
          {block.title && (
            <div style={{ color: 'var(--text-text-default)', fontWeight: 500, marginBottom: 4, fontSize: 'var(--font-size-sm)' }}>
              ▸ {block.title}
            </div>
          )}
          {block.content}
        </div>
      )
    case 'status':
      return (
        <div key={idx} className="message-status">
          <span className="status-dot-pulse" />
          {block.content}
        </div>
      )
  }
}

/* =============================================================
   Conversation view (user + agent messages paired into turns)
   ============================================================= */
function visibleAssistantBlocks(blocks: MessageBlock[]): MessageBlock[] {
  return studentVisibleBlocks(blocks)
}

function studentVisibleText(blocks: MessageBlock[]): string {
  return studentVisibleBlocks(blocks)
    .filter((b) => (b.type === 'text' || b.type === 'code') && b.content.trim())
    .map((b) => b.content)
    .join('\n\n')
}

function AssistantActionBar({ text }: { text: string }) {
  const [vote, setVote] = useState<null | 'up' | 'down'>(null)
  const [copied, setCopied] = useState(false)
  const copiedTimer = useRef<number | null>(null)

  useEffect(() => () => {
    if (copiedTimer.current) window.clearTimeout(copiedTimer.current)
  }, [])

  const copyAll = () => {
    if (copied) return
    if (text) {
      void navigator.clipboard.writeText(text).catch(() => {})
    }
    setCopied(true)
    if (copiedTimer.current) window.clearTimeout(copiedTimer.current)
    copiedTimer.current = window.setTimeout(() => setCopied(false), 4000)
  }

  return (
    <div data-item-type="widget:action-bar">
      <div className="latest-assistant-bar latest-assistant-bar-stage-0">
        <div className="latest-assistant-bar-left-part">
          <div className="assistant-action-bar">
            <div className="assistant-action-bar-buttons">
              <IconBtn
                icon={vote === 'up' ? 'like-fill' : 'like'}
                size="large"
                label="赞"
                tooltip="赞"
                testId="chat-icon-like"
                className={`action-bar-icon${vote === 'up' ? ' active' : ''}`}
                onClick={() => setVote((v) => (v === 'up' ? null : 'up'))}
              />
              <IconBtn
                icon={vote === 'down' ? 'unlike-fill' : 'unlike'}
                size="large"
                label="踩"
                tooltip="踩"
                testId="chat-icon-unlike"
                className={vote === 'down' ? 'active' : ''}
                onClick={() => setVote((v) => (v === 'down' ? null : 'down'))}
              />
              <IconBtn
                icon={copied ? 'copy-check' : 'copy'}
                size="large"
                label="复制全部"
                tooltip="复制全部"
                testId="chat-icon-copy"
                className={copied ? 'checked' : ''}
                onClick={copyAll}
              />
              <IconBtn
                icon="retry"
                size="large"
                label="重试"
                tooltip="重试"
                testId="chat-icon-retry"
              />
            </div>
          </div>
        </div>
        <div className="latest-assistant-bar-right-part">
          <span className="latest-assistant-bar-ai-disclaimer">由 AI 生成</span>
        </div>
      </div>
    </div>
  )
}

function ConversationView({ messages }: { messages: ChatMessage[]; streaming?: boolean }) {
  const turns: { user?: ChatMessage; agent?: ChatMessage }[] = []
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i]
    if (msg.role === 'user') {
      turns.push({ user: msg, agent: messages[i + 1]?.role === 'assistant' ? messages[i + 1] : undefined })
      if (messages[i + 1]?.role === 'assistant') i++
    } else if (msg.role === 'assistant') {
      turns.push({ agent: msg })
    }
  }

  return (
    <>
      {turns.map((turn, turnIdx) => {
        const isLast = turnIdx === turns.length - 1
        const visible = turn.agent ? visibleAssistantBlocks(turn.agent.blocks) : []
        const showAnswer = visible.length > 0
        return (
          <div key={`turn-${turnIdx}`} className={`turn ${isLast ? 'turn--last' : ''}`} data-turn-id={turn.user?.id || turn.agent?.id}>
            {turn.user && (
              <div className="turn__user-message" data-role="user">
                <section className="user-message" data-role="user" data-mode="code">
                  <div className="user-message__main">
                    <div className="user-message__content-area">
                      <div className="user-message__text-box">
                        <div className="user-message__text-wrapper">
                          <div className="user-message__text-inner">
                            <div className="user-message__text-content custom-scrollbar user-message__text-content--no-expand">
                              <div className="user-message-query-line">
                                <span className="user-message-query-text">
                                  {turn.user.blocks.map((b) => b.content).join('\n\n')}
                                </span>
                              </div>
                              {turn.user.attachments && turn.user.attachments.length > 0 && (
                                <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                  {turn.user.attachments.map((name) => (
                                    <span
                                      key={name}
                                      style={{
                                        fontSize: 12,
                                        color: 'var(--text-text-secondary)',
                                        background: 'var(--bg-bg-overlay-l1)',
                                        border: '1px solid var(--border-neutral-l1, transparent)',
                                        borderRadius: 6,
                                        padding: '2px 8px',
                                      }}
                                    >
                                      {name}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="user-message__bottom-bar">
                    <div className="user-message__bottom-bar-hover-actions">
                      <span className="trigger-jIoLhZ">
                        <span className="textEllipsis-uRFsZA singleLine-Bo6pad user-message__time">{turn.user.time}</span>
                      </span>
                      <span className="user-message__bottom-bar-divider" />
                      <div className="user-message__action-buttons">
                        <span className="trigger-jIoLhZ">
                          <span className="user-message__icon-wrapper">
                            <IconBtn icon="copy" size="small" variant="quaternary" label="复制" className="iconCopy-Giwy3p" />
                          </span>
                        </span>
                        <span className="trigger-jIoLhZ">
                          <IconBtn icon="delete" size="small" variant="quaternary" label="删除" />
                        </span>
                        <span className="trigger-jIoLhZ">
                          <IconBtn icon="revert" size="small" variant="quaternary" label="回退" />
                        </span>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            )}
            {turn.agent && (
              <div className="turn__agent-row">
                <div className="turn__agent-message" data-role="assistant">
                  <div data-item-type="turn:assistant-avatar">
                    <div className="agent-message__header">
                      <div className="agent-avatar agent-avatar--solo-code" style={{ width: 18, height: 18 }}>
                        <Icon name="work" size={12} />
                      </div>
                      <span className="agent-message__title">{turn.agent.author}</span>
                    </div>
                  </div>
                  <div data-item-type="agent:before-plans"></div>
                  {showAnswer ? (
                    <div data-item-type="plan-item:toolcall">
                      <div className="agent-plan-item" data-toolcall-type="finish">
                        <div className="core-finish-card">
                          <div className="core-finish-card__summary">
                            <div className="markdown-renderer">
                              {visible.map((b, i) => renderBlock(b, i))}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div data-item-type="plan-item:toolcall">
                      <div className="agent-plan-item" data-toolcall-type="finish" />
                    </div>
                  )}
                  <div data-item-type="agent:notification"></div>
                  <div data-item-type="agent:after-plans">
                    <div data-virtual-item-empty="after-plans" style={{ height: 0, overflow: 'hidden' }}></div>
                  </div>
                  {showAnswer && <AssistantActionBar text={studentVisibleText(turn.agent.blocks)} />}
                  <div data-item-type="agent:feedback"></div>
                  <div data-item-type="agent:last-content"></div>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}

/* =============================================================
   Composer – chat-input-v2
   ============================================================= */
const PLACEHOLDER_BY_MODE: Record<ModeTabId, string> = {
  work: '帮你整理论文综述、编写 PPT、分析 Excel 等日常工作，输出专业级工作成果。',
  code: `围绕你的资料开始学习，${PRODUCT_NAME} 会决定下一步。`,
  design: '从想法到设计，生成可交付的页面原型',
}

const EMPTY_EDITOR_HTML = '<p class="chat-input-v2__paragraph" dir="auto"><br></p>'

function readEditableText(el: HTMLElement): string {
  return (el.innerText || el.textContent || '').replace(/\u00a0/g, ' ').replace(/\n$/, '')
}

function isEditorEmpty(text: string): boolean {
  return text.replace(/\u200b/g, '').trim().length === 0
}

function ComposerPlusIcon() {
  return (
    <svg className="trae-icon trae-icon-add" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M7.375 13.5V8.625H2.5C2.15482 8.625 1.875 8.34518 1.875 8C1.875 7.65482 2.15482 7.375 2.5 7.375H7.375V2.5C7.375 2.15482 7.65482 1.875 8 1.875C8.34518 1.875 8.625 2.15482 8.625 2.5V7.375H13.5C13.8452 7.375 14.125 7.65482 14.125 8C14.125 8.34518 13.8452 8.625 13.5 8.625H8.625V13.5C8.625 13.8452 8.34518 14.125 8 14.125C7.65482 14.125 7.375 13.8452 7.375 13.5Z" fill="currentColor" />
    </svg>
  )
}

function ComposerPluginIcon() {
  return (
    <svg className="trae-icon trae-icon-Plugin-puzzle-piece messageInputPluginToolbarIcon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M12.7087 5.33337C12.7087 4.57409 12.093 3.95855 11.3337 3.95837H9.66675C9.32157 3.95837 9.04175 3.67855 9.04175 3.33337V3.00037C9.04175 2.42507 8.57505 1.95837 7.99976 1.95837C7.42462 1.95855 6.95874 2.42518 6.95874 3.00037V3.33337C6.95874 3.67844 6.67877 3.9582 6.33374 3.95837H4.66675C3.90736 3.95837 3.29175 4.57399 3.29175 5.33337V10.6664C3.29175 11.4258 3.90735 12.0414 4.66675 12.0414H11.3337C12.093 12.0412 12.7087 11.4257 12.7087 10.6664V10.2709C11.5809 10.1276 10.7089 9.16706 10.7087 8.00037C10.7087 6.83347 11.5807 5.8711 12.7087 5.72791V5.33337ZM13.9587 6.33337C13.9587 6.67844 13.6788 6.9582 13.3337 6.95837H12.9998C12.4246 6.95855 11.9587 7.42519 11.9587 8.00037C11.9589 8.5754 12.4247 9.04121 12.9998 9.04138H13.3337C13.6787 9.04156 13.9586 9.32146 13.9587 9.66638V10.6664C13.9587 12.1161 12.7834 13.2912 11.3337 13.2914H4.66675C3.21701 13.2914 2.04175 12.1162 2.04175 10.6664V5.33337C2.04175 3.88363 3.217 2.70837 4.66675 2.70837H5.72925C5.87264 1.5807 6.83317 0.708536 7.99976 0.708374C9.1665 0.708374 10.1278 1.58057 10.2712 2.70837H11.3337C12.7834 2.70855 13.9587 3.88374 13.9587 5.33337V6.33337Z" />
    </svg>
  )
}

function ComposerMicIcon() {
  return (
    <svg className="trae-icon trae-icon-microphone" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M7.37588 14V13.2598C5.00179 13.0269 3.56866 11.4947 2.81924 10.3398C2.63161 10.0503 2.71437 9.66342 3.00381 9.47559C3.29332 9.28796 3.68023 9.37072 3.86806 9.66016C4.56507 10.7341 5.84777 12.042 8.00088 12.042C10.154 12.0419 11.4367 10.7341 12.1337 9.66016C12.3216 9.37067 12.7084 9.28785 12.9979 9.47559C13.2874 9.6634 13.3701 10.0503 13.1825 10.3398C12.4331 11.4946 10.9998 13.0268 8.62588 13.2598V14C8.62588 14.3451 8.34601 14.6249 8.00088 14.625C7.6557 14.625 7.37588 14.3452 7.37588 14ZM10.0429 4.66699C10.0429 3.53945 9.12839 2.62506 8.00088 2.625C6.87329 2.625 5.95888 3.53941 5.95888 4.66699V7.33301C5.95888 8.46057 6.87329 9.375 8.00088 9.375C9.12838 9.37494 10.0429 8.46053 10.0429 7.33301V4.66699ZM11.2929 7.33301C11.2929 9.15088 9.81874 10.6249 8.00088 10.625C6.18293 10.625 4.70888 9.15092 4.70888 7.33301V4.66699C4.70888 2.84905 6.18293 1.375 8.00088 1.375C9.81874 1.37506 11.2929 2.84909 11.2929 4.66699V7.33301Z" fill="currentColor" />
    </svg>
  )
}

function ComposerChevronIcon() {
  return (
    <svg className="trae-icon trae-icon-up" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M6.85078 6.93148C7.48529 6.29716 8.51406 6.29727 9.14863 6.93148L11.1086 8.89144C11.3526 9.1355 11.3526 9.53117 11.1086 9.77523C10.8645 10.0193 10.4689 10.0192 10.2248 9.77523L8.26485 7.81527C8.11842 7.66921 7.88093 7.6691 7.73457 7.81527L5.77559 9.77523C5.53151 10.0193 5.1349 10.0193 4.89082 9.77523C4.64707 9.53121 4.64707 9.13546 4.89082 8.89144L6.85078 6.93148Z" fill="currentColor" />
    </svg>
  )
}

function SendArrowIcon() {
  return (
    <svg className="trae-icon trae-icon-arrow_up chat-input-v2-send-button-arrow-icon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M7.65576 2.14423C7.89827 1.98431 8.22841 2.01097 8.44189 2.2243L12.4419 6.2243C12.686 6.46838 12.686 6.86499 12.4419 7.10907C12.1978 7.35298 11.8012 7.35309 11.5571 7.10907L8.62451 4.17645V13.3337C8.62434 13.6787 8.34458 13.9587 7.99951 13.9587C7.65461 13.9585 7.37469 13.6786 7.37451 13.3337V4.17645L4.44189 7.10907C4.1978 7.35298 3.80115 7.35309 3.55713 7.10907C3.31326 6.86504 3.31327 6.46834 3.55713 6.2243L7.55713 2.2243L7.65576 2.14423Z" />
    </svg>
  )
}

function SendVoiceIcon() {
  return (
    <svg className="trae-icon trae-icon-chat chat-input-v2-send-button-voice-icon" width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M2.37305 10V6C2.37305 5.6539 2.6539 5.37305 3 5.37305C3.3461 5.37305 3.62695 5.6539 3.62695 6V10C3.62695 10.3461 3.3461 10.627 3 10.627C2.6539 10.627 2.37305 10.3461 2.37305 10ZM12.373 8.66659V7.33325C12.373 6.98715 12.6539 6.7063 13 6.7063C13.3461 6.7063 13.627 6.98715 13.627 7.33325V8.66659C13.627 9.01268 13.3461 9.29354 13 9.29354C12.6539 9.29354 12.373 9.01268 12.373 8.66659ZM9.03979 10.6666V5.33325C9.03979 4.98715 9.32065 4.7063 9.66675 4.7063C10.0128 4.7063 10.2937 4.98715 10.2937 5.33325V10.6666C10.2937 11.0127 10.0128 11.2935 9.66675 11.2935C9.32065 11.2935 9.03979 11.0127 9.03979 10.6666ZM5.7063 13.3334V2.66675C5.7063 2.32065 5.98715 2.03979 6.33325 2.03979C6.67935 2.03979 6.96021 2.32065 6.96021 2.66675V13.3334C6.96021 13.6795 6.67935 13.9604 6.33325 13.9604C5.98715 13.9604 5.7063 13.6795 5.7063 13.3334Z" />
    </svg>
  )
}

function Composer({
  value, onChange, onSend, mode, disabled, variant = 'conversation', autoFocus = false,
  capability = 'chat',
  onCapabilityChange,
  tools = [],
  selectedTools = [],
  onToggleTool,
  attachments = [],
  onAddFiles,
  onRemoveAttachment,
  streaming = false,
  onCancel,
}: {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  mode: ModeTabId
  disabled?: boolean
  variant?: 'home' | 'conversation'
  autoFocus?: boolean
  capability?: string
  onCapabilityChange?: (id: string) => void
  tools?: ToolItem[]
  selectedTools?: string[]
  onToggleTool?: (name: string) => void
  attachments?: FileAttachment[]
  onAddFiles?: (files: FileList) => void
  onRemoveAttachment?: (filename: string) => void
  streaming?: boolean
  onCancel?: () => void
}) {
  const editableRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const composingRef = useRef(false)
  const [focused, setFocused] = useState(!!autoFocus)
  const [capOpen, setCapOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [plusOpen, setPlusOpen] = useState(false)
  const [plusHover, setPlusHover] = useState('上传图片')
  const plusMenuRef = useRef<HTMLSpanElement>(null)
  const plusListRef = useRef<HTMLDivElement>(null)
  const pluginMenuRef = useRef<HTMLSpanElement>(null)
  const pluginListRef = useRef<HTMLDivElement>(null)
  const capMenuRef = useRef<HTMLDivElement>(null)
  const capListRef = useRef<HTMLDivElement>(null)
  const [plusPos, setPlusPos] = useState({ top: 0, left: 0 })
  const [pluginPos, setPluginPos] = useState({ top: 0, left: 0 })
  const [capPos, setCapPos] = useState({ top: 0, left: 0 })
  const closePlus = useCallback(() => setPlusOpen(false), [])
  const closeTools = useCallback(() => setToolsOpen(false), [])
  const closeCap = useCallback(() => setCapOpen(false), [])
  useDismiss(plusOpen, closePlus, plusMenuRef)
  useDismiss(toolsOpen, closeTools, pluginMenuRef)
  useDismiss(capOpen, closeCap, capMenuRef)

  useLayoutEffect(() => {
    if (!plusOpen) return
    const trigger = plusMenuRef.current?.querySelector('.messageInputToolbarIconBtn') as HTMLElement | null
    const menu = plusListRef.current
    if (!trigger || !menu) return
    const r = trigger.getBoundingClientRect()
    setPlusPos({ top: Math.max(8, r.top - menu.offsetHeight - 6), left: r.left })
  }, [plusOpen])

  useLayoutEffect(() => {
    if (!toolsOpen) return
    const trigger = pluginMenuRef.current?.querySelector('.messageInputPluginToolbar') as HTMLElement | null
    const pop = pluginListRef.current
    if (!trigger || !pop) return
    const r = trigger.getBoundingClientRect()
    setPluginPos({ top: Math.max(8, r.top - pop.offsetHeight - 6), left: r.left })
  }, [toolsOpen])

  useLayoutEffect(() => {
    if (!capOpen) return
    const trigger = capMenuRef.current?.querySelector('.core-model-select-trigger') as HTMLElement | null
    const list = capListRef.current
    if (!trigger || !list) return
    const r = trigger.getBoundingClientRect()
    const h = list.offsetHeight
    const w = list.offsetWidth
    setCapPos({
      top: Math.max(8, r.top - h - 4),
      left: Math.max(8, r.right - w),
    })
  }, [capOpen])
  const empty = isEditorEmpty(value)
  const canSend = (!empty || attachments.length > 0) && !disabled && !streaming
  const capabilityLabel = CAPABILITIES.find((item) => item.id === capability)?.label || '对话'

  useLayoutEffect(() => {
    const el = editableRef.current
    if (!el) return
    if (!el.innerHTML) {
      el.innerHTML = EMPTY_EDITOR_HTML
    }
    if (empty && readEditableText(el).trim() !== '') {
      el.innerHTML = EMPTY_EDITOR_HTML
    }
    el.style.height = 'auto'
    const next = el.scrollHeight
    if (next > 0) {
      el.style.height = `${Math.min(next, 152)}px`
    }
  }, [value, empty])

  useEffect(() => {
    if (!autoFocus) return
    const el = editableRef.current
    if (!el) return
    const id = window.requestAnimationFrame(() => {
      el.focus()
      setFocused(true)
    })
    return () => window.cancelAnimationFrame(id)
  }, [autoFocus])

  const emitChange = (el: HTMLElement) => {
    onChange(readEditableText(el))
  }

  const trySend = () => {
    if (composingRef.current) return
    const el = editableRef.current
    const text = el ? readEditableText(el) : value
    if ((isEditorEmpty(text) && attachments.length === 0) || disabled || streaming) return
    onChange(text)
    onSend()
    window.setTimeout(() => {
      editableRef.current?.focus()
    }, 0)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const composing =
      composingRef.current ||
      e.nativeEvent.isComposing ||
      e.keyCode === 229
    if (e.key !== 'Enter' || e.shiftKey) return
    if (composing) return
    e.preventDefault()
    trySend()
  }

  const focusEditor = () => {
    editableRef.current?.focus()
  }

  const containerClass = [
    'chat-input-v2-container',
    focused ? 'chat-input-v2-container--has-focus' : 'chat-input-v2-container--no-focus',
    empty ? 'chat-input-v2-container--empty' : '',
    'messageInputChatInput',
    variant === 'home' ? 'messageInputChatInputHome' : 'messageInputChatInputConversation',
  ].filter(Boolean).join(' ')

  const editor = (
    <div className="messageInputContainer" data-mode="code">
      {variant === 'conversation' && (
        <div className="channelContainer-m36aPB messageInputToastContainer" />
      )}
      <div className="messageInputEditorWrapper">
        <div className={containerClass}>
          <div className="chat-input-v2-editor-part">
            <div className="chat-input-v2-upper-area">
              <div className="chat-input-v2-slot-header" />
              <div
                className="chat-input-v2-input-box-wrapper chat-input-v2-input-box--modern-scroll"
                onMouseDown={(e) => {
                  const t = e.target as HTMLElement
                  if (t === e.currentTarget || t.classList.contains('chat-input-v2-placeholder')) {
                    e.preventDefault()
                    focusEditor()
                  }
                }}
              >
                <div
                  className="chat-input-v2-placeholder"
                  id="chat-input-v2-placeholder-MessageEditor"
                  style={{ display: empty ? 'block' : 'none' }}
                >
                  {PLACEHOLDER_BY_MODE[mode]}
                </div>
                <div
                  ref={editableRef}
                  className="chat-input-v2-input-box-editable"
                  contentEditable
                  role="textbox"
                  aria-multiline="true"
                  spellCheck
                  tabIndex={0}
                  suppressContentEditableWarning
                  style={{ userSelect: 'text', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                  data-placeholder-hidden={empty ? 'false' : 'true'}
                  onFocus={() => setFocused(true)}
                  onBlur={() => setFocused(false)}
                  onCompositionStart={() => {
                    composingRef.current = true
                  }}
                  onCompositionEnd={(e) => {
                    composingRef.current = false
                    emitChange(e.currentTarget)
                  }}
                  onInput={(e) => emitChange(e.currentTarget)}
                  onKeyDown={onKeyDown}
                />
              </div>
            </div>
            {attachments.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '0 12px 8px' }}>
                {attachments.map((file) => (
                  <button
                    key={file.filename}
                    type="button"
                    onClick={() => onRemoveAttachment?.(file.filename)}
                    style={{
                      fontSize: 12,
                      color: 'var(--text-text-secondary)',
                      background: 'var(--bg-bg-overlay-l1)',
                      border: '1px solid var(--border-neutral-l1, transparent)',
                      borderRadius: 6,
                      padding: '2px 8px',
                      cursor: 'pointer',
                    }}
                  >
                    {file.filename} ×
                  </button>
                ))}
              </div>
            )}
            <div className="chat-input-v2-editor-part-lower-content">
              <div className="chat-input-v2-editor-part-lower__left">
                <div className="left-l">
                  <span ref={plusMenuRef} className="trigger-jIoLhZ" style={{ position: 'relative' }}>
                    <HoverTooltip text="添加文件及更多" disabled={plusOpen}>
                      <button
                        type="button"
                        className="messageInputToolbarIconBtn"
                        aria-label="添加文件及更多"
                        aria-haspopup="menu"
                        aria-expanded={plusOpen}
                        onClick={() => {
                          setPlusOpen((v) => !v)
                          setToolsOpen(false)
                          setCapOpen(false)
                        }}
                      >
                        <ComposerPlusIcon />
                      </button>
                    </HoverTooltip>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      hidden
                      onChange={(e) => {
                        if (e.target.files && e.target.files.length) onAddFiles?.(e.target.files)
                        e.currentTarget.value = ''
                      }}
                    />
                    {plusOpen && (
                      <div
                        ref={plusListRef}
                        className="cascadeMenu-vEfgk4 cascadeMenuCompact-dZSx8L cascadeMenuTop-JKmCgk"
                        data-placement="top"
                        data-level="0"
                        style={{ top: plusPos.top, left: plusPos.left }}
                      >
                        <div className="cascadeMenuContent-tUO2DP" role="menu">
                          <div className="cascadeMenuGroup-QOU4ge">
                            <div className="cascadeMenuGroupContent-erkIKZ">
                              <button
                                type="button"
                                role="menuitem"
                                aria-label="上传图片"
                                className={`cascadeMenuItem-MYlrAy${plusHover === '上传图片' ? ' cascadeMenuItemHighlighted-MCjioq' : ''}`}
                                onMouseEnter={() => setPlusHover('上传图片')}
                                onClick={() => {
                                  closePlus()
                                  fileInputRef.current?.click()
                                }}
                              >
                                <span className="cascadeMenuItemInner-K6B214">
                                  <span className="cascadeMenuItemIcon-SLejGm"><Icon name="image" size={16} /></span>
                                  <span className="cascadeMenuItemContent-edbTCu"><span className="cascadeMenuItemTitle-k1Reti">上传图片</span></span>
                                </span>
                              </button>
                              <button
                                type="button"
                                role="menuitem"
                                aria-label="当前项目的文件"
                                className={`cascadeMenuItem-MYlrAy${plusHover === '当前项目的文件' ? ' cascadeMenuItemHighlighted-MCjioq' : ''}`}
                                onMouseEnter={() => setPlusHover('当前项目的文件')}
                                onClick={closePlus}
                              >
                                <span className="cascadeMenuItemInner-K6B214">
                                  <span className="cascadeMenuItemIcon-SLejGm"><Icon name="folder" size={16} /></span>
                                  <span className="cascadeMenuItemContent-edbTCu"><span className="cascadeMenuItemTitle-k1Reti">当前项目的文件</span></span>
                                  <span className="cascadeMenuItemArrow-v9eb0K"><Icon name="chevron-right" size={16} /></span>
                                </span>
                              </button>
                            </div>
                          </div>
                          <div className="cascadeMenuDivider-hnyI7h" />
                          <div className="cascadeMenuGroup-QOU4ge">
                            <div className="cascadeMenuGroupContent-erkIKZ">
                              {([
                                { label: '命令', icon: 'command' },
                                { label: '插件', icon: 'plugin' },
                                { label: '技能', icon: 'skill' },
                              ] as const).map((item) => (
                                <button
                                  key={item.label}
                                  type="button"
                                  role="menuitem"
                                  aria-label={item.label}
                                  className={`cascadeMenuItem-MYlrAy${plusHover === item.label ? ' cascadeMenuItemHighlighted-MCjioq' : ''}`}
                                  onMouseEnter={() => setPlusHover(item.label)}
                                  onClick={closePlus}
                                >
                                  <span className="cascadeMenuItemInner-K6B214">
                                    <span className="cascadeMenuItemIcon-SLejGm"><Icon name={item.icon} size={16} /></span>
                                    <span className="cascadeMenuItemContent-edbTCu"><span className="cascadeMenuItemTitle-k1Reti">{item.label}</span></span>
                                    <span className="cascadeMenuItemArrow-v9eb0K"><Icon name="chevron-right" size={16} /></span>
                                  </span>
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                    {plusOpen && plusHover === '插件' && (
                      <div className="cascadeMenu-vEfgk4 plusPluginFlyout" role="menu" style={{ top: plusPos.top, left: plusPos.left + 188 }}>
                        <div className="cascadeMenuContent-tUO2DP">
                          <div className="availablePluginsHeader-P_cU8B">可用插件</div>
                          {tools.slice(0, 4).map((tool) => (
                            <button key={tool.name} type="button" className="cascadeMenuItem-MYlrAy" onClick={() => { onToggleTool?.(tool.name); closePlus() }}>
                              <span className="cascadeMenuItemInner-K6B214">
                                <span className="cascadeMenuItemContent-edbTCu"><span className="cascadeMenuItemTitle-k1Reti">{tool.label}</span></span>
                              </span>
                            </button>
                          ))}
                          <div className="cascadeMenuDivider-hnyI7h" />
                          <button type="button" className="cascadeMenuItem-MYlrAy" onClick={closePlus}>
                            <span className="cascadeMenuItemInner-K6B214"><span className="cascadeMenuItemTitle-k1Reti">管理插件</span></span>
                          </button>
                          <button type="button" className="cascadeMenuItem-MYlrAy" onClick={closePlus}>
                            <span className="cascadeMenuItemInner-K6B214"><span className="cascadeMenuItemTitle-k1Reti">探索更多插件</span></span>
                          </button>
                        </div>
                      </div>
                    )}
                  </span>
                  <span ref={pluginMenuRef} className="trigger-jIoLhZ" style={{ position: 'relative' }}>
                    <HoverTooltip text="调用插件" disabled={toolsOpen}>
                      <span className="wrapper-RV5xqM">
                        <button
                          type="button"
                          className={`messageInputPluginToolbar${toolsOpen ? ' messageInputPluginToolbarActive' : ''}`}
                          aria-label="调用插件"
                          aria-expanded={toolsOpen}
                          onClick={() => { setToolsOpen((v) => !v); setPlusOpen(false); setCapOpen(false) }}
                        >
                          <span className="messageInputPluginToolbarIconWrapper" aria-hidden="true">
                            <ComposerPluginIcon />
                          </span>
                        </button>
                      </span>
                    </HoverTooltip>
                    {toolsOpen && (
                      <div
                        ref={pluginListRef}
                        className="availablePluginsPopover-lLsv2r"
                        role="dialog"
                        style={{ top: pluginPos.top, left: pluginPos.left }}
                      >
                        <div className="availablePluginsHeader-P_cU8B">可用插件</div>
                        <div className="availablePluginsList-JTlNb1 custom-scrollbar">
                          {tools.map((tool) => {
                            const on = selectedTools.includes(tool.name)
                            return (
                              <div key={tool.name} className="availablePluginsMenuItemFrame-Y_o7RI">
                                <button
                                  type="button"
                                  className="availablePluginsMenuItem-fEHYkF"
                                  aria-pressed={on}
                                  onClick={() => onToggleTool?.(tool.name)}
                                >
                                  <span className="availablePluginsItemMain-lz8TUi">
                                    <Icon name="plugin" size={16} className="availablePluginsActionIcon-s3RRwP" />
                                    <span className="availablePluginsItemName-pn1yr8">{tool.label}</span>
                                  </span>
                                </button>
                              </div>
                            )
                          })}
                        </div>
                        <div className="availablePluginsDivider-QxJoxe" />
                        <div className="availablePluginsMenuItemFrame-Y_o7RI">
                          <button type="button" className="availablePluginsMenuItem-fEHYkF" onClick={closeTools}>
                            <span className="availablePluginsItemMain-lz8TUi">
                              <Icon name="filter" size={16} className="availablePluginsActionIcon-s3RRwP" />
                              <span>管理插件</span>
                            </span>
                          </button>
                        </div>
                        <div className="availablePluginsMenuItemFrame-Y_o7RI">
                          <button type="button" className="availablePluginsMenuItem-fEHYkF" onClick={closeTools}>
                            <span className="availablePluginsItemMain-lz8TUi">
                              <Icon name="expand" size={16} className="availablePluginsActionIcon-s3RRwP" />
                              <span>探索更多插件</span>
                            </span>
                          </button>
                        </div>
                      </div>
                    )}
                  </span>
                </div>
                <div className="left-l-select">
                  <div className="model-select-area">
                    <div className="model-select-area-model">
                      <div>
                        <div ref={capMenuRef} className="core-model-select" style={{ position: 'relative' }}>
                          <button
                            type="button"
                            role="combobox"
                            aria-expanded={capOpen}
                            data-state={capOpen ? 'open' : 'closed'}
                            className="core-model-select-trigger"
                            onClick={() => { setCapOpen((v) => !v); setToolsOpen(false); setPlusOpen(false) }}
                          >
                            <div className="core-model-select-trigger-value">
                              <span>{capabilityLabel}</span>
                            </div>
                            <span aria-hidden="true" className="core-model-select-trigger-arrow">
                              <ComposerChevronIcon />
                            </span>
                          </button>
                          {capOpen && (
                            <div
                              ref={capListRef}
                              className="core-model-select-portal-content"
                              role="listbox"
                              data-side="top"
                              data-align="end"
                              data-state="open"
                              style={{ top: capPos.top, left: capPos.left }}
                            >
                              <div className="core-model-select-portal-viewport">
                                <div className="core-model-select-portal-inner-content">
                                  <div className="core-model-select-model-list">
                                    <div role="group" className="core-model-select-model-group">
                                      <div className="core-model-select-model-group-label"><span>能力</span></div>
                                      {CAPABILITIES.map((item) => (
                                        <button
                                          key={item.id}
                                          type="button"
                                          role="option"
                                          aria-selected={item.id === capability}
                                          className="core-model-select-model-item"
                                          onClick={() => {
                                            onCapabilityChange?.(item.id)
                                            setCapOpen(false)
                                          }}
                                        >
                                          <div className="core-model-select-model-item-wrapper">
                                            <div className="core-model-select-model-item-inner-wrapper">
                                              <span className="core-model-select-model-item-name">{item.label}</span>
                                            </div>
                                            {item.id === capability && (
                                              <div className="core-model-select-model-item-check">
                                                <Icon name="check" size={16} />
                                              </div>
                                            )}
                                          </div>
                                        </button>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div className="chat-input-v2-editor-part-lower__right">
                <div className="chat-input-v2-slot-toolbar-right">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <HoverTooltip text="语音输入 (⌃ V)">
                      <span style={{ display: 'inline-flex' }}>
                        <button type="button" className="rtcVoicePluginButton" aria-label="语音输入">
                          <ComposerMicIcon />
                        </button>
                      </span>
                    </HoverTooltip>
                  </div>
                </div>
                <span className="wrapper-RV5xqM">
                  <HoverTooltip text={streaming ? '停止' : canSend ? '发送' : '语音讨论'}>
                    <span style={{ display: 'inline-flex' }}>
                      <button
                        type="button"
                        className={`chat-input-v2-send-button${canSend || streaming ? '' : ' voice-call-mode'}`}
                        onClick={streaming ? onCancel : trySend}
                        aria-label={streaming ? '停止' : canSend ? '发送' : '语音讨论'}
                      >
                        {streaming ? (
                          <span style={{ width: 10, height: 10, borderRadius: 2, background: 'currentColor', display: 'inline-block' }} />
                        ) : canSend ? <SendArrowIcon /> : <SendVoiceIcon />}
                      </button>
                    </span>
                  </HoverTooltip>
                </span>
              </div>
            </div>
            <div className="chat-input-v2-slot-overlay" />
          </div>
        </div>
      </div>
    </div>
  )

  if (variant === 'home') return editor

  return (
    <>
      <div className="channelContainer-m36aPB sessionToastContainer-hJoxUa" />
      {editor}
    </>
  )
}

/* =============================================================
   Split Handle – drag to resize right panel
   ============================================================= */
interface SplitHandleProps {
  onDragStart?: () => void
}
function SplitHandle({ onDragStart }: SplitHandleProps) {
  const [dragging, setDragging] = useState(false)

  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    setDragging(true)
    onDragStart?.()
    document.body.classList.add('dragging-resize')
    const startX = e.clientX
    const root = document.documentElement
    const cur = parseInt(
      getComputedStyle(root).getPropertyValue('--right-panel-default-width') || '395',
      10
    )
    const minW = 392
    const maxW = Math.min(window.innerWidth * 0.6, 800)

    const onMove = (ev: MouseEvent) => {
      const delta = startX - ev.clientX
      let next = cur + delta
      next = Math.max(minW, Math.min(maxW, next))
      root.style.setProperty('--right-panel-default-width', `${next}px`)
    }
    const onUp = () => {
      setDragging(false)
      document.body.classList.remove('dragging-resize')
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      try {
        const w = parseInt(
          getComputedStyle(document.documentElement).getPropertyValue('--right-panel-default-width'),
          10
        )
        localStorage.setItem('trae:rightPanelWidth', String(w))
      } catch { /* ignore storage errors */ }
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  return (
    <div
      className={`splitHandle-IEUrKW splitHandleHorizontal-JdteEX ${dragging ? 'dragging' : ''}`}
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation="vertical"
      aria-label="调整右栏宽度"
    />
  )
}

/* =============================================================
   Right Panel (context-status)
   ============================================================= */
function RightPanel({
  onClose, session, attachments = [],
}: {
  onClose: () => void
  session?: ChassisSession | null
  attachments?: string[]
}) {
  const pct = contextUsage.percent
  return (
    <div className="rightContentWrapper-jhsdbE">
      <div className="pinnedPanelWrapper-wMW068">
        <div className="container-UhGXJa containerPassthrough-IjBXaD">
          <div className="content-FHMU5b">
            <div className="panel-efpq6k panelPinned-lBPQ4I">
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                {/* Tab bar */}
                <div className="tabBar-Fos90P">
                  <div className="tabListArea-fsHLNV">
                    <div className="tabList-QinFV4">
                      <div className="tabItem-wqUDGi tabItemActive-uKd7Iz">
                        <div className="tabContent-B4P0lk">
                          <span className="tabIcon-eVydLj">
                            <Icon name="task" size={14} />
                          </span>
                          <span className="trigger-jIoLhZ">
                            <span className="textEllipsis-uRFsZA singleLine-Bo6pad tabTitle-yKC9bK">任务摘要</span>
                          </span>
                        </div>
                      </div>
                    </div>
                    <span className="trigger-jIoLhZ">
                      <button className="button-muTeiY tertiary-gVkSeX default-siL9wr addButton-ZjHzJB" disabled aria-label="新增">
                        <span className="prefixIcon-xbE610">
                          <Icon name="plus" size={16} />
                        </span>
                      </button>
                    </span>
                  </div>
                  <div className="actions-LvRwyL">
                    <span className="trigger-jIoLhZ">
                      <button className="button-muTeiY tertiary-gVkSeX default-siL9wr actionButton-t5TiB8" aria-label="展开">
                        <span className="prefixIcon-xbE610">
                          <Icon name="expand" size={16} />
                        </span>
                      </button>
                    </span>
                    <span className="trigger-jIoLhZ">
                      <button className="button-muTeiY tertiary-gVkSeX default-siL9wr actionButton-t5TiB8" aria-label="关闭面板" onClick={onClose}>
                        <span className="prefixIcon-xbE610">
                          <Icon name="view-left" size={16} />
                        </span>
                      </button>
                    </span>
                  </div>
                </div>

                {/* Panel content */}
                <div id="session-panel-container" style={{ display: 'flex', position: 'relative', flex: '1 1 0%', minHeight: 0, overflow: 'hidden' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 0%', minHeight: 0, overflow: 'hidden' }}>
                    <div className="panelShell-tL6HkN">
                      <div className="panelContent-g2g4AM">
                        <div className="container-xaMdj0">
                          <div className="context-status_sidebar context-status_sidebar--code">
                            {/* 思考 (progress) */}
                            <div className="context-status_section context-status_section--progress">
                              <div className="context-status_section-header context-status_section-header--clickable">
                                <div className="context-status_section-header-left">
                                  <span className="context-status_section-title">待办</span>
                                  <span className="context-status_section-chevron">
                                    <Icon name="chevron-down" size={14} />
                                  </span>
                                </div>
                              </div>
                              <div className="context-status_section-content">
                                <div className="context-status_empty-state">
                                  <div className="context-status_empty-state-icon">
                                    <Icon name="task" size={16} />
                                  </div>
                                  <div className="context-status_empty-state-content">
                                    <div className="context-status_empty-state-title">暂无待办</div>
                                    <div className="context-status_empty-state-description">复杂任务的进展会显示在这里</div>
                                    {attachments.length > 0 && (
                                      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-text-secondary)' }}>
                                        附件：{attachments.join('、')}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>

                            <div className="context-status_divider-wrapper">
                              <div className="divider-OMH_4r">
                                <hr className="line-HcMivY" />
                              </div>
                            </div>

                            {/* 上下文 */}
                            <div className="context-status_section context-status_section--context">
                              <div className="context-status_section-header context-status_section-header--clickable">
                                <div className="context-status_section-header-left">
                                  <span className="context-status_section-title">上下文</span>
                                  <span className="context-status_section-chevron">
                                    <Icon name="chevron-down" size={14} />
                                  </span>
                                  <span className="trigger-jIoLhZ">
                                    <span className="context-status_section-info-icon">
                                      <Icon name="info" size={14} />
                                    </span>
                                  </span>
                                </div>
                                <button className="context-status_section-compact-btn">压缩</button>
                              </div>
                              <div className="context-status_section-content">
                                <div className="context-status_context-panel">
                                  <div className="context-status_usage-bar">
                                    <div className="context-status_usage-bar-track">
                                      {contextUsage.segments.map((s, i) => (
                                        <span key={i} className="trigger-jIoLhZ">
                                          <div
                                            className="context-status_usage-bar-segment"
                                            style={{
                                              width: `${s.width}%`,
                                              backgroundColor: 'color-mix(in srgb, var(--accent-accent-slate, #747E94) 32%, transparent)',
                                            }}
                                          />
                                        </span>
                                      ))}
                                    </div>
                                    <span className="trigger-jIoLhZ">
                                      <span className="context-status_usage-bar-percent">{pct}%</span>
                                    </span>
                                  </div>
                                  <div className="context-status_context-panel-content">
                                    <div className="context-status_empty-state">
                                      <div className="context-status_empty-state-icon">
                                        <Icon name="context" size={16} />
                                      </div>
                                      <div className="context-status_empty-state-content">
                                        <div className="context-status_empty-state-title">暂未使用上下文</div>
                                        <div className="context-status_empty-state-description">追踪 TraeWork 工作时使用的工具和文件</div>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* =============================================================
   Debug Overlay
   ============================================================= */
function DebugOverlay({
  sidebarOpen, statusOpen, theme, mode, leftWidth, rightWidth, mainWidth,
}: {
  sidebarOpen: boolean
  statusOpen: boolean
  theme: 'light' | 'dark'
  mode: ModeTabId
  leftWidth: number
  rightWidth: number
  mainWidth: number
}) {
  const [vpW, setVpW] = useState(window.innerWidth)
  const [vpH, setVpH] = useState(window.innerHeight)
  useEffect(() => {
    const f = () => { setVpW(window.innerWidth); setVpH(window.innerHeight) }
    window.addEventListener('resize', f)
    return () => window.removeEventListener('resize', f)
  }, [])
  return (
    <div className="debug-overlay" role="status" aria-label="Debug overlay">
      <h4>🔍 Debug Mode</h4>
      <div className="debug-grid">
        <div className="k">Viewport</div>       <div className="v">{vpW} × {vpH}</div>
        <div className="k">Left Panel</div>     <div className="v">{sidebarOpen ? `${leftWidth}px` : 'OFF'}</div>
        <div className="k">Main Workspace</div> <div className="v">{mainWidth}px</div>
        <div className="k">Right Panel</div>    <div className="v">{statusOpen ? `${rightWidth}px` : 'OFF'}</div>
        <div className="k">Theme</div>          <div className="v">{theme}</div>
        <div className="k">Mode</div>           <div className="v">{mode}</div>
        <div className="k">Left</div>           <div className="v">{sidebarOpen ? 'ON' : 'OFF'}</div>
        <div className="k">Status</div>         <div className="v">{statusOpen ? 'ON' : 'OFF'}</div>
      </div>
    </div>
  )
}

/* =============================================================
   Main App
   ============================================================= */
const LS_THEME = 'trae:theme'
const LS_LEFT = 'trae:sidebarOpen'
const LS_STATUS = 'trae:statusOpen'
const LS_RIGHTW = 'trae:rightPanelWidth'

function readBoolLs(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return fallback
    return v === '1' || v === 'true'
  } catch { return fallback }
}
function readStrLs(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}

export default function App() {
  // --- Theme ---
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = readStrLs(LS_THEME, '') as 'light' | 'dark' | ''
    if (saved) return saved
    return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  })
  const [language, setLanguage] = useState<LanguageId>(() => (
    readStrLs(LS_LANGUAGE, 'zh') === 'en' ? 'en' : 'zh'
  ))
  const [responseLanguage, setResponseLanguage] = useState<LanguageId>(() => (
    readStrLs(LS_RESPONSE_LANGUAGE, readStrLs(LS_LANGUAGE, 'zh')) === 'en' ? 'en' : 'zh'
  ))
  const [voiceAutoplay, setVoiceAutoplay] = useState(() => readBoolLs(LS_VOICE_AUTOPLAY, false))
  const [chatTimeout, setChatTimeout] = useState(() => {
    const raw = parseInt(readStrLs(LS_CHAT_TIMEOUT, String(DEFAULT_CHAT_TIMEOUT)), 10)
    return clampChatTimeout(Number.isNaN(raw) ? DEFAULT_CHAT_TIMEOUT : raw)
  })
  const [settingsOpen, setSettingsOpen] = useState(false)
  useEffect(() => {
    const html = document.documentElement
    html.setAttribute('data-theme', theme)
    try { localStorage.setItem(LS_THEME, theme) } catch { /* ignore storage errors */ }
  }, [theme])
  useEffect(() => {
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
    try { localStorage.setItem(LS_LANGUAGE, language) } catch { /* ignore storage errors */ }
  }, [language])
  useEffect(() => {
    try { localStorage.setItem(LS_RESPONSE_LANGUAGE, responseLanguage) } catch { /* ignore */ }
  }, [responseLanguage])
  useEffect(() => {
    try { localStorage.setItem(LS_VOICE_AUTOPLAY, voiceAutoplay ? '1' : '0') } catch { /* ignore */ }
    if (!voiceAutoplay) stopSpeech()
  }, [voiceAutoplay])
  useEffect(() => {
    try { localStorage.setItem(LS_CHAT_TIMEOUT, String(chatTimeout)) } catch { /* ignore */ }
  }, [chatTimeout])
  useEffect(() => {
    let cancelled = false
    void loadRuntimeUiSettings().then((ui) => {
      if (cancelled) return
      if (ui.response_language === 'zh' || ui.response_language === 'en') {
        setResponseLanguage(ui.response_language)
      }
      if (typeof ui.voice_autoplay === 'boolean') setVoiceAutoplay(ui.voice_autoplay)
      if (typeof ui.chat_response_timeout === 'number') {
        setChatTimeout(clampChatTimeout(ui.chat_response_timeout))
      }
    })
    return () => { cancelled = true }
  }, [])

  // --- Layout state ---
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => readBoolLs(LS_LEFT, true))
  const [statusOpen, setStatusOpen] = useState<boolean>(() => readBoolLs(LS_STATUS, true))

  // Apply right panel width from localStorage
  useEffect(() => {
    try {
      const w = parseInt(readStrLs(LS_RIGHTW, '395'), 10)
      if (!Number.isNaN(w) && w >= 392 && w <= 1200) {
        document.documentElement.style.setProperty('--right-panel-default-width', `${w}px`)
      }
    } catch { /* ignore storage errors */ }
  }, [])

  useEffect(() => {
    document.body.setAttribute('data-sidebar-collapsed', String(!sidebarOpen))
    try { localStorage.setItem(LS_LEFT, sidebarOpen ? '1' : '0') } catch { /* ignore storage errors */ }
  }, [sidebarOpen])
  useEffect(() => {
    try { localStorage.setItem(LS_STATUS, statusOpen ? '1' : '0') } catch { /* ignore storage errors */ }
  }, [statusOpen])

  // --- Mode & sessions ---
  const [mode, setMode] = useState<ModeTabId>('code')
  const [sessions, setSessions] = useState<ChassisSession[]>(() => readSessions())
  const [expandedTreeId, setExpandedTreeId] = useState<string | null>(null)
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false)
  const [capability, setCapability] = useState('chat')
  const [tools, setTools] = useState<ToolItem[]>([])
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [streaming, setStreaming] = useState(false)
  const [connectError, setConnectError] = useState('')

  const initialHash = typeof window !== 'undefined' ? parseHash() : { view: 'chat' as ViewId, sessionId: '' }
  const [view, setView] = useState<ViewId>(() => {
    if (typeof window !== 'undefined' && window.location.hash) return initialHash.view
    try {
      const saved = sessionStorage.getItem('trae:view') as ViewId | null
      if (saved && ['chat', 'new-task', 'automation', 'marketplace', 'my-files', 'design-system'].includes(saved)) return saved
    } catch { /* ignore */ }
    return 'chat'
  })
  useEffect(() => {
    try { sessionStorage.setItem('trae:view', view) } catch { /* ignore */ }
  }, [view])
  const [selectedTask, setSelectedTask] = useState<string>(() => {
    if (initialHash.sessionId) return initialHash.sessionId
    if (view === 'new-task') return ''
    const first = readSessions()[0]?.id || ''
    const saved = readSelectedId(first)
    return readSessions().some((s) => s.id === saved) ? saved : first
  })
  const [selectedPlugin, setSelectedPlugin] = useState<{ name: string; description: string; publisher: string; color: string; icon: string } | null>(null)
  const [selectedSkill, setSelectedSkill] = useState<{ name: string; description: string; publisher: string; icon: string; category?: string } | null>(null)

  const activeTaskId = view === 'chat'
    ? (sessions.some((s) => s.id === selectedTask) ? selectedTask : (sessions[0]?.id ?? ''))
    : selectedTask

  useEffect(() => { writeSessions(sessions) }, [sessions])
  useEffect(() => { writeSelectedId(activeTaskId) }, [activeTaskId])
  useEffect(() => {
    const next = hashFor(view, activeTaskId)
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [view, activeTaskId])

  const selectedSession = sessions.find((s) => s.id === activeTaskId)
  const messages = selectedSession?.messages ?? []
  const lastAssistantText = (() => {
    const last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant') return ''
    return studentVisibleBlocks(last.blocks).map((b) => b.content).join('')
  })()
  const taskItems: TaskItem[] = sessions.map((s) => ({
    id: s.id,
    label: s.label,
    time: s.time,
    pinned: s.pinned,
  }))

  // --- Composer ---
  const [composerText, setComposerText] = useState('')
  const composerTextRef = useRef(composerText)
  const setDraft = useCallback((next: string) => {
    composerTextRef.current = next
    setComposerText(next)
  }, [])
  const viewRef = useRef(view)
  const selectedTaskRef = useRef(selectedTask)
  const sessionsRef = useRef(sessions)
  useEffect(() => { composerTextRef.current = composerText }, [composerText])
  useEffect(() => { viewRef.current = view }, [view])
  useEffect(() => { selectedTaskRef.current = activeTaskId }, [activeTaskId])
  useEffect(() => { sessionsRef.current = sessions }, [sessions])
  const chatEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, selectedTask, lastAssistantText])

  const openNewConversation = useCallback(() => {
    setComposerText('')
    setAttachments([])
    setSelectedTask('')
    setView('new-task')
  }, [])

  const persistSessions = useCallback((next: ChassisSession[]) => {
    const sorted = sortSessions(next)
    sessionsRef.current = sorted
    setSessions(sorted)
  }, [])

  const handlePinTask = useCallback((id: string) => {
    const current = sessionsRef.current.find((s) => s.id === id)
    if (!current) return
    const pinned = !current.pinned
    const next = sessionsRef.current.map((s) => (s.id === id ? { ...s, pinned } : s))
    if (pinned) {
      const item = next.find((s) => s.id === id)!
      persistSessions([item, ...next.filter((s) => s.id !== id)])
      return
    }
    persistSessions(next)
  }, [persistSessions])

  const handleRenameTask = useCallback((id: string, label: string) => {
    persistSessions(sessionsRef.current.map((s) => (s.id === id ? { ...s, label } : s)))
    const target = sessionsRef.current.find((s) => s.id === id)
    const backendId = target?.backendId || (isPendingSessionId(id) ? null : id)
    if (backendId) {
      void renameSessionApi(backendId, label).catch(() => { /* keep local title */ })
    }
  }, [persistSessions])

  const handleDeleteTask = useCallback((id: string) => {
    const target = sessionsRef.current.find((s) => s.id === id)
    const remaining = sessionsRef.current.filter((s) => s.id !== id)
    persistSessions(remaining)
    const backendId = target?.backendId || (isPendingSessionId(id) ? null : id)
    if (backendId) {
      void deleteSessionApi(backendId).catch(() => { /* already removed locally */ })
    }
    if (selectedTaskRef.current === id) {
      const nextId = remaining[0]?.id ?? ''
      selectedTaskRef.current = nextId
      setSelectedTask(nextId)
      setView(nextId ? 'chat' : 'new-task')
    }
  }, [persistSessions])

  const wsRef = useRef<UnifiedWSClient | null>(null)
  const turnRef = useRef<{ sessionId: string; assistantId: string; turnId: string | null; events: StreamEvent[]; blocks: MessageBlock[] } | null>(null)
  const capabilityRef = useRef(capability)
  const selectedToolsRef = useRef(selectedTools)
  const attachmentsRef = useRef(attachments)
  const responseLanguageRef = useRef(responseLanguage)
  const voiceAutoplayRef = useRef(voiceAutoplay)
  const chatTimeoutRef = useRef(chatTimeout)
  const turnIdleTimerRef = useRef<number | null>(null)
  useEffect(() => { capabilityRef.current = capability }, [capability])
  useEffect(() => { selectedToolsRef.current = selectedTools }, [selectedTools])
  useEffect(() => { attachmentsRef.current = attachments }, [attachments])
  useEffect(() => { responseLanguageRef.current = responseLanguage }, [responseLanguage])
  useEffect(() => { voiceAutoplayRef.current = voiceAutoplay }, [voiceAutoplay])
  useEffect(() => { chatTimeoutRef.current = chatTimeout }, [chatTimeout])

  const clearTurnIdleTimer = useCallback(() => {
    if (turnIdleTimerRef.current != null) {
      window.clearTimeout(turnIdleTimerRef.current)
      turnIdleTimerRef.current = null
    }
  }, [])

  const remapSessionId = useCallback((fromId: string, toId: string) => {
    sessionsRef.current = sessionsRef.current.map((s) => (
      s.id === fromId ? { ...s, id: toId, backendId: toId } : s
    ))
    setSessions(sessionsRef.current)
    if (selectedTaskRef.current === fromId) {
      selectedTaskRef.current = toId
      setSelectedTask(toId)
    }
    if (turnRef.current?.sessionId === fromId) turnRef.current.sessionId = toId
  }, [])

  const patchAssistantBlocks = useCallback((sessionId: string, assistantId: string, blocks: MessageBlock[]) => {
    sessionsRef.current = sessionsRef.current.map((s) => {
      if (s.id !== sessionId) return s
      return {
        ...s,
        messages: s.messages.map((m) => (m.id === assistantId ? { ...m, blocks: [...blocks] } : m)),
      }
    })
    setSessions(sessionsRef.current)
  }, [])

  const failTurnIdle = useCallback(() => {
    const turn = turnRef.current
    if (!turn) return
    const turnId = turn.turnId
    if (turnId) wsRef.current?.send({ type: 'cancel_turn', turn_id: turnId })
    turn.blocks = [{
      type: 'status',
      title: '错误',
      content: '等待回复超时，请稍后重试或在设置中延长等待时间。',
    }]
    patchAssistantBlocks(turn.sessionId, turn.assistantId, turn.blocks)
    setStreaming(false)
  }, [patchAssistantBlocks])

  const armTurnIdleTimer = useCallback(() => {
    clearTurnIdleTimer()
    turnIdleTimerRef.current = window.setTimeout(failTurnIdle, chatTimeoutRef.current * 1000)
  }, [clearTurnIdleTimer, failTurnIdle])

  const handleStreamEvent = useCallback((event: StreamEvent) => {
    const turn = turnRef.current
    if (!turn) return
    const sid = sessionIdFromEvent(event)
    if (sid && sid !== turn.sessionId) remapSessionId(turn.sessionId, sid)
    if (event.turn_id) turn.turnId = event.turn_id
    armTurnIdleTimer()
    if (event.type === 'session' || event.type === 'session_meta') return
    if (event.type === 'done') {
      clearTurnIdleTimer()
      turn.blocks = eventsToBlocks(turn.events, '')
      patchAssistantBlocks(turn.sessionId, turn.assistantId, turn.blocks)
      setStreaming(false)
      if (voiceAutoplayRef.current) {
        const spoken = visibleAnswerFromEvents(turn.events)
        if (spoken.trim()) void speakReply(spoken)
      }
      return
    }
    turn.events.push(event)
    const next = eventsToBlocks(turn.events, '')
    turn.blocks = next
    patchAssistantBlocks(turn.sessionId, turn.assistantId, turn.blocks)
    if (event.type === 'error') {
      clearTurnIdleTimer()
      setStreaming(false)
    }
  }, [armTurnIdleTimer, clearTurnIdleTimer, patchAssistantBlocks, remapSessionId])

  useEffect(() => {
    const client = new UnifiedWSClient(
      handleStreamEvent,
      () => setConnectError(STREAM_CONNECT_ERROR),
      () => setConnectError(''),
    )
    wsRef.current = client
    client.connect()
    return () => {
      clearTurnIdleTimer()
      stopSpeech()
      client.disconnect()
      wsRef.current = null
    }
  }, [clearTurnIdleTimer, handleStreamEvent])

  useEffect(() => {
    let cancelled = false
    void loadServerSessions().then((server) => {
      if (cancelled) return
      setSessions((local) => mergeSessions(server, local.length ? local : readSessions()))
    }).catch(() => {
      if (!cancelled) setConnectError(STREAM_CONNECT_ERROR)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    void listToggleableTools().then((items) => {
      setTools(items)
      setSelectedTools(items.filter((item) => item.enabled && !item.comingSoon).map((item) => item.name))
    })
  }, [])

  const handleSettingToolToggle = useCallback((name: string) => {
    const target = tools.find((tool) => tool.name === name)
    if (!target || target.comingSoon || !target.toggleable) return
    const nextEnabled = !target.enabled
    const nextTools = tools.map((tool) => (
      tool.name === name ? { ...tool, enabled: nextEnabled } : tool
    ))
    setTools(nextTools)
    setSelectedTools((cur) => {
      if (nextEnabled) return cur.includes(name) ? cur : [...cur, name]
      return cur.filter((item) => item !== name)
    })
    const names = nextTools
      .filter((tool) => tool.toggleable && !tool.comingSoon && tool.enabled)
      .map((tool) => tool.name)
    void setEnabledOptionalTools(names).catch(() => { /* keep optimistic state */ })
  }, [tools])

  useEffect(() => {
    if (!activeTaskId || activeTaskId.startsWith('pending-')) return
    const current = sessionsRef.current.find((s) => s.id === activeTaskId)
    if (current && current.messages.length > 0 && current.backendId) return
    const ctrl = new AbortController()
    void loadSessionMessages(activeTaskId, ctrl.signal).then((msgs) => {
      if (!msgs.length) return
      sessionsRef.current = sessionsRef.current.map((s) => (
        s.id === activeTaskId ? { ...s, messages: msgs, backendId: s.backendId || activeTaskId } : s
      ))
      setSessions(sessionsRef.current)
    }).catch(() => { /* keep cache */ })
    return () => ctrl.abort()
  }, [activeTaskId])

  useEffect(() => {
    const onHash = () => {
      const next = parseHash()
      setView(next.view)
      if (next.view === 'chat' && next.sessionId) setSelectedTask(next.sessionId)
      if (next.view === 'new-task') setSelectedTask('')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const submitLockRef = useRef(false)
  const handleSend = useCallback(() => {
    if (submitLockRef.current || streaming) return
    const text = composerTextRef.current.replace(/\u200b/g, '').trim()
    const files = attachmentsRef.current
    if (!text && files.length === 0) return
    submitLockRef.current = true
    const time = formatClock()
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      author: 'You',
      time,
      blocks: [{ type: 'text', content: text }],
      attachments: files.map((f) => f.filename),
    }
    const assistantId = `a-${Date.now()}`
    const pendingAssistant: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      author: PRODUCT_NAME,
      time,
      blocks: [],
    }

    const isNew = viewRef.current === 'new-task' || !selectedTaskRef.current
    const titleBox = { id: selectedTaskRef.current }
    if (isNew) {
      const pendingId = `pending-${Date.now()}`
      titleBox.id = pendingId
      const created: ChassisSession = {
        id: pendingId,
        backendId: null,
        label: NEW_SESSION_TITLE,
        time,
        messages: [userMsg, pendingAssistant],
      }
      persistSessions([created, ...sessionsRef.current])
      selectedTaskRef.current = pendingId
      setSelectedTask(pendingId)
      setView('chat')
      window.setTimeout(() => {
        const nextLabel = deriveSessionTitle(text)
        const trackId = turnRef.current?.sessionId || titleBox.id
        sessionsRef.current = sessionsRef.current.map((s) => (
          s.id === trackId || s.id === titleBox.id ? { ...s, label: nextLabel } : s
        ))
        setSessions(sessionsRef.current)
      }, 400)
    } else {
      const currentId = selectedTaskRef.current
      titleBox.id = currentId
      sessionsRef.current = sessionsRef.current.map((s) => (
        s.id === currentId
          ? { ...s, time, messages: [...s.messages, userMsg, pendingAssistant] }
          : s
      ))
      setSessions(sessionsRef.current)
    }
    setComposerText('')
    setAttachments([])
    submitLockRef.current = false

    const existing = sessionsRef.current.find((s) => s.id === titleBox.id)
    const backendId = existing?.backendId || (titleBox.id.startsWith('pending-') ? null : titleBox.id)
    turnRef.current = {
      sessionId: titleBox.id,
      assistantId,
      turnId: null,
      events: [],
      blocks: [],
    }
    setStreaming(true)
    setConnectError('')
    stopSpeech()
    armTurnIdleTimer()

    const sent = wsRef.current?.send({
      type: 'start_turn',
      content: text,
      capability: capabilityRef.current,
      tools: selectedToolsRef.current,
      session_id: backendId,
      attachments: files.map((f) => ({
        type: f.type,
        filename: f.filename,
        mime_type: f.mime_type,
        base64: f.base64,
      })),
      language: responseLanguageRef.current,
    })
    if (!sent) {
      clearTurnIdleTimer()
      turnRef.current.blocks = [{ type: 'status', title: '错误', content: CREATE_SESSION_ERROR }]
      patchAssistantBlocks(titleBox.id, assistantId, turnRef.current.blocks)
      setStreaming(false)
    }
  }, [armTurnIdleTimer, clearTurnIdleTimer, patchAssistantBlocks, persistSessions, streaming])

  const handleCancel = useCallback(() => {
    const turnId = turnRef.current?.turnId
    if (turnId) wsRef.current?.send({ type: 'cancel_turn', turn_id: turnId })
    clearTurnIdleTimer()
    stopSpeech()
    setStreaming(false)
  }, [clearTurnIdleTimer])

  const handleAddFiles = useCallback((list: FileList) => {
    void Promise.all(Array.from(list).map(fileToAttachment)).then((next) => {
      setAttachments((cur) => {
        const names = new Set(cur.map((f) => f.filename))
        return [...cur, ...next.filter((f) => !names.has(f.filename))]
      })
    })
  }, [])

  // --- Debug mode ---
  const [debug, setDebug] = useState(false)
  useEffect(() => {
    const check = () => {
      const sp = new URLSearchParams(window.location.search)
      setDebug(sp.get('debug') === 'true')
    }
    check()
    window.addEventListener('popstate', check)
    return () => window.removeEventListener('popstate', check)
  }, [])

  // --- Debug: measure panels ---
  const sideRef = useRef<HTMLElement | null>(null)
  const mainRef = useRef<HTMLElement | null>(null)
  const rightRef = useRef<HTMLElement | null>(null)
  const [meas, setMeas] = useState({ l: 0, m: 0, r: 0 })
  useLayoutEffect(() => {
    if (!debug) return
    const measure = () => {
      setMeas({
        l: sideRef.current?.offsetWidth ?? 0,
        m: mainRef.current?.offsetWidth ?? 0,
        r: rightRef.current?.offsetWidth ?? 0,
      })
    }
    measure()
    const ro = new ResizeObserver(measure)
    if (sideRef.current) ro.observe(sideRef.current)
    if (mainRef.current) ro.observe(mainRef.current)
    if (rightRef.current) ro.observe(rightRef.current)
    window.addEventListener('resize', measure)
    const t = setInterval(measure, 500)
    return () => { ro.disconnect(); window.removeEventListener('resize', measure); clearInterval(t) }
  }, [debug, sidebarOpen, statusOpen])

  const layoutClasses = ['layout-kZA4Q1']
  if (!sidebarOpen) layoutClasses.push('layoutCollapsed-_ACuDn')

  const containerClasses = ['container-UhGXJa']
  containerClasses.push(sidebarOpen ? 'containerHorizontal-zbia0V' : 'containerPassthrough-IjBXaD')

  const mainClasses = ['main-KqevMo']
  if (statusOpen) mainClasses.push('mainPinned-mHr1bw')

  const composerTools = tools.filter((tool) => tool.enabled && !tool.comingSoon)

  return (
    <div className={`app-root ${debug ? 'debug-root' : ''}`}>
      <div className={layoutClasses.join(' ')}>
        {/* ---- Sidebar container (wraps sidebar + divider, mirrors real TraeWork) ---- */}
        <div className={containerClasses.join(' ')}>
          <div
            className="content-FHMU5b"
            style={sidebarOpen ? { width: '300px' } : undefined}
          >
            <Sidebar
              mode={mode}
              onModeChange={(next) => {
                setMode(next)
                if (next === 'work' || next === 'design') {
                  setSelectedTask('')
                  setView('new-task')
                }
              }}
              collapsed={!sidebarOpen}
              onToggleCollapse={() => setSidebarOpen((s) => !s)}
              items={taskItems}
              selectedTask={activeTaskId}
              onSelectTask={(id) => { setSelectedTask(id); setView('chat'); setSelectedPlugin(null); }}
              expandedTreeId={expandedTreeId}
              onToggleTree={(id) => setExpandedTreeId((cur) => (cur === id ? null : id))}
              onPinTask={handlePinTask}
              onRenameTask={handleRenameTask}
              onDeleteTask={handleDeleteTask}
              activeNavItem={view === 'new-task' ? 'create-task' : view === 'marketplace' ? 'plugin' : view === 'automation' ? 'automation' : view === 'my-files' ? 'my-files' : view === 'design-system' ? 'design-system' : undefined}
              onNavigate={(id) => {
                if (id === 'create-task') openNewConversation()
                else if (id === 'plugin') setView('marketplace')
                else if (id === 'automation') setView('automation')
                else if (id === 'my-files') setView('my-files')
                else if (id === 'design-system') setView('design-system')
              }}
              theme={theme}
              language={language}
              onToggleTheme={() => {
                setTheme((t) => {
                  const next = t === 'dark' ? 'light' : 'dark'
                  persistInterfaceSettings({ theme: next })
                  return next
                })
              }}
              onOpenSettings={() => setSettingsOpen(true)}
              hideSessions={mode !== 'code'}
              searchDocs={sessions.map((s) => ({
                id: s.id,
                title: s.label,
                snippet: (s.messages || []).map((m) => m.blocks?.map((b) => b.content).join(' ') || '').join(' '),
              }))}
            />
          </div>

          {/* ---- Split handle between sidebar & main ---- */}
          {sidebarOpen && (
            <div className="splitHandle-IEUrKW splitHandleHorizontal-JdteEX sidebar-divider" aria-hidden />
          )}
        </div>

        {/* ---- Main (direct child of layout) ---- */}
        <main
          id="main-container"
          ref={(el) => (mainRef.current = el)}
          className={mainClasses.join(' ')}
        >
          {view === 'chat' && (
            <>
              <div className="contentWrapper-U1GjQr" style={{ minWidth: '392px' }}>
                <div className="selectionTopBarSlot-ZSaIcZ" />
                <header className="header-fId8VF">
                  {!sidebarOpen && (
                    <div className="headerLeft-fpC5cY">
                      <div style={{ display: 'inline-flex' }}>
                        <IconBtn icon="view-left" label="展开侧边栏" title="展开侧边栏" onClick={() => setSidebarOpen(true)} />
                      </div>
                      <IconBtn icon="search" label="搜索" title="搜索" />
                      <IconBtn icon="plus" label="新建对话" title="新建对话" onClick={openNewConversation} />
                    </div>
                  )}
                  <div className="headerCenter-HRprYa">
                    <div className="taskHeader-wmHGD9">
                      <span className="wrapper-RV5xqM">
                        <div className="infoArea-Y4r_8m">
                          <div className="iconWrap-_fRuU8">
                            <Icon name="cloud" size={14} />
                          </div>
                          <span className="taskName-iaeIsX">{selectedSession?.label || ''}</span>
                          <div className="timeWrap-ksZO3X">
                            <span className="timeText-bjF8AM">{selectedSession?.time || ''}</span>
                          </div>
                        </div>
                      </span>
                      <div
                        className="moreBtn-h2uOKe"
                        role="button"
                        tabIndex={0}
                        aria-label="更多"
                        onClick={() => setHeaderMenuOpen((v) => !v)}
                      >
                        <Icon name="more-action" size={16} />
                        {headerMenuOpen && selectedSession && (
                          <div className="taskMenu headerTaskMenu" role="menu">
                            <button type="button" className="taskMenuItem" onClick={() => { handlePinTask(selectedSession.id); setHeaderMenuOpen(false) }}>
                              <Icon name="pin-line" size={16} className="taskMenuIcon" />
                              <span>{selectedSession.pinned ? '取消置顶' : '置顶任务'}</span>
                            </button>
                            <button type="button" className="taskMenuItem" onClick={() => setHeaderMenuOpen(false)}>
                              <Icon name="edit" size={16} className="taskMenuIcon" />
                              <span>重命名</span>
                            </button>
                            <button type="button" className="taskMenuItem taskMenuItemDelete" onClick={() => { handleDeleteTask(selectedSession.id); setHeaderMenuOpen(false) }}>
                              <Icon name="delete" size={16} className="taskMenuIconDelete" />
                              <span>删除</span>
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="headerRight-A9O9pk">
                    <IconBtn
                      icon={statusOpen ? 'pin-line' : 'right-off'}
                      label={statusOpen ? '隐藏工具面板' : '展开面板'}
                      tooltip={statusOpen ? '隐藏工具面板 ⌘⌃B' : '展开面板 ⌘⌃B'}
                      onClick={() => setStatusOpen((s) => !s)}
                      style={statusOpen ? { background: 'var(--bg-bg-overlay-l1)', color: 'var(--icon-icon-default)' } : undefined}
                    />
                  </div>
                </header>

                <div className="workspace-nQt_sr">
                  <div className={`${statusOpen ? 'mainContentPinned-AlsI8K' : 'mainContent-I6jtPZ'}`}>
                    <div id="agent-chat-view" className="chatArea-zQPQwl">
                      <div className="chatInner-c6091C">
                        <div className="chatContent-h48jjm">
                          <div className="ai-chat chat-session">
                            <div className="virtualized-message-list-view">
                              <div className="virtualized-message-list-view__content">
                                <div className="virtualized-message-list-view__scroller virtualized-message-list-view__scroller--hide-scrollbar">
                                  <div className="virtualized-message-list-view__virtuoso" style={{ position: 'relative' }}>
                                    <ConversationView messages={messages} streaming={streaming} />
                                    <div ref={chatEndRef} />
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                        {connectError && (
                          <div style={{ padding: '8px 16px', color: 'var(--status-error-default, #f65a5a)', fontSize: 13 }}>
                            {connectError}
                          </div>
                        )}
                        <Composer
                          value={composerText}
                          onChange={setDraft}
                          onSend={handleSend}
                          mode={mode}
                          variant="conversation"
                          autoFocus
                          capability={capability}
                          onCapabilityChange={setCapability}
                          tools={composerTools}
                          selectedTools={selectedTools}
                          onToggleTool={(name) => setSelectedTools((cur) => (
                            cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name]
                          ))}
                          attachments={attachments}
                          onAddFiles={handleAddFiles}
                          onRemoveAttachment={(name) => setAttachments((cur) => cur.filter((f) => f.filename !== name))}
                          streaming={streaming}
                          onCancel={handleCancel}
                        />
                      </div>
                    </div>
                  </div>
                </div>
                <div className="selectionBottomBarSlot-YGV02n" />
              </div>

              {/* ---- Right panel ---- */}
              {statusOpen && (
                <div className="container-UhGXJa containerHorizontal-zbia0V splitContainer-GcSkag">
                  <SplitHandle />
                  <div className="content-FHMU5b splitContent-ukT2__" style={{ width: 'var(--right-panel-default-width)' }}>
                    <div ref={(el) => (rightRef.current = el)} style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%' }}>
                      <RightPanel
                        onClose={() => setStatusOpen(false)}
                        session={selectedSession}
                        attachments={selectedSession?.messages.flatMap((m) => m.attachments ?? []) ?? []}
                      />
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {view === 'new-task' && (
            <div className="contentWrapper-U1GjQr">
              {(() => {
                const homeComposer = (
                  <Composer
                    value={composerText}
                    onChange={setDraft}
                    onSend={handleSend}
                    mode={mode}
                    variant="home"
                    autoFocus
                    capability={capability}
                    onCapabilityChange={setCapability}
                    tools={composerTools}
                    selectedTools={selectedTools}
                    onToggleTool={(name) => setSelectedTools((cur) => (
                      cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name]
                    ))}
                    attachments={attachments}
                    onAddFiles={handleAddFiles}
                    onRemoveAttachment={(name) => setAttachments((cur) => cur.filter((f) => f.filename !== name))}
                    streaming={streaming}
                    onCancel={handleCancel}
                  />
                )
                if (mode === 'work') return <WorkHomePage composer={homeComposer} />
                if (mode === 'design') return <DesignHomePage composer={homeComposer} />
                return <NewTaskPage composer={homeComposer} />
              })()}
            </div>
          )}

          {view === 'my-files' && <ModeShellPage title="我的文件" />}
          {view === 'design-system' && <ModeShellPage title="设计系统" />}

          {view === 'automation' && (
            <div className="contentWrapper-U1GjQr">
              <AutomationPage onContinueLearning={() => setView('chat')} />
            </div>
          )}

          {view === 'marketplace' && (
            <div className="contentWrapper-U1GjQr" style={{ position: 'relative' }}>
              <MarketplacePage onSelectPlugin={(p) => setSelectedPlugin(p)} onSelectSkill={(s) => setSelectedSkill(s)} />
              {selectedPlugin && (
                <PluginDetailModal
                  plugin={selectedPlugin}
                  onClose={() => setSelectedPlugin(null)}
                />
              )}
              {selectedSkill && (
                <SkillDetailModal
                  skill={selectedSkill}
                  onClose={() => setSelectedSkill(null)}
                />
              )}
            </div>
          )}
        </main>
      </div>

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        theme={theme}
        onThemeChange={setTheme}
        language={language}
        onLanguageChange={setLanguage}
        responseLanguage={responseLanguage}
        onResponseLanguageChange={setResponseLanguage}
        voiceAutoplay={voiceAutoplay}
        onVoiceAutoplayChange={setVoiceAutoplay}
        chatTimeout={chatTimeout}
        onChatTimeoutChange={setChatTimeout}
        tools={tools}
        onToggleTool={handleSettingToolToggle}
        accountName="Xike"
        accountPlan="Free"
      />

      {debug && (
        <DebugOverlay
          sidebarOpen={sidebarOpen}
          statusOpen={statusOpen}
          theme={theme}
          mode={mode}
          leftWidth={meas.l}
          rightWidth={meas.r}
          mainWidth={meas.m}
        />
      )}
    </div>
  )
}
