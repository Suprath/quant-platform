"use client";

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Play, Square, Activity, Loader2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import Link from 'next/link';

interface LiveStatus {
    status: string;
    strategy?: string;
    cash?: number;
    message?: string;
}

interface Strategy {
    name: string;
    value: string;
    file: string;
}

export function LiveTradingControl() {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [selectedStrategy, setSelectedStrategy] = useState<string>("");
    const [capital, setCapital] = useState<string>("100000");
    const [status, setStatus] = useState<LiveStatus | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            // Fetch Strategies
            try {
                const res = await fetch(`${API_URL}/api/v1/strategies`);
                const data = await res.json();
                setStrategies(data.strategies || []);
            } catch (e) {
                console.error("Failed to fetch strategies", e);
                setError("Failed to load strategies");
            }

            // Fetch Status
            try {
                const res = await fetch(`${API_URL}/api/v1/live/status`);
                const data = await res.json();
                setStatus(data);
            } catch {
                // Silent fail for status polling
            }
        };

        fetchData();
        const interval = setInterval(fetchData, 3000); // Poll
        return () => clearInterval(interval);
    }, [API_URL]);

    const handleStart = async () => {
        if (!selectedStrategy) return;
        setLoading(true);
        setError(null);
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
                setError(data.message);
            } else {
                // Refresh status immediately
                const statusRes = await fetch(`${API_URL}/api/v1/live/status`);
                setStatus(await statusRes.json());
            }
        } catch (e) {
            console.error("Start failed", e);
            setError("Failed to start strategy");
        } finally {
            setLoading(false);
        }
    };

    const handleStop = async () => {
        setLoading(true);
        setError(null);
        try {
            await fetch(`${API_URL}/api/v1/live/stop`, { method: 'POST' });
            // Refresh status immediately
            const statusRes = await fetch(`${API_URL}/api/v1/live/status`);
            setStatus(await statusRes.json());
        } catch (e) {
            console.error("Stop failed", e);
            setError("Failed to stop strategy");
        } finally {
            setLoading(false);
        }
    };

    const isRunning = status?.status === 'running';

    return (
        <Card className="w-full">
            <CardHeader>
                <div className="flex justify-between items-center">
                    <div>
                        <CardTitle className="flex items-center gap-2">
                            <Activity className="h-5 w-5 text-blue-500" />
                            Live Paper Trading
                        </CardTitle>
                        <CardDescription>Execute strategies with simulated market execution</CardDescription>
                    </div>
                    {isRunning && (
                        <Badge variant="default" className="bg-green-500 animate-pulse">
                            ACTIVE: {status.strategy?.split('.').pop()}
                        </Badge>
                    )}
                    {!isRunning && (
                        <Badge variant="secondary">STOPPED</Badge>
                    )}
                </div>
            </CardHeader>
            <CardContent className="space-y-4">
                {error && (
                    <Alert variant="destructive">
                        <AlertTitle>Error</AlertTitle>
                        <AlertDescription>{error}</AlertDescription>
                    </Alert>
                )}
                {isRunning ? (
                    <div className="grid grid-cols-2 gap-4">
                        <div className="p-4 bg-muted/50 rounded-lg">
                            <h3 className="text-sm font-medium text-muted-foreground">Cash Balance</h3>
                            <p className="text-2xl font-bold">₹{status?.cash?.toLocaleString()}</p>
                        </div>
                        <div className="p-4 bg-muted/50 rounded-lg">
                            <h3 className="text-sm font-medium text-muted-foreground">Status</h3>
                            <p className="text-lg font-medium text-green-600">Running</p>
                        </div>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Select Strategy</label>
                            <Select onValueChange={setSelectedStrategy} value={selectedStrategy}>
                                <SelectTrigger>
                                    <SelectValue placeholder="Choose Algorithm..." />
                                </SelectTrigger>
                                <SelectContent>
                                    {strategies.map((s) => (
                                        <SelectItem key={s.value} value={s.value}>
                                            {s.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">Initial Capital (₹)</label>
                            <Input
                                type="number"
                                value={capital}
                                onChange={(e) => setCapital(e.target.value)}
                            />
                        </div>
                    </div>
                )}
            </CardContent>
            <CardFooter className="justify-end gap-2 border-t pt-4">
                {isRunning ? (
                    <>
                        <Button variant="destructive" onClick={handleStop} disabled={loading}>
                            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                            <Square className="mr-2 h-4 w-4 fill-current" /> Stop Strategy
                        </Button>
                        <Link href="/dashboard/live" className="ml-2">
                            <Button variant="secondary">
                                <Activity className="mr-2 h-4 w-4" /> View Dashboard
                            </Button>
                        </Link>
                    </>
                ) : (
                    <Button onClick={handleStart} disabled={loading || !selectedStrategy} className="bg-green-600 hover:bg-green-700 text-white">
                        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        <Play className="mr-2 h-4 w-4 fill-current" /> Start Live Trading
                    </Button>
                )}
            </CardFooter>
        </Card>
    );
}
