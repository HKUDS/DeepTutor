import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom'
import { PRODUCT_NAME } from './brand'

type IconSvgProps = { name: string; size?: number }
const PageIcon: React.FC<IconSvgProps> = ({ name, size = 16 }) => {
  const s = { width: size, height: size }
  switch (name) {
    case 'code':
      return <svg {...s} viewBox="0 0 36 36" fill="none"><path d="M19.649 5.39976C19.8701 4.51583 20.766 3.97857 21.65 4.19957C22.5339 4.42066 23.0712 5.31654 22.8502 6.20054L16.3502 32.2005C16.1291 33.0845 15.2332 33.6217 14.3492 33.4007C13.4653 33.1796 12.928 32.2837 13.149 31.3998L19.649 5.39976ZM7.15389 11.0668C7.83499 10.4617 8.87769 10.5235 9.48299 11.2044C10.0881 11.8855 10.0271 12.9282 9.34627 13.5336L6.13241 16.39C4.68932 17.6729 4.68937 19.9274 6.13241 21.2103L9.34627 24.0668C10.0271 24.6721 10.088 25.7148 9.48299 26.3959C8.87768 27.0769 7.835 27.1387 7.15389 26.5336L3.94002 23.6771C1.02 21.0815 1.01999 16.5188 3.94002 13.9232L7.15389 11.0668ZM26.5162 11.2044C27.1216 10.5234 28.1652 10.4613 28.8463 11.0668L32.0592 13.9232C34.8878 16.4376 34.9765 20.7982 32.3248 23.4281L32.0592 23.6771L28.8463 26.5336C28.1652 27.139 27.1216 27.077 26.5162 26.3959C25.9111 25.7147 25.9729 24.672 26.6539 24.0668L29.8668 21.2103C31.3098 19.9274 31.3099 17.6729 29.8668 16.39L26.6539 13.5336C25.9729 12.9282 25.9111 11.8855 26.5162 11.2044Z" fill="currentColor"/></svg>
    case 'showcase_app':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><path d="M11.7327 1.85156C12.8718 1.85156 13.7952 2.77498 13.7952 3.91406V14.4141C13.7952 15.5532 12.8718 16.4766 11.7327 16.4766H5.73267C4.59362 16.4765 3.67017 15.5531 3.67017 14.4141V3.91406C3.67017 2.77501 4.59362 1.85161 5.73267 1.85156H11.7327ZM5.73267 2.97656C5.21494 2.97661 4.79517 3.39633 4.79517 3.91406V14.4141C4.79517 14.9318 5.21494 15.3515 5.73267 15.3516H11.7327C12.2504 15.3516 12.6702 14.9318 12.6702 14.4141V3.91406C12.6702 3.3963 12.2504 2.97656 11.7327 2.97656H10.2288C10.2093 3.29028 9.95164 3.53891 9.63306 3.53906H7.83228C7.51377 3.53881 7.256 3.29023 7.23657 2.97656H5.73267ZM9.67017 12.9141C9.98083 12.9141 10.2327 13.1659 10.2327 13.4766C10.2327 13.7872 9.98083 14.0391 9.67017 14.0391H7.79517C7.48455 14.039 7.23267 13.7872 7.23267 13.4766C7.23267 13.1659 7.48455 12.9141 7.79517 12.9141H9.67017Z"/></svg>
    case 'showcase_project':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><g clipPath="url(#clip0_project)"><path d="M9.12891 1.6875C9.67582 1.68755 10.2002 1.90526 10.5869 2.29199L14.208 5.91309C14.5948 6.29984 14.8124 6.82417 14.8125 7.37109V13.5C14.8125 15.0533 13.5533 16.3125 12 16.3125H6C4.44671 16.3125 3.1875 15.0533 3.1875 13.5V4.5C3.1875 2.9467 4.4467 1.6875 6 1.6875H9.12891ZM6 2.8125C5.06802 2.8125 4.3125 3.56802 4.3125 4.5V13.5C4.3125 14.432 5.06802 15.1875 6 15.1875H12C12.932 15.1875 13.6875 14.432 13.6875 13.5V7.37109C13.6875 7.35147 13.6858 7.33197 13.6846 7.3125H11.25C10.1109 7.3125 9.1875 6.38908 9.1875 5.25V2.81543C9.16803 2.8142 9.14853 2.8125 9.12891 2.8125H6ZM11.625 12.1875C11.9357 12.1875 12.1875 12.4393 12.1875 12.75C12.1875 13.0607 11.9357 13.3125 11.625 13.3125H6.75C6.43934 13.3125 6.1875 13.0607 6.1875 12.75C6.1875 12.4393 6.43934 12.1875 6.75 12.1875H11.625ZM9 9.1875C9.31066 9.1875 9.5625 9.43934 9.5625 9.75C9.5625 10.0607 9.31066 10.3125 9 10.3125H6.75C6.43934 10.3125 6.1875 10.0607 6.1875 9.75C6.1875 9.43934 6.43934 9.1875 6.75 9.1875H9ZM10.3125 5.25C10.3125 5.76777 10.7322 6.1875 11.25 6.1875H12.8926L10.3125 3.60742V5.25Z"/></g><defs><clipPath id="clip0_project"><path d="M0 0H18V18H0z"/></clipPath></defs></svg>
    case 'showcase_game':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><path d="M14.5625 5.0625C14.5625 4.16503 13.835 3.4375 12.9375 3.4375H5.0625C4.16504 3.4375 3.4375 4.16504 3.4375 5.0625V12.9375C3.4375 13.835 4.16503 14.5625 5.0625 14.5625H12.9375C13.835 14.5625 14.5625 13.835 14.5625 12.9375V5.0625ZM15.8125 12.9375C15.8125 14.5254 14.5254 15.8125 12.9375 15.8125H5.0625C3.47469 15.8125 2.1875 14.5254 2.1875 12.9375V5.0625C2.1875 3.47468 3.47468 2.1875 5.0625 2.1875H12.9375C14.5254 2.1875 15.8125 3.47469 15.8125 5.0625V12.9375Z"/><path d="M10.7614 11.8182C10.7614 11.2345 11.2345 10.7614 11.8182 10.7614C12.4018 10.7614 12.875 11.2345 12.875 11.8182C12.875 12.4018 12.4018 12.875 11.8182 12.875C11.2345 12.875 10.7614 12.4018 10.7614 11.8182ZM7.94318 9C7.94318 8.41635 8.41635 7.94318 9 7.94318C9.58365 7.94318 10.0568 8.41635 10.0568 9C10.0568 9.58365 9.58365 10.0568 9 10.0568C8.41635 10.0568 7.94318 9.58365 7.94318 9ZM5.125 6.18182C5.125 5.59815 5.59815 5.125 6.18182 5.125C6.76548 5.125 7.23864 5.59815 7.23864 6.18182C7.23864 6.76548 6.76548 7.23864 6.18182 7.23864C5.59815 7.23864 5.125 6.76548 5.125 6.18182Z"/></svg>
    case 'showcase_tools':
      return <svg {...s} viewBox="0 0 18 18" fill="currentColor"><path d="M14.5649 5.13184C14.5649 4.19502 13.8055 3.43555 12.8687 3.43555H5.13135C4.19454 3.43555 3.43506 4.19503 3.43506 5.13184V12.8691C3.43506 13.806 4.19453 14.5654 5.13135 14.5654H12.8687C13.8055 14.5654 14.5649 13.806 14.5649 12.8691V5.13184ZM15.8149 12.8691C15.8149 14.4963 14.4959 15.8154 12.8687 15.8154H5.13135C3.50419 15.8154 2.18506 14.4964 2.18506 12.8691V5.13184C2.18506 3.50467 3.50418 2.18555 5.13135 2.18555H12.8687C14.4959 2.18555 15.8149 3.50468 15.8149 5.13184V12.8691Z"/><path d="M5.18257 5.55806C5.42665 5.31398 5.82326 5.31398 6.06734 5.55806L7.37984 6.87056C7.62391 7.11464 7.62391 7.51125 7.37984 7.75532L6.06734 9.06782C5.82326 9.3119 5.42665 9.3119 5.18257 9.06782C4.93849 8.82375 4.93849 8.42714 5.18257 8.18306L6.05269 7.31294L5.18257 6.44282C4.93849 6.19875 4.93849 5.80214 5.18257 5.55806Z"/></svg>
    case 'automation':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M13.373 8C13.373 5.03239 10.9676 2.62695 8 2.62695C5.03239 2.62695 2.62695 5.03239 2.62695 8C2.62695 10.9676 5.03239 13.373 8 13.373C10.9676 13.373 13.373 10.9676 13.373 8ZM7.37305 5.33333C7.37305 4.98723 7.6539 4.70638 8 4.70638C8.3461 4.70638 8.62695 4.98723 8.62695 5.33333V7.74023L10.11 9.22331C10.3548 9.46804 10.3548 9.8653 10.11 10.11C9.8653 10.3548 9.46804 10.3548 9.22331 10.11L7.55664 8.44336C7.43912 8.32584 7.37305 8.1662 7.37305 8V5.33333ZM14.627 8C14.627 11.6598 11.6598 14.627 8 14.627C4.3402 14.627 1.37305 11.6598 1.37305 8C1.37305 4.34019 4.34019 1.37305 8 1.37305C11.6598 1.37305 14.627 4.3402 14.627 8ZM2.99887 1.05728C3.24354.812617 3.64031.812292 3.88506 1.05682C4.12979 1.30155 4.12979 1.69874 3.88506 1.94346L1.94328 3.88525C1.69855 4.12997 1.30136 4.12997 1.05663 3.88525.812106 3.6405.812431 3.24372 1.05709 2.99906L2.99887 1.05728ZM13.163 1.05728C12.9183.812617 12.5216.812292 12.2768 1.05682C12.0321 1.30155 12.0321 1.69874 12.2768 1.94346L14.2186 3.88525C14.4633 4.12997 14.8605 4.12997 15.1052 3.88525 15.3498 3.6405 15.3494 3.24372 15.1048 2.99906L13.163 1.05728z"/></svg>
    case 'close':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 4l8 8M12 4l-8 8"/></svg>
    case 'search':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2"><circle cx="7" cy="7" r="5"/><path d="M11 11l3.5 3.5"/></svg>
    case 'github':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M7.99992 1.30029C11.6833 1.30029 14.6666 4.28363 14.6666 7.96696C14.6662 9.36379 14.2278 10.7253 13.4131 11.86C12.5984 12.9946 11.4484 13.8452 10.1249 14.292C9.79158 14.3586 9.66658 14.1503 9.66658 13.9753C9.66658 13.7503 9.67492 13.0336 9.67492 12.142C9.67492 11.517 9.46659 11.117 9.22492 10.9086C10.7083 10.742 12.2666 10.1753 12.2666 7.61696C12.2666 6.88363 12.0083 6.29196 11.5833 5.82529C11.6499 5.65863 11.8833 4.97529 11.5166 4.05863C11.5166 4.05863 10.9583 3.87529 9.68325 4.74196C9.14992 4.59196 8.58325 4.51696 8.01659 4.51696C7.44992 4.51696 6.88325 4.59196 6.34992 4.74196C5.07492 3.88363 4.51659 4.05863 4.51659 4.05863C4.14992 4.97529 4.38325 5.65863 4.44992 5.82529C4.02492 6.29196 3.76659 6.89196 3.76659 7.61696C3.76659 10.167 5.31659 10.742 6.79992 10.9086C6.60825 11.0753 6.43325 11.367 6.37492 11.8003C5.99159 11.9753 5.03325 12.2586 4.43325 11.2503C4.30825 11.0503 3.93325 10.5586 3.40825 10.567C2.84992 10.5753 3.18325 10.8836 3.41659 11.0086C3.69992 11.167 4.02492 11.7586 4.09992 11.9503C4.23325 12.3253 4.66659 13.042 6.34159 12.7336C6.34159 13.292 6.34992 13.817 6.34992 13.9753C6.34992 14.1503 6.22492 14.3503 5.89159 14.292C4.56378 13.85 3.40886 13.0011 2.59066 11.8658C1.77246 10.7305 1.33252 9.36638 1.33325 7.96696C1.33325 4.28363 4.31659 1.30029 7.99992 1.30029Z"/></svg>
    case 'disk':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M2.95801 11.5C2.95807 11.6876 3.03246 11.8682 3.16504 12.001C3.29774 12.1337 3.47836 12.2088 3.66602 12.209H12.333C12.5208 12.209 12.7012 12.1337 12.834 12.001C12.9667 11.8682 13.041 11.6877 13.041 11.5V7.13379H2.95801V11.5ZM8.67383 8.82031C9.08785 8.82054 9.42383 9.15624 9.42383 9.57031C9.4237 9.98428 9.08777 10.3201 8.67383 10.3203H8.66699C8.25286 10.3203 7.91712 9.98441 7.91699 9.57031C7.91699 9.1561 8.25278 8.82031 8.66699 8.82031H8.67383ZM11.0068 8.82031C11.421 8.8204 11.7568 9.15616 11.7568 9.57031C11.7567 9.98436 11.4209 10.3202 11.0068 10.3203H11C10.5859 10.3203 10.2501 9.98441 10.25 9.57031C10.25 9.1561 10.5858 8.82031 11 8.82031H11.0068ZM4.72852 3.79883C4.63154 3.81249 4.53795 3.84648 4.4541 3.89844C4.34224 3.96788 4.25097 4.06763 4.19238 4.18555L4.19141 4.1875L3.34082 5.88379H12.6582L11.8076 4.1875L11.8066 4.18555C11.748 4.06762 11.6578 3.96788 11.5459 3.89844C11.4618 3.84632 11.3678 3.81244 11.2705 3.79883L11.1729 3.79199H4.82715L4.72852 3.79883Z"/></svg>
    case 'down':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M10.2249 6.22429C10.469 5.98059 10.8647 5.98048 11.1087 6.22429C11.3528 6.46837 11.3528 6.86498 11.1087 7.10905L9.14876 9.06804C8.51414 9.70255 7.48548 9.70261 6.8509 9.06804L4.89094 7.10905C4.64687 6.86498 4.64687 6.46837 4.89094 6.22429C5.13502 5.98021 5.53163 5.98021 5.77571 6.22429L7.73469 8.18425C7.88112 8.33067 8.1185 8.3306 8.26497 8.18425L10.2249 6.22429Z"/></svg>
    case 'plugin':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M4 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path d="M8 4v8M4 8h8"/></svg>
    case 'chevron-left':
      return <svg {...s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 4l-4 4 4 4"/></svg>
    case 'download':
      return <svg {...s} viewBox="0 0 16 16" fill="currentColor"><path d="M8 2.5C8.27614 2.5 8.5 2.72386 8.5 3V9.37868L10.4394 7.43934C10.6344 7.24435 10.9402 7.24435 11.1352 7.43934C11.3302 7.63432 11.3302 7.9401 11.1352 8.13508L8.56091 10.7094C8.36593 10.9044 8.06015 10.9044 7.86517 10.7094L5.29091 8.13508C5.09593 7.9401 5.09593 7.63432 5.29091 7.43934C5.48589 7.24435 5.79167 7.24435 5.98665 7.43934L7.92606 9.37868V3C7.92606 2.72386 8.14992 2.5 8.42606 2.5H8ZM3.5 12.5C3.5 12.2239 3.72386 12 4 12H12C12.2761 12 12.5 12.2239 12.5 12.5V13.5C12.5 13.7761 12.2761 14 12 14H4C3.72386 14 3.5 13.7761 3.5 13.5V12.5Z"/></svg>
    default:
      return null
  }
}

/* ============ NewTaskPage ============ */
export function NewTaskPage({ composer }: { composer: React.ReactNode }) {
  return (
    <>
      <header className="header-x7rPuS">
        <div className="headerCenter-cba9zB"></div>
        <div className="headerRight-QHfr9M"></div>
      </header>
      <div className="workspace-sBvxKr" style={{ ['--input-center-offset' as any]: '331px' }}>
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <div className="animationContainer-umIyNq" style={{ opacity: 1 }}>
              <div className="mainTextContainer-pXscK4">
                <span className="icon-rzUsCL" style={{ opacity: 1 }}>
                  <PageIcon name="code" size={36} />
                </span>
                <span className="titleText-H3MNV2 codeText-Lcyw9U" style={{ opacity: 1, transform: 'translateX(5px)' }}>Learn</span>
                <span className="withTraeText-dLQCwg" style={{ width: 'auto', opacity: 1 }}>
                  <span className="withTraeInner-hAXYMl">with {PRODUCT_NAME}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="homeMessageInput-bhe4cx">
          {composer}
        </div>
        <div className="showcaseWrapper-kvK9FF" style={{ opacity: 1, transform: 'none' }}>
          <div className="showcaseSection-pTXHyZ">
            <div className="chipContainer-Wo8qmB">
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_app" size={16} /></span><span className="chipText-YMz4j8">应用开发</span></div>
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_project" size={16} /></span><span className="chipText-YMz4j8">项目理解</span></div>
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_game" size={16} /></span><span className="chipText-YMz4j8">游戏创意</span></div>
              <div className="chip-Fx63TH"><span className="chipIcon-AN8sSU"><PageIcon name="showcase_tools" size={16} /></span><span className="chipText-YMz4j8">工具脚本</span></div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

const WORK_PPT_SUB = ['经验分享', '活动复盘', '商业计划'] as const

export function WorkHomePage({ composer }: { composer: React.ReactNode }) {
  const [pptOpen, setPptOpen] = useState(false)
  return (
    <>
      <header className="header-x7rPuS">
        <div className="headerCenter-cba9zB" />
        <div className="headerRight-QHfr9M">
          <span className="downloadChip-trae">下载桌面端</span>
        </div>
      </header>
      <div className="workspace-sBvxKr" style={{ ['--input-center-offset' as any]: '331px' }}>
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <div className="animationContainer-umIyNq" style={{ opacity: 1 }}>
              <div className="mainTextContainer-pXscK4">
                <span className="icon-rzUsCL" style={{ opacity: 1 }}>
                  <PageIcon name="plugin" size={36} />
                </span>
                <span className="titleText-H3MNV2 codeText-Lcyw9U" style={{ opacity: 1, transform: 'translateX(5px)' }}>Work</span>
                <span className="withTraeText-dLQCwg" style={{ width: 'auto', opacity: 1 }}>
                  <span className="withTraeInner-hAXYMl">with TRAE</span>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="homeMessageInput-bhe4cx">{composer}</div>
        <div className="showcaseWrapper-kvK9FF" style={{ opacity: 1, transform: 'none' }}>
          <div className="showcaseSection-pTXHyZ">
            <div className="chipContainer-Wo8qmB">
              <div
                className="chip-Fx63TH"
                onMouseEnter={() => setPptOpen(true)}
              >
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_app" size={16} /></span>
                <span className="chipText-YMz4j8">生成 PPT</span>
              </div>
              <div className="chip-Fx63TH">
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_project" size={16} /></span>
                <span className="chipText-YMz4j8">数据分析</span>
              </div>
              <div className="chip-Fx63TH">
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_tools" size={16} /></span>
                <span className="chipText-YMz4j8">深度研究</span>
              </div>
              <div className="chip-Fx63TH">
                <span className="chipIcon-AN8sSU"><PageIcon name="showcase_game" size={16} /></span>
                <span className="chipText-YMz4j8">生成文档</span>
              </div>
            </div>
            {pptOpen && (
              <div className="workChipSubRow">
                <span className="workChipSubTitle">生成 PPT</span>
                <button type="button" className="workChipSubClose" aria-label="关闭" onClick={() => setPptOpen(false)}>×</button>
                <div className="workChipSubItems">
                  {WORK_PPT_SUB.map((label) => (
                    <span key={label} className="workChipSubItem">{label}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

const DESIGN_CARDS = [
  { title: '设计还原', desc: '设计还原：上传 UI 参考截图，还原同款电商详情页' },
  { title: '概念成稿', desc: '概念成稿：一句话描述想法，直出完整小程序原型' },
  { title: '规范出图', desc: '规范出图：对齐设计规范，产出高保真 SaaS 系统' },
] as const

export function DesignHomePage({ composer }: { composer: React.ReactNode }) {
  return (
    <>
      <header className="header-x7rPuS">
        <div className="headerCenter-cba9zB" />
        <div className="headerRight-QHfr9M">
          <span className="downloadChip-trae">下载桌面端</span>
        </div>
      </header>
      <div className="workspace-sBvxKr" style={{ ['--input-center-offset' as any]: '331px' }}>
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <div className="animationContainer-umIyNq" style={{ opacity: 1 }}>
              <div className="mainTextContainer-pXscK4">
                <span className="icon-rzUsCL" style={{ opacity: 1 }}>
                  <PageIcon name="plugin" size={36} />
                </span>
                <span className="titleText-H3MNV2 codeText-Lcyw9U" style={{ opacity: 1, transform: 'translateX(5px)' }}>Design</span>
                <span className="withTraeText-dLQCwg" style={{ width: 'auto', opacity: 1 }}>
                  <span className="withTraeInner-hAXYMl">with TRAE</span>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="homeMessageInput-bhe4cx">{composer}</div>
        <div className="showcaseWrapper-kvK9FF" style={{ opacity: 1 }}>
          <div className="designCardRow">
            {DESIGN_CARDS.map((card) => (
              <div key={card.title} className="designCard">
                <div className="designCardPreview" aria-hidden />
                <div className="designCardTitle">{card.title}</div>
                <div className="designCardDesc">{card.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

export function ModeShellPage({ title }: { title: string }) {
  return (
    <div className="contentWrapper-U1GjQr">
      <header className="header-x7rPuS">
        <div className="headerCenter-cba9zB" />
        <div className="headerRight-QHfr9M" />
      </header>
      <div className="workspace-sBvxKr">
        <div className="welcomeTitleWrapper-WfrDR6">
          <div className="traeWorkTitle-NJggA3">
            <span className="titleText-H3MNV2">{title}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ============ Automation Page ============ */

const AutomationIcon: React.FC<{ iconKey: string }> = ({ iconKey }) => {
  const icons: Record<string, React.ReactNode> = {
    news: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="4.80078" y="24.1484" width="15.2" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="30.1484" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="36.1484" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <path d="M26.6433 36.3516L30.2273 26.4116H32.1453L35.7293 36.3516H34.1193L33.2093 33.7616H29.1493L28.2533 36.3516H26.6433ZM29.6253 32.3896H32.7473L31.1793 27.8536L29.6253 32.3896ZM36.9188 36.3516V26.4116H38.4308V36.3516H36.9188Z" fill="#9599A6" />
        <circle cx="7.20078" cy="7.19688" r="2.4" fill="#FF6464" />
        <circle cx="15.2008" cy="7.19688" r="2.4" fill="#FFA83D" />
        <circle cx="23.2008" cy="7.19688" r="2.4" fill="#25B14C" />
      </>
    ),
    sentiment: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="4.80078" y="24.9453" width="15.2" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="30.9453" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="36.9453" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <path d="M33.0648 34.9942C32.0492 34.9942 31.4219 35.6812 31.0037 36.1492C30.7946 36.3882 30.6253 36.5774 30.4561 36.6968C30.2868 36.8163 30.1474 36.8661 29.9283 36.8661C29.5998 36.8661 29.4006 36.6968 29.2214 36.4778C29.0521 36.2488 28.9426 36.0297 28.9426 36.0297L27.7676 36.4678C27.7676 36.4678 27.917 36.8661 28.2356 37.2744C28.5543 37.6826 29.1318 38.1406 29.9283 38.1406C30.4262 38.1406 30.8643 37.9614 31.1929 37.7324C31.5115 37.4934 31.7505 37.2146 31.9596 36.9856C32.3778 36.5176 32.5869 36.2587 33.0847 36.2587C33.035 36.2587 33.1544 36.2886 33.254 36.3981C33.3536 36.4977 33.4233 36.5973 33.4233 36.5973L33.5926 36.896H34.3991L34.5982 36.6172C34.5982 36.6172 34.6679 36.5077 34.7675 36.3981C34.8671 36.2986 34.9965 36.2587 34.9368 36.2587C35.4346 36.2587 35.6437 36.5176 36.0619 36.9856C36.271 37.2246 36.51 37.5034 36.8286 37.7324C37.1473 37.9714 37.5854 38.1406 38.0932 38.1406C38.8898 38.1406 39.4573 37.6826 39.7859 37.2744C40.1045 36.8761 40.2539 36.4678 40.2539 36.4678L39.0789 36.0297C39.0789 36.0297 38.9993 36.2587 38.83 36.4778C38.6607 36.7068 38.4317 36.8661 38.1031 36.8661C37.8741 36.8661 37.7546 36.8064 37.5854 36.6968C37.4161 36.5774 37.2269 36.3882 37.0178 36.1492C36.5996 35.6713 35.9723 34.9942 34.9567 34.9942C34.5086 34.9942 34.2298 35.1933 34.0207 35.3825C33.7917 35.1933 33.493 34.9942 33.0648 34.9942ZM38.4019 27.4187C39.7959 27.4187 40.921 28.5438 40.921 29.9378C40.921 31.3318 39.7959 32.457 38.4019 32.457C37.0079 32.457 35.8827 31.3318 35.8827 29.9378C35.8827 28.5438 36.9979 27.4187 38.4019 27.4187ZM29.5998 27.4187C30.9938 27.4187 32.1189 28.5438 32.1189 29.9378C32.1189 31.3318 30.9938 32.457 29.5998 32.457C28.2058 32.457 27.0806 31.3318 27.0806 29.9378C27.0806 28.5438 28.2058 27.4187 29.5998 27.4187ZM29.5998 26.1641C27.9576 26.1641 26.5556 27.2173 26.0425 28.6887C25.9039 29.086 25.8857 29.512 25.8857 29.9328C25.8857 30.3536 25.9039 30.7797 26.0425 31.177C26.5556 32.6483 27.9576 33.7016 29.5998 33.7016C31.6808 33.7016 33.3735 32.0089 33.3735 29.9279C33.3735 29.5694 33.6424 29.3006 34.0008 29.3006C34.3593 29.3006 34.6281 29.5694 34.6281 29.9279C34.6281 32.0089 36.3208 33.7016 38.4019 33.7016C40.0439 33.7016 41.4447 32.6557 41.9575 31.1863C42.0962 30.789 42.1146 30.363 42.1151 29.9423C42.1156 29.5152 42.0977 29.0827 41.956 28.6797C41.4404 27.2131 40.0407 26.1641 38.4019 26.1641C36.8983 26.1641 35.5939 27.0502 34.9866 28.3248C34.6978 28.1555 34.3593 28.046 34.0008 28.046C33.6424 28.046 33.3038 28.1455 33.015 28.3248C32.4077 27.0502 31.1033 26.1641 29.5998 26.1641Z" fill="#9599A6" />
        <circle cx="7.20078" cy="7.19688" r="2.4" fill="#FF6464" />
        <circle cx="15.2008" cy="7.19688" r="2.4" fill="#FFA83D" />
        <circle cx="23.2008" cy="7.19688" r="2.4" fill="#25B14C" />
      </>
    ),
    competitor: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="4.80078" y="24.9453" width="15.2" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="30.9453" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="36.9453" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <path d="M34.001 26.8151V29.4818M36.6676 32.1484H39.3343M34.001 34.8151V37.4818M28.6676 32.1484C28.6676 32.1484 30.5741 32.1484 31.3343 32.1484M34.001 38.1484C30.6873 38.1484 28.001 35.4622 28.001 32.1484C28.001 28.8347 30.6873 26.1484 34.001 26.1484C37.3147 26.1484 40.001 28.8347 40.001 32.1484C40.001 35.4622 37.3147 38.1484 34.001 38.1484Z" stroke="#9599A6" strokeWidth="1.33" strokeLinecap="round" />
        <circle cx="7.20078" cy="7.19688" r="2.4" fill="#FF6464" />
        <circle cx="15.2008" cy="7.19688" r="2.4" fill="#FFA83D" />
        <circle cx="23.2008" cy="7.19688" r="2.4" fill="#25B14C" />
      </>
    ),
    stock: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="4.80078" y="24.9453" width="15.2" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="30.9453" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <rect x="4.80078" y="36.9453" width="11.6" height="2.4" rx="0.756" fill="#666B75" />
        <path d="M40.001 38.1484H29.0676C28.6943 38.1484 28.5076 38.1484 28.365 38.0758C28.2395 38.0119 28.1376 37.9099 28.0736 37.7844C28.001 37.6418 28.001 37.4551 28.001 37.0818V26.1484M40.001 28.8151L36.3781 32.438C36.2461 32.57 36.1801 32.636 36.104 32.6607C36.037 32.6825 35.9649 32.6825 35.898 32.6607C35.8219 32.636 35.7559 32.57 35.6239 32.438L34.3781 31.1922C34.2461 31.0602 34.1801 30.9942 34.104 30.9695C34.037 30.9477 33.9649 30.9477 33.898 30.9695C33.8219 30.9942 33.7559 31.0602 33.6239 31.1922L30.6676 34.1484M40.001 28.8151H37.3343M40.001 28.8151V31.4818" stroke="#9599A6" strokeWidth="1.33" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="7.20078" cy="7.19688" r="2.4" fill="#FF6464" />
        <circle cx="15.2008" cy="7.19688" r="2.4" fill="#FFA83D" />
        <circle cx="23.2008" cy="7.19688" r="2.4" fill="#25B14C" />
      </>
    ),
    security: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="6.85938" y="8" width="4" height="2.85714" rx="0.714286" fill="#8585FF" />
        <rect x="11.6211" y="8" width="23.6905" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="36.0732" y="8" width="6.78571" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="6.85938" y="14.125" width="4" height="2.85714" rx="0.714286" fill="#00B983" fillOpacity="0.8" />
        <rect x="11.6211" y="14.125" width="23.2381" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="6.85938" y="20.25" width="4" height="2.85714" rx="0.714286" fill="#00B983" opacity="0.8" />
        <rect x="11.6211" y="20.25" width="6.79" height="2.85714" rx="0.714286" fill="#666B75" />
        <path d="M40.0039 32.1484C40.0039 34.3576 38.213 36.1484 36.0039 36.1484C33.7948 36.1484 32.0039 34.3576 32.0039 32.1484C32.0039 29.9393 33.7948 28.1484 36.0039 28.1484C38.213 28.1484 40.0039 29.9393 40.0039 32.1484Z" stroke="#9599A6" strokeWidth="1.33" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M28.0039 32.1484H29.3372" stroke="#9599A6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M28.0039 28.8125H30.0039" stroke="#9599A6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M28.0039 35.4844H30.0039" stroke="#9599A6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M39.001 35.1484L40.6676 36.8151" stroke="#9599A6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
    bug: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="6.85938" y="8" width="4" height="2.85714" rx="0.714286" fill="#8585FF" />
        <rect x="11.6211" y="8" width="23.6905" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="36.0732" y="8" width="6.78571" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="6.85938" y="14.125" width="4" height="2.85714" rx="0.714286" fill="#00B983" fillOpacity="0.8" />
        <rect x="11.6211" y="14.125" width="23.2381" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect opacity="0.8" x="6.85938" y="20.25" width="4" height="2.85714" rx="0.714286" fill="#00B983" />
        <rect x="11.6211" y="20.25" width="6.79" height="2.85714" rx="0.714286" fill="#666B75" />
        <path d="M30.001 32.8151V34.1484C30.001 36.3576 31.7918 38.1484 34.001 38.1484C36.2101 38.1484 38.001 36.3576 38.001 34.1484V32.8151M30.001 32.8151H28.001M30.001 32.8151V31.4818C30.001 30.3772 30.8964 29.4818 32.001 29.4818H36.001C37.1056 29.4818 38.001 30.3772 38.001 31.4818V32.8151M38.001 32.8151H40.001M30.001 35.4818L28.1676 36.1484M38.001 35.4818L39.8343 36.1484M34.001 32.8151V37.4818M31.3343 29.1484V28.8151C31.3343 27.3423 32.5282 26.1484 34.001 26.1484C35.4737 26.1484 36.6676 27.3423 36.6676 28.8151V29.1484M30.181 30.1484L28.1676 29.4818M37.6676 30.1484L39.8343 29.4818" stroke="#9599A6" strokeWidth="1.33" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
    coverage: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="6.85938" y="8" width="4" height="2.85714" rx="0.714286" fill="#8585FF" />
        <rect x="11.6211" y="8" width="23.6905" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="36.0732" y="8" width="6.78571" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="6.85938" y="14.125" width="4" height="2.85714" rx="0.714286" fill="#00B983" fillOpacity="0.8" />
        <rect x="11.6211" y="14.125" width="23.2381" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect opacity="0.8" x="6.85938" y="20.25" width="4" height="2.85714" rx="0.714286" fill="#00B983" />
        <rect x="11.6211" y="20.25" width="6.79" height="2.85714" rx="0.714286" fill="#666B75" />
        <path d="M32.0013 27.0078C30.0736 27.5815 28.668 29.3672 28.668 31.4813C28.668 34.0586 30.7573 36.1479 33.3346 36.1479C35.4487 36.1479 37.2344 34.7422 37.8081 32.8145" stroke="#9599A6" strokeWidth="1.33" strokeLinecap="round" />
        <path d="M39.3345 37.4849L36.7012 34.8516" stroke="#9599A6" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M36.668 25.8174C36.6904 25.8175 36.7105 25.8317 36.7188 25.8525L37.1836 27.0605C37.2851 27.3247 37.4938 27.5332 37.7578 27.6348L38.9658 28.0996C38.987 28.1078 39.001 28.1286 39.001 28.1514C39.0008 28.174 38.9869 28.194 38.9658 28.2021L37.7578 28.667C37.4938 28.7686 37.2851 28.9771 37.1836 29.2412L36.7188 30.4492C36.7106 30.4703 36.6905 30.4842 36.668 30.4844C36.6452 30.4844 36.6244 30.4704 36.6162 30.4492L36.1514 29.2412C36.0498 28.9772 35.8412 28.7685 35.5771 28.667L34.3691 28.2021C34.3483 28.1939 34.3341 28.1739 34.334 28.1514C34.334 28.1287 34.3481 28.1078 34.3691 28.0996L35.5771 27.6348C35.8412 27.5332 36.0498 27.3247 36.1514 27.0605L36.6162 25.8525C36.6244 25.8315 36.6453 25.8174 36.668 25.8174Z" fill="#9599A6" stroke="#9599A6" strokeWidth="0.666667" />
      </>
    ),
    summary: (
      <>
        <rect width="48" height="48" rx="5.6" fill="#E0E2F2" fillOpacity="0.08" />
        <rect x="0.25" y="0.25" width="47.5" height="47.5" rx="5.35" stroke="#E0E2F2" strokeOpacity="0.1" strokeWidth="0.5" />
        <rect x="6.85938" y="8" width="4" height="2.85714" rx="0.714286" fill="#8585FF" />
        <rect x="11.6211" y="8" width="23.6905" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="36.0732" y="8" width="6.78571" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect x="6.85938" y="14.125" width="4" height="2.85714" rx="0.714286" fill="#00B983" fillOpacity="0.8" />
        <rect x="11.6211" y="14.125" width="23.2381" height="2.85714" rx="0.714286" fill="#666B75" />
        <rect opacity="0.8" x="6.85938" y="20.25" width="4" height="2.85714" rx="0.714286" fill="#00B983" />
        <rect x="11.6211" y="20.25" width="6.79" height="2.85714" rx="0.714286" fill="#666B75" />
        <path d="M28.3359 36.1494V28.1494C28.3359 26.6776 29.5291 25.4844 31.001 25.4844H36.0645C36.8553 25.4844 37.605 25.8359 38.1113 26.4434L39.5479 28.167C39.9469 28.6458 40.1659 29.2498 40.166 29.873V36.1494C40.166 37.6213 38.9728 38.8145 37.501 38.8145H31.001C29.5291 38.8145 28.3359 37.6213 28.3359 36.1494ZM29.666 36.1494C29.666 36.8867 30.2637 37.4844 31.001 37.4844H37.501C38.2383 37.4844 38.8359 36.8867 38.8359 36.1494V29.873C38.8358 29.5609 38.7262 29.2584 38.5264 29.0186L37.0898 27.2949C36.8363 26.9906 36.4606 26.8145 36.0645 26.8145H31.001C30.2637 26.8145 29.666 27.4121 29.666 28.1494V36.1494Z" fill="#9599A6" />
        <path d="M36.251 30.4844C36.6182 30.4844 36.916 30.7821 36.916 31.1494C36.916 31.5167 36.6182 31.8145 36.251 31.8145H32.251C31.8837 31.8145 31.5859 31.5167 31.5859 31.1494C31.5859 30.7821 31.8837 30.4844 32.251 30.4844H36.251Z" fill="#9599A6" />
        <path d="M36.251 34.4844C36.6182 34.4844 36.916 34.7821 36.916 35.1494C36.916 35.5167 36.6182 35.8145 36.251 35.8145H32.251C31.8837 35.8145 31.5859 35.5167 31.5859 35.1494C31.5859 34.7821 31.8837 34.4844 32.251 34.4844H36.251Z" fill="#9599A6" />
        <path d="M34.916 33.1494C34.916 33.5167 34.6182 33.8145 34.251 33.8145C33.8837 33.8145 33.5859 33.5167 33.5859 33.1494L33.5859 29.1494C33.5859 28.7821 33.8837 28.4844 34.251 28.4844C34.6182 28.4844 34.916 28.7821 34.916 29.1494L34.916 33.1494Z" fill="#9599A6" />
      </>
    ),
  }

  return (
    <div className="cardIcon-ZFp7gR">
      <span className="cardIconImg-Ir2I_1" role="img">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          {icons[iconKey]}
        </svg>
      </span>
    </div>
  )
}

type SpaceExample = {
  name: string
  desc: string
  iconKey: string
}

const spaceExamples: SpaceExample[] = [
  { name: '线性代数', desc: '围绕方程组、向量和矩阵组织资料与对话。', iconKey: 'summary' },
  { name: '论文精读', desc: '把论文、笔记和后续对话放在同一个上下文里。', iconKey: 'news' },
  { name: '英语阅读', desc: '先放阅读材料，再在这个空间里继续往下读。', iconKey: 'sentiment' },
  { name: '统计基础', desc: '这个空间里的资料和对话与其他主题分开。', iconKey: 'competitor' },
  { name: '写作练习', desc: '可以先有一个空空间，稍后再放入资料。', iconKey: 'stock' },
  { name: '历史笔记', desc: '用来放史料和自己的笔记，不是进度看板。', iconKey: 'security' },
  { name: '程序设计', desc: '围绕题目和代码练习组织学习。', iconKey: 'bug' },
  { name: '经济学导论', desc: '用来放教材章节和相关对话。', iconKey: 'coverage' },
]

const headerBtnBase: React.CSSProperties = {
  alignItems: 'center',
  borderRadius: '6px',
  cursor: 'pointer',
  display: 'inline-flex',
  fontSize: '14px',
  gap: '4px',
  height: '32px',
  justifyContent: 'center',
  lineHeight: '20px',
  padding: '0 12px',
}

interface AutomationPageProps {
  onContinueLearning?: () => void
}

export function AutomationPage({ onContinueLearning }: AutomationPageProps) {
  const [selectedSpace, setSelectedSpace] = useState<SpaceExample | null>(null)
  const [creating, setCreating] = useState(false)

  return (
    <div className="root-Bkr7v6">
      <div className="scrollArea-fvGujy">
        <div className="scrollContent-Q7fN_Z">
          <div className="headerRail-GfhRry">
            <div className="titleGroup-R6DD_m">
              <h1 className="title-yQrHui">学习空间</h1>
              <p className="subtitle-Gi_Tjb">长期学习上下文。下面是页面示例，不是你已经建好的空间。</p>
            </div>
            <div className="headerActions-TKXare" style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className="button-muTeiY primary-ZG2S1H large-psSWuL"
                style={{
                  ...headerBtnBase,
                  background: 'var(--bg-bg-invert)',
                  border: 'none',
                  color: 'var(--text-text-onaccent)',
                }}
                onClick={() => setCreating(true)}
              >
                <span>＋ 新建空间</span>
              </button>
            </div>
          </div>
          <div className="contentRail-dRMjXS">
            <div className="container-YgYmSM">
              {spaceExamples.map((space) => (
                <div
                  key={space.name}
                  className="card-_oFXKS"
                  onClick={() => setSelectedSpace(space)}
                  style={{ cursor: 'pointer' }}
                >
                  <AutomationIcon iconKey={space.iconKey} />
                  <div className="cardTextGroup-KWTVxc">
                    <span className="cardName-LP1Fhu">{space.name}</span>
                    <span className="cardDescription-VEKD4l">{space.desc}</span>
                  </div>
                  <button
                    type="button"
                    className="button-muTeiY secondary-J0eGRO"
                    style={{
                      ...headerBtnBase,
                      background: 'transparent',
                      border: '1px solid var(--border-border-neutral-l2)',
                      color: 'var(--text-text-default)',
                      fontSize: '13px',
                      marginTop: '8px',
                      alignSelf: 'flex-start',
                    }}
                    onClick={(e) => {
                      e.stopPropagation()
                      onContinueLearning?.()
                    }}
                  >
                    继续学习
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {selectedSpace && (
        <SpaceDetailModal
          space={selectedSpace}
          onClose={() => setSelectedSpace(null)}
          onContinueLearning={() => {
            setSelectedSpace(null)
            onContinueLearning?.()
          }}
        />
      )}
      {creating && (
        <CreateSpaceModal onClose={() => setCreating(false)} />
      )}
    </div>
  )
}

function SpaceDetailModal({
  space,
  onClose,
  onContinueLearning,
}: {
  space: SpaceExample
  onClose: () => void
  onContinueLearning: () => void
}) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '480px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">{space.name}</h2>
              <p className="detailDescription-kBy0Ek">长期学习上下文</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '20px', color: 'var(--text-text-secondary)', fontSize: '14px', lineHeight: '22px' }}>
            <p>{space.desc}</p>
            <p style={{ marginTop: '12px' }}>空间用来放资料和对话，不是对话本身，也不是课程目录。</p>
            <p style={{ marginTop: '12px' }}>现在点「继续学习」只会回到现有对话界面，不会新开一段学习。</p>
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onClose} style={{
              background: 'transparent', border: '1px solid var(--border-border-neutral-l2)',
              borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              关闭
            </button>
            <button className="detailBtnPrimary-NtBx72" onClick={onContinueLearning} style={{
              background: 'var(--bg-bg-invert)', borderRadius: '4px',
              color: 'var(--text-text-onaccent)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              继续学习
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

function CreateSpaceModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [notice, setNotice] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()} style={{ width: '480px', height: 'auto' }}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailTitleGroup-cpT99c">
              <h2 className="detailTitle-X7zIZu">新建空间</h2>
              <p className="detailDescription-kBy0Ek">现在还不会保存</p>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div style={{ padding: '20px', color: 'var(--text-text-secondary)', fontSize: '14px', lineHeight: '22px' }}>
            {notice ? (
              <p>现在还不能真正创建空间。接入之后，这里才会保存。</p>
            ) : (
              <>
                <label htmlFor="space-name-input" style={{ display: 'block', marginBottom: '8px', color: 'var(--text-text-default)' }}>
                  空间名称
                </label>
                <input
                  id="space-name-input"
                  className="input-yEGQlg"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如：线性代数"
                  style={{
                    width: '100%',
                    background: 'var(--bg-bg-input)',
                    border: '1px solid var(--border-border-neutral-l2)',
                    borderRadius: '6px',
                    color: 'var(--text-text-default)',
                    fontSize: '14px',
                    height: '32px',
                    outline: 'none',
                    padding: '0 10px',
                  }}
                />
                <p style={{ marginTop: '12px' }}>提交后不会显示创建成功，也不会出现在空间列表里。</p>
              </>
            )}
          </div>
          <div className="detailActionBar-BhqrLr">
            <button className="detailBtn-j5pRnW" onClick={onClose} style={{
              background: 'transparent', border: '1px solid var(--border-border-neutral-l2)',
              borderRadius: '4px', color: 'var(--text-text-default)', cursor: 'pointer',
              display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
              height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
            }}>
              {notice ? '知道了' : '取消'}
            </button>
            {!notice && (
              <button className="detailBtnPrimary-NtBx72" onClick={() => setNotice(true)} style={{
                background: 'var(--bg-bg-invert)', borderRadius: '4px',
                color: 'var(--text-text-onaccent)', cursor: 'pointer',
                display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
              }}>
                创建空间
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ============ Plugin Marketplace Page ============ */
const categories = ['全部', '推荐', '开发工具', '调研分析', '界面设计', '内容创作', '效率提升']

type PluginState = 'installed' | 'available'
const plugins: PluginData[] = [
  { name: '飞书', description: '连接你的飞书账号，让 Lumen 操作云文档、多维表格、日历、消息等飞书功能', publisher: 'Lumen', color: '📱', icon: '📱', category: '推荐', state: 'installed' },
  { name: '企业微信', description: '企业微信插件：消息、通讯录、会议、日程、待办、文档、在线表格、智能表格、智能文档。通过 wecom-cli 与企业微信交互。', publisher: 'Lumen', color: '💼', icon: '💼', category: '推荐', state: 'installed' },
  { name: '钉钉', description: '钉钉协作工作流，支持企业消息、文档、日历、审批和组织效率场景。', publisher: 'Lumen', color: '🔧', icon: '🔧', category: '推荐', state: 'available' },
  { name: 'tencent-docs', description: 'Access Tencent Docs through the official MCP server.', publisher: 'Lumen', color: '📄', icon: '📄', category: '推荐', state: 'available' },
  { name: 'CodeRabbit', description: '在 Agent 中使用由 CodeRabbit 提供支持的 AI 代码审查。', publisher: 'Lumen', color: '🐰', icon: '🐰', category: '开发工具', state: 'available' },
  { name: 'Langfuse 可观测性', description: 'Langfuse 可观测性集成，支持查询追踪、调试异常、分析会话，并通过 MCP 工具管理提示词。', publisher: 'Lumen', color: '📊', icon: '📊', category: '开发工具', state: 'available' },
  { name: 'Cloudflare', description: '面向 Cloudflare 平台的插件，集成了适用于 Workers、Wrangler、Agents SDK 和官方 Cloudflare API MCP Server 的精选技能。', publisher: 'Lumen', color: '☁️', icon: '☁️', category: '开发工具', state: 'available' },
  { name: 'Chrome Dev Tools', description: '一键接入的 chrome-devtools-mcp 插件封装，聚焦浏览器调试与性能优化技能。', publisher: 'Lumen', color: '🌐', icon: '🌐', category: '开发工具', state: 'available' },
  { name: 'NVIDIA生态开发', description: '面向 NVIDIA 生态的技能，覆盖 GPU 加速、CUDA、AI Agent、推理、机器人、Physical AI、Omniverse 与仿真。', publisher: 'Lumen', color: '🎮', icon: '🎮', category: '开发工具', state: 'available' },
  { name: "Writer's Loop", description: 'A portable writing workflow for planning, critique, revision, style distillation, translation, and local preference learning.', publisher: 'Lumen', color: '✍️', icon: '✍️', category: '开发工具', state: 'available' },
  { name: 'Zotero', description: '通过 Agent 与 Zotero 协作：搜索你的文献库、导出 BibTeX、插入引文，并通过 Zotero 桌面应用导入参考文献。', publisher: 'Lumen', color: '📚', icon: '📚', category: '调研分析', state: 'available' },
  { name: 'X Twitter Scraper', description: 'X (Twitter) data and automation skill for agents using Xquik REST API, MCP, webhooks, SDKs, and confirmation-gated actions.', publisher: 'Lumen', color: '🐦', icon: '🐦', category: '调研分析', state: 'available' },
  { name: 'ngs-analysis', description: 'Guided NGS intake, local execution, and public-pipeline routing for BCL, FASTQ, DNA variant, RNA-seq, single-cell, epigenomics, amplicon, and metagenomics analyses.', publisher: 'Lumen', color: '🧬', icon: '🧬', category: '调研分析', state: 'available' },
  { name: 'Mixpanel', description: '借助 mixpanel_headless Python SDK 和相关技能分析 Mixpanel 数据。', publisher: 'Lumen', color: '📈', icon: '📈', category: '调研分析', state: 'available' },
  { name: '浏览器游戏开发', description: '提供面向浏览器游戏的设计、原型开发与发布工作流，支持引导式 2D / 3D 流程、资源管线和试玩测试。', publisher: 'Lumen', color: '🎲', icon: '🎲', category: '界面设计', state: 'available' },
  { name: 'Web 数据可视化', description: '提供 Agent 内的 Web 数据可视化工作流，支持从设计、评审到实现、测试和导出，覆盖图表、地图、仪表盘、甘特图、UML、叙事滚动、报告、幻灯片、移动端视图、可分享状态和高级 WebGL 能力。', publisher: 'Lumen', color: '📉', icon: '📉', category: '界面设计', state: 'available' },
  { name: 'Remotion', description: '面向 Remotion 视频创作的技能，涵盖最佳实践、动画、音频、字幕、3D 等能力，帮助你用 React 构建程序化视频。', publisher: 'Lumen', color: '🎬', icon: '🎬', category: '内容创作', state: 'available' },
  { name: 'HyperFrames', description: '面向 HyperFrames 的视频创作能力，支持用 HTML 生成视频，并实现合成编排、GSAP 动画、字幕、配音、音频响应式视觉效果和网页转视频。', publisher: 'Lumen', color: '🎞️', icon: '🎞️', category: '内容创作', state: 'available' },
  { name: '飞书', description: '连接你的飞书账号，让 Lumen 操作云文档、多维表格、日历、消息等飞书功能', publisher: 'Lumen', color: '📱', icon: '📱', category: '效率提升', state: 'available' },
  { name: '企业微信', description: '企业微信插件：消息、通讯录、会议、日程、待办、文档、在线表格、智能表格、智能文档。通过 wecom-cli 与企业微信交互。', publisher: 'Lumen', color: '💼', icon: '💼', category: '效率提升', state: 'available' },
  { name: '钉钉', description: '钉钉协作工作流，支持企业消息、文档、日历、审批和组织效率场景。', publisher: 'Lumen', color: '🔧', icon: '🔧', category: '效率提升', state: 'available' },
  { name: 'tencent-docs', description: 'Access Tencent Docs through the official MCP server.', publisher: 'Lumen', color: '📄', icon: '📄', category: '效率提升', state: 'available' },
  { name: 'notion', description: 'Notion workflows for implementation planning, research synthesis, meeting preparation, and knowledge capture.', publisher: 'Lumen', color: '🗒️', icon: '🗒️', category: '效率提升', state: 'available' },
  { name: 'Superpowers', description: '一套经过验证的 Agentic 技能框架与软件开发方法，帮助团队更好地完成规划、TDD、调试和协作。', publisher: 'Lumen', color: '⚡', icon: '⚡', category: '效率提升', state: 'available' },
]

type SkillData = {
  name: string
  description: string
  publisher: string
  icon: string
  category?: string
}

const skills: SkillData[] = [
  { name: 'alipay-payment-integration', description: '支付宝支付产品接入最佳实践指南，涵盖从线下到线上的全场景支付。', publisher: 'Alipay', icon: '💰', category: '推荐' },
  { name: 'byted-bp-cdn-pagesdeploy', description: '一键部署静态网站至 BytePlus Edge Pages 平台。', publisher: 'BytePlus', icon: '🚀', category: '推荐' },
  { name: 'composition-patterns', description: '你关于组合模式的权威参考，涵盖函数组合、管道与 compose、以及 React 组合模式等。', publisher: 'Vercel Labs', icon: '⚛️', category: '推荐' },
  { name: 'douyin-interact-creation', description: '抖音互动创作能力，帮助你创建有趣的互动视频内容。', publisher: '抖音', icon: '🎵', category: '推荐' },
  { name: 'vercel-deploy', description: 'Vercel 部署集成，支持一键部署你的应用。', publisher: 'Vercel', icon: '▲', category: '开发工具' },
  { name: 'github-actions', description: 'GitHub Actions 集成，支持 CI/CD 工作流自动化。', publisher: 'GitHub', icon: '🐙', category: '开发工具' },
  { name: 'figma-design', description: 'Figma 设计集成，支持从设计稿到代码的转换。', publisher: 'Figma', icon: '🎨', category: '界面设计' },
]

function getSkillIconUrl(name: string): string {
  const iconMap: Record<string, string> = {
    'alipay-payment-integration': '💰',
    'byted-bp-cdn-pagesdeploy': '🚀',
    'composition-patterns': '⚛️',
    'douyin-interact-creation': '🎵',
    'vercel-deploy': '▲',
    'github-actions': '🐙',
    'figma-design': '🎨',
  }
  return iconMap[name] || '📦'
}

export interface PluginData {
  name: string
  description: string
  publisher: string
  color: string
  icon: string
  category?: string
  state?: PluginState
}

interface MarketplacePageProps {
  onSelectPlugin: (plugin: PluginData) => void
  onSelectSkill: (skill: SkillData) => void
}

export function MarketplacePage({ onSelectPlugin, onSelectSkill }: MarketplacePageProps) {
  const [activeTab, setActiveTab] = useState<'plugins' | 'skills'>('plugins')
  const [activeCategory, setActiveCategory] = useState('全部')
  const [searchText, setSearchText] = useState('')
  const [installedPlugins, setInstalledPlugins] = useState<Set<string>>(new Set(plugins.filter(p => p.state === 'installed').map(p => p.name)))

  const filteredPlugins = plugins.filter((p) => {
    const matchCategory = activeCategory === '全部' || p.category === activeCategory
    const matchSearch = !searchText || p.name.toLowerCase().includes(searchText.toLowerCase())
    return matchCategory && matchSearch
  })

  const categorySections = categories.filter((c) => c !== '全部').map((cat) => ({
    title: cat,
    plugins: filteredPlugins.filter((p) => p.category === cat),
  }))

  const filteredSkills = skills.filter((s) => {
    const matchCategory = activeCategory === '全部' || s.category === activeCategory
    const matchSearch = !searchText || s.name.toLowerCase().includes(searchText.toLowerCase())
    return matchCategory && matchSearch
  })

  const skillCategorySections = categories.filter((c) => c !== '全部').map((cat) => ({
    title: cat,
    skills: filteredSkills.filter((s) => s.category === cat),
  }))

  const toggleInstall = (name: string) => {
    setInstalledPlugins(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  return (
    <div className="marketplacePage-U60AB4">
      <div className="root-Bkr7v6">
        <div className="scrollArea-fvGujy">
          <div className="scrollContent-Q7fN_Z">
            <div className="headerRail-GfhRry">
              <div className="titleGroup-R6DD_m">
                <h1 className="title-yQrHui">资料库</h1>
                <p className="subtitle-Gi_Tjb">发现并管理学习资料和知识内容，扩展 Lumen 的学习能力。</p>
              </div>
              <div className="headerActions-TKXare">
                <button className="button-muTeiY secondary-J0eGRO large-psSWuL" style={{
                  alignItems: 'center', background: 'transparent', border: '1px solid var(--border-border-neutral-l2)',
                  borderRadius: '6px', color: 'var(--text-text-default)', cursor: 'pointer',
                  display: 'inline-flex', fontSize: '13px', gap: '4px', height: '32px',
                  justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                }}>
                  <PageIcon name="settings" size={14} />
                  <span>管理</span>
                </button>
              </div>
            </div>
            <div className="stickyNavigation-vpcdcv">
              <div className="toolbarRail-Qlt0C7">
                <div className="tabSlider-Ol2p3T">
                  <button
                    className={activeTab === 'plugins' ? 'tabSliderItemActive-yIgLwL' : 'tabSliderItem-bXa2uc'}
                    onClick={() => setActiveTab('plugins')}
                  >
                    插件
                  </button>
                  <button
                    className={activeTab === 'skills' ? 'tabSliderItemActive-yIgLwL' : 'tabSliderItem-bXa2uc'}
                    onClick={() => setActiveTab('skills')}
                  >
                    技能
                  </button>
                </div>
                <div className="toolbarEnd-CGhDms">
                  <div className="searchSlot-ionH2H">
                    <div className="searchInputInputRoot-ql5R96">
                      <span className="searchInputInputIcon-_qGz4O">
                        <PageIcon name="search" size={16} />
                      </span>
                      <input
                        className="input-yEGQlg"
                        placeholder={activeTab === 'plugins' ? '搜索插件' : '搜索技能'}
                        value={searchText}
                        onChange={(e) => setSearchText(e.target.value)}
                        style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-text-default)', fontSize: '13px' }}
                      />
                    </div>
                  </div>
                  {activeTab === 'skills' && (
                    <button className="button-muTeiY primary-ZG2S1H large-psSWuL" style={{
                      alignItems: 'center', background: 'var(--bg-bg-invert)', borderRadius: '4px',
                      color: 'var(--text-text-onaccent)', cursor: 'pointer', display: 'inline-flex',
                      fontSize: '13px', gap: '4px', height: '32px', justifyContent: 'center',
                      padding: '0 12px',
                    }}>
                      <span>+ 安装技能</span>
                    </button>
                  )}
                </div>
              </div>
              <div className="filtersRail-_VFXr1">
                <div className="categoryNav-TtjHNd">
                  {categories.map((cat) => (
                    <button
                      key={cat}
                      className={activeCategory === cat ? 'categoryNavItemActive-k6zapU' : 'categoryNavItem-HXakRf'}
                      onClick={() => setActiveCategory(cat)}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="contentRail-dRMjXS">
              {activeTab === 'plugins' ? (
                <div className="pluginsContentInner-amtMMJ">
                  {activeCategory === '全部' ? (
                    categorySections.map((section) =>
                      section.plugins.length > 0 ? (
                        <div key={section.title} className="categorySection-T0Z3c3">
                          <span className="categorySectionTitle-b_hOUf">{section.title}</span>
                          <div className="pluginsGrid-u71c96">
                            {section.plugins.map((p) => {
                              const isInstalled = installedPlugins.has(p.name)
                              return (
                                <div
                                  key={p.name}
                                  className="pluginCard-cq4jH5"
                                  onClick={() => onSelectPlugin(p)}
                                >
                                  <div className="pluginCardHeader-RvwB47">
                                    <div className="marketIcon-ZTaS8Y">
                                      <span className="marketIconPluginImage-hG9jDA">{p.icon}</span>
                                    </div>
                                    <div className="pluginCardBody-bY5she">
                                      <span className="pluginCardName-ncj_7T">{p.name}</span>
                                      <span className="pluginCardDesc-bK19VV">{p.description}</span>
                                    </div>
                                    <button
                                      className="pluginCardActionButton-oekY_b"
                                      onClick={(e) => { e.stopPropagation(); toggleInstall(p.name) }}
                                    >
                                      {isInstalled ? (
                                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '2px' }}>✓ 使用</span>
                                      ) : (
                                        <span style={{ display: 'inline-flex', alignItems: 'center' }}>+ 安装</span>
                                      )}
                                    </button>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ) : null
                    )
                  ) : (
                    <div className="categorySection-T0Z3c3">
                      <div className="pluginsGrid-u71c96">
                        {filteredPlugins.map((p) => {
                          const isInstalled = installedPlugins.has(p.name)
                          return (
                            <div
                              key={p.name}
                              className="pluginCard-cq4jH5"
                              onClick={() => onSelectPlugin(p)}
                            >
                              <div className="pluginCardHeader-RvwB47">
                                <div className="marketIcon-ZTaS8Y">
                                  <span className="marketIconPluginImage-hG9jDA">{p.icon}</span>
                                </div>
                                <div className="pluginCardBody-bY5she">
                                  <span className="pluginCardName-ncj_7T">{p.name}</span>
                                  <span className="pluginCardDesc-bK19VV">{p.description}</span>
                                </div>
                                <button
                                  className="pluginCardActionButton-oekY_b"
                                  onClick={(e) => { e.stopPropagation(); toggleInstall(p.name) }}
                                >
                                  {isInstalled ? (
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '2px' }}>✓ 使用</span>
                                  ) : (
                                    <span style={{ display: 'inline-flex', alignItems: 'center' }}>+ 安装</span>
                                  )}
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="pluginsContentInner-amtMMJ">
                  {activeCategory === '全部' ? (
                    skillCategorySections.map((section) =>
                      section.skills.length > 0 ? (
                        <div key={section.title} className="categorySection-T0Z3c3">
                          <span className="categorySectionTitle-b_hOUf">{section.title}</span>
                          <div className="skillsGrid-qtaVFy">
                            {section.skills.map((skill) => (
                              <div
                                key={skill.name}
                                className="skillCard-ZYOuVS"
                                onClick={() => onSelectSkill(skill)}
                              >
                                <div className="skillCardHeader-W2sqOU">
                                  <div className="marketIcon-ZTaS8Y">
                                    <span className="marketIconSkillImage-BqDFkD" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '20px' }}>{skill.icon}</span>
                                  </div>
                                  <div className="skillCardBody-xR2lZi">
                                    <div className="skillCardName-gePr1m">{skill.name}</div>
                                    <div className="skillCardDesc-_LvYuN">{skill.description}</div>
                                  </div>
                                  <button className="skillCardActionButton-FLd4yA">
                                    <span>+ 安装</span>
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null
                    )
                  ) : (
                    <div className="categorySection-T0Z3c3">
                      <div className="skillsGrid-qtaVFy">
                        {filteredSkills.map((skill) => (
                          <div
                            key={skill.name}
                            className="skillCard-ZYOuVS"
                            onClick={() => onSelectSkill(skill)}
                          >
                            <div className="skillCardHeader-W2sqOU">
                              <div className="marketIcon-ZTaS8Y">
                                <span className="marketIconSkillImage-BqDFkD" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '20px' }}>{skill.icon}</span>
                              </div>
                              <div className="skillCardBody-xR2lZi">
                                <div className="skillCardName-gePr1m">{skill.name}</div>
                                <div className="skillCardDesc-_LvYuN">{skill.description}</div>
                              </div>
                              <button className="skillCardActionButton-FLd4yA">
                                <span>+ 安装</span>
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ============ Workspace Page (main chat view) ============ */
export function WorkspacePage() {
  return (
    <div className="workspacePage" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="header-fId8VF">
        <div className="headerCenter-HRprYa">
          <div className="taskHeader-wmHGD9">
            <span className="wrapper-RV5xqM">
              <div className="infoArea-Y4r_8m">
                <div className="iconWrap-_fRuU8">
                  <PageIcon name="automation" size={14} />
                </div>
                <span className="taskName-iaeIsX">Greeting</span>
                <div className="timeWrap-ksZO3X">
                  <span className="timeText-bjF8AM">18:12</span>
                </div>
              </div>
            </span>
            <div className="moreBtn-h2uOKe">
              <PageIcon name="down" size={16} />
            </div>
          </div>
        </div>
      </div>
      <div className="workspace-nQt_sr">
        <div className="mainContent-I6jtPZ">
          <div id="agent-chat-view" className="chatArea-zQPQwl">
            <div className="chatInner-c6091C">
              <div className="chatContent-h48jjm">
                <div className="ai-chat chat-session">
                  <div className="virtualized-message-list-view">
                    <div className="virtualized-message-list-view__content">
                      <div className="virtualized-message-list-view__scroller virtualized-message-list-view__scroller--hide-scrollbar">
                        <div className="virtualized-message-list-view__virtuoso" style={{ position: 'relative' }}>
                          <div className="turn turn--last" data-turn-id="m-2">
                            <div className="turn__agent-row">
                              <div className="turn__agent-message" data-role="assistant">
                                <div data-item-type="turn:assistant-avatar">
                                  <div className="agent-message__header">
                                    <div className="agent-avatar agent-avatar--solo-code" style={{ width: 18, height: 18 }}>
                                      <PageIcon name="code" size={12} />
                                    </div>
                                    <span className="agent-message__title">Lumen</span>
                                  </div>
                                </div>
                                <div className="markdown-renderer">
                                  <p className="markdown-p">你好！我是 Lumen，有什么可以帮你的？</p>
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

/* ============ Skill Detail Modal ============ */
interface SkillDetailProps {
  skill: SkillData
  onClose: () => void
}

export function SkillDetailModal({ skill, onClose }: SkillDetailProps) {
  const [installing, setInstalling] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const alipayMarkdown = (
    <div className="detailMarkdownInner-grR20b">
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 16px 0' }}>
        所有支付宝支付产品的文档均为在线动态链接，接入前务必阅读对应产品的在线文档获取最新接口参数和代码示例。
      </p>
      <h2 style={{ color: 'var(--text-text-default)', fontSize: '16px', fontWeight: 600, margin: '0 0 12px 0' }}>
        文档访问规范
      </h2>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        访问支付宝在线文档时，直接使用 curl 获取内容：
      </p>
      <pre style={{ background: 'var(--bg-bg-overlay-l1)', borderRadius: '6px', padding: '12px', fontSize: '12px', color: 'var(--text-text-secondary)', overflow: 'auto', margin: '0 0 16px 0' }}>
{`# 示例: 获取当面付文档
curl -sL "https://ideservice.alipay.com/cms/site/0izcu3"`}
      </pre>
      <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 12px 0' }}>
        递归访问
      </h3>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        文档页面可能包含子链接，你必须自动跟进所有子链接以获取完整文档。具体规则：
      </p>
      <ol style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 16px 20px', padding: 0 }}>
        <li>仅跟进文档正文中的 URL</li>
        <li>忽略站内导航链接（产品首页、产品列表、产品分类、产品索引等）</li>
        <li>除非文档明确要求，否则跳过认证步骤</li>
      </ol>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        递归访问文档页面：
      </p>
      <pre style={{ background: 'var(--bg-bg-overlay-l1)', borderRadius: '6px', padding: '12px', fontSize: '12px', color: 'var(--text-text-secondary)', overflow: 'auto', margin: '0 0 16px 0' }}>
{`# 访问除最后一页外的所有页面
curl -sL "https://ideservice.alipay.com/cms/site/0izal0"   # 支付渠道
curl -sL "https://ideservice.alipay.com/cms/site/0izal1"   # 营销促销`}
      </pre>
      <h2 style={{ color: 'var(--text-text-default)', fontSize: '16px', fontWeight: 600, margin: '0 0 12px 0' }}>
        密钥配置方式
      </h2>
      <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
        步骤1. 密钥获取方式
      </h3>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 12px 0' }}>
        登录支付宝开放平台获取应用的 AppID、支付宝公钥以及应用私钥。应用公钥不需要手动配置，使用 RSA2 即可。
      </p>
      <ul style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: '0 0 16px 20px', padding: 0 }}>
        <li><strong style={{ color: 'var(--text-text-default)' }}>创建应用</strong>：在支付宝开放平台创建应用，获取 AppID。<a style={{ color: 'var(--text-text-link)' }} href="#">了解更多</a></li>
        <li><strong style={{ color: 'var(--text-text-default)' }}>配置密钥</strong>：使用 RSA2 生成密钥对，配置应用公钥。<a style={{ color: 'var(--text-text-link)' }} href="#">配置方法</a></li>
      </ul>
      <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
        步骤2. 配置应用密钥
      </h3>
      <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: 0 }}>
        在配置文件中设置应用的 AppID、应用私钥、支付宝公钥等参数。务必使用配置文件管理密钥，不要将密钥硬编码在代码或提交到代码仓库中。
      </p>
    </div>
  )

  const isAlipay = skill.name === 'alipay-payment-integration'

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailHeaderRow-L8ZCMj">
              <div className="detailIcon-qGQGfs">
                <span style={{ fontSize: '24px' }}>{skill.icon}</span>
              </div>
              <div className="detailTitleGroup-cpT99c">
                <h2 className="detailTitle-X7zIZu">{skill.name}</h2>
                <p className="detailPublisher-VPxyqw">by {skill.publisher}</p>
              </div>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div className="detailDocSection-Mil5SR">
            <div className="detailDescriptionCard-FtwEk8">
              <p className="detailDescriptionText-apMOdF">
                {skill.description}
              </p>
            </div>
            <div className="detailMarkdownCard-kxmm37">
              {isAlipay ? alipayMarkdown : (
                <div className="detailMarkdownInner-grR20b">
                  <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
                    技能说明
                  </h3>
                  <p style={{ color: 'var(--text-text-secondary)', fontSize: '13px', lineHeight: '22px', margin: 0 }}>
                    {skill.description}
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="detailActionBar-BhqrLr">
            <div className="detailActionRight-CxGqmX" style={{ marginLeft: 'auto' }}>
              <button
                className="detailBtnPrimary-NtBx72"
                disabled={installing}
                onClick={() => setInstalling(true)}
                style={{
                  background: 'var(--bg-bg-invert)', borderRadius: '4px',
                  color: 'var(--text-text-onaccent)', cursor: installing ? 'not-allowed' : 'pointer',
                  display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                  height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                  opacity: installing ? 0.6 : 1,
                }}
              >
                {installing ? '安装中...' : '+ 安装技能'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

/* ============ Plugin Detail Modal ============ */
interface PluginDetailProps {
  plugin: PluginData
  onClose: () => void
}

const skillTemplates = [
  { name: 'alipay-payment-integration', desc: '支付宝支付产品接入最佳实践指南，涵盖从线下到线上的全场景支付。', icon: '💰' },
  { name: 'byted-bp-cdn-pagesdeploy', desc: '一键部署静态网站至 BytePlus Edge Pages 平台。', icon: '🚀' },
]

export function PluginDetailModal({ plugin, onClose }: PluginDetailProps) {
  const [installing, setInstalling] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return ReactDOM.createPortal(
    <div className="detailMask-W8jDqu" onClick={onClose}>
      <div className="detailPanel-NZOW7g" onClick={(e) => e.stopPropagation()}>
        <div className="detailBody-mX1HCM">
          <div className="detailInfoSection-c234JE">
            <div className="detailHeaderRow-L8ZCMj">
              <div className="detailIcon-qGQGfs">
                <span style={{ fontSize: '24px' }}>{plugin.icon}</span>
              </div>
              <div className="detailTitleGroup-cpT99c">
                <h2 className="detailTitle-X7zIZu">{plugin.name}</h2>
                <p className="detailDescription-kBy0Ek">{plugin.description}</p>
                <p className="detailPublisher-VPxyqw">{plugin.publisher}</p>
              </div>
            </div>
            <button className="detailCloseBtn-cE6qVp" onClick={onClose} style={{
              alignItems: 'center', background: 'transparent', border: 'none',
              borderRadius: '4px', color: 'var(--icon-icon-secondary)',
              cursor: 'pointer', display: 'flex', height: '32px',
              justifyContent: 'center', width: '32px',
            }}>
              <PageIcon name="close" size={20} />
            </button>
          </div>
          <div className="detailDocSection-Mil5SR">
            <div className="detailDescriptionCard-FtwEk8">
              <p className="detailDescriptionText-apMOdF">
                {plugin.name} 是一个强大的插件，旨在提升你的开发效率。它提供了丰富的功能集，帮助你更快地编写代码、调试程序、生成文档等。无论是新手还是专家开发者，都能从中受益。
              </p>
            </div>
            <div className="detailMarkdownCard-kxmm37">
              <div className="detailMarkdownInner-grR20b">
                <h3 style={{ color: 'var(--text-text-default)', fontSize: '14px', fontWeight: 600, margin: '0 0 8px 0' }}>
                  可用技能
                </h3>
                <div>
                  <div className="skillsGrid-qtaVFy">
                    {skillTemplates.map((s) => (
                      <div key={s.name} className="skillCard-ZYOuVS">
                        <div className="skillCardHeader-W2sqOU">
                          <div className="cardIcon-ZFp7gR" style={{ alignItems: 'center', display: 'flex', fontSize: '24px', justifyContent: 'center' }}>
                            {s.icon}
                          </div>
                          <div className="skillCardBody-xR2lZi">
                            <span className="skillCardName-gePr1m">{s.name}</span>
                            <span className="skillCardDesc-_LvYuN">{s.desc}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="detailActionBar-BhqrLr">
            <div className="detailActionRight-CxGqmX" style={{ marginLeft: 'auto' }}>
              <button
                className="detailBtnPrimary-NtBx72"
                disabled={installing}
                onClick={() => setInstalling(true)}
                style={{
                  background: 'var(--bg-bg-invert)', borderRadius: '4px',
                  color: 'var(--text-text-onaccent)', cursor: installing ? 'not-allowed' : 'pointer',
                  display: 'inline-flex', fontSize: '13px', fontWeight: 500, gap: '6px',
                  height: '32px', justifyContent: 'center', lineHeight: '20px', padding: '0 12px',
                  opacity: installing ? 0.6 : 1,
                }}
              >
                {installing ? '安装中...' : '+ 安装技能'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}