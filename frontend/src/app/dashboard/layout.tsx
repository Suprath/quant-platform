import Link from 'next/link';
import { GlobalStatusBar } from '@/components/GlobalStatusBar';

const MONO = 'ui-monospace, "Geist Mono", monospace';
const SIDEBAR_BG = '#0d1117';
const BORDER = '#1f2937';

const NAV_ITEMS = [
  { href: '/', icon: '⌂', label: 'HOME' },
  { href: '/dashboard/live', icon: '◉', label: 'LIVE' },
  { href: '/dashboard/orderflow', icon: '⚡', label: 'FLOW', highlight: '#34d399' },
  { href: '/dashboard/conviction', icon: '◈', label: 'CONV', highlight: '#f59e0b' },
  { href: '/dashboard/edge', icon: '◇', label: 'EDGE' },
  { href: '/dashboard/options', icon: 'Ψ', label: 'OPT' },
  { href: '/dashboard/backtest', icon: '▶', label: 'TEST' },
  { href: '/ide', icon: '{}', label: 'IDE' },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <GlobalStatusBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Sidebar */}
        <nav style={{
          width: 52, background: SIDEBAR_BG, borderRight: `1px solid ${BORDER}`,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          padding: '8px 0', gap: 2, flexShrink: 0,
        }}>
          <div style={{ color: '#60a5fa', fontSize: 11, fontWeight: 900,
            marginBottom: 10, padding: 6, fontFamily: MONO }}>K</div>
          {NAV_ITEMS.map(({ href, icon, label, highlight }) => (
            <Link key={href} href={href} style={{ textDecoration: 'none' }}>
              <div style={{
                width: 38, padding: '6px 4px', borderRadius: 4, textAlign: 'center',
                cursor: 'pointer', fontFamily: MONO,
                background: highlight ? `rgba(${highlight === '#34d399' ? '52,211,153' : '245,158,11'},0.12)` : 'transparent',
                border: highlight ? `1px solid ${highlight}33` : '1px solid transparent',
              }}>
                <div style={{ fontSize: 14 }}>{icon}</div>
                <div style={{ fontSize: 7, marginTop: 1,
                  color: highlight ?? '#6b7280', fontWeight: highlight ? 700 : 400 }}>
                  {label}
                </div>
              </div>
            </Link>
          ))}
          <Link href="/settings" style={{ marginTop: 'auto', textDecoration: 'none' }}>
            <div style={{ width: 38, padding: '6px 4px', borderRadius: 4,
              textAlign: 'center', fontFamily: MONO }}>
              <div style={{ fontSize: 14 }}>⚙</div>
              <div style={{ fontSize: 7, color: '#6b7280' }}>SET</div>
            </div>
          </Link>
        </nav>
        {/* Page content */}
        <main style={{ flex: 1, overflow: 'hidden' }}>{children}</main>
      </div>
    </div>
  );
}
