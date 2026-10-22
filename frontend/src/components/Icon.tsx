import type { ReactNode } from 'react'

export type IconName =
  | 'grid' | 'pulse' | 'wallet' | 'file' | 'chart' | 'users' | 'settings' | 'search' | 'bell' | 'chevron' | 'arrow' | 'external'
  | 'spark' | 'shield' | 'trend' | 'clock' | 'check' | 'building' | 'filter' | 'close' | 'news' | 'up' | 'down' | 'alert' | 'plus' | 'send' | 'bank' | 'logout' | 'switch'

const paths: Record<IconName, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  pulse: <><path d="M3 12h4l2.4-6 4.2 12L16 12h5" /><path d="M4 20h16" /></>,
  wallet: <><path d="M4 7V5a2 2 0 0 1 2-2h12" /><rect x="3" y="6" width="18" height="14" rx="3" /><path d="M16 11h5v5h-5a2.5 2.5 0 0 1 0-5Z" /></>,
  file: <><path d="M6 2h8l4 4v16H6z" /><path d="M14 2v5h5M9 12h6M9 16h6" /></>,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  users: <><circle cx="9" cy="8" r="4" /><path d="M2 21v-2a6 6 0 0 1 12 0v2M16 4a4 4 0 0 1 0 8M16 15a6 6 0 0 1 6 6" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />,
  chevron: <path d="m8 10 4 4 4-4" />,
  arrow: <path d="M5 12h14M14 7l5 5-5 5" />,
  external: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6" /></>,
  spark: <><path d="m12 3 1.2 4.2L17 9l-3.8 1.8L12 15l-1.2-4.2L7 9l3.8-1.8z" /><path d="m5 14 .7 2.3L8 17l-2.3.7L5 20l-.7-2.3L2 17l2.3-.7zM19 2l.5 1.5L21 4l-1.5.5L19 6l-.5-1.5L17 4l1.5-.5z" /></>,
  shield: <><path d="M12 2 4 5v6c0 5.2 3.4 9 8 11 4.6-2 8-5.8 8-11V5z" /><path d="m9 12 2 2 4-4" /></>,
  trend: <><path d="m3 17 6-6 4 4 8-9" /><path d="M15 6h6v6" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  building: <path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h2M9 13h2M9 17h2M15 9h1M15 13h1M15 17h1" />,
  filter: <path d="M4 5h16M7 12h10M10 19h4" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  news: <><path d="M4 5h13v14H6a2 2 0 0 1-2-2z" /><path d="M17 9h3v8a2 2 0 0 1-2 2M7 9h7M7 13h7" /></>,
  up: <path d="M7 11v9H4v-9zM7 12l4-8c1.5 0 2.5 1 2 3l-.5 3H19a2 2 0 0 1 2 2.4l-1.2 6A2 2 0 0 1 17.8 20H7" />,
  down: <path d="M7 13V4H4v9zM7 12l4 8c1.5 0 2.5-1 2-3l-.5-3H19a2 2 0 0 0 2-2.4l-1.2-6A2 2 0 0 0 17.8 4H7" />,
  alert: <><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17.5v.5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  send: <path d="m4 12 16-8-6 16-2-7z" />,
  logout: <path d="M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5M16 8l4 4-4 4M20 12H9" />,
  switch: <path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7" />,
  bank: <path d="M3 10 12 4l9 6M5 10v8M9 10v8M15 10v8M19 10v8M3 20h18" />,
}

export function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  return (
    <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  )
}
