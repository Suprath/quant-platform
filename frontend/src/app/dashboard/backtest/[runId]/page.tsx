"use client";

import React, { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
    ArrowLeft, Loader2, TrendingUp, TrendingDown, Activity,
    IndianRupee, BarChart3, Target, Percent, Scale, Clock, Zap
} from 'lucide-react';
import Link from 'next/link';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { ScannerResults } from "@/components/ScannerResults";

interface Trade {
    time: string;
    symbol: string;
    name: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    price: number;
    pnl: number | null;
}

interface Stats {
    netProfit: number;
    totalReturn: number;
    maxDrawdown: number;
    maxDdDuration: number;
    winRate: number;
    totalTrades: number;
    sharpeRatio: number;
    sortinoRatio: number;
    calmarRatio: number;
    cagr: number;
    profitFactor: number;
    expectancy: number;
    avgWin: number;
    avgLoss: number;
    brokeragePaid: number;
}

interface EquityCurvePoint {
    time: string;
    equity: number;
}

export default function BacktestResultPage() {
    const params = useParams();
    const runId = params.runId as string;
    const [trades, setTrades] = useState<Trade[]>([]);
    const [loading, setLoading] = useState(true);
    const [stats, setStats] = useState<Stats | null>(null);
    const [equityCurve, setEquityCurve] = useState<EquityCurvePoint[]>([]);
    const [statsError, setStatsError] = useState<string | null>(null);
    const [visibleTradeCount, setVisibleTradeCount] = useState(100);

    useEffect(() => {
        if (!runId) return;

        const fetchData = async () => {
            try {
                const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

                const [tradesRes, statsRes] = await Promise.all([
                    fetch(`${API_URL}/api/v1/backtest/trades/${runId}`),
                    fetch(`${API_URL}/api/v1/backtest/stats/${runId}`)
                ]);

                if (!tradesRes.ok) throw new Error("Failed to fetch trades");
                const tradesData = await tradesRes.json();

                let statsData = null;
                if (statsRes.ok) {
                    statsData = await statsRes.json();
                }

                processBacktestData(tradesData, statsData);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [runId]);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const processBacktestData = (tradesData: any[], statsData: Record<string, any> | null) => {
        if (statsData?.error) {
            setStatsError(statsData.error);
        }

        // Map trades + compute brokerage in a single pass
        const initialCash = 100000;
        let estBrokerage = 0;
        const mappedTrades: Trade[] = tradesData.map(t => {
            const turnover = t.price * Math.abs(t.quantity);
            const flat = Math.min(20, turnover * 0.0003);
            const stt = t.side === 'SELL' ? turnover * 0.00025 : 0;
            const gst = flat * 0.18;
            estBrokerage += flat + stt + gst;
            return {
                ...t,
                name: t.stock_name || t.name || t.symbol?.replace(/^(NSE_EQ|BSE_EQ)\|/, '') || 'UNKNOWN',
            };
        });
        setTrades(mappedTrades);

        if (statsData && statsData.sharpe_ratio !== undefined) {
            setStats({
                netProfit: statsData.net_profit ?? 0,
                totalReturn: statsData.total_return ?? 0,
                maxDrawdown: statsData.max_drawdown ?? 0,
                maxDdDuration: statsData.max_dd_duration ?? 0,
                winRate: statsData.win_rate ?? 0,
                totalTrades: statsData.total_trades ?? 0,
                sharpeRatio: statsData.sharpe_ratio ?? 0,
                sortinoRatio: statsData.sortino_ratio ?? 0,
                calmarRatio: statsData.calmar_ratio ?? 0,
                cagr: statsData.cagr ?? 0,
                profitFactor: statsData.profit_factor ?? 0,
                expectancy: statsData.expectancy ?? 0,
                avgWin: statsData.avg_win ?? 0,
                avgLoss: statsData.avg_loss ?? 0,
                brokeragePaid: estBrokerage
            });

            // Use precomputed & downsampled equity curve from backend (≤500 points)
            if (statsData.equity_curve && Array.isArray(statsData.equity_curve) && statsData.equity_curve.length > 0) {
                const engineCurve = statsData.equity_curve.map((pt: { time: string, equity: number }) => ({
                    time: new Date(pt.time).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
                    equity: pt.equity
                }));
                if (engineCurve.length === 1) engineCurve.push({ time: 'End', equity: engineCurve[0].equity });
                setEquityCurve(engineCurve);
                return;
            }
        } else {
            // Fallback: compute basic stats from trades
            let currentEquity = initialCash;
            tradesData.forEach(t => {
                if (t.pnl !== null && t.pnl !== undefined && t.pnl !== 0) {
                    currentEquity += t.pnl;
                }
            });
            const netProfit = currentEquity - initialCash;
            const totalReturn = (netProfit / initialCash) * 100;
            const wins = tradesData.filter(t => t.pnl !== null && t.pnl > 0).length;
            const tradesWithPnl = tradesData.filter(t => t.pnl !== null && t.pnl !== 0).length;
            const winRate = tradesWithPnl > 0 ? (wins / tradesWithPnl) * 100 : 0;

            setStats({
                netProfit,
                totalReturn,
                maxDrawdown: 0,
                maxDdDuration: 0,
                winRate,
                totalTrades: tradesData.length,
                sharpeRatio: 0,
                sortinoRatio: 0,
                calmarRatio: 0,
                cagr: 0,
                profitFactor: 0,
                expectancy: 0,
                avgWin: 0,
                avgLoss: 0,
                brokeragePaid: estBrokerage
            });
        }

        // Fallback equity curve from trades (only if backend curve not available)
        let currentEquity = initialCash;
        const curve = [{ time: 'Start', equity: initialCash }];
        // Downsample: only emit every Nth trade for chart if too many
        const maxChartPoints = 500;
        const stride = Math.max(1, Math.floor(tradesData.length / maxChartPoints));
        let idx = 0;
        tradesData.forEach(t => {
            if (t.pnl !== null && t.pnl !== undefined && t.pnl !== 0) {
                currentEquity += t.pnl;
                idx++;
                if (idx % stride === 0 || idx === tradesData.length) {
                    curve.push({
                        time: new Date(t.time).toLocaleTimeString(),
                        equity: currentEquity
                    });
                }
            }
        });
        if (curve.length === 1) curve.push({ time: 'End', equity: currentEquity });
        setEquityCurve(curve);
    };

    if (loading) {
        return (
            <div className="flex h-screen items-center justify-center bg-[#0a0a0b]">
                <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                <span className="ml-3 text-slate-400">Loading Backtest Results...</span>
            </div>
        );
    }

    const formatCurrency = (v: number) => `₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
    const formatPct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;

    const formatSymbol = (symbolInput: string, nameInput: string) => {
        const rawSymbol = symbolInput ? symbolInput.replace(/^(NSE_FO|NSE_EQ|BSE_EQ|BFO)\|/, '') : '';
        const rawName = nameInput && nameInput !== symbolInput ? nameInput.replace(/^(NSE_FO|NSE_EQ|BSE_EQ|BFO)\|/, '') : rawSymbol;

        const targetToParse = rawName !== rawSymbol && rawName.length > 5 ? rawName : rawSymbol;
        const match = targetToParse.match(/^([A-Z]+)(\d{2}[A-Z]{3})(\d+)(CE|PE)$/i);

        if (match) {
            const [, underlying, expiry, strike, type] = match;
            return `${underlying} ${expiry} ${strike} ${type}`;
        }

        return targetToParse;
    };

    return (
        <div className="min-h-screen bg-[#0a0a0b] text-slate-200 p-4 md:p-6 space-y-6">
            {/* Header */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                    <Link href="/ide">
                        <Button variant="outline" size="icon" className="bg-slate-800/50 border-slate-700 hover:bg-slate-700 text-slate-300">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight text-white">Backtest Results</h1>
                        <p className="text-slate-500 text-xs font-mono mt-0.5">{runId}</p>
                    </div>
                </div>
                <Badge variant="outline" className={`text-sm px-3 py-1.5 ${stats && stats.netProfit >= 0
                    ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10'
                    : 'border-red-500/40 text-red-400 bg-red-500/10'
                    }`}>
                    {stats ? formatPct(stats.totalReturn) : '—'}
                </Badge>
            </div>

            {statsError && (
                <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 p-4 rounded-lg flex items-center gap-3">
                    <Activity className="h-5 w-5 shrink-0" />
                    <div>
                        <h3 className="font-semibold text-sm">Strategy completed with ZERO trades.</h3>
                        <p className="text-xs text-amber-400/80 mt-0.5">Your strategy script executed successfully but did not open or close any positions. {statsError}</p>
                    </div>
                </div>
            )}

            {stats && (
                <>
                    {/* ── Row 1: Primary Performance Cards ── */}
                    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
                        {/* Net Profit */}
                        <Card className="bg-[#111113] border-slate-800/60">
                            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1.5 gap-2">
                                <CardTitle className="text-xs font-medium text-slate-400 truncate">Net Profit</CardTitle>
                                <IndianRupee className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                            </CardHeader>
                            <CardContent>
                                <div className={`text-xl md:text-2xl font-bold ${stats.netProfit >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                    {stats.netProfit >= 0 ? "+" : "-"}{formatCurrency(stats.netProfit)}
                                </div>
                                <p className="text-[10px] text-slate-500 mt-0.5">{formatPct(stats.totalReturn)} Return</p>
                            </CardContent>
                        </Card>

                        {/* Sharpe Ratio */}
                        <Card className="bg-[#111113] border-slate-800/60">
                            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1.5 gap-2">
                                <CardTitle className="text-xs font-medium text-slate-400 truncate">Sharpe Ratio</CardTitle>
                                <TrendingUp className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                            </CardHeader>
                            <CardContent>
                                <div className={`text-xl md:text-2xl font-bold ${stats.sharpeRatio >= 1 ? "text-emerald-400" : stats.sharpeRatio >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                                    {stats.sharpeRatio.toFixed(2)}
                                </div>
                                <p className="text-[10px] text-slate-500 mt-0.5">
                                    {stats.sharpeRatio >= 2 ? "Excellent" : stats.sharpeRatio >= 1 ? "Good" : stats.sharpeRatio > 0 ? "Below Avg" : "Negative"}
                                </p>
                            </CardContent>
                        </Card>

                        {/* Max Drawdown */}
                        <Card className="bg-[#111113] border-slate-800/60">
                            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1.5 gap-2">
                                <CardTitle className="text-xs font-medium text-slate-400 truncate">Max Drawdown</CardTitle>
                                <TrendingDown className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                            </CardHeader>
                            <CardContent>
                                <div className="text-xl md:text-2xl font-bold text-red-400">
                                    {stats.maxDrawdown !== 0 ? `${stats.maxDrawdown.toFixed(2)}%` : '0.00%'}
                                </div>
                                <p className="text-[10px] text-slate-500 mt-0.5">
                                    {stats.maxDdDuration > 0 ? `${stats.maxDdDuration} day recovery` : '—'}
                                </p>
                            </CardContent>
                        </Card>

                        {/* Win Rate */}
                        <Card className="bg-[#111113] border-slate-800/60">
                            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1.5 gap-2">
                                <CardTitle className="text-xs font-medium text-slate-400 truncate">Win Rate</CardTitle>
                                <Target className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                            </CardHeader>
                            <CardContent>
                                <div className={`text-xl md:text-2xl font-bold ${stats.winRate >= 50 ? "text-emerald-400" : "text-yellow-400"}`}>
                                    {stats.winRate.toFixed(1)}%
                                </div>
                                <p className="text-[10px] text-slate-500 mt-0.5">{stats.totalTrades} trades</p>
                            </CardContent>
                        </Card>
                    </div>

                    {/* ── Row 2: Extended Metrics (two rows on mobile, one on desktop) ── */}
                    <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
                        {/* Sortino */}
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">Sortino</span>
                                <Scale className="h-3 w-3 text-slate-600" />
                            </div>
                            <div className={`text-lg font-bold ${stats.sortinoRatio >= 1 ? "text-emerald-400" : stats.sortinoRatio >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                                {stats.sortinoRatio.toFixed(2)}
                            </div>
                        </div>

                        {/* CAGR */}
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">CAGR</span>
                                <Percent className="h-3 w-3 text-slate-600" />
                            </div>
                            <div className={`text-lg font-bold ${stats.cagr >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                {stats.cagr.toFixed(2)}%
                            </div>
                        </div>

                        {/* Calmar */}
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">Calmar</span>
                                <BarChart3 className="h-3 w-3 text-slate-600" />
                            </div>
                            <div className={`text-lg font-bold ${stats.calmarRatio >= 1 ? "text-emerald-400" : "text-yellow-400"}`}>
                                {stats.calmarRatio.toFixed(2)}
                            </div>
                        </div>

                        {/* Profit Factor */}
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">Profit Factor</span>
                                <Activity className="h-3 w-3 text-slate-600" />
                            </div>
                            <div className={`text-lg font-bold ${stats.profitFactor >= 1 ? "text-emerald-400" : "text-red-400"}`}>
                                {stats.profitFactor.toFixed(2)}
                            </div>
                        </div>

                        {/* Expectancy */}
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">Expectancy</span>
                                <Zap className="h-3 w-3 text-slate-600" />
                            </div>
                            <div className={`text-lg font-bold ${stats.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                ₹{stats.expectancy.toFixed(2)}
                            </div>
                        </div>

                        {/* Brokerage */}
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider">Brokerage</span>
                                <IndianRupee className="h-3 w-3 text-slate-600" />
                            </div>
                            <div className="text-lg font-bold text-amber-400">
                                ₹{stats.brokeragePaid.toFixed(2)}
                            </div>
                        </div>
                    </div>

                    {/* ── Row 3: Avg Win/Loss inline ── */}
                    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3 flex items-center justify-between">
                            <div>
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5">Avg Win</span>
                                <span className="text-base font-bold text-emerald-400">₹{stats.avgWin.toFixed(2)}</span>
                            </div>
                            <TrendingUp className="h-4 w-4 text-emerald-500/40" />
                        </div>
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3 flex items-center justify-between">
                            <div>
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5">Avg Loss</span>
                                <span className="text-base font-bold text-red-400">₹{Math.abs(stats.avgLoss).toFixed(2)}</span>
                            </div>
                            <TrendingDown className="h-4 w-4 text-red-500/40" />
                        </div>
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3 flex items-center justify-between">
                            <div>
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5">Current Capital</span>
                                <span className="text-base font-bold text-white">{formatCurrency(100000 + stats.netProfit)}</span>
                            </div>
                            <IndianRupee className="h-4 w-4 text-slate-600" />
                        </div>
                        <div className="bg-[#111113] border border-slate-800/60 rounded-lg p-3 flex items-center justify-between">
                            <div>
                                <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-0.5">Total Trades</span>
                                <span className="text-base font-bold text-white">{stats.totalTrades}</span>
                            </div>
                            <Clock className="h-4 w-4 text-slate-600" />
                        </div>
                    </div>
                </>
            )}

            {/* Scanner & Volume */}
            <ScannerResults runId={runId} />

            {/* Equity Curve */}
            <Card className="bg-[#111113] border-slate-800/60">
                <CardHeader>
                    <CardTitle className="text-white text-lg">Equity Curve</CardTitle>
                </CardHeader>
                <CardContent className="h-[350px] md:h-[400px]">
                    <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={equityCurve}>
                            <defs>
                                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                            <XAxis dataKey="time" minTickGap={50} tick={{ fill: '#64748b', fontSize: 10 }} />
                            <YAxis domain={['auto', 'auto']} tick={{ fill: '#64748b', fontSize: 10 }} />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#111', border: '1px solid #333', borderRadius: '8px' }}
                                itemStyle={{ color: '#fff' }}
                                formatter={(value: number | string | undefined) => {
                                    const num = typeof value === 'number' ? value : 0;
                                    return [`₹${num.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`, 'Equity'];
                                }}
                            />
                            <Area
                                type="monotone"
                                dataKey="equity"
                                stroke="#22c55e"
                                strokeWidth={2}
                                fill="url(#equityGrad)"
                                dot={false}
                            />
                        </AreaChart>
                    </ResponsiveContainer>
                </CardContent>
            </Card>

            {/* Trades Table */}
            <Card className="bg-[#111113] border-slate-800/60">
                <CardHeader>
                    <CardTitle className="text-white text-lg">Executed Trades</CardTitle>
                </CardHeader>
                <CardContent className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow className="border-slate-800">
                                <TableHead className="text-slate-400">Time</TableHead>
                                <TableHead className="text-slate-400">Stock</TableHead>
                                <TableHead className="text-slate-400">Side</TableHead>
                                <TableHead className="text-slate-400">Quantity</TableHead>
                                <TableHead className="text-slate-400">Price</TableHead>
                                <TableHead className="text-slate-400">PnL</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {trades.slice().reverse().slice(0, visibleTradeCount).map((trade, i) => (
                                <TableRow key={i} className="border-slate-800/40 hover:bg-slate-800/20">
                                    <TableCell className="font-mono text-xs text-slate-300">{new Date(trade.time).toLocaleString()}</TableCell>
                                    <TableCell className={`text-slate-200 ${trade.symbol.startsWith('NSE_FO|') ? 'font-mono text-[11px] tracking-tight' : ''}`}>
                                        {formatSymbol(trade.symbol, trade.name)}
                                    </TableCell>
                                    <TableCell>
                                        <Badge variant={trade.side === 'BUY' ? 'default' : 'destructive'}
                                            className={trade.side === 'BUY'
                                                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                                : 'bg-red-500/20 text-red-400 border-red-500/30'
                                            }>
                                            {trade.side}
                                        </Badge>
                                    </TableCell>
                                    <TableCell className="text-slate-300">{trade.quantity}</TableCell>
                                    <TableCell className="text-slate-300">₹{trade.price.toFixed(2)}</TableCell>
                                    <TableCell className={`font-mono ${trade.pnl !== null && trade.pnl > 0 ? "text-emerald-400 font-bold" :
                                        trade.pnl !== null && trade.pnl < 0 ? "text-red-400 font-bold" :
                                            "text-slate-500"
                                        }`}>
                                        {trade.pnl !== null && trade.pnl !== 0
                                            ? `${trade.pnl > 0 ? '+' : ''}₹${trade.pnl.toFixed(2)}`
                                            : <span className="text-slate-600">—</span>}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                    {trades.length > visibleTradeCount && (
                        <div className="flex justify-center mt-4">
                            <Button
                                variant="outline"
                                className="border-slate-700 text-slate-300 hover:bg-slate-800"
                                onClick={() => setVisibleTradeCount(prev => prev + 200)}
                            >
                                Load More ({trades.length - visibleTradeCount} remaining)
                            </Button>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
