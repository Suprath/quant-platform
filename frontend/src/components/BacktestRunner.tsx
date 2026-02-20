"use client";

import React, { useState, useRef, useEffect } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Link from 'next/link';
import {
    Dialog,
    DialogContent,
    DialogTrigger,
} from "@/components/ui/dialog";
import { Play, Loader2, TrendingUp, Terminal as TerminalIcon, BarChart3, Clock, DollarSign, Activity, Settings2, Target, Percent } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface Trade {
    time: string;
    symbol: string;
    side: string;
    quantity: number;
    price: number;
    pnl: number;
}

interface LogEntry {
    time: string;
    message: string;
    type: string;
}

export function BacktestRunner({ strategyName, strategyCode, projectFiles }: { strategyName: string, strategyCode: string, projectFiles?: Record<string, string> }) {
    const [isOpen, setIsOpen] = useState(false);
    const [activeRunId, setActiveRunId] = useState<string | null>(null);
    const [lastRunId, setLastRunId] = useState<string | null>(null);
    const pollIntervalRef = React.useRef<NodeJS.Timeout | null>(null);

    const [isLoading, setIsLoading] = useState(false);
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [isComplete, setIsComplete] = useState(false);

    const [equityHistory, setEquityHistory] = useState<{ time: string, equity: number }[]>([]);
    const [trades, setTrades] = useState<Trade[]>([]);

    const [config, setConfig] = useState({
        symbol: "NSE_EQ|INE002A01018",
        startDate: "2024-01-01",
        endDate: "2024-01-31",
        cash: 100000,
        speed: "fast"
    });

    const [stats, setStats] = useState({
        totalReturn: "0.0%",
        netProfit: 0.0,
        sharpeRatio: 0.0,
        maxDrawdown: "0.0%",
        winRate: "0.0%",
        totalTrades: 0,
        profitFactor: 0.0
    });

    const addLog = (message: string, type: 'info' | 'success' | 'warning' | 'error' = 'info', time?: string) => {
        const t = time || new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
        setLogs(prev => [...prev, { time: t, message, type }]);
    };

    const stopBacktest = async () => {
        if (!activeRunId) return;
        try {
            const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
            await fetch(`${API_URL}/api/v1/backtest/stop/${activeRunId}`, { method: 'POST' });
            addLog("HALT SIGNAL SENT: Backtest stopped by user.", 'error');

            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            setIsLoading(false);
            setIsComplete(true);
            setActiveRunId(null);
        } catch (e) {
            console.error("Failed to stop backtest", e);
            addLog("Failed to stop backtest engine connection.", 'error');
        }
    };

    const runBacktest = async () => {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

        setIsLoading(true);
        setIsComplete(false);
        setActiveRunId(null);
        setLogs([]);
        setEquityHistory([]);
        setTrades([]);
        setStats({
            totalReturn: "0.0%", netProfit: 0.0, sharpeRatio: 0.0,
            maxDrawdown: "0.0%", winRate: "0.0%", totalTrades: 0, profitFactor: 0.0
        });

        addLog(`Initiating engine dispatch for strategy: ${strategyName}`, 'warning');

        try {
            const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

            // 1. Trigger Backtest
            const response = await fetch(`${API_URL}/api/v1/backtest/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    strategy_code: strategyCode,
                    symbol: config.symbol,
                    start_date: config.startDate,
                    end_date: config.endDate,
                    initial_cash: config.cash,
                    strategy_name: strategyName,
                    project_files: projectFiles || undefined,
                    speed: config.speed
                })
            });

            if (!response.ok) throw new Error("Engine rejected the strategy deployment request.");

            const data = await response.json();
            const runId = data.run_id;
            setActiveRunId(runId);
            setLastRunId(runId);
            addLog(`Container provisioned. Run ID: ${runId}`, 'success');
            addLog("Awaiting data stream from runtime engine...", 'info');

            // 2. Poll Logs
            pollIntervalRef.current = setInterval(async () => {
                try {
                    const logRes = await fetch(`${API_URL}/api/v1/backtest/logs/${runId}`);
                    if (logRes.ok) {
                        const logData = await logRes.json();

                        // Parse log array into formatted entries
                        const parsedLogs: LogEntry[] = logData.logs.map((l: string) => {
                            const match = l.match(/^([\d-:\s]+) - (INFO|ERROR|WARNING) - (.*)$/);
                            if (match) return { time: match[1], type: match[2].toLowerCase(), message: match[3] };
                            return { time: '', type: 'info', message: l };
                        });
                        setLogs(parsedLogs);

                        // Check for completion
                        const isFinished = parsedLogs.some((l) => l.message.includes("Backtest Runner Finished") || l.message.includes("Backtest Stopped"));

                        // -----------------------------------------------------------------
                        // LIVE TRADES & EQUITY UPDATE (Fetch during every poll)
                        // -----------------------------------------------------------------
                        try {
                            const tradesRes = await fetch(`${API_URL}/api/v1/backtest/trades/${runId}`);
                            if (tradesRes.ok) {
                                const tradesData = await tradesRes.json();
                                setTrades(tradesData);

                                if (tradesData.length > 0) {
                                    let currentEquity = config.cash;
                                    const hist = [{ time: config.startDate, equity: currentEquity }];
                                    tradesData.forEach((t: Trade) => {
                                        currentEquity += (t.pnl || 0);
                                        hist.push({
                                            time: new Date(t.time).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
                                            equity: currentEquity
                                        });
                                    });
                                    if (isFinished) {
                                        hist.push({ time: config.endDate, equity: currentEquity });
                                    }
                                    setEquityHistory(hist);

                                    const totalPnL = tradesData.reduce((acc: number, t: Trade) => acc + (t.pnl || 0), 0);
                                    setStats(prev => ({
                                        ...prev,
                                        totalTrades: tradesData.length,
                                        netProfit: totalPnL,
                                        totalReturn: `${((totalPnL / config.cash) * 100).toFixed(2)}%`
                                    }));
                                }
                            }
                        } catch (err) {
                            console.error("Live trades fetch error", err);
                        }

                        if (isFinished) {
                            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                            setIsLoading(false);
                            setIsComplete(true);
                            setActiveRunId(null);

                            addLog("Execution terminated. Fetching telemetry and insights...", 'success');

                            try {
                                const statsRes = await fetch(`${API_URL}/api/v1/backtest/stats/${runId}`);
                                if (statsRes.ok) {
                                    const statsData = await statsRes.json();
                                    if (statsData && statsData.sharpe_ratio !== undefined) {
                                        setStats(prev => ({
                                            ...prev,
                                            sharpeRatio: statsData.sharpe_ratio,
                                            maxDrawdown: `${statsData.max_drawdown}%`,
                                            winRate: `${statsData.win_rate}%`,
                                            totalTrades: statsData.total_trades,
                                            netProfit: statsData.net_profit,
                                            totalReturn: `${statsData.total_return.toFixed(2)}%`,
                                            profitFactor: statsData.profit_factor
                                        }));
                                    }
                                }
                            } catch (err) {
                                console.error("Failed to fetch results", err);
                                addLog("Error fetching insights telemetry.", 'error');
                            }
                        }
                    }
                } catch (e) {
                    console.error("Polling error", e);
                }
            }, 1500);

        } catch (error) {
            addLog(`Error: ${error}`, 'error');
            setIsLoading(false);
            setActiveRunId(null);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={setIsOpen}>
            <DialogTrigger asChild>
                <div className="flex gap-2">
                    <Button size="sm" className="bg-blue-600 hover:bg-blue-500 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all">
                        <Play className="mr-2 h-4 w-4 fill-current" /> Run Backtest
                    </Button>
                </div>
            </DialogTrigger>
            <DialogContent className="max-w-[95vw] h-[95vh] bg-[#0a0a0b] border-slate-800 p-0 flex flex-col overflow-hidden text-slate-300 shadow-2xl">
                {/* Header Control Bar */}
                <div className="flex items-center justify-between border-b border-slate-800 bg-[#111113] p-4 shadow-md z-10 box-border h-20 shrink-0 min-h-[5rem]">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-3 border-r border-slate-700 pr-5">
                            <Activity className="h-6 w-6 text-purple-500" />
                            <div>
                                <h1 className="text-xl font-bold tracking-tight text-white">{strategyName}</h1>
                                <p className="text-xs text-slate-500 font-mono">BACKTEST ENGINE PRE-FLIGHT</p>
                            </div>
                        </div>

                        {/* Config Controls inline */}
                        <div className="flex items-center gap-3 pl-2">
                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800">
                                <Clock className="h-4 w-4 text-slate-500" />
                                <Input type="date" value={config.startDate} onChange={e => setConfig({ ...config, startDate: e.target.value })} className="h-7 w-[125px] bg-transparent border-none focus-visible:ring-0 px-0 text-sm font-mono text-white" />
                                <span className="text-slate-600">→</span>
                                <Input type="date" value={config.endDate} onChange={e => setConfig({ ...config, endDate: e.target.value })} className="h-7 w-[125px] bg-transparent border-none focus-visible:ring-0 px-0 text-sm font-mono text-white" />
                            </div>

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800">
                                <DollarSign className="h-4 w-4 text-slate-500" />
                                <Input type="number" value={config.cash} onChange={e => setConfig({ ...config, cash: parseInt(e.target.value) })} className="h-7 w-[100px] bg-transparent border-none focus-visible:ring-0 px-0 text-sm font-mono text-white hide-arrows" />
                            </div>

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800">
                                <Settings2 className="h-4 w-4 text-slate-500" />
                                <Select value={config.speed} onValueChange={v => setConfig({ ...config, speed: v })}>
                                    <SelectTrigger className="h-7 w-[100px] bg-transparent border-none focus:ring-0 text-white font-mono text-sm px-0">
                                        <SelectValue placeholder="Speed" />
                                    </SelectTrigger>
                                    <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white">
                                        <SelectItem value="fast">Fast</SelectItem>
                                        <SelectItem value="medium">Medium</SelectItem>
                                        <SelectItem value="slow">Slow</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-3">
                        {isLoading ? (
                            <Button onClick={stopBacktest} variant="destructive" className="h-10 px-6 font-semibold shadow-[0_0_15px_rgba(239,68,68,0.4)]">
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> HALT EXECUTION
                            </Button>
                        ) : (
                            <Button onClick={runBacktest} className="h-10 px-8 bg-blue-600 hover:bg-blue-500 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all font-semibold uppercase tracking-wider">
                                <Play className="mr-2 h-4 w-4 fill-current" /> Initialize Run
                            </Button>
                        )}
                        {isComplete && lastRunId && (
                            <Link href={`/dashboard/backtest/${lastRunId}`} target="_blank">
                                <Button variant="outline" className="h-10 border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800">
                                    <TrendingUp className="mr-2 h-4 w-4" /> Full Dashboard
                                </Button>
                            </Link>
                        )}
                    </div>
                </div>

                {/* Main Content Body */}
                <div className="flex flex-1 overflow-hidden">
                    {/* Left Panel: Chart & Data */}
                    <div className="flex-1 flex flex-col border-r border-slate-800 min-w-0 p-4 gap-4 overflow-y-auto custom-scrollbar">

                        {/* Equity Curve Chart */}
                        <div className="h-[45%] min-h-[300px] border border-slate-800 bg-[#111113] rounded-xl p-4 flex flex-col relative overflow-hidden shrink-0">
                            <div className="flex items-center justify-between mb-4 z-10">
                                <h3 className="text-sm font-semibold text-white tracking-wide uppercase flex items-center gap-2">
                                    <BarChart3 className="h-4 w-4 text-blue-500" />
                                    Equity Curve Analysis
                                </h3>
                                {isComplete && (
                                    <Badge className={stats.netProfit >= 0 ? "bg-green-500/20 text-green-400 border-green-500/50" : "bg-red-500/20 text-red-400 border-red-500/50"}>
                                        {stats.totalReturn} ROI
                                    </Badge>
                                )}
                            </div>

                            <div className="flex-1 min-h-0 relative">
                                {!isComplete && equityHistory.length === 0 ? (
                                    <div className="absolute inset-0 flex items-center justify-center text-slate-600 font-mono text-sm border-2 border-dashed border-slate-800 rounded-lg">
                                        {isLoading ? "Awaiting Data Stream..." : "Chart will render upon completion."}
                                    </div>
                                ) : (
                                    <ResponsiveContainer width="100%" height="100%">
                                        <AreaChart data={equityHistory} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                                            <defs>
                                                <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                                                    <stop offset="5%" stopColor={stats.netProfit >= 0 ? "#3b82f6" : "#ef4444"} stopOpacity={0.3} />
                                                    <stop offset="95%" stopColor={stats.netProfit >= 0 ? "#3b82f6" : "#ef4444"} stopOpacity={0} />
                                                </linearGradient>
                                            </defs>
                                            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                                            <XAxis
                                                dataKey="time"
                                                stroke="#475569"
                                                fontSize={11}
                                                tickMargin={10}
                                                tickFormatter={(v) => v.split(',')[0]} // Just show date if long string
                                            />
                                            <YAxis
                                                stroke="#475569"
                                                fontSize={11}
                                                tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`}
                                                domain={['auto', 'auto']}
                                            />
                                            <Tooltip
                                                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f8fafc', borderRadius: '8px' }}
                                                itemStyle={{ color: '#3b82f6' }}
                                                formatter={(value: unknown) => [`₹${Number(value).toFixed(2)}`, 'Equity']}
                                                labelStyle={{ color: '#94a3b8', marginBottom: '4px' }}
                                            />
                                            <Area
                                                type="monotone"
                                                dataKey="equity"
                                                stroke={stats.netProfit >= 0 ? "#3b82f6" : "#ef4444"}
                                                strokeWidth={2}
                                                fillOpacity={1}
                                                fill="url(#colorEquity)"
                                                isAnimationActive={true}
                                            />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                )}
                            </div>
                        </div>

                        {/* Top Insights Layer */}
                        <div className="grid grid-cols-4 gap-4 shrink-0">
                            {[
                                { label: "Net Profit", val: `₹${stats.netProfit.toFixed(1)}`, icon: DollarSign, color: stats.netProfit >= 0 ? 'text-green-400' : 'text-red-400' },
                                { label: "Win Rate", val: stats.winRate, icon: Target, color: 'text-blue-400' },
                                { label: "Max Drawdown", val: stats.maxDrawdown, icon: Percent, color: 'text-red-400' },
                                { label: "Sharpe Ratio", val: stats.sharpeRatio.toFixed(2), icon: Activity, color: 'text-purple-400' },
                            ].map((s, i) => (
                                <div key={i} className="bg-[#111113] border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-xs font-semibold text-slate-500 uppercase">{s.label}</span>
                                        <s.icon className={`h-4 w-4 opacity-50 ${s.color}`} />
                                    </div>
                                    <span className={`text-2xl font-bold tracking-tight font-mono ${s.color}`}>
                                        {isComplete ? s.val : "---"}
                                    </span>
                                </div>
                            ))}
                        </div>

                        {/* Trades Table */}
                        <div className="flex-1 min-h-[250px] border border-slate-800 bg-[#111113] rounded-xl p-4 overflow-hidden flex flex-col shrink-0 mb-4">
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-sm font-semibold text-white tracking-wide uppercase">Execution History</h3>
                                <Badge variant="outline" className="border-slate-700 text-slate-400 font-mono">
                                    {isComplete ? `${trades.length} TRADES` : "WAITING"}
                                </Badge>
                            </div>
                            <div className="flex-1 overflow-y-auto custom-scrollbar border border-slate-800/50 rounded-lg">
                                <table className="w-full text-sm text-left font-mono">
                                    <thead className="text-xs uppercase bg-[#1a1a1e] text-slate-500 sticky top-0 z-10 shadow-sm">
                                        <tr>
                                            <th className="px-4 py-3 font-medium">Time</th>
                                            <th className="px-4 py-3 font-medium">Symbol</th>
                                            <th className="px-4 py-3 font-medium">Side</th>
                                            <th className="px-4 py-3 font-medium text-right">Qty</th>
                                            <th className="px-4 py-3 font-medium text-right">Price</th>
                                            <th className="px-4 py-3 font-medium text-right">PnL</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800">
                                        {trades.length === 0 ? (
                                            <tr>
                                                <td colSpan={6} className="px-4 py-8 text-center text-slate-600">
                                                    No executions recorded yet.
                                                </td>
                                            </tr>
                                        ) : (
                                            trades.map((t, idx) => (
                                                <tr key={idx} className="hover:bg-[#151518] transition-colors">
                                                    <td className="px-4 py-2 text-slate-400">{new Date(t.time).toLocaleString('en-US', { hour12: false, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
                                                    <td className="px-4 py-2 font-medium text-slate-300">{t.symbol.split('|').pop()}</td>
                                                    <td className="px-4 py-2">
                                                        <span className={t.side === 'BUY' ? 'text-blue-400' : 'text-purple-400'}>{t.side}</span>
                                                    </td>
                                                    <td className="px-4 py-2 text-right text-slate-300">{t.quantity}</td>
                                                    <td className="px-4 py-2 text-right text-slate-300">₹{t.price.toFixed(2)}</td>
                                                    <td className={`px-4 py-2 text-right font-medium ${(t.pnl || 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                                                        {t.pnl ? (t.pnl > 0 ? `+₹${t.pnl.toFixed(2)}` : `-₹${Math.abs(t.pnl).toFixed(2)}`) : "—"}
                                                    </td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>

                    {/* Right Panel: Terminal logs */}
                    <div className="w-[450px] bg-[#0a0a0b] flex flex-col p-4 shrink-0 z-0">
                        <div className="flex items-center gap-2 mb-3">
                            <TerminalIcon className="h-4 w-4 text-slate-500" />
                            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Runtime Telemetry</h3>
                        </div>
                        <LogPanel logs={logs} isLoading={isLoading} />
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}

function LogPanel({ logs, isLoading }: { logs: LogEntry[], isLoading: boolean }) {
    const bottomRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (bottomRef.current) {
            bottomRef.current.scrollTop = bottomRef.current.scrollHeight;
        }
    }, [logs]);

    return (
        <div
            ref={bottomRef}
            className="flex-1 bg-[#050505] border border-slate-800/80 rounded-xl p-4 overflow-y-auto font-mono text-xs shadow-inner custom-scrollbar relative"
        >
            <div className="space-y-1.5 pb-8">
                {logs.length === 0 ? (
                    <div className="text-slate-600 flex items-center justify-center h-full">System standby. Awaiting deployment.</div>
                ) : (
                    logs.map((log, i) => (
                        <div key={i} className="flex gap-3 leading-relaxed hover:bg-white/5 px-1 -mx-1 rounded transition-colors break-words">
                            <span className="text-slate-600 shrink-0 select-none">[{log.time || '--:--:--'}]</span>
                            <span className={`
                                ${log.type === 'error' ? 'text-red-400 font-semibold' : ''}
                                ${log.type === 'success' ? 'text-green-400' : ''}
                                ${log.type === 'warning' ? 'text-amber-400' : ''}
                                ${log.type === 'info' ? 'text-slate-300' : 'text-slate-300'}
                                flex-1
                            `}>
                                {log.message}
                            </span>
                        </div>
                    ))
                )}
                {isLoading && (
                    <div className="flex items-center gap-2 text-blue-500 mt-4 animate-pulse">
                        <Loader2 className="h-3 w-3 animate-spin inline" />
                        <span>Receiving telemetry stream...</span>
                    </div>
                )}
            </div>
        </div>
    );
}
