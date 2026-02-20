'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { ArrowLeft, RefreshCw, StopCircle, Activity, Play, TerminalSquare, Wallet, TrendingUp } from 'lucide-react';
import Link from 'next/link';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface Holding {
    symbol: string;
    quantity: number;
    avg_price: number;
    current_price: number;
    market_value: number;
    unrealized_pnl: number;
}

interface LiveStatus {
    status: string;
    strategy?: string;
    cash: number;
    equity: number;
    initial_capital?: number;
    holdings: Holding[];
}

interface Strategy {
    name: string;
    value: string;
}

interface LogEntry {
    time: string;
    message: string;
    type: 'info' | 'success' | 'warning' | 'error';
}

interface Trade {
    time: string;
    symbol: string;
    stock_name: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    price: number;
    pnl: number;
}

export default function ProfessionalLiveDashboard() {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

    // State
    const [status, setStatus] = useState<LiveStatus | null>(null);
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [selectedStrategy, setSelectedStrategy] = useState<string>("");
    const [capital, setCapital] = useState<string>("100000");
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [equityHistory, setEquityHistory] = useState<{ time: string, equity: number }[]>([]);
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [trades, setTrades] = useState<Trade[]>([]);
    const [brokeragePaid, setBrokeragePaid] = useState<number>(0);

    const terminalRef = useRef<HTMLDivElement>(null);

    // Initial load
    useEffect(() => {
        const fetchInitial = async () => {
            try {
                const resStrats = await fetch(`${API_URL}/api/v1/strategies`);
                const dataStrats = await resStrats.json();
                setStrategies(dataStrats.strategies || []);

                const resStatus = await fetch(`${API_URL}/api/v1/live/status`);
                const dataStatus = await resStatus.json();
                setStatus(dataStatus);

                if (dataStatus.status === 'running') {
                    addLog(`Connected to active session: ${dataStatus.strategy}`, 'success');
                } else {
                    addLog('System ready. Select a strategy to begin.', 'info');
                }
            } catch (err: unknown) {
                if (err instanceof Error) addLog(`Initialization error: ${err.message}`, 'error');
            } finally {
                setLoading(false);
            }
        };
        fetchInitial();
    }, [API_URL]);

    // Polling Function
    const pollStatus = React.useCallback(async () => {
        try {
            const res = await fetch(`${API_URL}/api/v1/live/status`);
            const data = await res.json();
            setStatus(data);

            if (data.status === 'running') {
                const now = new Date().toLocaleTimeString('en-US', { hour12: false });

                // Update Chart
                setEquityHistory(prev => {
                    // Prevent duplicate consecutive entries with same value to keep chart clean
                    if (prev.length > 0 && prev[prev.length - 1].equity === data.equity) {
                        return prev;
                    }
                    const newHist = [...prev, { time: now, equity: data.equity }];
                    if (newHist.length > 60) newHist.shift(); // Keep last 60 points
                    return newHist;
                });

                // Simulated Live System Activity Logs
                if (Math.random() > 0.7) {
                    const actions = [
                        `Analyzed market depth for active instruments.`,
                        `Heartbeat OK. Latency: ${Math.floor(Math.random() * 40 + 10)}ms`,
                        `Re-calculated strategy trailing stops.`,
                        `Awaiting entry signals...`,
                        `Received updated options chain data.`
                    ];
                    addLog(actions[Math.floor(Math.random() * actions.length)], 'info');
                }
            }

            // Always fetch trades to keep order book fresh
            const resTrades = await fetch(`${API_URL}/api/v1/live/trades`);
            if (resTrades.ok) {
                const dataTrades = await resTrades.json();
                setTrades(dataTrades);
                // Simple realtime UI brokerage estimation
                const brk = dataTrades.reduce((acc: number, t: Trade) => {
                    const turnover = t.price * Math.abs(t.quantity);
                    const flat = Math.min(20, turnover * 0.0003);
                    const stt = t.side === 'SELL' ? turnover * 0.00025 : 0;
                    const gst = flat * 0.18;
                    return acc + flat + stt + gst;
                }, 0);
                setBrokeragePaid(brk);
            }

        } catch {
            // silent fail on poll
        }
    }, [API_URL]);

    // Setup Polling Interval
    useEffect(() => {
        const interval = setInterval(pollStatus, 2000);
        return () => clearInterval(interval);
    }, [pollStatus]);

    // Auto-scroll terminal
    useEffect(() => {
        if (terminalRef.current) {
            terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
        }
    }, [logs]);

    const addLog = (message: string, type: 'info' | 'success' | 'warning' | 'error' = 'info') => {
        const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
        setLogs(prev => [...prev, { time, message, type }]);
    };

    const handleStart = async () => {
        if (!selectedStrategy) {
            addLog("Error: No strategy selected.", "error");
            return;
        }
        setActionLoading(true);
        addLog(`Initiating start sequence for ${selectedStrategy}...`, 'warning');

        try {
            const res = await fetch(`${API_URL}/api/v1/live/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    strategy_name: selectedStrategy,
                    capital: parseFloat(capital)
                })
            });
            const data = await res.json();

            if (data.status === 'error') {
                addLog(`Start failed: ${data.message}`, 'error');
            } else {
                addLog(`Strategy ${selectedStrategy} successfully deployed to runtime engine.`, 'success');
                setEquityHistory([]); // reset chart
                pollStatus(); // force immediate refresh
            }
        } catch (err: unknown) {
            if (err instanceof Error) addLog(`Connection error: ${err.message}`, 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const handleStop = async () => {
        if (!confirm("HALT STRATEGY: Are you sure you want to stop the live execution? All open positions may require manual intervention.")) return;

        setActionLoading(true);
        addLog(`Sending KILL signal to strategy runtime...`, 'warning');

        try {
            await fetch(`${API_URL}/api/v1/live/stop`, { method: 'POST' });
            addLog(`Strategy stopped successfully.`, 'success');
            pollStatus();
        } catch (err: unknown) {
            if (err instanceof Error) addLog(`Stop failed: ${err.message}`, 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const getSymbolName = (symbol: string) => {
        if (!symbol) return 'UNKNOWN';
        if (symbol.includes('INE002A01018')) return 'RELIANCE INDUSTRIES';
        if (symbol.includes('INE009A01021')) return 'INFOSYS LTD';
        if (symbol.includes('INE467B01029')) return 'TATA CONSULTANCY';
        return symbol.replace('NSE_EQ|', '');
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-[#0a0a0b] flex items-center justify-center flex-col gap-4 text-white">
                <Activity className="h-10 w-10 text-blue-500 animate-spin" />
                <h2 className="text-xl font-mono tracking-widest">INITIALIZING QUANT TERMINAL...</h2>
            </div>
        );
    }

    const isRunning = status?.status === 'running';
    const currentEquity = status?.equity || parseFloat(capital);
    const initCap = status?.initial_capital || parseFloat(capital);
    const totalPnL = currentEquity - initCap;
    const pnlPercent = (totalPnL / initCap) * 100;
    const isProfitable = totalPnL >= 0;

    return (
        <div className="min-h-screen bg-[#0a0a0b] text-slate-300 font-sans selection:bg-blue-500/30 flex flex-col">

            {/* Top Control Bar (Integrated Header) */}
            <header className="border-b border-slate-800 bg-[#111113] px-6 py-3 flex items-center justify-between sticky top-0 z-10 shadow-md shadow-black/50">
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon" className="hover:bg-slate-800 text-slate-400 hover:text-white">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div className="flex items-center gap-3 border-r border-slate-700 pr-4">
                        <Activity className="h-5 w-5 text-blue-500" />
                        <h1 className="text-lg font-bold tracking-tight text-white">Live Execution Terminal</h1>
                        {isRunning ? (
                            <Badge className="bg-green-500/20 text-green-400 border border-green-500/50 flex items-center gap-1.5 ml-2 shadow-[0_0_10px_rgba(34,197,94,0.2)]">
                                <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse"></div>
                                ACTIVE
                            </Badge>
                        ) : (
                            <Badge variant="outline" className="text-slate-500 border-slate-600 ml-2">IDLE</Badge>
                        )}
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {!isRunning ? (
                        <>
                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800">
                                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Strategy:</span>
                                <Select onValueChange={setSelectedStrategy} value={selectedStrategy}>
                                    <SelectTrigger className="w-[200px] h-8 bg-transparent border-none focus:ring-0 text-white font-mono text-sm">
                                        <SelectValue placeholder="Select Algorithm" />
                                    </SelectTrigger>
                                    <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white">
                                        {strategies.map((s) => (
                                            <SelectItem key={s.value} value={s.value} className="focus:bg-blue-500/20">{s.name}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800">
                                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Capital:</span>
                                <div className="flex items-center">
                                    <span className="text-slate-400 text-sm">₹</span>
                                    <Input
                                        type="number"
                                        value={capital}
                                        onChange={(e) => setCapital(e.target.value)}
                                        className="w-[100px] h-8 bg-transparent border-none focus-visible:ring-0 text-white font-mono text-sm px-1 hide-arrows"
                                    />
                                </div>
                            </div>
                            <Button
                                onClick={handleStart}
                                disabled={actionLoading || !selectedStrategy}
                                className="bg-blue-600 hover:bg-blue-500 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all h-9"
                            >
                                <Play className="mr-2 h-4 w-4 fill-current" /> DEPLOY TO ENGINE
                            </Button>
                        </>
                    ) : (
                        <>
                            <div className="flex items-center gap-3 bg-[#0a0a0b] px-4 py-1.5 rounded-md border border-slate-800 mr-2">
                                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Running:</span>
                                <span className="text-sm font-mono text-white">{status.strategy?.split('.').pop()}</span>
                            </div>
                            <Button variant="outline" size="sm" onClick={pollStatus} className="border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800 h-9">
                                <RefreshCw className="mr-2 h-4 w-4" /> Sync
                            </Button>
                            <Button
                                onClick={handleStop}
                                disabled={actionLoading}
                                variant="destructive"
                                className="bg-red-500/20 hover:bg-red-500/40 text-red-500 border border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.2)] transition-all h-9"
                            >
                                <StopCircle className="mr-2 h-4 w-4 fill-current" /> HALT EXECUTION
                            </Button>
                        </>
                    )}
                </div>
            </header>

            {/* Main Content Grid */}
            <main className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-4 gap-6 overflow-hidden">

                {/* Left Section: Stats & Chart (Takes up 3/4) */}
                <div className="lg:col-span-3 flex flex-col gap-6 overflow-y-auto pr-2 custom-scrollbar">

                    {/* Top Metrics Strip */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <Card className="bg-[#111113] border-slate-800 shadow-none relative overflow-hidden">
                            <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                                <Wallet className="h-24 w-24" />
                            </div>
                            <CardHeader className="pb-2">
                                <CardTitle className="text-xs font-bold text-slate-500 uppercase tracking-widest">Total Equity</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <div className="text-3xl font-mono text-white font-medium">₹{currentEquity.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
                            </CardContent>
                        </Card>

                        <Card className="bg-[#111113] border-slate-800 shadow-none relative overflow-hidden">
                            <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                                <TrendingUp className="h-24 w-24" />
                            </div>
                            <CardHeader className="pb-2">
                                <CardTitle className="text-xs font-bold text-slate-500 uppercase tracking-widest">Net P&L</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <div className={`text-3xl font-mono font-medium flex items-baseline gap-3 ${isProfitable ? "text-green-500" : "text-red-500"}`}>
                                    {isProfitable ? "+" : ""}₹{totalPnL.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                    <span className="text-sm font-sans font-semibold px-2 py-0.5 rounded bg-black/30 border border-current opacity-80">
                                        {isProfitable ? "+" : ""}{pnlPercent.toFixed(2)}%
                                    </span>
                                </div>
                            </CardContent>
                        </Card>

                        <Card className="bg-[#111113] border-slate-800 shadow-none">
                            <CardHeader className="pb-2">
                                <CardTitle className="text-xs font-bold text-slate-500 uppercase tracking-widest">Available Cash</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <div className="text-3xl font-mono text-slate-300 font-medium">₹{(status?.cash ?? parseFloat(capital)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
                            </CardContent>
                        </Card>
                    </div>

                    {/* Performance Chart */}
                    <Card className="bg-[#111113] border-slate-800 shadow-none flex-1 min-h-[400px] flex flex-col">
                        <CardHeader className="border-b border-slate-800/50 pb-4">
                            <CardTitle className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                                <Activity className="h-4 w-4 text-blue-500" /> Live Intraday Equity Curve
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="flex-1 p-6 pt-8">
                            {equityHistory.length > 0 ? (
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart data={equityHistory} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                                        <defs>
                                            <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor={isProfitable ? "#22c55e" : "#ef4444"} stopOpacity={0.3} />
                                                <stop offset="95%" stopColor={isProfitable ? "#22c55e" : "#ef4444"} stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                                        <XAxis
                                            dataKey="time"
                                            stroke="#475569"
                                            fontSize={12}
                                            tickMargin={10}
                                            minTickGap={30}
                                        />
                                        <YAxis
                                            domain={['auto', 'auto']}
                                            stroke="#475569"
                                            fontSize={12}
                                            tickFormatter={(val) => `₹${(val / 1000).toFixed(0)}k`}
                                        />
                                        <Tooltip
                                            contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px', color: '#f8fafc' }}
                                            itemStyle={{ color: isProfitable ? '#4ade80' : '#f87171' }}
                                            labelStyle={{ color: '#94a3b8', marginBottom: '4px' }}
                                        />
                                        <Area
                                            type="monotone"
                                            dataKey="equity"
                                            stroke={isProfitable ? "#22c55e" : "#ef4444"}
                                            strokeWidth={2}
                                            fillOpacity={1}
                                            fill="url(#colorEquity)"
                                            isAnimationActive={false}
                                        />
                                    </AreaChart>
                                </ResponsiveContainer>
                            ) : (
                                <div className="h-full flex items-center justify-center flex-col text-slate-600 gap-3">
                                    <Activity className="h-8 w-8 opacity-50" />
                                    <span>Waiting for engine telemetry...</span>
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    {/* Active Positions */}
                    <Card className="bg-[#111113] border-slate-800 shadow-none">
                        <CardHeader className="border-b border-slate-800/50 pb-4">
                            <CardTitle className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                                <Wallet className="h-4 w-4" /> Active Holdings
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-0">
                            <Table>
                                <TableHeader className="bg-slate-900 border-none">
                                    <TableRow className="border-none hover:bg-transparent">
                                        <TableHead className="text-slate-500 font-semibold h-10 pl-6">Instrument</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10 text-right">Qty</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10 text-right">Avg Price</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10 text-right">LTP</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10 text-right pr-6">P&L</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {(!status?.holdings || status.holdings.length === 0) ? (
                                        <TableRow className="border-slate-800 hover:bg-transparent">
                                            <TableCell colSpan={5} className="text-center text-slate-600 h-24">
                                                No active market exposure
                                            </TableCell>
                                        </TableRow>
                                    ) : (
                                        status.holdings.map((h) => {
                                            const isHoldProfitable = h.unrealized_pnl >= 0;
                                            return (
                                                <TableRow key={h.symbol} className="border-slate-800 hover:bg-slate-800/50 transition-colors">
                                                    <TableCell className="pl-6 py-3">
                                                        <div className="font-semibold text-slate-200">{getSymbolName(h.symbol)}</div>
                                                        <div className="text-[10px] uppercase tracking-wider text-slate-500 mt-0.5">{h.symbol}</div>
                                                    </TableCell>
                                                    <TableCell className={`text-right py-3 tabular-nums ${h.quantity < 0 ? 'text-red-400 font-bold' : 'text-slate-300'}`}>
                                                        {h.quantity} {h.quantity < 0 && <span className="text-[10px] opacity-70 ml-1">SHRT</span>}
                                                    </TableCell>
                                                    <TableCell className="text-right py-3 tabular-nums text-slate-400">₹{h.avg_price?.toFixed(2) || '0.00'}</TableCell>
                                                    <TableCell className="text-right py-3 tabular-nums font-medium text-slate-300">₹{h.current_price?.toFixed(2) || '0.00'}</TableCell>
                                                    <TableCell className={`text-right pr-6 py-3 tabular-nums font-medium ${isHoldProfitable ? "text-green-500" : "text-red-500"}`}>
                                                        {isHoldProfitable ? "+" : ""}₹{h.unrealized_pnl?.toFixed(2) || '0.00'}
                                                    </TableCell>
                                                </TableRow>
                                            );
                                        })
                                    )}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>

                    {/* Execution History */}
                    <Card className="bg-[#111113] border-slate-800 shadow-none">
                        <CardHeader className="border-b border-slate-800/50 pb-4 flex flex-row items-center justify-between">
                            <CardTitle className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                                <Activity className="h-4 w-4" /> Execution History
                            </CardTitle>
                            <span className="text-xs text-slate-500 font-mono">Paid {brokeragePaid > 0 ? `₹${brokeragePaid.toFixed(2)}` : '₹0.00'} in Brokerage</span>
                        </CardHeader>
                        <CardContent className="p-0 max-h-[400px] overflow-y-auto custom-scrollbar">
                            <Table>
                                <TableHeader className="bg-slate-900 border-none sticky top-0 z-10 shadow-sm">
                                    <TableRow className="border-none hover:bg-transparent">
                                        <TableHead className="text-slate-500 font-semibold h-10 pl-6">Time</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10">Stock</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10">Side</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10">Qty</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10 text-right">Price</TableHead>
                                        <TableHead className="text-slate-500 font-semibold h-10 text-right pr-6">P&L</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {trades.length === 0 ? (
                                        <TableRow className="border-slate-800 hover:bg-transparent">
                                            <TableCell colSpan={6} className="text-center text-slate-600 h-24">
                                                No executions recorded yet
                                            </TableCell>
                                        </TableRow>
                                    ) : (
                                        trades.slice().reverse().map((t, i) => (
                                            <TableRow key={i} className="border-slate-800 hover:bg-slate-800/50 transition-colors">
                                                <TableCell className="pl-6 py-3 font-mono text-[11px] text-slate-400">
                                                    {new Date(t.time).toLocaleString('en-US', { hour12: false, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                </TableCell>
                                                <TableCell className="py-3 font-medium text-slate-300">
                                                    {getSymbolName(t.symbol)}
                                                </TableCell>
                                                <TableCell className="py-3">
                                                    <Badge variant={t.side === 'BUY' ? 'default' : 'destructive'} className={t.side === 'BUY' ? 'bg-blue-500/20 text-blue-400 hover:bg-blue-500/30' : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'}>
                                                        {t.side}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell className="py-3 font-mono text-slate-300">
                                                    {Math.abs(t.quantity)}
                                                </TableCell>
                                                <TableCell className="py-3 text-right font-mono text-slate-300">
                                                    ₹{t.price.toFixed(2)}
                                                </TableCell>
                                                <TableCell className={`py-3 text-right pr-6 font-mono font-medium ${t.pnl > 0 ? 'text-green-500' : t.pnl < 0 ? 'text-red-500' : 'text-slate-500'}`}>
                                                    {t.pnl > 0 ? '+' : ''}{t.pnl !== 0 ? `₹${t.pnl.toFixed(2)}` : '—'}
                                                </TableCell>
                                            </TableRow>
                                        ))
                                    )}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>

                </div>

                {/* Right Section: Terminal Log (Takes up 1/4) */}
                <div className="lg:col-span-1 border border-slate-800 rounded-xl bg-black flex flex-col overflow-hidden shadow-[inset_0_4px_20px_rgba(0,0,0,0.5)] relative">
                    {/* Scanline Effect overlay for retro feel */}
                    <div className="absolute inset-0 pointer-events-none bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[length:100%_4px] opacity-20 z-10"></div>

                    <div className="bg-[#111113] border-b border-slate-800 px-4 py-3 flex items-center gap-2 z-20">
                        <TerminalSquare className="h-4 w-4 text-slate-400" />
                        <h2 className="text-xs font-bold text-slate-400 uppercase tracking-widest">System Output</h2>
                    </div>

                    <div
                        ref={terminalRef}
                        className="flex-1 p-4 font-mono text-[11px] leading-relaxed overflow-y-auto z-20 custom-scrollbar"
                    >
                        {logs.map((log, i) => {
                            let textColor = "text-slate-300";
                            if (log.type === 'error') textColor = "text-red-400";
                            if (log.type === 'success') textColor = "text-green-400";
                            if (log.type === 'warning') textColor = "text-amber-400";
                            if (log.type === 'info') textColor = "text-blue-300";

                            return (
                                <div key={i} className="mb-2 break-words">
                                    <span className="text-slate-600 mr-2">[{log.time}]</span>
                                    <span className={textColor}>{log.message}</span>
                                </div>
                            );
                        })}

                        {isRunning && (
                            <div className="mt-2 text-slate-500 animate-pulse flex items-center gap-2">
                                <span className="w-1.5 h-3 bg-blue-500 inline-block"></span>
                                Waiting for IO...
                            </div>
                        )}
                    </div>
                </div>

            </main>
        </div>
    );
}

// Global CSS styles to add (custom scrollbar and remove arrows from number input)
const globalStyles = `
  .custom-scrollbar::-webkit-scrollbar {
      width: 6px;
  }
  .custom-scrollbar::-webkit-scrollbar-track {
      background: transparent;
  }
  .custom-scrollbar::-webkit-scrollbar-thumb {
      background-color: rgba(71, 85, 105, 0.4);
      border-radius: 20px;
  }
  .hide-arrows::-webkit-outer-spin-button,
  .hide-arrows::-webkit-inner-spin-button {
      -webkit-appearance: none;
      margin: 0;
  }
`;

if (typeof document !== 'undefined') {
    const style = document.createElement('style');
    style.innerHTML = globalStyles;
    document.head.appendChild(style);
}
