
"use client";

import React, { useState } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
    SheetFooter,
} from "@/components/ui/sheet";
import { Play, Loader2 } from 'lucide-react';
// import { api } from '@/lib/api';

export function BacktestRunner({ strategyName }: { strategyName: string, strategyCode: string }) {
    const [isOpen, setIsOpen] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [logs, setLogs] = useState<string[]>([]);

    const [config, setConfig] = useState({
        symbol: "NSE_EQ|INE002A01018",
        startDate: "2024-01-01",
        endDate: "2024-01-10",
        cash: 100000
    });

    const runBacktest = async () => {
        setIsLoading(true);
        setLogs(["🚀 Starting backtest...", `Strategy: ${strategyName}`, `Symbol: ${config.symbol}`]);

        try {
            // Mocking API call for now
            // await api.post('/backtest/run', { ...config, code: strategyCode });

            // Simulate logs
            setTimeout(() => setLogs(prev => [...prev, "📥 Downloading data..."]), 1000);
            setTimeout(() => setLogs(prev => [...prev, "⚙️ Initializing Engine..."]), 2000);
            setTimeout(() => setLogs(prev => [...prev, "🟢 Market Open"]), 2500);
            setTimeout(() => setLogs(prev => [...prev, "💰 BUY 10 @ 2450.0"]), 3000);
            setTimeout(() => setLogs(prev => [...prev, "💰 SELL 10 @ 2500.0"]), 4000);
            setTimeout(() => setLogs(prev => [...prev, "🔴 Market Close"]), 4500);
            setTimeout(() => {
                setLogs(prev => [...prev, "✅ Backtest Complete. P&L: +500.0 (2.0%)"]);
                setIsLoading(false);
            }, 5000);

        } catch {
            setLogs(prev => [...prev, "❌ Error starting backtest"]);
            setIsLoading(false);
        }
    };

    return (
        <Sheet open={isOpen} onOpenChange={setIsOpen}>
            <SheetTrigger asChild>
                <Button size="sm">
                    <Play className="mr-2 h-4 w-4" /> Run Backtest
                </Button>
            </SheetTrigger>
            <SheetContent className="w-[400px] sm:w-[540px] flex flex-col">
                <SheetHeader>
                    <SheetTitle>Run Backtest</SheetTitle>
                    <SheetDescription>
                        Configure parameters for {strategyName}
                    </SheetDescription>
                </SheetHeader>

                <div className="grid gap-4 py-4">
                    <div className="grid grid-cols-4 items-center gap-4">
                        <Label htmlFor="symbol" className="text-right">Symbol</Label>
                        <Input
                            id="symbol"
                            value={config.symbol}
                            onChange={(e) => setConfig({ ...config, symbol: e.target.value })}
                            className="col-span-3"
                        />
                    </div>
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

                <div className="flex-1 bg-black text-green-400 font-mono text-xs p-4 rounded-md overflow-y-auto border border-zinc-800">
                    {logs.length === 0 ? (
                        <span className="text-zinc-500">Waiting to start...</span>
                    ) : (
                        logs.map((log, i) => <div key={i}>{log}</div>)
                    )}
                    {isLoading && <Loader2 className="h-4 w-4 animate-spin mt-2" />}
                </div>

                <SheetFooter className="mt-4">
                    <Button onClick={runBacktest} disabled={isLoading} className="w-full">
                        {isLoading ? "Running..." : "Start Backtest"}
                    </Button>
                </SheetFooter>
            </SheetContent>
        </Sheet>
    );
}
