'use client';
import { useEffect, useState } from 'react';
import { useOrderFlowStore } from '@/stores/orderflowStore';

const MONO = 'ui-monospace, "Geist Mono", monospace';

export function GlobalStatusBar() {
  const [time, setTime] = useState('');
  const { wsStatus, cusumFires } = useOrderFlowStore();

  useEffect(() => {
    const tick = () => {
      setTime(
        new Date().toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour12: false,
        })
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const wsDotColor = wsStatus === 'connected' ? '#34d399' : wsStatus === 'connecting' ? '#f59e0b' : '#f87171';

  return (
    <div style={{
      background: '#111827', borderBottom: '1px solid #1f2937',
      padding: '3px 12px', display: 'flex', gap: 16, alignItems: 'center',
      fontFamily: MONO, fontSize: 9, flexShrink: 0, zIndex: 10,
    }}>
      <span style={{ color: '#34d399', fontWeight: 700 }}>⬤ NSE</span>
      <span style={{ color: '#60a5fa' }}>KIRA</span>
      {/* WS status dot */}
      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <span style={{ color: wsDotColor, fontSize: 8 }}>⬤</span>
        <span style={{ color: wsDotColor, fontWeight: 700 }}>OF</span>
      </span>
      {/* CUSUM fire count */}
      <span style={{ color: '#f59e0b', fontWeight: 700 }}>⚡ {cusumFires.length}</span>
      <span style={{ color: '#6b7280', marginLeft: 'auto' }}>{time} IST</span>
    </div>
  );
}
