"use client";

import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Play, Square, Loader2 } from 'lucide-react';

const API_URL = "http://localhost:8002";

export function ESTIControls() {
    const [loading, setLoading] = useState(false);
    const [isRunning, setIsRunning] = useState(false);

    // Form State
    const [config, setConfig] = useState({
        startDate: "2024-01-01",
        endDate: "2025-01-01",
        trainWindow: 60,
        testWindow: 20
    });

    const handleStart = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_URL}/train/walk-forward`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    start_date: config.startDate,
                    end_date: config.endDate,
                    train_window_days: Number(config.trainWindow),
                    test_window_days: Number(config.testWindow)
                })
            });
            if (res.ok) setIsRunning(true);
        } catch (err) {
            console.error("Start failed", err);
        } finally {
            setLoading(false);
        }
    };

    const handleStop = async () => {
        setLoading(true);
        try {
            await fetch(`${API_URL}/train/stop`, { method: "POST" });
            setIsRunning(false);
        } catch (err) {
            console.error("Stop failed", err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card className="bg-black/40 backdrop-blur-md border-white/10 shadow-2xl">
            <CardHeader className="pb-4 border-b border-white/10">
                <CardTitle className="text-slate-200 font-semibold tracking-wide">
                    Training Controls
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6 pt-6">
                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label className="text-slate-400 text-xs uppercase tracking-wider">Start Date</Label>
                        <Input
                            type="date"
                            value={config.startDate}
                            onChange={(e) => setConfig({ ...config, startDate: e.target.value })}
                            className="bg-black/50 border-white/10 text-slate-200 focus-visible:ring-indigo-500 focus-visible:border-indigo-500"
                        />
                    </div>
                    <div className="space-y-2">
                        <Label className="text-slate-400 text-xs uppercase tracking-wider">End Date</Label>
                        <Input
                            type="date"
                            value={config.endDate}
                            onChange={(e) => setConfig({ ...config, endDate: e.target.value })}
                            className="bg-black/50 border-white/10 text-slate-200 focus-visible:ring-indigo-500 focus-visible:border-indigo-500"
                        />
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label className="text-slate-400 text-xs uppercase tracking-wider">Train (Days)</Label>
                        <Input
                            type="number"
                            value={config.trainWindow}
                            onChange={(e) => setConfig({ ...config, trainWindow: Number(e.target.value) })}
                            className="bg-black/50 border-white/10 text-slate-200 focus-visible:ring-indigo-500 focus-visible:border-indigo-500"
                        />
                    </div>
                    <div className="space-y-2">
                        <Label className="text-slate-400 text-xs uppercase tracking-wider">Test (Days)</Label>
                        <Input
                            type="number"
                            value={config.testWindow}
                            onChange={(e) => setConfig({ ...config, testWindow: Number(e.target.value) })}
                            className="bg-black/50 border-white/10 text-slate-200 focus-visible:ring-indigo-500 focus-visible:border-indigo-500"
                        />
                    </div>
                </div>

                <div className="pt-4 border-t border-white/10">
                    {!isRunning ? (
                        <Button
                            className="w-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 hover:text-emerald-300 transition-all font-semibold tracking-wide shadow-[0_0_15px_rgba(16,185,129,0.15)] hover:shadow-[0_0_20px_rgba(16,185,129,0.3)]"
                            onClick={handleStart}
                            disabled={loading}
                        >
                            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4 fill-current" />}
                            Start Infinite Walk-Forward
                        </Button>
                    ) : (
                        <Button
                            className="w-full bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 hover:text-red-300 transition-all font-semibold tracking-wide shadow-[0_0_15px_rgba(239,68,68,0.15)] hover:shadow-[0_0_20px_rgba(239,68,68,0.3)]"
                            onClick={handleStop}
                            disabled={loading}
                        >
                            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Square className="mr-2 h-4 w-4 fill-current" />}
                            Stop Training
                        </Button>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
