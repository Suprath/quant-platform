"use client";

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Zap, TrendingUp, Users } from 'lucide-react';
import { Badge } from "@/components/ui/badge";

const API_URL = "http://localhost:8002"; // Adjust if needed

interface CycleData {
    cycle?: number;
    test_sharpe?: number;
    train_sharpe?: number;
    pressure_level?: number;
    status?: string;
}

interface PopulationStats {
    alive_count: number;
    size: number;
}

interface SurvivalStats {
    avg_health: number;
}

interface TrainingStatus {
    metrics?: {
        current_cycle?: CycleData;
    };
    current_epoch?: number;
    elapsed_seconds?: number;
    population?: PopulationStats;
    survival?: SurvivalStats;
}

export function ESTIMetrics() {
    const [status, setStatus] = useState<TrainingStatus | null>(null);

    useEffect(() => {
        const fetchStatus = async () => {
            try {
                const res = await fetch(`${API_URL}/train/status`);
                const data = await res.json();
                setStatus(data);
            } catch (err) {
                console.error("Failed to fetch training status", err);
            }
        };

        const interval = setInterval(fetchStatus, 2000);
        fetchStatus();
        return () => clearInterval(interval);
    }, []);

    if (!status) return <div className="animate-pulse">Loading metrics...</div>;

    const currentCycle = status.metrics?.current_cycle || {};
    const bestSharpe = currentCycle.test_sharpe ?? 0.0;
    const pressureLevel = currentCycle.pressure_level ?? 0;
    const statusText = currentCycle.status || "IDLE";

    // Determine status color
    let statusColor = "bg-gray-500";
    if (statusText === "GROWING") statusColor = "bg-green-500";
    else if (statusText === "STALLING") statusColor = "bg-yellow-500";
    else if (statusText === "PRESSURE") statusColor = "bg-orange-500";
    else if (statusText === "PLATEAU") statusColor = "bg-red-500";

    return (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Training Cycle</CardTitle>
                    <Activity className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-2xl font-bold">
                        Cycle {currentCycle.cycle || 0}
                    </div>
                    <p className="text-xs text-muted-foreground">
                        Epoch {status.current_epoch} • {status.elapsed_seconds}s
                    </p>
                </CardContent>
            </Card>

            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Growth Status</CardTitle>
                    <Zap className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="flex items-center gap-2">
                        <Badge className={`${statusColor} text-white`}>{statusText}</Badge>
                        <span className="text-sm font-bold">Lvl {pressureLevel}</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                        Pressure Escalation
                    </p>
                </CardContent>
            </Card>

            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Best Sharpe (Test)</CardTitle>
                    <TrendingUp className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-2xl font-bold">
                        {bestSharpe.toFixed(2)}
                    </div>
                    <p className="text-xs text-muted-foreground">
                        Train: {currentCycle.train_sharpe?.toFixed(2) || "0.00"}
                    </p>
                </CardContent>
            </Card>

            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Population</CardTitle>
                    <Users className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-2xl font-bold">
                        {status.population?.alive_count ?? 0} / {status.population?.size ?? 0}
                    </div>
                    <p className="text-xs text-muted-foreground">
                        Avg Health: {status.survival?.avg_health.toFixed(2) ?? "0.00"}
                    </p>
                </CardContent>
            </Card>
        </div>
    );
}
