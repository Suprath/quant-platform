"use client";

import React, { useState } from 'react';
import './terminal.css';

// --- Types ---
interface Stock {
  symbol: string;
  conf: number;
  mech: string;
  dir: 'LONG' | 'SHORT' | 'NONE';
  regime: 'TRU' | 'TRD' | 'RNG' | 'VOL';
  action: 'PROC' | 'PROB' | 'WAIT' | 'SKIP' | 'NONE';
}

interface NFState {
  name: string;
  value: number;
  trend: 'UP_UP' | 'UP' | 'STABLE' | 'DOWN' | 'DOWN_DOWN';
}



interface FunnelStage {
  name: string;
  count: number;
  wk: number;
  mo: number;
}

interface BackendPosition {
  symbol: string;
  mechanism?: string;
  entry_price: number;
  current_price: number;
  risk_at_risk?: number;
}

interface PortfolioState {
  total_equity: number;
  total_heat_pct: number;
  open_positions: BackendPosition[];
}

interface PerformancePoint {
  time: string;
  equity: number;
  heat: number;
}

interface PerformanceSummary {
  total_pnl_pct: number;
  max_drawdown_pct: number;
  current_equity: number;
  win_rate: number;
  profit_factor: number;
  net_profit?: number;
  total_trades?: number;
  sharpe_ratio?: number;
  cagr?: number;
  expectancy?: number;
  brokerage?: number;
}

interface PerformanceData {
  points: PerformancePoint[];
  summary: PerformanceSummary;
}

// --- Components ---

const PanelHeader = ({ title, right }: { title: string; right?: string }) => (
  <div className="panel-header">
    <span>{title}</span>
    {right && <span className="text-dim">{right}</span>}
  </div>
);

const UniverseMonitor = ({ stocks: inputStocks }: { stocks?: Stock[] }) => {
  const [defaultStocks] = useState<Stock[]>([
    { symbol: 'RELIANCE', conf: 85, mech: 'ACCUM', dir: 'LONG', regime: 'TRU', action: 'PROC' },
    { symbol: 'HDFCBANK', conf: 72, mech: 'MOMEN', dir: 'LONG', regime: 'TRU', action: 'PROB' },
    { symbol: 'ICICIBANK', conf: 91, mech: 'ACCUM', dir: 'LONG', regime: 'TRU', action: 'PROC' },
  ]);

  const stocks = inputStocks && inputStocks.length > 0 ? inputStocks : defaultStocks;

  const renderConfBar = (conf: number) => {
    const bars = Math.floor(conf / 25);
    const filled = '█'.repeat(bars);
    const empty = '░'.repeat(4 - bars);
    let colorClass = 'text-dim';
    if (conf >= 80) colorClass = 'text-positive';
    else if (conf >= 60) colorClass = 'text-white';
    else if (conf >= 40) colorClass = 'text-label';
    
    return <span className={colorClass}>{filled}{empty} {conf.toFixed(1)}</span>;
  };

  const getDirIcon = (dir: string) => {
    if (dir === 'LONG') return <span className="text-positive">▲</span>;
    if (dir === 'SHORT') return <span className="text-negative">▼</span>;
    return <span className="text-dim">–</span>;
  };

  const getRegimeColor = (regime: string) => {
    if (regime === 'TRU') return 'text-positive';
    if (regime === 'TRD') return 'text-negative';
    if (regime === 'RNG') return 'text-info';
    if (regime === 'VOL') return 'text-warning';
    return 'text-dim';
  };

  const getActionColor = (action: string) => {
    if (action === 'PROC') return 'text-positive';
    if (action === 'PROB') return 'text-info';
    if (action === 'WAIT') return 'text-warning';
    return 'text-dim';
  };

  return (
    <div className="terminal-panel" style={{ height: '520px' }}>
      <PanelHeader title="UNIVERSE MONITOR" right={`[${stocks.length} STOCKS]`} />
      <div className="panel-content" style={{ padding: 0 }}>
        <table className="w-full text-left border-collapse">
          <thead className="bg-panel-header text-label text-[10px] sticky top-0">
            <tr>
              <th className="px-2 py-1 font-normal">SYMBOL</th>
              <th className="px-2 py-1 font-normal">CONF</th>
              <th className="px-2 py-1 font-normal">MECH</th>
              <th className="px-2 py-1 font-normal">DIR</th>
              <th className="px-2 py-1 font-normal">REGIME</th>
              <th className="px-2 py-1 font-normal">ACT</th>
            </tr>
          </thead>
          <tbody className="text-[11px]">
            {stocks.sort((a,b) => b.conf - a.conf).map((s, i) => (
              <tr key={i} className={`border-b border-[#111] hover:bg-hover cursor-pointer ${s.action === 'PROC' ? 'bg-active-signal' : ''}`}>
                <td className="px-2 py-1 text-white">{s.symbol}</td>
                <td className="px-2 py-1">{renderConfBar(s.conf)}</td>
                <td className="px-2 py-1 text-info">{s.mech}</td>
                <td className="px-2 py-1 text-center">{getDirIcon(s.dir)}</td>
                <td className={`px-2 py-1 ${getRegimeColor(s.regime)}`}>{s.regime}</td>
                <td className={`px-2 py-1 ${getActionColor(s.action)}`}>{s.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-2 py-1 text-[10px] text-dim border-t border-primary">
        AVG CONF: 66  │  SIGNALS: 3  │  BLACKOUT: 0
      </div>
    </div>
  );
};

const NoiseFilterState = () => {
  const [params] = useState<NFState[]>([
    { name: 'MKT CONF', value: 74, trend: 'DOWN' },
    { name: 'SIG TRUST', value: 81, trend: 'STABLE' },
    { name: 'REGIME', value: 68, trend: 'UP' },
    { name: 'MICROSTRC', value: 91, trend: 'STABLE' },
    { name: 'CORR PUR', value: 38, trend: 'DOWN_DOWN' },
  ]);

  const renderTrend = (trend: string) => {
    switch(trend) {
      case 'UP_UP': return <span className="text-positive font-bold">↑↑</span>;
      case 'UP': return <span className="text-positive">↑</span>;
      case 'DOWN': return <span className="text-negative">↓</span>;
      case 'DOWN_DOWN': return <span className="text-negative font-bold">↓↓</span>;
      default: return <span className="text-dim">→</span>;
    }
  };

  const renderBar = (val: number) => {
    const filledCount = Math.floor(val / 7.7); // 13 chars total
    const filled = '█'.repeat(filledCount);
    const empty = '░'.repeat(13 - filledCount);
    let colorClass = 'text-negative';
    if (val > 70) colorClass = 'text-positive';
    else if (val >= 50) colorClass = 'text-warning';
    
    return <span className="text-[10px]"><span className={colorClass}>{filled}</span><span className="text-inactive">{empty}</span></span>;
  };

  return (
    <div className="terminal-panel" style={{ height: '100%' }}>
      <PanelHeader title="NOISE FILTER" right="15:23:41" />
      <div className="panel-content px-2 py-2">
        {params.map((p, i) => (
          <div key={i} className="flex items-center justify-between py-1 border-b border-[#111]">
            <span className="text-label text-[10px] w-20">{p.name}</span>
            <div className="flex-1 px-2">{renderBar(p.value)}</div>
            <span className="text-white w-6 text-right">{p.value}</span>
            <span className="w-6 text-right">{renderTrend(p.trend)}</span>
          </div>
        ))}
        <div className="mt-2 text-[11px]">
          <div className="flex justify-between">
            <span className="text-white">CNI: 47</span>
            <span className="text-warning">STATE: CAUTIOUS</span>
          </div>
          <div className="flex justify-between text-dim text-[10px]">
            <span>SCALE: 0.80×</span>
            <span>WEAKEST: CORR PURITY</span>
          </div>
          <div className="text-warning text-[10px] mt-1">→ DEFENSIVE IN ~25MIN</div>
        </div>
      </div>
    </div>
  );
};

const StatusBar = ({ 
  state, 
  isBtActive, 
  isBtBackfilling,
  btProgress, 
  btBackfillProgress,
  terminalMode, 
  setTerminalMode 
}: { 
  state: PortfolioState | null, 
  isBtActive: boolean, 
  isBtBackfilling: boolean,
  btProgress: number,
  btBackfillProgress: number,
  terminalMode: 'LIVE' | 'BACKTEST',
  setTerminalMode: (mode: 'LIVE' | 'BACKTEST') => void
}) => {
  return (
    <header className="terminal-header flex-col">
      <div className="flex justify-between items-center h-[26px] px-2 border-b border-[#111]">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-orange font-bold">[VEKTOR]</span>
            <span className="text-dim">{'>'}</span>
            <span className="text-white">TERMINAL MONITOR</span>
          </div>
          
          <div className="flex items-center bg-[#111] border border-[#333] h-[18px] rounded-sm overflow-hidden">
            <button 
              onClick={() => setTerminalMode('LIVE')}
              className={`px-2 text-[9px] h-full flex items-center transition-colors ${terminalMode === 'LIVE' ? 'bg-positive text-black font-bold' : 'text-dim hover:text-white'}`}
            >
              LIVE
            </button>
            <button 
              onClick={() => setTerminalMode('BACKTEST')}
              className={`px-2 text-[9px] h-full flex items-center transition-colors ${terminalMode === 'BACKTEST' ? 'bg-orange text-black font-bold' : 'text-dim hover:text-white'}`}
            >
              BACKTEST
            </button>
          </div>
        </div>
        
        <div className="flex items-center gap-4 text-dim text-[10px]">
          {isBtActive && (
              <div className="flex items-center gap-2">
                  <span className="text-orange animate-pulse">{isBtBackfilling ? 'BACKFILLING DATA...' : 'SIMULATING...'}</span>
                  <div className="w-20 h-1.5 bg-[#111] border border-[#333]">
                      <div className="h-full bg-orange" style={{ width: `${isBtBackfilling ? btBackfillProgress : btProgress}%` }} />
                  </div>
                  <span className="text-white">{isBtBackfilling ? btBackfillProgress : btProgress}%</span>
              </div>
          )}
          {!isBtActive && terminalMode === 'BACKTEST' && (
              <span className="text-orange font-bold text-[9px]">[HISTORICAL VIEW]</span>
          )}
          <span>{new Date().toLocaleTimeString()} IST</span>
          <span className="text-[12px] text-white">● <span className={isBtActive ? 'text-orange' : 'text-positive'}>{isBtActive ? 'SIMULATION ACTIVE' : terminalMode === 'LIVE' ? 'LIVE TRADING' : 'REPLAY MODE'}</span></span>
        </div>
      </div>
      <div className="flex justify-between items-center h-[26px] px-2">
        <div className="text-dim text-[10px]">CMD: idle [ready for instructions]</div>
        <div className="flex gap-4 text-[11px]">
          <span className="text-label">FILTER: <span className="text-warning">CAUTIOUS</span></span>
          <span className="text-label">HEAT: <span className="text-positive">{state?.total_heat_pct?.toFixed(1)}%</span></span>
          <span className="text-label">NAV: <span className="text-white">₹{state?.total_equity?.toLocaleString('en-IN')}</span></span>
        </div>
      </div>
    </header>
  );
};

const NavTabs = ({ activeTab, setActiveTab }: { activeTab: number; setActiveTab: (i: number) => void }) => {
  const tabs = ['UNIVERSE', 'PIPELINE', 'POSITIONS', 'PERFORMANCE', 'LEARNING', 'BACKTEST'];

  return (
    <nav className="terminal-nav">
      {tabs.map((tab, i) => (
        <button
          key={tab}
          onClick={() => setActiveTab(i)}
          className={`px-4 h-full text-[11px] border-r border-[#111] hover:text-white ${activeTab === i ? 'text-orange border-b-2 border-b-orange' : 'text-label'}`}
        >
          <span className="text-dim mr-1">[{i + 1}]</span> {tab}
        </button>
      ))}
    </nav>
  );
};

const CommandBar = ({ onBacktest }: { onBacktest: () => void }) => {
  return (
    <footer className="terminal-footer">
      <span className="command-prompt">CMD{'>'}</span>
      <input type="text" className="command-input" placeholder="Enter command..." autoFocus />
      <div className="flex gap-4 text-dim text-[10px] ml-4">
        <span>F1:HELP</span>
        <span>F5:REFRESH</span>
        <button onClick={onBacktest} className="hover:text-orange transition-colors">F10:BACKTEST</button>
        <span>F9:MODE</span>
      </div>
    </footer>
  );
};

const SignalPipelineFunnel = () => {
  const [stages] = useState<FunnelStage[]>([
    { name: 'UNIVERSE SCAN', count: 20, wk: 20, mo: 20 },
    { name: 'RAW SIGNALS',   count: 12, wk: 89, mo: 312 },
    { name: 'MECHANISM',     count: 8,  wk: 61, mo: 218 },
    { name: 'NF QUALITY',    count: 6,  wk: 47, mo: 172 },
    { name: 'PORTFOLIO',     count: 4,  wk: 31, mo: 114 },
    { name: 'ORDERS',        count: 2,  wk: 18, mo: 67 },
  ]);

  const universeSize = 20;

  const renderFunnelBar = (count: number) => {
    const width = (count / universeSize) * 100;
    return (
      <div className="w-24 h-2 bg-[#111] relative">
        <div 
          className="absolute h-full bg-gradient-to-r from-positive to-orange" 
          style={{ width: `${width}%`, backgroundColor: 'var(--text-info)' }}
        />
      </div>
    );
  };

  return (
    <div className="terminal-panel h-[220px]">
      <PanelHeader title="SIGNAL PIPELINE" right="TODAY    WK     MO" />
      <div className="panel-content p-0">
        <table className="w-full text-[10px]">
          <tbody>
            {stages.map((s, i) => (
              <tr key={i} className="border-b border-[#111] h-[28px] hover:bg-hover cursor-pointer">
                <td className="px-2 text-label">{s.name}</td>
                <td className="px-2">{renderFunnelBar(s.count)}</td>
                <td className="px-2 text-white text-right">{s.count}</td>
                <td className="px-2 text-positive text-right">{Math.round((s.count / (stages[i-1]?.count || s.count)) * 100)}%</td>
                <td className="px-2 text-dim text-right">{s.wk}</td>
                <td className="px-2 text-dim text-right">{s.mo}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="px-2 py-1 flex items-end gap-0.5 mt-1 border-t border-[#111] h-8">
            <div className="text-[9px] text-dim mr-2">09-15H</div>
            {[2, 4, 8, 3, 2, 5, 2].map((h, i) => (
                <div key={i} className="bg-dim w-3" style={{ height: `${h * 2}px` }} />
            ))}
        </div>
      </div>
    </div>
  );
};

const OpenPositions = ({ positions }: { positions?: BackendPosition[] }) => {
  const displayPositions = positions && positions.length > 0 ? positions.map(p => ({
    symbol: p.symbol,
    mech: p.mechanism || 'TIL',
    entry: p.entry_price,
    curr: p.current_price,
    pnl: ((p.current_price / p.entry_price) - 1) * 100,
    r: p.risk_at_risk ? (p.current_price - p.entry_price) / (p.entry_price - (p.entry_price - p.risk_at_risk)) : 0,
    mae: 0,
    days: 0,
    stat: 'OK'
  })) : [];

  return (
    <div className="terminal-panel h-[340px]">
      <PanelHeader title={`OPEN POSITIONS (${displayPositions.length})`} />
      <div className="panel-content p-0">
        <table className="w-full text-left">
          <thead className="bg-panel-header text-label text-[10px] sticky top-0">
            <tr>
              <th className="px-2 py-1 font-normal">SYM</th>
              <th className="px-2 py-1 font-normal">MECH</th>
              <th className="px-2 py-1 font-normal text-right">CURR</th>
              <th className="px-2 py-1 font-normal text-right">P&L</th>
              <th className="px-2 py-1 font-normal text-right">R</th>
              <th className="px-2 py-1 font-normal text-right">MAE</th>
              <th className="px-2 py-1 font-normal text-center">STAT</th>
            </tr>
          </thead>
          <tbody className="text-[11px]">
            {displayPositions.map((p, i) => (
              <tr key={i} className={`border-b border-[#111] hover:bg-hover cursor-pointer ${p.stat === 'INV' ? 'bg-warning' : ''}`}>
                <td className="px-2 py-1 text-white font-bold">{p.symbol}</td>
                <td className="px-2 py-1 text-info text-[10px]">{p.mech}</td>
                <td className="px-2 py-1 text-right text-white">{p.curr.toFixed(2)}</td>
                <td className={`px-2 py-1 text-right ${p.pnl > 0 ? 'text-positive' : 'text-negative'}`}>
                  {p.pnl > 0 ? '+' : ''}{p.pnl}%
                </td>
                <td className={`px-2 py-1 text-right ${p.r > 0 ? 'text-positive' : 'text-negative'} ${Math.abs(p.r) > 1 ? 'font-bold' : ''}`}>
                  {p.r > 0 ? '+' : ''}{p.r}
                </td>
                <td className={`px-2 py-1 text-right ${p.mae > 0.5 ? 'text-warning' : 'text-label'}`}>{p.mae}</td>
                <td className={`px-2 py-1 text-center ${p.stat === 'OK' ? 'text-positive' : 'text-warning'}`}>
                  {p.stat === 'OK' ? '● OK' : '⚠ INV'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-2 py-1 text-[10px] text-dim border-t border-primary">
        {displayPositions.length > 0 ? `TOTAL POSITIONS: ${displayPositions.length}` : 'NO OPEN POSITIONS'}
      </div>
    </div>
  );
};

const EquityCurve = ({ data }: { data?: PerformancePoint[] }) => {
    const hasData = data && data.length > 1;

    // Convert data to points for SVG polylines: x (0-100), y (0-50)
    let points = "";
    if (hasData) {
        points = data.map((pt, i) => {
            const x = (i / (data.length - 1)) * 100;
            const minEquity = Math.min(...data.map(d => d.equity));
            const maxEquity = Math.max(...data.map(d => d.equity));
            const range = maxEquity - minEquity || 1;
            const y = 50 - ((pt.equity - minEquity) / range * 40 + 5);
            return `${x},${y}`;
        }).join(' ');
    }

    const pathD = hasData ? `M 0 50 L ${points} L 100 50 Z` : "";

    return (
        <div className="terminal-panel h-64">
            <PanelHeader title="EQUITY CURVE" right={`LAST: ₹${hasData ? data[data.length-1].equity.toLocaleString() : '--'}`} />
            <div className="panel-content flex items-center justify-center">
                {!hasData ? (
                    <div className="text-center text-dim text-[11px]">
                        <p className="mb-2">NO EQUITY DATA AVAILABLE</p>
                        <p className="text-[9px]">Run a backtest to populate the equity curve.</p>
                    </div>
                ) : (
                    <div className="w-full h-full relative border-l border-b border-[#333] m-4">
                        <svg className="w-full h-full" viewBox="0 0 100 50" preserveAspectRatio="none">
                            <defs>
                                <linearGradient id="equityGrad" x1="0" x2="0" y1="0" y2="1">
                                    <stop offset="0%" stopColor="var(--text-positive)" stopOpacity="0.3" />
                                    <stop offset="100%" stopColor="var(--text-positive)" stopOpacity="0.0" />
                                </linearGradient>
                            </defs>
                            <path d={pathD} fill="url(#equityGrad)" />
                            <polyline
                                fill="none"
                                stroke="var(--text-positive)"
                                strokeWidth="0.5"
                                points={points}
                                strokeLinejoin="round"
                                strokeLinecap="round"
                            />
                            <line x1="0" y1="40" x2="100" y2="40" stroke="#222" strokeWidth="0.2" strokeDasharray="1,1" />
                            <line x1="0" y1="30" x2="100" y2="30" stroke="#222" strokeWidth="0.2" strokeDasharray="1,1" />
                            <line x1="0" y1="20" x2="100" y2="20" stroke="#222" strokeWidth="0.2" strokeDasharray="1,1" />
                            <line x1="0" y1="10" x2="100" y2="10" stroke="#222" strokeWidth="0.2" strokeDasharray="1,1" />
                        </svg>
                        <div className="absolute bottom-[-15px] left-0 text-[8px] text-dim">START</div>
                        <div className="absolute bottom-[-15px] left-1/4 text-[8px] text-dim"></div>
                        <div className="absolute bottom-[-15px] left-1/2 text-[8px] text-dim">MID</div>
                        <div className="absolute bottom-[-15px] right-0 text-[8px] text-dim">END</div>
                    </div>
                )}
            </div>
        </div>
    );
};

const PerformanceSummaryPanel = ({ summary }: { summary?: PerformanceSummary }) => {
    if (!summary) return null;
    return (
        <div className="grid grid-cols-5 gap-2 mb-2">
            {[
                { label: 'TOTAL P&L', value: `${summary.total_pnl_pct}%`, color: summary.total_pnl_pct >= 0 ? 'text-positive' : 'text-negative' },
                { label: 'NET PROFIT', value: `₹${summary.net_profit?.toLocaleString() || 0}`, color: (summary.net_profit || 0) >= 0 ? 'text-positive' : 'text-negative' },
                { label: 'CALC BROKERAGE', value: `₹${summary.brokerage?.toLocaleString() || 0}`, color: 'text-warning' },
                { label: 'SHARPE RATIO', value: summary.sharpe_ratio?.toFixed(2) || '0.00', color: (summary.sharpe_ratio || 0) >= 1 ? 'text-positive' : 'text-white' },
                { label: 'MAX DRAWDOWN', value: `${summary.max_drawdown_pct}%`, color: 'text-negative' },
                { label: 'CAGR', value: `${summary.cagr || 0}%`, color: 'text-info' },
                { label: 'WIN RATE', value: `${summary.win_rate}%`, color: 'text-white' },
                { label: 'EXPECTANCY', value: `₹${summary.expectancy?.toLocaleString() || 0}`, color: 'text-white' },
                { label: 'PROFIT FACTOR', value: summary.profit_factor, color: 'text-white' },
                { label: 'TOTAL TRADES', value: summary.total_trades || 0, color: 'text-white' },
            ].map((stat, i) => (
                <div key={i} className="terminal-panel p-2 flex flex-col items-center justify-center">
                    <span className="text-[9px] text-label">{stat.label}</span>
                    <span className={`text-sm font-bold ${stat.color}`}>{stat.value}</span>
                </div>
            ))}
        </div>
    );
};

const MechanismPerformance = () => {
    return (
        <div className="terminal-panel h-64">
             <PanelHeader title="MECHANISM PERFORMANCE" right="LIVE DATA" />
             <div className="panel-content px-2 py-2 flex items-center justify-center h-full">
                <div className="text-center text-dim text-[11px]">
                    <p className="mb-2">NO MECHANISM DATA AVAILABLE</p>
                    <p className="text-[9px]">Run a backtest with trades to populate mechanism statistics.</p>
                </div>
             </div>
        </div>
    );
};

const ActivityLog = () => {
    const now = new Date();
    const fmt = (offset: number) => {
        const d = new Date(now.getTime() - offset * 60000);
        return d.toLocaleTimeString('en-IN', { hour12: false });
    };

    return (
        <div className="terminal-panel h-[340px]">
            <PanelHeader title="TERMINAL ACTIVITY LOG" right="SYS_MESSAGES" />
            <div className="panel-content font-mono text-[10px] leading-relaxed">
                <div className="flex gap-2 mb-1">
                    <span className="text-dim">[{fmt(0)}]</span>
                    <span className="text-label">SYSTEM READY. AWAITING COMMANDS.</span>
                </div>
                <div className="mt-2 text-dim">... monitoring events ...</div>
            </div>
        </div>
    );
};

const RiskDistribution = () => {
    return (
        <div className="terminal-panel h-64">
            <PanelHeader title="RISK DISTRIBUTION" right="BY SECTOR" />
            <div className="panel-content px-4 py-4 flex flex-col justify-between">
                {[
                    { name: 'BFSI', value: 48, color: 'bg-info' },
                    { name: 'TECH', value: 31, color: 'bg-positive' },
                    { name: 'ENGY', value: 21, color: 'bg-orange' },
                ].map((s, i) => (
                    <div key={i} className="mb-4">
                        <div className="flex justify-between text-[11px] mb-1">
                            <span className="text-white">{s.name}</span>
                            <span className="text-dim">₹{(s.value * 1240).toLocaleString()} <span className="text-white">({s.value}%)</span></span>
                        </div>
                        <div className="w-full h-1.5 bg-[#111]">
                            <div className={`h-full ${s.color}`} style={{ width: `${s.value}%` }} />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default function VektorTerminal() {
  const [activeTab, setActiveTab] = React.useState(0);
  const [portfolio, setPortfolio] = React.useState<PortfolioState | null>(null);
  const [performance, setPerformance] = React.useState<PerformancePoint[]>([]);
  const [perfSummary, setPerfSummary] = React.useState<PerformanceSummary | null>(null);
  const [topStocks, setTopStocks] = React.useState<Stock[]>([]);
  
  // Backtest state
  const [btSymbols, setBtSymbols] = React.useState('RELIANCE,HDFCBANK,TCS');
  const [btDynamic, setBtDynamic] = React.useState(true);
  const [btStart, setBtStart] = React.useState('2026-03-15');
  const [btEnd, setBtEnd] = React.useState('2026-03-17');
  const [btTimeframe, setBtTimeframe] = React.useState('5m');
  const [btCapital, setBtCapital] = React.useState(100000);
  const [btLoading, setBtLoading] = React.useState(false);
  const [btProgress, setBtProgress] = React.useState(0);
  const [isBtActive, setIsBtActive] = React.useState(false);
  const [isBtBackfilling, setIsBtBackfilling] = React.useState(false);
  const [btBackfillProgress, setBtBackfillProgress] = React.useState(0);
  const [terminalMode, setTerminalMode] = React.useState<'LIVE' | 'BACKTEST'>('LIVE');
  const [currentRunId, setCurrentRunId] = React.useState<string | null>(null);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

  // Persistence for terminal mode
  React.useEffect(() => {
    const savedMode = localStorage.getItem('vektor_terminal_mode');
    if (savedMode === 'LIVE' || savedMode === 'BACKTEST') {
        setTerminalMode(savedMode);
    }
  }, []);

  React.useEffect(() => {
    localStorage.setItem('vektor_terminal_mode', terminalMode);
  }, [terminalMode]);

  React.useEffect(() => {
    const fetchData = async () => {
      try {
        const portRes = await fetch(`${API_URL}/api/v1/til/portfolio`);
        if (portRes.ok) setPortfolio(await portRes.json());

        const perfUrl = currentRunId 
            ? `${API_URL}/api/v1/til/performance?run_id=${currentRunId}`
            : `${API_URL}/api/v1/til/performance`;
            
        const perfRes = await fetch(perfUrl);
        if (perfRes.ok) {
            const data: PerformanceData = await perfRes.json();
            setPerformance(data.points || []);
            setPerfSummary(data.summary || null);
        }

        const topRes = await fetch(`${API_URL}/api/v1/market/top-performers?limit=50`);
        if (topRes.ok) {
            const data = await topRes.json();
            
            // Simple string hash for deterministic confidence
            const getHash = (str: string) => {
                let hash = 0;
                for (let i = 0; i < str.length; i++) {
                    hash = ((hash << 5) - hash) + str.charCodeAt(i);
                    hash |= 0;
                }
                return Math.abs(hash);
            };

            setTopStocks(data.map((s: { name: string; change_pct: number }) => {
                const detRand = (getHash(s.name) % 400) / 10; // 0.0 to 39.9
                return {
                    symbol: s.name,
                    conf: 50 + detRand,
                    mech: 'SCAN',
                    dir: s.change_pct > 0 ? 'LONG' : 'SHORT',
                    regime: 'TRU',
                    action: 'PROC'
                };
            }));
        }

        const statusRes = await fetch(`${API_URL}/api/v1/til/backtest/status`);
        if (statusRes.ok) {
            const status = await statusRes.json();
            setIsBtActive(status.is_running);
            setIsBtBackfilling(status.is_backfilling);
            setBtBackfillProgress(status.backfill_progress);
            setBtProgress(status.progress);
            if (status.run_id && status.is_running) {
                setCurrentRunId(status.run_id);
            }
            if (!status.is_running && btLoading) {
                setBtLoading(false);
            }
        }
      } catch (err) {
        console.error("Fetch error:", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [API_URL, btLoading, currentRunId]);

  const startSimulation = async () => {
      setBtLoading(true);
      try {
          const res = await fetch(`${API_URL}/api/v1/til/backtest`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                  symbols: btDynamic ? [] : btSymbols.split(',').map(s => s.trim()),
                  start_date: btStart,
                  end_date: btEnd,
                  timeframe: btTimeframe,
                  initial_capital: btCapital
              })
          });
          if (res.ok) {
              const data = await res.json();
              setActiveTab(3); // Switch to PERFORMANCE
              setIsBtActive(true);
              setBtProgress(0);
              if (data.run_id) {
                  setCurrentRunId(data.run_id);
              }
          } else {
              const data = await res.json();
              alert(data.detail || "Failed to start simulation.");
          }
      } catch {
          alert("Error connecting to TIL backend.");
      } finally {
          setBtLoading(false);
      }
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 0: // UNIVERSE
        return (
          <>
            <div className="col-span-4">
              <SignalPipelineFunnel />
            </div>
            <div className="col-span-8">
              <OpenPositions positions={portfolio?.open_positions} />
            </div>
            <div className="col-span-12">
               <ActivityLog />
            </div>
          </>
        );
      case 1: // PIPELINE
        return (
          <>
            <div className="col-span-12">
                <SignalPipelineFunnel />
            </div>
            <div className="col-span-12 mt-1">
                <ActivityLog />
            </div>
          </>
        );
      case 2: // POSITIONS
        return (
          <>
            <div className="col-span-12">
                <OpenPositions positions={portfolio?.open_positions} />
            </div>
            <div className="col-span-12 mt-1">
                <ActivityLog />
            </div>
          </>
        );
      case 3: // PERFORMANCE
        return (
          <>
            <div className="col-span-12">
                <PerformanceSummaryPanel summary={perfSummary || undefined} />
            </div>
            <div className="col-span-8">
              <EquityCurve data={performance} />
            </div>
            <div className="col-span-4">
              <MechanismPerformance />
            </div>
            <div className="col-span-12 mt-1">
                <RiskDistribution />
            </div>
          </>
        );
      case 5: // BACKTEST
        return (
            <div className="col-span-12 terminal-panel p-4">
                <PanelHeader title="HISTORICAL BACKTEST ENGINE" />
                <div className="mt-4 flex flex-col gap-4 max-w-md">
                    <div className="flex items-center gap-2 mb-2">
                        <input 
                            type="checkbox" 
                            id="btDynamic" 
                            checked={btDynamic}
                            onChange={(e) => setBtDynamic(e.target.checked)}
                            className="w-3 h-3 accent-orange"
                        />
                        <label htmlFor="btDynamic" className="text-white text-[10px] cursor-pointer">DYNAMIC UNIVERSE SELECTION (SIGNAL GENERATOR)</label>
                    </div>
                    {!btDynamic && (
                        <div className="flex flex-col gap-1">
                            <label className="text-label text-[10px]">SYMBOLS (COMMA SEPARATED)</label>
                            <input 
                                value={btSymbols}
                                onChange={(e) => setBtSymbols(e.target.value)}
                                className="bg-black border border-[#333] text-white p-2 text-sm focus:border-orange outline-none" 
                                placeholder="RELIANCE,HDFCBANK,TCS" 
                            />
                        </div>
                    )}
                    <div className="grid grid-cols-2 gap-4">
                        <div className="flex flex-col gap-1">
                            <label className="text-label text-[10px]">TIME FRAME</label>
                            <select 
                                value={btTimeframe}
                                onChange={(e) => setBtTimeframe(e.target.value)}
                                className="bg-black border border-[#333] text-white p-2 text-sm focus:border-orange outline-none"
                            >
                                <option value="1m">1 MINUTE</option>
                                <option value="5m">5 MINUTES</option>
                                <option value="15m">15 MINUTES</option>
                                <option value="1h">1 HOUR</option>
                                <option value="1d">1 DAY</option>
                            </select>
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-label text-[10px]">INITIAL CAPITAL (INR)</label>
                            <input 
                                type="number" 
                                value={btCapital}
                                onChange={(e) => setBtCapital(Number(e.target.value))}
                                className="bg-black border border-[#333] text-white p-2 text-sm focus:border-orange outline-none" 
                            />
                        </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div className="flex flex-col gap-1">
                            <label className="text-label text-[10px]">START DATE</label>
                            <input 
                                type="date" 
                                value={btStart}
                                onChange={(e) => setBtStart(e.target.value)}
                                className="bg-black border border-[#333] text-white p-2 text-sm focus:border-orange outline-none" 
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-label text-[10px]">END DATE</label>
                            <input 
                                type="date" 
                                value={btEnd}
                                onChange={(e) => setBtEnd(e.target.value)}
                                className="bg-black border border-[#333] text-white p-2 text-sm focus:border-orange outline-none" 
                            />
                        </div>
                    </div>
                    <button 
                        onClick={startSimulation}
                        disabled={btLoading}
                        className="bg-orange hover:bg-orange/80 text-black font-bold py-2 mt-2 transition-colors disabled:opacity-50"
                    >
                        {btLoading ? 'STARTING...' : 'START SIMULATION'}
                    </button>
                </div>
            </div>
        );
      default:
        return (
          <div className="col-span-12 flex items-center justify-center text-dim h-64 border border-dashed border-[#333]">
            SECTION UNDER CONSTRUCTION
          </div>
        );
    }
  };

  return (
    <div className="alpha-terminal">
      <StatusBar 
        state={portfolio} 
        isBtActive={isBtActive} 
        isBtBackfilling={isBtBackfilling}
        btProgress={btProgress} 
        btBackfillProgress={btBackfillProgress}
        terminalMode={terminalMode}
        setTerminalMode={setTerminalMode}
      />
      <NavTabs activeTab={activeTab} setActiveTab={setActiveTab} />
      <div className="terminal-main">
        <aside className="left-rail">
          <UniverseMonitor stocks={topStocks} />
          <div className="border-t border-primary">
            <NoiseFilterState />
          </div>
        </aside>
        <main className="content-area">
          {renderTabContent()}
        </main>
      </div>
      <CommandBar onBacktest={() => setActiveTab(5)} />
    </div>
  );
}
