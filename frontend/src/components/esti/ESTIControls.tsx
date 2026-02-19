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
        <Card>
            <CardHeader>
                <CardTitle>Training Controls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label>Start Date</Label>
                        <Input
                            type="date"
                            value={config.startDate}
                            onChange={(e) => setConfig({ ...config, startDate: e.target.value })}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>End Date</Label>
                        <Input
                            type="date"
                            value={config.endDate}
                            onChange={(e) => setConfig({ ...config, endDate: e.target.value })}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label>Train Window (Days)</Label>
                        <Input
                            type="number"
                            value={config.trainWindow}
                            onChange={(e) => setConfig({ ...config, trainWindow: Number(e.target.value) })}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Test Window (Days)</Label>
                        <Input
                            type="number"
                            value={config.testWindow}
                            onChange={(e) => setConfig({ ...config, testWindow: Number(e.target.value) })}
                        />
                    </div>
                </div>

                <div className="pt-2">
                    {!isRunning ? (
                        <Button
                            className="w-full bg-green-600 hover:bg-green-700"
                            onClick={handleStart}
                            disabled={loading}
                        >
                            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                            Start Infinite Walk-Forward
                        </Button>
                    ) : (
                        <Button
                            className="w-full bg-red-600 hover:bg-red-700"
                            onClick={handleStop}
                            disabled={loading}
                        >
                            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Square className="mr-2 h-4 w-4" />}
                            Stop Training
                        </Button>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
