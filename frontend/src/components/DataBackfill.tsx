
"use client";

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Database, Download, CheckCircle2, Loader2, XCircle } from 'lucide-react';

interface BackfillStatus {
    running: boolean;
    finished: boolean;
    total_stocks: number;
    completed_stocks: number;
    current_stock: string;
    current_stock_progress: number;
    overall_progress: number;
    total_candles: number;
    logs: string[];
    error: string | null;
}

export function DataBackfill() {
    const [startDate, setStartDate] = useState('2025-01-01');
    const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);
    const [status, setStatus] = useState<BackfillStatus | null>(null);
    const [isStarting, setIsStarting] = useState(false);
    const [expanded, setExpanded] = useState(false);

    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

    const pollStatus = useCallback(async () => {
        try {
            const res = await fetch(`${API_URL}/api/v1/backfill/status`);
            if (res.ok) {
                const data = await res.json();
                setStatus(data);
                return data.running;
            }
        } catch {
            // Service not available yet
        }
        return false;
    }, [API_URL]);

    // Poll while running
    useEffect(() => {
        let interval: NodeJS.Timeout;
        if (status?.running) {
            interval = setInterval(async () => {
                const still = await pollStatus();
                if (!still) clearInterval(interval);
            }, 2000);
        }
        return () => { if (interval) clearInterval(interval); };
    }, [status?.running, pollStatus]);

    const handleStart = async () => {
        setIsStarting(true);
        try {
            const res = await fetch(`${API_URL}/api/v1/backfill/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_date: startDate,
                    end_date: endDate,
                    stocks: null,  // all stocks
                    interval: "1",
                    unit: "minutes"
                }),
            });
            if (res.ok) {
                setExpanded(true);
                // Start polling
                setTimeout(pollStatus, 1000);
                // Set a temporary running state
                setStatus(prev => prev ? { ...prev, running: true } : {
                    running: true, finished: false, total_stocks: 20, completed_stocks: 0,
                    current_stock: "Starting...", current_stock_progress: 0, overall_progress: 0,
                    total_candles: 0, logs: ["🚀 Starting backfill..."], error: null
                });
            } else {
                const err = await res.text();
                alert(`Failed to start: ${err}`);
            }
        } catch (e) {
            alert(`Error: ${e}`);
        }
        setIsStarting(false);
    };

    const isRunning = status?.running;
    const isFinished = status?.finished;
    const hasError = status?.error;

    return (
        <Card className="border-dashed">
            <CardHeader className="cursor-pointer pb-3" onClick={() => setExpanded(!expanded)}>
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Database className="h-5 w-5 text-blue-500" />
                        <CardTitle className="text-base">Market Data Backfill</CardTitle>
                        {isRunning && <Badge variant="secondary" className="bg-yellow-500/20 text-yellow-400 animate-pulse">Running</Badge>}
                        {isFinished && !isRunning && <Badge variant="secondary" className="bg-green-500/20 text-green-400">Complete</Badge>}
                    </div>
                    <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>
                        {expanded ? '▲' : '▼'}
                    </Button>
                </div>
                {!expanded && <CardDescription>Download historical OHLC data for 20 Nifty 50 stocks</CardDescription>}
            </CardHeader>

            {expanded && (
                <CardContent className="space-y-4">
                    {/* Config Row */}
                    {!isRunning && (
                        <div className="flex items-end gap-4">
                            <div className="space-y-1">
                                <Label className="text-xs text-muted-foreground">Start Date</Label>
                                <Input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="w-40 h-8 text-sm" />
                            </div>
                            <div className="space-y-1">
                                <Label className="text-xs text-muted-foreground">End Date</Label>
                                <Input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="w-40 h-8 text-sm" />
                            </div>
                            <Button onClick={handleStart} disabled={isStarting} size="sm" className="h-8">
                                {isStarting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Download className="h-4 w-4 mr-1" />}
                                {isStarting ? 'Starting...' : 'Download All Stocks'}
                            </Button>
                        </div>
                    )}

                    {/* Progress Section */}
                    {status && (isRunning || isFinished || hasError) && (
                        <div className="space-y-3">
                            {/* Overall Progress */}
                            <div className="space-y-1">
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">
                                        Overall: {status.completed_stocks}/{status.total_stocks} stocks
                                    </span>
                                    <span className="font-mono font-bold">{status.overall_progress}%</span>
                                </div>
                                <Progress value={status.overall_progress} className="h-3" />
                            </div>

                            {/* Current Stock */}
                            {isRunning && (
                                <div className="space-y-1">
                                    <div className="flex justify-between text-xs">
                                        <span className="flex items-center gap-1">
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                            {status.current_stock}
                                        </span>
                                        <span className="font-mono">{status.current_stock_progress}%</span>
                                    </div>
                                    <Progress value={status.current_stock_progress} className="h-1.5" />
                                </div>
                            )}

                            {/* Stats Row */}
                            <div className="flex gap-4 text-xs text-muted-foreground">
                                <span>📊 {status.total_candles.toLocaleString()} candles downloaded</span>
                                {isFinished && <span className="text-green-500 flex items-center gap-1"><CheckCircle2 className="h-3 w-3" /> Done!</span>}
                                {hasError && <span className="text-red-500 flex items-center gap-1"><XCircle className="h-3 w-3" /> {status.error}</span>}
                            </div>

                            {/* Logs */}
                            <div className="bg-black/50 rounded-md p-2 max-h-[120px] overflow-y-auto border border-zinc-800">
                                {status.logs.map((log, i) => (
                                    <div key={i} className="text-xs font-mono text-zinc-400">{log}</div>
                                ))}
                            </div>
                        </div>
                    )}
                </CardContent>
            )}
        </Card>
    );
}
