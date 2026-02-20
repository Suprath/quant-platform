"use client";

import React, { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Loader2, TrendingUp, Activity, IndianRupee } from 'lucide-react';
import Link from 'next/link';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { ScannerResults } from "@/components/ScannerResults";

interface Trade {
    time: string;
    symbol: string;
    name: string;
    side: 'BUY' | 'SELL';
    quantity: number;
    price: number;
    pnl: number;
}

interface Stats {
    netProfit: number;
    totalReturn: number; // percentage
    maxDrawdown: number; // percentage
    winRate: number; // percentage
    totalTrades: number;
    sharpeRatio: number;
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
    // const [logs, setLogs] = useState<string[]>([]); // Unused for now
    const [loading, setLoading] = useState(true);
    const [stats, setStats] = useState<Stats | null>(null);
    const [equityCurve, setEquityCurve] = useState<EquityCurvePoint[]>([]);

    useEffect(() => {
        if (!runId) return;

        const fetchData = async () => {
            try {
                const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

                // Fetch Trades & Stats
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

    const processBacktestData = (tradesData: Trade[], statsData: Record<string, number> | null) => {
        setTrades(tradesData);

        const initialCash = 100000; // Default if not provided
        let currentEquity = initialCash;
        let estBrokerage = 0;

        // Equity Curve Generation
        const curve = [{ time: 'Start', equity: initialCash }];

        tradesData.forEach(t => {
            // Estimate Brokerage
            const turnover = t.price * Math.abs(t.quantity);
            const flat = Math.min(20, turnover * 0.0003);
            const stt = t.side === 'SELL' ? turnover * 0.00025 : 0;
            const gst = flat * 0.18;
            estBrokerage += flat + stt + gst;

            if (t.pnl !== 0) {
                currentEquity += t.pnl;
                curve.push({
                    time: new Date(t.time).toLocaleTimeString(),
                    equity: currentEquity
                });
            }
        });

        if (statsData && statsData.sharpe_ratio !== undefined) {
            setStats({
                netProfit: statsData.net_profit,
                totalReturn: statsData.total_return,
                maxDrawdown: statsData.max_drawdown,
                winRate: statsData.win_rate,
                totalTrades: statsData.total_trades,
                sharpeRatio: statsData.sharpe_ratio,
                brokeragePaid: estBrokerage
            });
        } else {
            // Fallback purely on frontend calculation if stats missing
            const netProfit = currentEquity - initialCash;
            const totalReturn = (netProfit / initialCash) * 100;
            const wins = tradesData.filter(t => t.pnl > 0).length;
            const winRate = tradesData.filter(t => t.pnl !== 0).length > 0
                ? (wins / tradesData.filter(t => t.pnl !== 0).length) * 100
                : 0;

            setStats({
                netProfit,
                totalReturn,
                maxDrawdown: 0,
                winRate,
                totalTrades: tradesData.length,
                sharpeRatio: 0,
                brokeragePaid: estBrokerage
            });
        }

        setEquityCurve(curve);
    };

    if (loading) {
        return (
            <div className="flex h-screen items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                <span className="ml-2">Loading Backtest Results...</span>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <Link href="/ide">
                        <Button variant="outline" size="icon">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight">Backtest Results</h1>
                        <p className="text-muted-foreground text-sm font-mono">{runId}</p>
                    </div>
                </div>
                <div>
                    {/* Export / Share Actions could go here */}
                </div>
            </div>

            {/* Stats Cards */}
            {stats && (
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Net Profit</CardTitle>
                            <IndianRupee className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className={`text-2xl font-bold ${stats.netProfit >= 0 ? "text-green-500" : "text-red-500"}`}>
                                {stats.netProfit >= 0 ? "+" : "-"}₹{Math.abs(stats.netProfit).toFixed(2)}
                            </div>
                            <p className="text-xs text-muted-foreground">
                                {stats.totalReturn > 0 ? "+" : ""}{stats.totalReturn.toFixed(2)}% Return
                            </p>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Current Capital</CardTitle>
                            <IndianRupee className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold">₹{(100000 + stats.netProfit).toFixed(2)}</div>
                            <p className="text-xs text-muted-foreground">
                                Starting: ₹100,000
                            </p>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Max Drawdown</CardTitle>
                            <Activity className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold text-red-500">
                                {stats.maxDrawdown > 0 ? `-${stats.maxDrawdown.toFixed(2)}%` : '0.00%'}
                            </div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Sharpe Ratio</CardTitle>
                            <TrendingUp className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold">{stats.sharpeRatio.toFixed(2)}</div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Estimated Brokerage</CardTitle>
                            <IndianRupee className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold text-yellow-500">
                                ₹{stats.brokeragePaid.toFixed(2)}
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}

            {/* Scanner & Volume Visuals */}
            <ScannerResults runId={runId} />

            {/* Equity Curve */}
            <Card>
                <CardHeader>
                    <CardTitle>Equity Curve</CardTitle>
                </CardHeader>
                <CardContent className="h-[400px]">
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={equityCurve}>
                            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                            <XAxis dataKey="time" minTickGap={50} />
                            <YAxis domain={['auto', 'auto']} />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#111', border: '1px solid #333' }}
                                itemStyle={{ color: '#fff' }}
                            />
                            <Line
                                type="monotone"
                                dataKey="equity"
                                stroke="#22c55e"
                                strokeWidth={2}
                                dot={false}
                            />
                        </LineChart>
                    </ResponsiveContainer>
                </CardContent>
            </Card>

            {/* Trades Table */}
            <Card>
                <CardHeader>
                    <CardTitle>Executed Trades</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Time</TableHead>
                                <TableHead>Stock</TableHead>
                                <TableHead>Side</TableHead>
                                <TableHead>Quantity</TableHead>
                                <TableHead>Price</TableHead>
                                <TableHead>PnL</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {trades.slice().reverse().map((trade, i) => (
                                <TableRow key={i}>
                                    <TableCell className="font-mono text-xs">{new Date(trade.time).toLocaleString()}</TableCell>
                                    <TableCell>{trade.name !== trade.symbol ? trade.name : trade.symbol}</TableCell>
                                    <TableCell>
                                        <Badge variant={trade.side === 'BUY' ? 'default' : 'destructive'}>{trade.side}</Badge>
                                    </TableCell>
                                    <TableCell>{trade.quantity}</TableCell>
                                    <TableCell>₹{trade.price.toFixed(2)}</TableCell>
                                    <TableCell className={trade.pnl > 0 ? "text-green-500 font-bold" : trade.pnl < 0 ? "text-red-500 font-bold" : ""}>
                                        {trade.pnl !== 0 ? `₹${trade.pnl.toFixed(2)}` : '-'}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>
        </div>
    );
}
