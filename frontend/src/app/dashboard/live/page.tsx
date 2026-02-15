"use client";

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowLeft, RefreshCw, StopCircle, Activity } from 'lucide-react';
import Link from 'next/link';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

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
    holdings: Holding[];
}

export default function LiveDashboardPage() {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
    const [status, setStatus] = useState<LiveStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [equityHistory, setEquityHistory] = useState<{ time: string, value: number }[]>([]);

    const fetchStatus = React.useCallback(async () => {
        try {
            const res = await fetch(`${API_URL}/api/v1/live/status`);
            const data = await res.json();
            setStatus(data);

            if (data.status === 'running') {
                setEquityHistory(prev => {
                    const now = new Date().toLocaleTimeString();
                    // Keep last 50 points
                    const newHist = [...prev, { time: now, value: data.equity }];
                    if (newHist.length > 50) newHist.shift();
                    return newHist;
                });
            }
            setError(null);
        } catch (e) {
            console.error("Failed to fetch live status", e);
            setError("Failed to connect to Strategy Runtime");
            setStatus(null);
        } finally {
            setLoading(false);
        }
    }, [API_URL]);

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 2000);
        return () => clearInterval(interval);
    }, [fetchStatus]);

    const handleStop = async () => {
        if (!confirm("Are you sure you want to stop the live strategy?")) return;
        try {
            await fetch(`${API_URL}/api/v1/live/stop`, { method: 'POST' });
            fetchStatus();
        } catch (e) {
            console.error("Stop failed", e);
            alert("Failed to stop strategy");
        }
    };

    if (loading) return <div className="p-8">Loading Dashboard...</div>;

    if (error) {
        return (
            <div className="min-h-screen bg-background p-8 flex flex-col items-center justify-center gap-4">
                <Alert variant="destructive" className="max-w-md">
                    <Activity className="h-4 w-4" />
                    <AlertTitle>Error</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
                <Link href="/">
                    <Button>
                        <ArrowLeft className="mr-2 h-4 w-4" /> Back to Home
                    </Button>
                </Link>
            </div>
        );
    }

    if (!status || status.status !== 'running') {
        return (
            <div className="min-h-screen bg-background p-8 flex flex-col items-center justify-center gap-4">
                <Alert className="max-w-md">
                    <Activity className="h-4 w-4" />
                    <AlertTitle>No Active Strategy</AlertTitle>
                    <AlertDescription>
                        There is no live strategy running currently.
                    </AlertDescription>
                </Alert>
                <Link href="/">
                    <Button>
                        <ArrowLeft className="mr-2 h-4 w-4" /> Back to Home
                    </Button>
                </Link>
            </div>
        );
    }

    const totalPnL = status.equity - 100000; // Assuming 100k start, ideally should come from backend
    const pnlColor = totalPnL >= 0 ? "text-green-500" : "text-red-500";

    return (
        <div className="min-h-screen bg-background flex flex-col">
            {/* Header */}
            <header className="border-b px-6 py-3 flex items-center justify-between bg-card">
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div>
                        <h1 className="text-xl font-bold flex items-center gap-2">
                            Live Trading
                            <Badge variant="default" className="bg-green-500 animate-pulse">LIVE</Badge>
                        </h1>
                        <p className="text-sm text-muted-foreground">{status.strategy}</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={fetchStatus}>
                        <RefreshCw className="mr-1 h-3 w-3" /> Refresh
                    </Button>
                    <Button variant="destructive" size="sm" onClick={handleStop}>
                        <StopCircle className="mr-2 h-4 w-4" /> Stop Strategy
                    </Button>
                </div>
            </header>

            <main className="flex-1 p-6 grid grid-cols-1 md:grid-cols-3 gap-6 overflow-y-auto">

                {/* Left Column: Stats & Positions */}
                <div className="md:col-span-2 space-y-6">
                    {/* Key Metrics */}
                    <div className="grid grid-cols-3 gap-4">
                        <Card>
                            <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Total Equity</CardTitle></CardHeader>
                            <CardContent>
                                <div className="text-2xl font-bold">₹{status.equity.toLocaleString()}</div>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Cash Balance</CardTitle></CardHeader>
                            <CardContent>
                                <div className="text-2xl font-bold">₹{status.cash.toLocaleString()}</div>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">Net P&L</CardTitle></CardHeader>
                            <CardContent>
                                <div className={`text-2xl font-bold ${pnlColor}`}>
                                    {totalPnL > 0 ? "+" : ""}₹{totalPnL.toLocaleString()}
                                </div>
                            </CardContent>
                        </Card>
                    </div>

                    {/* Equity Chart */}
                    <Card className="h-[300px]">
                        <CardHeader><CardTitle>Equity Curve (Live)</CardTitle></CardHeader>
                        <CardContent className="h-[250px]">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={equityHistory}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                                    <XAxis dataKey="time" hide />
                                    <YAxis domain={['auto', 'auto']} />
                                    <Tooltip />
                                    <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} />
                                </LineChart>
                            </ResponsiveContainer>
                        </CardContent>
                    </Card>

                    {/* Positions */}
                    <Card>
                        <CardHeader><CardTitle>Open Positions</CardTitle></CardHeader>
                        <CardContent>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Symbol</TableHead>
                                        <TableHead className="text-right">Qty</TableHead>
                                        <TableHead className="text-right">Avg Price</TableHead>
                                        <TableHead className="text-right">LTP</TableHead>
                                        <TableHead className="text-right">PnL</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {(!status.holdings || status.holdings.length === 0) ? (
                                        <TableRow>
                                            <TableCell colSpan={5} className="text-center text-muted-foreground">No open positions</TableCell>
                                        </TableRow>
                                    ) : (
                                        status.holdings.map((h) => (
                                            <TableRow key={h.symbol}>
                                                <TableCell className="font-medium">{h.symbol}</TableCell>
                                                <TableCell className="text-right">{h.quantity}</TableCell>
                                                <TableCell className="text-right">₹{h.avg_price?.toFixed(2) || '0.00'}</TableCell>
                                                <TableCell className="text-right">₹{h.current_price?.toFixed(2) || '0.00'}</TableCell>
                                                <TableCell className={`text-right ${h.unrealized_pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                                                    {h.unrealized_pnl > 0 ? "+" : ""}₹{h.unrealized_pnl?.toFixed(2) || '0.00'}
                                                </TableCell>
                                            </TableRow>
                                        ))
                                    )}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </div>

                {/* Right Column: Recent Activity / Logs (Placeholder for now) */}
                <div className="space-y-6">
                    <Card className="h-full flex flex-col">
                        <CardHeader><CardTitle>System Activity</CardTitle></CardHeader>
                        <CardContent className="flex-1 bg-black/50 text-xs font-mono p-4 rounded-md mx-4 mb-4 overflow-y-auto">
                            <div className="text-muted-foreground">Real-time logs will appear here</div>
                            <div className="text-green-500">System Connected.</div>
                            <div className="text-green-500">Monitoring {status.strategy}...</div>
                        </CardContent>
                    </Card>
                </div>

            </main>
        </div>
    );
}
