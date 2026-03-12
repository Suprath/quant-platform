"use client";

import React, { useState, useEffect, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Loader2, ArrowLeft, RefreshCw, AlertCircle, BarChart2, LineChart, Table as TableIcon, Zap } from "lucide-react";
import Link from 'next/link';
import {
    ResponsiveContainer,
    ComposedChart,
    Area,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
} from 'recharts';
interface OptionContract {
    instrument_token: string;
    symbol: string;
    strike: number;
    option_type: "CE" | "PE";
    lot_size: number;
    ltp: number;
    volume: number;
    oi: number;
    bid: number;
    ask: number;
    iv: number;
    delta: number;
    gamma: number;
    theta: number;
    vega: number;
}

interface OrganizedChain {
    [strike: number]: {
        CE?: OptionContract;
        PE?: OptionContract;
    };
}

const COMMON_UNDERLYING = ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "HDFCBANK", "INFY"];

export default function OptionsChainPage() {
    const [underlying, setUnderlying] = useState<string>("NIFTY");
    const [expiryDates, setExpiryDates] = useState<string[]>([]);
    const [selectedExpiry, setSelectedExpiry] = useState<string>("");

    const [chain, setChain] = useState<OrganizedChain>({});
    const [useMockData, setUseMockData] = useState<boolean>(false);
    const [selectedMetric, setSelectedMetric] = useState<string>("oi");
    const [viewMode, setViewMode] = useState<"table" | "chart" | "both">("both");
    const [loadingExpiries, setLoadingExpiries] = useState<boolean>(false);
    const [loadingChain, setLoadingChain] = useState<boolean>(false);
    const [lastSync, setLastSync] = useState<Date | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [syncing, setSyncing] = useState<boolean>(false);
    const [priming, setPriming] = useState<boolean>(false);

    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

    // 1. Fetch valid expiry dates when underlying changes
    useEffect(() => {
        const fetchExpiries = async () => {
            setLoadingExpiries(true);
            setError(null);
            try {
                const res = await fetch(`${API_URL}/api/v1/options/expiries/${underlying}`);
                if (!res.ok) throw new Error("Failed to fetch expiries");
                const data = await res.json();
                setExpiryDates(data.expiries || []);
                if (data.expiries && data.expiries.length > 0) {
                    setSelectedExpiry(data.expiries[0]);
                } else {
                    setSelectedExpiry("");
                    setChain({});
                }
            } catch (err: unknown) {
                setError(err instanceof Error ? err.message : String(err));
            } finally {
                setLoadingExpiries(false);
            }
        };
        fetchExpiries();
    }, [underlying, API_URL]);

    // 2. Fetch the chain when underlying OR expiry changes
    const fetchChain = async () => {
        if (!selectedExpiry) return;
        setLoadingChain(true);
        setError(null);
        try {
            const res = await fetch(`${API_URL}/api/v1/options/chain/${underlying}?expiry=${selectedExpiry}${useMockData ? '&mock=true' : ''}`);
            if (!res.ok) throw new Error("Failed to fetch chain");
            const data = await res.json();

            const organized: OrganizedChain = {};
            if (data.contracts && Array.isArray(data.contracts)) {
                data.contracts.forEach((c: OptionContract) => {
                    if (!organized[c.strike]) organized[c.strike] = {};
                    if (c.option_type === 'CE') organized[c.strike].CE = c;
                    if (c.option_type === 'PE') organized[c.strike].PE = c;
                });
            }
            setChain(organized);
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoadingChain(false);
        }
    };

    const syncRealTime = async () => {
        if (!selectedExpiry) return;
        setSyncing(true);
        setError(null);
        try {
            const res = await fetch(`${API_URL}/api/v1/options/sync/${underlying}?expiry=${selectedExpiry}`, {
                method: 'POST'
            });
            if (!res.ok) throw new Error("Failed to start sync");
            await res.json();
            setLastSync(new Date());

            setTimeout(() => {
                fetchChain();
                setSyncing(false);
            }, 1500);
        } catch (err) {
            console.error(err);
            setError("Failed to initiate real-time sync");
            setSyncing(false);
        }
    };

    const primeChain = async () => {
        if (!selectedExpiry) return;
        setPriming(true);
        setError(null);
        try {
            const resp = await fetch(`${API_URL}/api/v1/options/prime/${underlying}?expiry=${selectedExpiry}`, {
                method: 'POST'
            });
            if (!resp.ok) throw new Error("Failed to backfill data");
            const data = await resp.json();
            if (data.status === 'success') {
                setLastSync(new Date());
                await fetchChain();
            } else {
                throw new Error(data.message || "Priming failed");
            }
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setPriming(false);
        }
    };

    useEffect(() => {
        fetchChain();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedExpiry, underlying, useMockData, API_URL]);

    // Derived: Sorted Strike Prices
    const strikes = Object.keys(chain).map(Number).sort((a, b) => a - b);

    // Derived: Chart Data
    const chartData = useMemo(() => {
        return strikes.map(strike => ({
            strike,
            ce_oi: chain[strike].CE?.oi || 0,
            pe_oi: chain[strike].PE?.oi || 0,
            ce_vol: chain[strike].CE?.volume || 0,
            pe_vol: chain[strike].PE?.volume || 0,
            ce_delta: Math.abs(chain[strike].CE?.delta || 0),
            pe_delta: Math.abs(chain[strike].PE?.delta || 0),
            ce_iv: (chain[strike].CE?.iv || 0) * 100,
            pe_iv: (chain[strike].PE?.iv || 0) * 100,
            ce_theta: Math.abs(chain[strike].CE?.theta || 0),
            pe_theta: Math.abs(chain[strike].PE?.theta || 0),
            ce_ltp: chain[strike].CE?.ltp || 0,
            pe_ltp: chain[strike].PE?.ltp || 0
        }));
    }, [strikes, chain]);

    const METRICS = [
        { id: "oi", label: "Open Interest", ceColor: "#10b981", peColor: "#ef4444", type: "bar" },
        { id: "vol", label: "Volume", ceColor: "#3b82f6", peColor: "#f59e0b", type: "bar" },
        { id: "iv", label: "Implied Volatility", ceColor: "#8b5cf6", peColor: "#d946ef", type: "line" },
        { id: "delta", label: "Delta (Absolute)", ceColor: "#ec4899", peColor: "#06b6d4", type: "line" },
        { id: "ltp", label: "LTP", ceColor: "#10b981", peColor: "#ef4444", type: "line" }
    ];

    const currentMetric = METRICS.find(m => m.id === selectedMetric) || METRICS[0];

    return (
        <div className="min-h-screen bg-[#0a0a0b] text-slate-200 p-4 md:p-6 space-y-6">
            {/* Header / Nav */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                    <Link href="/dashboard">
                        <Button variant="outline" size="icon" className="bg-slate-800/50 border-slate-700 hover:bg-slate-700 text-slate-300">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
                            Options Chain
                        </h1>
                        <p className="text-slate-500 text-sm mt-0.5">Explore F&O Contracts & Expiries.</p>
                    </div>
                </div>
            </div>

            {/* Controls */}
            <Card className="bg-[#111113] border-slate-800/60 font-sans">
                <CardContent className="p-4 sm:p-6">
                    <div className="flex flex-col sm:flex-row gap-4 items-end">
                        <div className="space-y-2 flex-1">
                            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Underlying Asset</label>
                            <Select value={underlying} onValueChange={setUnderlying}>
                                <SelectTrigger className="bg-[#1a1a1e] border-slate-700 focus:ring-slate-700">
                                    <SelectValue placeholder="Select Underlying..." />
                                </SelectTrigger>
                                <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white">
                                    {COMMON_UNDERLYING.map(u => (
                                        <SelectItem key={u} value={u}>{u}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-2 flex-1">
                            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
                                Expiry Date
                                {loadingExpiries && <Loader2 className="h-3 w-3 animate-spin" />}
                            </label>
                            <Select value={selectedExpiry} onValueChange={setSelectedExpiry} disabled={loadingExpiries || expiryDates.length === 0}>
                                <SelectTrigger className="bg-[#1a1a1e] border-slate-700 focus:ring-slate-700">
                                    <SelectValue placeholder={expiryDates.length === 0 ? "No Expiries Found" : "Select Expiry..."} />
                                </SelectTrigger>
                                <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white h-[200px] overflow-y-auto">
                                    {expiryDates.map(d => (
                                        <SelectItem key={d} value={d}>
                                            {new Date(d).toLocaleDateString("en-IN", { day: 'numeric', month: 'short', year: 'numeric' })}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="flex flex-col gap-2 items-center justify-center h-full pb-1">
                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest leading-none">Mock Mode</label>
                            <Button
                                variant={useMockData ? "secondary" : "outline"}
                                size="sm"
                                className={`h-6 w-12 p-0 rounded-full transition-all duration-300 relative border-slate-700 ${useMockData ? 'bg-amber-600 hover:bg-amber-500 border-none' : 'bg-[#1a1a1e]'}`}
                                onClick={() => setUseMockData(!useMockData)}
                            >
                                <div className={`absolute top-1 h-4 w-4 rounded-full bg-white transition-all duration-300 ${useMockData ? 'translate-x-3' : '-translate-x-3'}`} />
                            </Button>
                        </div>
                        <div className="flex bg-[#1a1a1e] rounded-lg p-1 border border-slate-700 self-end h-[40px]">
                            <Button
                                variant={viewMode === 'chart' ? 'secondary' : 'ghost'}
                                size="sm"
                                className={`h-full px-3 ${viewMode === 'chart' ? 'bg-slate-700 text-white' : 'text-slate-400'}`}
                                onClick={() => setViewMode('chart')}
                            >
                                <LineChart className="h-4 w-4" />
                            </Button>
                            <Button
                                variant={viewMode === 'both' ? 'secondary' : 'ghost'}
                                size="sm"
                                className={`h-full px-3 ${viewMode === 'both' ? 'bg-slate-700 text-white' : 'text-slate-400'}`}
                                onClick={() => setViewMode('both')}
                            >
                                <BarChart2 className="h-4 w-4" />
                            </Button>
                            <Button
                                variant={viewMode === 'table' ? 'secondary' : 'ghost'}
                                size="sm"
                                className={`h-full px-3 ${viewMode === 'table' ? 'bg-slate-700 text-white' : 'text-slate-400'}`}
                                onClick={() => setViewMode('table')}
                            >
                                <TableIcon className="h-4 w-4" />
                            </Button>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 self-end sm:ml-auto">
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={primeChain}
                                disabled={priming || !selectedExpiry || useMockData}
                                className="h-9 px-4 border-slate-700 text-slate-300 hover:bg-slate-800 active:scale-95 transition-all"
                            >
                                {priming ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                                Backfill Chain
                            </Button>

                            <Button
                                variant="outline"
                                size="sm"
                                onClick={syncRealTime}
                                disabled={syncing || !selectedExpiry || useMockData}
                                className={`h-9 px-4 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 hover:text-emerald-300 transition-all active:scale-95 ${syncing ? 'animate-pulse' : ''}`}
                            >
                                {syncing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Zap className="mr-2 h-4 w-4 fill-emerald-400/20" />}
                                Sync Real-time
                            </Button>

                            <Button
                                variant="secondary"
                                size="sm"
                                className="bg-slate-800 hover:bg-slate-700 text-white border-none h-9 px-4 active:scale-95 transition-all"
                                onClick={fetchChain}
                                disabled={loadingChain || !selectedExpiry}
                            >
                                {loadingChain ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                                Refresh
                            </Button>
                        </div>
                    </div>

                    {lastSync && !useMockData && (
                        <div className="flex items-center gap-1.5 mt-4 w-fit px-3 py-1.5 rounded-md bg-emerald-500/5 border border-emerald-500/20">
                            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            <span className="text-[10px] font-bold text-emerald-500/80 uppercase tracking-wider">Live Feed Active</span>
                            <span className="text-[10px] text-emerald-500/40 font-medium ml-1">
                                Last Updated: {lastSync.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </span>
                        </div>
                    )}

                    {error && (
                        <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 text-red-400 rounded-lg text-sm flex items-center gap-2">
                            <AlertCircle className="h-4 w-4" />
                            {error}
                        </div>
                    )}
                </CardContent>
            </Card>

            {/* Visualization Section */}
            {(viewMode === 'chart' || viewMode === 'both') && strikes.length > 0 && (
                <Card className="bg-[#111113] border-slate-800/60 overflow-hidden">
                    <CardHeader className="flex flex-row items-center justify-between border-b border-slate-800/50 pb-3">
                        <div className="flex items-center gap-3">
                            <BarChart2 className="h-5 w-5 text-blue-400" />
                            <CardTitle className="text-sm font-medium text-slate-200 uppercase tracking-wider">Option Analytics Visualizer</CardTitle>
                        </div>
                        <Select value={selectedMetric} onValueChange={setSelectedMetric}>
                            <SelectTrigger className="w-[180px] bg-[#1a1a1e] border-slate-700 h-8 text-xs">
                                <SelectValue placeholder="Select Metric" />
                            </SelectTrigger>
                            <SelectContent className="bg-[#1a1a1e] border-slate-700 text-white">
                                {METRICS.map(m => (
                                    <SelectItem key={m.id} value={m.id} className="text-xs">{m.label}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </CardHeader>
                    <CardContent className="p-6">
                        <div className="h-[300px] w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                                    <defs>
                                        <linearGradient id="ceGradient" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor={currentMetric.ceColor} stopOpacity={0.3} />
                                            <stop offset="95%" stopColor={currentMetric.ceColor} stopOpacity={0} />
                                        </linearGradient>
                                        <linearGradient id="peGradient" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor={currentMetric.peColor} stopOpacity={0.3} />
                                            <stop offset="95%" stopColor={currentMetric.peColor} stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
                                    <XAxis
                                        dataKey="strike"
                                        stroke="#6b7280"
                                        tick={{ fill: '#6b7280', fontSize: 10 }}
                                        tickFormatter={(val) => `${val}`}
                                        minTickGap={30}
                                    />
                                    <YAxis stroke="#6b7280" tick={{ fill: '#6b7280', fontSize: 10 }} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px', fontSize: '12px' }}
                                        itemStyle={{ padding: '2px 0' }}
                                    />
                                    <Legend wrapperStyle={{ paddingTop: '20px', fontSize: '12px' }} />

                                    {currentMetric.type === 'bar' ? (
                                        <>
                                            <Bar dataKey={`ce_${selectedMetric}`} name={`Calls ${currentMetric.label}`} fill={currentMetric.ceColor} radius={[2, 2, 0, 0]} barSize={8} />
                                            <Bar dataKey={`pe_${selectedMetric}`} name={`Puts ${currentMetric.label}`} fill={currentMetric.peColor} radius={[2, 2, 0, 0]} barSize={8} />
                                        </>
                                    ) : (
                                        <>
                                            <Area type="monotone" dataKey={`ce_${selectedMetric}`} name={`Calls ${currentMetric.label}`} stroke={currentMetric.ceColor} fill="url(#ceGradient)" strokeWidth={2} />
                                            <Area type="monotone" dataKey={`pe_${selectedMetric}`} name={`Puts ${currentMetric.label}`} stroke={currentMetric.peColor} fill="url(#peGradient)" strokeWidth={2} />
                                        </>
                                    )}
                                </ComposedChart>
                            </ResponsiveContainer>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Chain Table */}
            {(viewMode === 'table' || viewMode === 'both') && (
                <Card className="bg-[#111113] border-slate-800/60 max-w-[100vw]">
                    <CardHeader>
                        <CardTitle className="text-sm font-medium text-slate-300 flex items-center justify-between">
                            <span>{underlying} Options expiring {selectedExpiry ? new Date(selectedExpiry).toLocaleDateString("en-IN", { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}</span>
                            <div className="flex items-center gap-4">
                                {useMockData && <span className="bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded-full text-[10px] uppercase font-bold tracking-tighter border border-blue-500/20">Simulated Data</span>}
                                <span className="text-slate-500 text-xs font-normal">Lot Size: {strikes.length > 0 ? chain[strikes[0]].CE?.lot_size || chain[strikes[0]].PE?.lot_size : '—'}</span>
                            </div>
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="p-0 overflow-x-auto custom-scrollbar">
                        {loadingChain ? (
                            <div className="py-24 flex items-center justify-center">
                                <Loader2 className="h-8 w-8 animate-spin text-slate-500" />
                            </div>
                        ) : strikes.length === 0 ? (
                            <div className="py-24 text-center text-slate-500">
                                {selectedExpiry ? "No contracts found for this expiry." : "Select an expiry to view the chain."}
                            </div>
                        ) : (
                            <div className="min-w-[1400px]">
                                <Table className="text-xs">
                                    <TableHeader>
                                        <TableRow className="border-slate-800 hover:bg-transparent bg-[#111113]">
                                            <TableHead colSpan={10} className="text-emerald-400/80 font-bold bg-[#1a1a1e]/50 text-center border-r border-slate-800">CALLS (CE)</TableHead>
                                            <TableHead className="text-slate-300 font-bold text-center bg-slate-800/50 w-[80px]">STRIKE</TableHead>
                                            <TableHead colSpan={10} className="text-red-400/80 font-bold bg-[#1a1a1e]/50 text-center border-l border-slate-800">PUTS (PE)</TableHead>
                                        </TableRow>
                                        <TableRow className="border-slate-800 hover:bg-transparent bg-[#111113] [&_th]:text-slate-400 [&_th]:font-semibold [&_th]:h-8 [&_th]:px-2">
                                            <TableHead className="text-right w-[60px]">Vol</TableHead>
                                            <TableHead className="text-right w-[60px]">OI</TableHead>
                                            <TableHead className="text-right w-[50px]">IV %</TableHead>
                                            <TableHead className="text-right w-[50px]">Delta</TableHead>
                                            <TableHead className="text-right w-[50px]">Gamma</TableHead>
                                            <TableHead className="text-right w-[50px]">Theta</TableHead>
                                            <TableHead className="text-right w-[50px]">Vega</TableHead>
                                            <TableHead className="text-right w-[60px]">Bid</TableHead>
                                            <TableHead className="text-right border-r border-slate-800/50 w-[60px]">Ask</TableHead>
                                            <TableHead className="text-right text-emerald-400/70 border-r border-slate-800 w-[70px]">LTP</TableHead>
                                            <TableHead className="text-center w-[80px]"></TableHead>
                                            <TableHead className="text-left text-red-400/70 border-l border-slate-800 w-[70px]">LTP</TableHead>
                                            <TableHead className="text-left w-[60px]">Bid</TableHead>
                                            <TableHead className="text-left border-r border-slate-800/50 w-[60px]">Ask</TableHead>
                                            <TableHead className="text-left w-[50px]">IV %</TableHead>
                                            <TableHead className="text-left w-[50px]">Delta</TableHead>
                                            <TableHead className="text-left w-[50px]">Gamma</TableHead>
                                            <TableHead className="text-left w-[50px]">Theta</TableHead>
                                            <TableHead className="text-left w-[50px]">Vega</TableHead>
                                            <TableHead className="text-left w-[60px]">Vol</TableHead>
                                            <TableHead className="text-left w-[60px]">OI</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {strikes.map(strike => (
                                            <TableRow key={strike} className="border-slate-800/40 hover:bg-slate-800/40 group transition-colors [&_td]:px-2 [&_td]:py-1.5">
                                                {chain[strike].CE ? (
                                                    <>
                                                        <TableCell className="text-right text-slate-400">
                                                            {chain[strike].CE.volume > 0 ? chain[strike].CE.volume.toLocaleString() : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-slate-400">
                                                            {chain[strike].CE.oi > 0 ? chain[strike].CE.oi.toLocaleString() : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-purple-400/80">
                                                            {chain[strike].CE.iv > 0 ? (chain[strike].CE.iv * 100).toFixed(1) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-slate-500">
                                                            {chain[strike].CE.delta !== 0 ? chain[strike].CE.delta.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-slate-500">
                                                            {chain[strike].CE.gamma !== 0 ? chain[strike].CE.gamma.toFixed(4) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-slate-500">
                                                            {chain[strike].CE.theta !== 0 ? chain[strike].CE.theta.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-slate-500">
                                                            {chain[strike].CE.vega !== 0 ? chain[strike].CE.vega.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-emerald-400/60">
                                                            {chain[strike].CE.bid > 0 ? chain[strike].CE.bid.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-right text-red-400/60 border-r border-slate-800/50">
                                                            {chain[strike].CE.ask > 0 ? chain[strike].CE.ask.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className={`text-right font-medium border-r border-slate-800 bg-emerald-500/5 group-hover:bg-emerald-500/10 transition-colors ${chain[strike].CE.ltp > 0 ? 'text-emerald-400' : 'text-slate-600'}`}>
                                                            {chain[strike].CE.ltp > 0 ? chain[strike].CE.ltp.toFixed(2) : '—'}
                                                        </TableCell>
                                                    </>
                                                ) : (
                                                    <TableCell colSpan={10} className="text-center text-slate-700 border-r border-slate-800">—</TableCell>
                                                )}
                                                <TableCell className="bg-slate-800/30 text-center font-bold text-white shadow-[inset_0_0_15px_rgba(0,0,0,0.3)] min-w-[80px]">
                                                    {strike}
                                                </TableCell>
                                                {chain[strike].PE ? (
                                                    <>
                                                        <TableCell className={`text-left font-medium border-l border-slate-800 bg-red-500/5 group-hover:bg-red-500/10 transition-colors ${chain[strike].PE.ltp > 0 ? 'text-red-400' : 'text-slate-600'}`}>
                                                            {chain[strike].PE.ltp > 0 ? chain[strike].PE.ltp.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-emerald-400/60">
                                                            {chain[strike].PE.bid > 0 ? chain[strike].PE.bid.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-red-400/60 border-r border-slate-800/50">
                                                            {chain[strike].PE.ask > 0 ? chain[strike].PE.ask.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-purple-400/80">
                                                            {chain[strike].PE.iv > 0 ? (chain[strike].PE.iv * 100).toFixed(1) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-slate-500">
                                                            {chain[strike].PE.delta !== 0 ? chain[strike].PE.delta.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-slate-500">
                                                            {chain[strike].PE.gamma !== 0 ? chain[strike].PE.gamma.toFixed(4) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-slate-500">
                                                            {chain[strike].PE.theta !== 0 ? chain[strike].PE.theta.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-slate-500">
                                                            {chain[strike].PE.vega !== 0 ? chain[strike].PE.vega.toFixed(2) : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-slate-400">
                                                            {chain[strike].PE.volume > 0 ? chain[strike].PE.volume.toLocaleString() : '—'}
                                                        </TableCell>
                                                        <TableCell className="text-left text-slate-400">
                                                            {chain[strike].PE.oi > 0 ? chain[strike].PE.oi.toLocaleString() : '—'}
                                                        </TableCell>
                                                    </>
                                                ) : (
                                                    <TableCell colSpan={10} className="text-center text-slate-700 border-l border-slate-800">—</TableCell>
                                                )}
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}
        </div>
    );
}
