
"use client";

import React, { useState } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Link from 'next/link';
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
    SheetFooter,
} from "@/components/ui/sheet";
import { Play, Loader2, TrendingUp } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    Table,
    TableBody,
    TableCell,
    TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

export function BacktestRunner({ strategyName, strategyCode }: { strategyName: string, strategyCode: string }) {
    const [isOpen, setIsOpen] = useState(false);
    const [activeRunId, setActiveRunId] = useState<string | null>(null);
    const [lastRunId, setLastRunId] = useState<string | null>(null);
    const pollIntervalRef = React.useRef<NodeJS.Timeout | null>(null);

    const [isLoading, setIsLoading] = useState(false);
    const [logs, setLogs] = useState<string[]>([]);
    const [isComplete, setIsComplete] = useState(false);

    const [config, setConfig] = useState({
        symbol: "NSE_EQ|INE002A01018",
        startDate: "2024-01-01",
        endDate: "2024-01-10",
        cash: 100000
    });

    // Mock Stats
    const [stats, setStats] = useState({
        totalReturn: "+2.0%",
        netProfit: 500.0,
        sharpeRatio: 1.85,
        maxDrawdown: "-0.5%",
        winRate: "66.7%",
        totalTrades: 3,
        profitFactor: 1.5
    });

    interface Trade {
        time: string;
        symbol: string;
        side: string;
        quantity: number;
        price: number;
        pnl: number;
    }
    const [trades, setTrades] = useState<Trade[]>([]);

    const stopBacktest = async () => {
        if (!activeRunId) return;
        try {
            const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
            await fetch(`${API_URL}/api/v1/backtest/stop/${activeRunId}`, { method: 'POST' });
            setLogs(prev => [...prev, "🛑 Backtest stopped by user."]);

            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            setIsLoading(false);
            setIsComplete(true); // Treat as complete so we can see partial logs/trades
            setActiveRunId(null);
        } catch (e) {
            console.error("Failed to stop backtest", e);
            setLogs(prev => [...prev, "❌ Failed to stop backtest."]);
        }
    };

    const runBacktest = async () => {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

        setIsLoading(true);
        setIsComplete(false);
        setActiveRunId(null);
        setLogs(["🚀 Starting backtest...", `Strategy: ${strategyName}`, `Symbol: ${config.symbol}`]);

        try {
            const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

            // 1. Trigger Backtest
            const response = await fetch(`${API_URL}/api/v1/backtest/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    strategy_code: strategyCode, // Pass actual code from IDE
                    symbol: config.symbol,
                    start_date: config.startDate,
                    end_date: config.endDate,
                    initial_cash: config.cash,
                    strategy_name: strategyName
                })
            });

            if (!response.ok) throw new Error("Failed to start backtest");

            const data = await response.json();
            const runId = data.run_id;
            setActiveRunId(runId);
            setLastRunId(runId);
            setLogs(prev => [...prev, `✅ Job Started: ${runId}`, "⏳ Waiting for logs..."]);

            // 2. Poll Logs
            pollIntervalRef.current = setInterval(async () => {
                try {
                    const logRes = await fetch(`${API_URL}/api/v1/backtest/logs/${runId}`);
                    if (logRes.ok) {
                        const logData = await logRes.json();
                        setLogs(logData.logs); // Replace logs with full history

                        // Check for completion
                        const isFinished = logData.logs.some((l: string) => l.includes("Backtest Runner Finished") || l.includes("Backtest Stopped by User"));

                        if (isFinished) {
                            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                            setIsLoading(false);
                            setIsComplete(true);
                            setActiveRunId(null);

                            if (!logs.includes("🏁 Execution Finished.")) {
                                setLogs(prev => [...prev, "🏁 Execution Finished."]);
                            }

                            // Valid JSON logs usually come as stringified JSON in the last line or separate endpoint
                            // For now, we fetch trades from the API
                            try {
                                const tradesRes = await fetch(`${API_URL}/api/v1/backtest/trades/${runId}`);
                                if (tradesRes.ok) {
                                    const tradesData = await tradesRes.json();
                                    setTrades(tradesData);

                                    // Calculate simple stats from trades if possible
                                    const totalPnL = tradesData.reduce((acc: number, t: Trade) => acc + (t.pnl || 0), 0);
                                    setStats(prev => ({
                                        ...prev,
                                        totalTrades: tradesData.length,
                                        netProfit: totalPnL,
                                        totalReturn: `${((totalPnL / config.cash) * 100).toFixed(2)}%`
                                    }));
                                }
                            } catch (err) {
                                console.error("Failed to fetch trades", err);
                            }
                        }
                    }
                } catch (e) {
                    console.error("Polling error", e);
                }
            }, 2000);

        } catch (error) {
            setLogs(prev => [...prev, `❌ Error: ${error}`]);
            setIsLoading(false);
            setActiveRunId(null);
        }
    };

    return (
        <Sheet open={isOpen} onOpenChange={setIsOpen}>
            <SheetTrigger asChild>
                <div className="flex gap-2">
                    <Button size="sm">
                        <Play className="mr-2 h-4 w-4" /> Run Backtest
                    </Button>
                    {isComplete && lastRunId && (
                        <Link href={`/dashboard/backtest/${lastRunId}`} target="_blank">
                            <Button size="sm" variant="outline">
                                <TrendingUp className="mr-2 h-4 w-4" /> View Dashboard
                            </Button>
                        </Link>
                    )}
                </div>
            </SheetTrigger>
            <SheetContent className="w-[500px] sm:w-[600px] flex flex-col">
                <SheetHeader>
                    <SheetTitle>Backtest Manager</SheetTitle>
                    <SheetDescription>
                        {strategyName}
                    </SheetDescription>
                </SheetHeader>

                <Tabs defaultValue="config" className="flex-1 flex flex-col mt-4">
                    <TabsList className="grid w-full grid-cols-3">
                        <TabsTrigger value="config">Config</TabsTrigger>
                        <TabsTrigger value="logs">Logs</TabsTrigger>
                        <TabsTrigger value="stats" disabled={!isComplete}>Result</TabsTrigger>
                    </TabsList>

                    <TabsContent value="config" className="flex-1 py-4">
                        <div className="grid gap-4">
                            {/* Symbol Input Removed as per user request (Strategy defines Universe) */}
                            {/* 
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="symbol" className="text-right">Symbol</Label>
                                <Input
                                    id="symbol"
                                    value={config.symbol}
                                    onChange={(e) => setConfig({ ...config, symbol: e.target.value })}
                                    className="col-span-3"
                                />
                            </div> 
                            */}
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="start" className="text-right">Start</Label>
                                <Input
                                    id="start"
                                    type="date"
                                    value={config.startDate}
                                    onChange={(e) => setConfig({ ...config, startDate: e.target.value })}
                                    className="col-span-3"
                                />
                            </div>
                            <div className="grid grid-cols-4 items-center gap-4">
                                <Label htmlFor="end" className="text-right">End</Label>
                                <Input
                                    id="end"
                                    type="date"
                                    value={config.endDate}
                                    onChange={(e) => setConfig({ ...config, endDate: e.target.value })}
                                    className="col-span-3"
                                />
                            </div>
                        </div>
                    </TabsContent>

                    <TabsContent value="logs" className="flex-1 h-full flex flex-col">
                        <div className="flex-1 bg-black text-green-400 font-mono text-xs p-4 rounded-md overflow-y-auto border border-zinc-800 min-h-[300px]">
                            {logs.length === 0 ? (
                                <span className="text-zinc-500">Waiting to start...</span>
                            ) : (
                                logs.map((log, i) => <div key={i}>{log}</div>)
                            )}
                            {isLoading && <Loader2 className="h-4 w-4 animate-spin mt-2" />}
                        </div>
                    </TabsContent>

                    <TabsContent value="stats" className="flex-1">
                        <div className="border rounded-md p-4 space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="font-semibold text-lg">Performance Summary</h3>
                                <Badge variant={stats.netProfit > 0 ? "default" : "destructive"} className="text-md px-3 py-1">
                                    {stats.totalReturn}
                                </Badge>
                            </div>

                            <Table>
                                <TableBody>
                                    <TableRow>
                                        <TableCell className="font-medium">Net Profit</TableCell>
                                        <TableCell className={stats.netProfit >= 0 ? "text-green-500" : "text-red-500"}>
                                            ₹{stats.netProfit.toFixed(2)}
                                        </TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell className="font-medium">Sharpe Ratio</TableCell>
                                        <TableCell>{stats.sharpeRatio}</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell className="font-medium">Max Drawdown</TableCell>
                                        <TableCell className="text-red-500">{stats.maxDrawdown}</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell className="font-medium">Win Rate</TableCell>
                                        <TableCell>{stats.winRate}</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell className="font-medium">Total Trades</TableCell>
                                        <TableCell>{stats.totalTrades}</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell className="font-medium">Profit Factor</TableCell>
                                        <TableCell>{stats.profitFactor}</TableCell>
                                    </TableRow>
                                </TableBody>
                            </Table>
                        </div>
                    </TabsContent>

                </Tabs>


                <SheetFooter className="mt-4">
                    {isLoading ? (
                        <Button onClick={stopBacktest} variant="destructive" className="w-full">
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Stop Backtest
                        </Button>
                    ) : (
                        <Button onClick={runBacktest} className="w-full">
                            <Play className="mr-2 h-4 w-4" /> Run Backtest
                        </Button>
                    )}
                </SheetFooter>
            </SheetContent>
        </Sheet>
    );
}
