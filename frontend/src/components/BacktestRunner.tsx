"use client";

import React, { useState, useEffect } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Link from 'next/link';
import {
    Dialog,
    DialogContent,
    DialogTrigger,
} from "@/components/ui/dialog";
import { Play, Loader2, TrendingUp, BarChart3, Clock, DollarSign, Activity, Settings2, Target, Percent, IndianRupee, Zap, Gauge, AlertTriangle, XCircle } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Search } from 'lucide-react';

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
    const [visibleTradeCount, setVisibleTradeCount] = useState(100);
    const [activeRunId, setActiveRunId] = useState<string | null>(null);
    const [lastRunId, setLastRunId] = useState<string | null>(null);
    const pollIntervalRef = React.useRef<NodeJS.Timeout | null>(null);

    const [isLoading, setIsLoading] = useState(false);
    const [isComplete, setIsComplete] = useState(false);

    const [equityHistory, setEquityHistory] = useState<{ time: string, equity: number }[]>([]);
    const [trades, setTrades] = useState<Trade[]>([]);

    // Speed metrics state
    const [liveSpeed, setLiveSpeed] = useState<number>(0);
    const [progress, setProgress] = useState<number>(0);
    const [maxSpeed, setMaxSpeed] = useState<number>(0);
    const [avgSpeed, setAvgSpeed] = useState<number>(0);
    const [speedFinal, setSpeedFinal] = useState<boolean>(false);

    // Strategy runtime error state
    const [runtimeErrors, setRuntimeErrors] = useState<string[]>([]);
    const [hasRuntimeError, setHasRuntimeError] = useState(false);

    const [searchQuery, setSearchQuery] = useState("");
    const [searchResults, setSearchResults] = useState<{ key: string, symbol: string, name: string, exchange: string, lot_size: number }[]>([]);
    const [searchOpen, setSearchOpen] = useState(false);

    useEffect(() => {
        if (searchQuery.length >= 3) {
            const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
            fetch(`${API_URL}/api/v1/instruments/search?query=${searchQuery}`)
                .then(r => r.json())
                .then(setSearchResults)
                .catch(() => setSearchResults([]));
        } else {
            setSearchResults([]);
        }
    }, [searchQuery]);

    const [config, setConfig] = useState({
        symbol: "NSE_EQ|INE002A01018",
        startDate: "2024-01-01",
        endDate: "2024-01-31",
        cash: 100000,
        speed: "fast",
        timeframe: "5m",
        tradingMode: "MIS"
    });

    const [stats, setStats] = useState({
        totalReturn: "0.0%",
        netProfit: 0.0,
        sharpeRatio: 0.0,
        maxDrawdown: "0.0%",
        winRate: "0.0%",
        totalTrades: 0,
        profitFactor: 0.0,
        brokeragePaid: 0.0
    });

    const [isBackfilling, setIsBackfilling] = useState(false);
    const [backfillMessage, setBackfillMessage] = useState("");

    const addLog = (message: string, type: 'info' | 'success' | 'warning' | 'error' = 'info') => {
        // Log stripped for Dashboard UI
        console.log(`[${type.toUpperCase()}] ${message}`);
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
            setIsBackfilling(false);
            setActiveRunId(null);
        } catch (e) {
            console.error("Failed to stop backtest", e);
            addLog("Failed to stop backtest engine connection.", 'error');
        }
    };

    const runBacktest = async () => {
        setIsLoading(true);
        setIsComplete(false);
        setIsBackfilling(false);
        setBackfillMessage("");
        setRuntimeErrors([]);
        setHasRuntimeError(false);
        setActiveRunId(null);
        setEquityHistory([]);
        setTrades([]);
        setLiveSpeed(0);
        setProgress(0);
        setMaxSpeed(0);
        setAvgSpeed(0);
        setSpeedFinal(false);
        setStats({
            totalReturn: "0.0%", netProfit: 0.0, sharpeRatio: 0.0,
            maxDrawdown: "0.0%", winRate: "0.0%", totalTrades: 0, profitFactor: 0.0, brokeragePaid: 0.0
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
                    speed: config.speed,
                    timeframe: config.timeframe,
                    trading_mode: config.tradingMode
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

                        // Parse log array into formatted entries — handle two formats:
                        // 1. Python logger: "ERROR:LoggerName:message" (+ multiline traceback)
                        // 2. Sentinel:      "YYYY-MM-DD HH:MM:SS - ERROR - message"
                        const parsedLogs: LogEntry[] = [];
                        let pendingError: LogEntry | null = null;
                        const tsPattern = /^(\d{4}-\d{2}-\d{2}[\d\s:]+) - (INFO|ERROR|WARNING) - (.*)$/;
                        const pyPattern = /^(ERROR|WARNING|INFO|DEBUG):[\w.]+:(.*)$/;

                        for (const raw of (logData.logs as string[])) {
                            const ts = raw.match(tsPattern);
                            const py = raw.match(pyPattern);
                            if (ts) {
                                if (pendingError) parsedLogs.push(pendingError);
                                pendingError = null;
                                parsedLogs.push({ time: ts[1], type: ts[2].toLowerCase(), message: ts[3] });
                            } else if (py) {
                                if (pendingError) parsedLogs.push(pendingError);
                                const entry: LogEntry = { time: '', type: py[1].toLowerCase(), message: py[2] };
                                if (py[1] === 'ERROR') {
                                    pendingError = entry; // may have traceback continuation lines
                                } else {
                                    pendingError = null;
                                    parsedLogs.push(entry);
                                }
                            } else if (pendingError) {
                                // Continuation/traceback line for previous ERROR entry
                                pendingError.message += '\n' + raw;
                            } else {
                                parsedLogs.push({ time: '', type: 'info', message: raw });
                            }
                        }
                        if (pendingError) parsedLogs.push(pendingError);

                        // ── Parse metrics from logs ──
                        let currentBackfilling = false;
                        let currentBackfillMsg = "";

                        for (const l of parsedLogs) {
                            // Check backfill status
                            if (l.message.includes("AUTO-BACKFILL: Checking")) {
                                currentBackfilling = true;
                                currentBackfillMsg = "Scanning missing data...";
                            } else if (l.message.includes("Backfilling ")) {
                                currentBackfilling = true;
                                // Extract the stock string like "[1/5] Backfilling RELIANCE..."
                                const bfMatch = l.message.match(/(\[\d+\/\d+\].*)/);
                                if (bfMatch) currentBackfillMsg = bfMatch[1];
                            } else if (l.message.includes("BACKFILL COMPLETE") || l.message.includes("All data present")) {
                                currentBackfilling = false;
                                currentBackfillMsg = "";
                            }

                            // Live speed
                            const speedMatch = l.message.match(/SPEED: ([\d,]+) ticks\/sec \| Progress: ([\d.]+)%/);
                            if (speedMatch && !l.message.includes('SPEED_FINAL')) {
                                const tps = parseInt(speedMatch[1].replace(/,/g, ''), 10);
                                const prog = parseFloat(speedMatch[2]);
                                setLiveSpeed(tps);
                                setProgress(prog);
                                setMaxSpeed(prev => Math.max(prev, tps));
                            }
                            // Final speed
                            const finalMatch = l.message.match(/SPEED_FINAL: avg=([\d,]+) max=([\d,]+) ticks\/sec/);
                            if (finalMatch) {
                                setAvgSpeed(parseInt(finalMatch[1].replace(/,/g, ''), 10));
                                setMaxSpeed(parseInt(finalMatch[2].replace(/,/g, ''), 10));
                                setSpeedFinal(true);
                                setProgress(100);
                            }
                        }

                        // Update backfill state dynamically if it changes during polling
                        setIsBackfilling(currentBackfilling);
                        if (currentBackfillMsg) setBackfillMessage(currentBackfillMsg);

                        // ── Parse strategy runtime errors ──
                        const newErrors: string[] = [];
                        for (const l of parsedLogs) {
                            if (l.type === 'error' && l.message) {
                                newErrors.push(l.message);
                            }
                        }
                        if (newErrors.length > 0) {
                            setRuntimeErrors(prev => {
                                // Deduplicate by message content
                                const prevSet = new Set(prev);
                                const unique = newErrors.filter(e => !prevSet.has(e));
                                return unique.length > 0 ? [...prev, ...unique] : prev;
                            });
                            setHasRuntimeError(true);
                            // Stop loading if there's a strategy error
                            if (newErrors.some(e => e.includes('STRATEGY_ERROR:'))) {
                                if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                                setIsLoading(false);
                            }
                        }

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

                                // Always construct graph history (downsampled to ≤500 points)
                                let currentEquity = config.cash;
                                let estBrokerage = 0;
                                const hist = [{ time: config.startDate, equity: currentEquity }];

                                if (tradesData.length > 0) {
                                    // Stride-sample: only push every Nth trade for the chart
                                    const maxChartPts = 500;
                                    const stride = Math.max(1, Math.floor(tradesData.length / maxChartPts));
                                    tradesData.forEach((t: Trade, idx: number) => {
                                        currentEquity += (t.pnl || 0);

                                        // Estimate Brokerage
                                        const turnover = t.price * Math.abs(t.quantity || 1);
                                        const flat = Math.min(20, turnover * 0.0003);
                                        const stt = t.side === 'SELL' ? turnover * 0.00025 : 0;
                                        const gst = flat * 0.18;
                                        estBrokerage += flat + stt + gst;

                                        // Only push chart point every Nth trade (or last trade)
                                        if ((idx + 1) % stride === 0 || idx === tradesData.length - 1) {
                                            hist.push({
                                                time: new Date(t.time).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
                                                equity: currentEquity
                                            });
                                        }
                                    });

                                    const totalPnL = tradesData.reduce((acc: number, t: Trade) => acc + (t.pnl || 0), 0);
                                    setStats((prev) => ({
                                        ...prev,
                                        totalTrades: tradesData.length,
                                        netProfit: totalPnL,
                                        totalReturn: `${((totalPnL / config.cash) * 100).toFixed(2)}%`,
                                        brokeragePaid: estBrokerage
                                    }));
                                }

                                // Always push the latest point
                                if (isFinished) {
                                    hist.push({ time: config.endDate, equity: currentEquity });
                                } else {
                                    const latestTime = parsedLogs.length > 0 ? parsedLogs[parsedLogs.length - 1].time : new Date().toLocaleTimeString();
                                    if (latestTime) {
                                        hist.push({ time: latestTime, equity: currentEquity });
                                    }
                                }
                            }
                        } catch (err) {
                            console.error("Live trades fetch error", err);
                        }

                        // -----------------------------------------------------------------
                        // PERFORMANCE CURVE FETCH (New: Real-time from server-side aggregates)
                        // -----------------------------------------------------------------
                        if (progress > 0 || isFinished) {
                            try {
                                const API_URL_TIL = process.env.NEXT_PUBLIC_TIL_API_URL || 'http://localhost:8003';
                                const perfRes = await fetch(`${API_URL_TIL}/api/v1/til/performance?run_id=${runId}`);
                                if (perfRes.ok) {
                                    const perfData = await perfRes.json();
                                    if (perfData.points && perfData.points.length > 0) {
                                        setEquityHistory(perfData.points);
                                        // Update summary stats from the same source for parity
                                        if (perfData.summary) {
                                            setStats(prev => ({
                                                ...prev,
                                                netProfit: perfData.summary.net_profit,
                                                totalReturn: `${perfData.summary.total_pnl_pct.toFixed(2)}%`,
                                                sharpeRatio: perfData.summary.sharpe_ratio,
                                                maxDrawdown: `${perfData.summary.max_drawdown_pct.toFixed(2)}%`,
                                                winRate: `${perfData.summary.win_rate_pct.toFixed(1)}%`,
                                                totalTrades: perfData.summary.total_trades
                                            }));
                                        }
                                    }
                                }
                            } catch (err) {
                                console.error("Performance fetch error", err);
                            }
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
            }, 500); // Optimized for 300M+ ticks/sec (reduced from 1500ms)

        } catch (error) {
            addLog(`Error: ${error}`, 'error');
            setIsLoading(false);
            setActiveRunId(null);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={setIsOpen} >
            <DialogTrigger asChild>
                <div className="flex gap-2">
                    <Button size="sm" className="bg-blue-600 hover:bg-blue-500 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all">
                        <Play className="mr-2 h-4 w-4 fill-current" /> Run Backtest
                    </Button>
                </div>
            </DialogTrigger>
            <DialogContent className="max-w-[95vw] h-[95vh] bg-[#0a0a0b] border-slate-800 p-0 flex flex-col overflow-hidden text-slate-300 shadow-2xl">
                {/* Header Control Bar */}
                <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between border-b border-slate-800 bg-[#111113] p-4 shadow-md z-10 box-border shrink-0 gap-4 flex-wrap">
                    <div className="flex flex-col md:flex-row items-start md:items-center gap-4 w-full lg:w-auto flex-wrap">
                        <div className="flex items-center gap-3 border-b md:border-b-0 md:border-r border-slate-700 pb-3 md:pb-0 pr-5 w-full md:w-auto shrink-0">
                            <Activity className="h-6 w-6 text-purple-500" />
                            <div>
                                <h1 className="text-xl font-bold tracking-tight text-white">{strategyName}</h1>
                                <p className="text-xs text-slate-500 font-mono">BACKTEST ENGINE PRE-FLIGHT</p>
                            </div>
                        </div>

                        {/* Config Controls inline */}
                        <div className="flex items-center gap-3 pl-0 md:pl-2 flex-wrap sm:flex-nowrap overflow-x-auto custom-scrollbar pb-2 sm:pb-0 w-full md:w-auto">
                            {/* Symbol Search Autocomplete */}
                            <div className="relative">
                                <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800 cursor-text hover:border-slate-600 transition-colors w-[180px]">
                                    <Search className="h-4 w-4 text-slate-500 shrink-0" />
                                    <input
                                        value={searchQuery || (config?.symbol ? config.symbol.split('|').pop() : "")}
                                        onChange={(e) => {
                                            setSearchQuery(e.target.value);
                                            setSearchOpen(true);
                                        }}
                                        onFocus={() => setSearchOpen(true)}
                                        placeholder="Search Symbol..."
                                        className="bg-transparent border-none outline-none text-sm font-mono text-white w-full placeholder:text-slate-600"
                                    />
                                </div>

                                {searchOpen && searchResults.length > 0 && (
                                    <div className="absolute top-full left-0 mt-2 w-[300px] bg-[#1a1a1e] border border-slate-700 rounded-md shadow-2xl z-50 max-h-[300px] overflow-y-auto custom-scrollbar">
                                        {searchResults.map((s, idx) => (
                                            <div
                                                key={idx}
                                                className="p-2 px-3 hover:bg-blue-600/20 hover:text-blue-400 cursor-pointer border-b border-slate-800 last:border-0 flex justify-between items-center transition-colors"
                                                onClick={() => {
                                                    setConfig({ ...config, symbol: s.key });
                                                    setSearchQuery(s.symbol);
                                                    setSearchOpen(false);
                                                }}
                                            >
                                                <div>
                                                    <div className="font-mono font-bold text-sm text-slate-300">{s.symbol}</div>
                                                    <div className="text-xs text-slate-500 truncate max-w-[180px]">{s.name}</div>
                                                </div>
                                                <Badge variant="outline" className={s.exchange === "NSE_EQ" ? "border-blue-500/30 text-blue-500" : "border-green-500/30 text-green-500"}>
                                                    {s.exchange}
                                                </Badge>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {searchOpen && searchQuery.length >= 3 && searchResults.length === 0 && (
                                    <div className="absolute top-full left-0 mt-2 w-[300px] bg-[#1a1a1e] border border-slate-700 rounded-md shadow-2xl z-50 p-4 text-sm text-slate-500 text-center">
                                        No symbols found.
                                    </div>
                                )}
                                {/* Close absolute overlay if click outside */}
                                {searchOpen && (
                                    <div className="fixed inset-0 z-40" onClick={() => setSearchOpen(false)} />
                                )}
                            </div>

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800 shrink-0">
                                <Clock className="h-4 w-4 text-slate-500" />
                                <Input type="date" value={config.startDate} onChange={e => setConfig({ ...config, startDate: e.target.value })} className="h-7 w-[125px] bg-transparent border-none focus-visible:ring-0 px-0 text-sm font-mono text-white" />
                                <span className="text-slate-600">→</span>
                                <Input type="date" value={config.endDate} onChange={e => setConfig({ ...config, endDate: e.target.value })} className="h-7 w-[125px] bg-transparent border-none focus-visible:ring-0 px-0 text-sm font-mono text-white" />
                            </div>

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800 shrink-0">
                                <DollarSign className="h-4 w-4 text-slate-500" />
                                <Input type="number" value={config.cash} onChange={e => setConfig({ ...config, cash: parseInt(e.target.value) })} className="h-7 w-[100px] bg-transparent border-none focus-visible:ring-0 px-0 text-sm font-mono text-white hide-arrows" />
                            </div>

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800 shrink-0">
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

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800 shrink-0">
                                <Clock className="h-4 w-4 text-slate-500" />
                                <Select value={config.timeframe} onValueChange={v => setConfig({ ...config, timeframe: v })}>
                                    <SelectTrigger className="h-7 w-[90px] bg-transparent border-none focus:ring-0 text-white font-mono text-sm px-0">
                                        <SelectValue placeholder="Period" />
                                    </SelectTrigger>
                                    <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white">
                                        <SelectItem value="1m">1 min</SelectItem>
                                        <SelectItem value="5m">5 min</SelectItem>
                                        <SelectItem value="15m">15 min</SelectItem>
                                        <SelectItem value="30m">30 min</SelectItem>
                                        <SelectItem value="1h">1 hour</SelectItem>
                                        <SelectItem value="1d">1 day</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>

                            <div className="flex items-center gap-2 bg-[#0a0a0b] px-3 py-1.5 rounded-md border border-slate-800 shrink-0">
                                <Target className="h-4 w-4 text-slate-500" />
                                <Select value={config.tradingMode} onValueChange={v => setConfig({ ...config, tradingMode: v })}>
                                    <SelectTrigger className="h-7 w-[100px] bg-transparent border-none focus:ring-0 text-white font-mono text-sm px-0">
                                        <SelectValue placeholder="Mode" />
                                    </SelectTrigger>
                                    <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white">
                                        <SelectItem value="MIS">Intraday (MIS)</SelectItem>
                                        <SelectItem value="CNC">Delivery (CNC)</SelectItem>
                                        <SelectItem value="OPTIONS">Options (F&O)</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-3 w-full lg:w-auto lg:justify-end mt-2 lg:mt-0">
                        {/* Backfill Indicator */}
                        {isLoading && isBackfilling && (
                            <div className="flex items-center gap-3 bg-[#111113] border border-amber-500/30 rounded-lg px-4 py-2 shrink-0 shadow-[0_0_12px_rgba(245,158,11,0.15)]">
                                <Loader2 className="h-4 w-4 text-amber-500 animate-spin" />
                                <div className="flex flex-col">
                                    <span className="text-amber-500 font-mono text-sm font-bold leading-tight">
                                        Backfilling Data
                                    </span>
                                    <span className="text-slate-400 text-xs font-mono truncate max-w-[150px]">
                                        {backfillMessage || "Initializing..."}
                                    </span>
                                </div>
                            </div>
                        )}

                        {/* Live Speed Indicator */}
                        {isLoading && liveSpeed > 0 && !isBackfilling && (
                            <div className="flex items-center gap-3 bg-[#0a0a0b] border border-emerald-500/30 rounded-lg px-4 py-2 shrink-0 shadow-[0_0_12px_rgba(16,185,129,0.15)]">
                                <Zap className="h-4 w-4 text-emerald-400 animate-pulse" />
                                <div className="flex flex-col">
                                    <span className="text-emerald-400 font-mono text-lg font-bold leading-tight">
                                        {liveSpeed >= 1_000_000 ? `${(liveSpeed / 1_000_000).toFixed(1)}M` : liveSpeed >= 1000 ? `${(liveSpeed / 1000).toFixed(0)}K` : liveSpeed}
                                        <span className="text-emerald-600 text-xs font-normal ml-1">ticks/s</span>
                                    </span>
                                    <div className="flex items-center gap-2 mt-0.5">
                                        <div className="w-24 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                            <div className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400 rounded-full transition-all duration-500"
                                                style={{ width: `${Math.min(progress, 100)}%` }} />
                                        </div>
                                        <span className="text-slate-500 text-[10px] font-mono">{progress.toFixed(0)}%</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {isLoading ? (
                            <Button onClick={stopBacktest} variant="destructive" className="h-10 px-6 font-semibold shadow-[0_0_15px_rgba(239,68,68,0.4)] shrink-0">
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> HALT EXECUTION
                            </Button>
                        ) : (
                            <Button onClick={runBacktest} className="h-10 px-8 bg-blue-600 hover:bg-blue-500 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all font-semibold uppercase tracking-wider shrink-0">
                                <Play className="mr-2 h-4 w-4 fill-current" /> Initialize Run
                            </Button>
                        )}
                        {/* Always visible when complete to draw attention, and with high contrast styling */}
                        {isComplete && lastRunId && (
                            <Link href={`/dashboard/backtest/${lastRunId}`} target="_blank" className="shrink-0">
                                <Button className="h-10 bg-indigo-600 hover:bg-indigo-500 text-white shadow-[0_0_20px_rgba(79,70,229,0.5)] transition-all font-bold tracking-wide animate-pulse">
                                    <TrendingUp className="mr-2 h-4 w-4" /> Full Dashboard
                                </Button>
                            </Link>
                        )}
                    </div>
                </div>

                {/* Main Content Body (Scrollable Area) */}
                <div className="flex-1 overflow-y-auto custom-scrollbar p-4 bg-[#0a0a0b]">
                    <div className="flex flex-col max-w-7xl mx-auto gap-6">

                        {/* ── Strategy Runtime Error Panel ── */}
                        {hasRuntimeError && runtimeErrors.length > 0 && (
                            <div className="border border-red-500/50 rounded-xl overflow-hidden shadow-[0_0_20px_rgba(239,68,68,0.15)]">
                                {/* Error Header */}
                                <div className="flex items-center justify-between px-4 py-3 bg-red-950/60 border-b border-red-500/30">
                                    <div className="flex items-center gap-2">
                                        <XCircle className="h-5 w-5 text-red-500 shrink-0" />
                                        <span className="text-red-400 font-bold text-sm tracking-wide uppercase">
                                            Strategy Runtime Error
                                        </span>
                                        <Badge className="bg-red-500/20 text-red-400 border-red-500/40 text-xs">
                                            {runtimeErrors.length} {runtimeErrors.length === 1 ? 'error' : 'errors'}
                                        </Badge>
                                    </div>
                                    <button
                                        onClick={() => { setHasRuntimeError(false); setRuntimeErrors([]); }}
                                        className="text-slate-500 hover:text-red-400 transition-colors text-xs font-mono px-2 py-1 hover:bg-red-500/10 rounded"
                                    >
                                        Dismiss
                                    </button>
                                </div>
                                {/* Error Messages */}
                                <div className="bg-[#0d0506] p-4 flex flex-col gap-4 max-h-[400px] overflow-y-auto custom-scrollbar">
                                    {runtimeErrors.map((err, idx) => {
                                        // Clean up STRATEGY_ERROR: prefix for display
                                        const rawMsg = err.replace(/^STRATEGY_ERROR:\s*/, '');
                                        // Unescape literal \n written by the backend into real newlines
                                        const displayMsg = rawMsg.replace(/\\n/g, '\n');
                                        // Split into first line (error type) and rest (traceback)
                                        const lines = displayMsg.split('\n').filter(l => l.trim());
                                        const headline = lines[lines.length - 1] || lines[0]; // last line = actual error (e.g. NameError: ...)
                                        const traceback = lines.slice(0, -1).join('\n'); // everything before = traceback context

                                        return (
                                            <div key={idx} className="flex flex-col gap-1">
                                                {/* Error headline */}
                                                <div className="flex items-start gap-2">
                                                    <AlertTriangle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                                                    <span className="text-red-400 font-mono text-sm font-semibold break-all">{headline}</span>
                                                </div>
                                                {/* Traceback block */}
                                                {traceback && (
                                                    <pre className="text-slate-400 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all bg-black/40 rounded-lg p-3 border border-slate-800/60 mt-1">
                                                        {traceback.trim()}
                                                    </pre>
                                                )}
                                                {idx < runtimeErrors.length - 1 && (
                                                    <div className="border-b border-red-900/40 mt-2" />
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* Top Insights Layer */}
                        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
                            {[
                                { label: "Net Profit", val: `₹${stats.netProfit.toFixed(1)}`, icon: IndianRupee, color: stats.netProfit >= 0 ? 'text-green-400' : 'text-red-400' },
                                { label: "Win Rate", val: stats.winRate, icon: Target, color: 'text-blue-400' },
                                { label: "Max Drawdown", val: stats.maxDrawdown, icon: Percent, color: 'text-red-400' },
                                { label: "Sharpe Ratio", val: stats.sharpeRatio.toFixed(2), icon: Activity, color: 'text-purple-400' },
                                { label: "Est. Brokerage", val: `₹${(stats.brokeragePaid || 0).toFixed(2)}`, icon: IndianRupee, color: 'text-yellow-500' },
                                {
                                    label: "Processing Speed",
                                    val: speedFinal
                                        ? `${avgSpeed >= 1_000_000 ? (avgSpeed / 1_000_000).toFixed(1) + 'M' : avgSpeed >= 1000 ? (avgSpeed / 1000).toFixed(0) + 'K' : avgSpeed} avg / ${maxSpeed >= 1_000_000 ? (maxSpeed / 1_000_000).toFixed(1) + 'M' : maxSpeed >= 1000 ? (maxSpeed / 1000).toFixed(0) + 'K' : maxSpeed} max`
                                        : liveSpeed > 0
                                            ? `${liveSpeed >= 1_000_000 ? (liveSpeed / 1_000_000).toFixed(1) + 'M' : liveSpeed >= 1000 ? (liveSpeed / 1000).toFixed(0) + 'K' : liveSpeed} ticks/s`
                                            : '---',
                                    icon: Gauge,
                                    color: 'text-emerald-400'
                                },
                            ].map((s, i) => {
                                const showVal = isComplete || i === 5;
                                const textLength = showVal && typeof s.val === 'string' ? s.val.length : 0;
                                const textSizeClass = textLength > 15 ? 'text-base lg:text-sm xl:text-base' : 'text-xl';

                                return (
                                    <div key={i} className="bg-[#111113] border border-slate-800 rounded-xl p-4 flex flex-col justify-between min-w-0 shadow-sm">
                                        <div className="flex flex-row items-center justify-between mb-3">
                                            <span className="text-xs font-semibold text-slate-500 uppercase truncate mr-2">{s.label}</span>
                                            <s.icon className={`h-4 w-4 opacity-50 shrink-0 ${s.color}`} />
                                        </div>
                                        <span className={`${textSizeClass} font-bold tracking-tight font-mono ${s.color} truncate`} title={showVal ? String(s.val) : ""}>
                                            {showVal ? s.val : "---"}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>

                        {/* Equity Curve Chart */}
                        <div className="h-[400px] border border-slate-800 bg-[#111113] rounded-xl p-4 flex flex-col relative overflow-hidden shadow-sm">
                            <div className="flex items-center justify-between mb-4 z-10 shrink-0">
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

                            {!isComplete && equityHistory.length === 0 ? (
                                <div className="absolute inset-0 flex items-center justify-center text-slate-600 font-mono text-sm border-2 border-dashed border-slate-800 rounded-lg">
                                    {isLoading ? "Awaiting Data Stream..." : "Chart will render upon completion."}
                                </div>
                            ) : ( // Ensure min 2 points are drawn
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart data={equityHistory.length === 1 ? [...equityHistory, ...equityHistory] : equityHistory} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
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
                                            tickFormatter={(v) => v ? v.split(',')[0] : ''} // Just show date if long string
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



                    {/* Trades Table */}
                    <div className="flex-1 min-h-[250px] border border-slate-800 bg-[#111113] rounded-xl p-4 overflow-hidden flex flex-col shrink-0 mb-4">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-sm font-semibold text-white tracking-wide uppercase">Execution History</h3>
                            <Badge variant="outline" className="border-slate-700 text-slate-400 font-mono">
                                {isComplete ? `${trades.length} TRADES` : "WAITING"}
                            </Badge>
                        </div>
                        <div className="flex-1 overflow-auto custom-scrollbar border border-slate-800/50 rounded-lg">
                            <table className="w-full text-sm text-left font-mono min-w-[600px]">
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
                                        trades.slice(0, visibleTradeCount).map((t, idx) => (
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
                            {trades.length > visibleTradeCount && (
                                <div className="flex justify-center py-3 border-t border-slate-800">
                                    <button
                                        className="text-sm text-blue-400 hover:text-blue-300 font-mono transition-colors"
                                        onClick={() => setVisibleTradeCount(prev => prev + 200)}
                                    >
                                        Show More ({trades.length - visibleTradeCount} remaining)
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog >
    );
}

