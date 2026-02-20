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
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {/* Cycle Card */}
            <Card className="bg-black/40 backdrop-blur-md border-white/10 relative overflow-hidden group">
                <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-blue-500/0 via-blue-500/50 to-blue-500/0 opacity-0 group-hover:opacity-100 transition-opacity" />
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium text-slate-300">Training Cycle</CardTitle>
                    <Activity className="h-4 w-4 text-blue-400" />
                </CardHeader>
                <CardContent>
                    <div className="text-3xl font-bold tracking-tight text-white">
                        Cycle {currentCycle.cycle || 0}
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                        Epoch {status.current_epoch} • {status.elapsed_seconds}s
                    </p>
                </CardContent>
            </Card>

            {/* Growth Status Card */}
            <Card className="bg-black/40 backdrop-blur-md border-white/10 relative overflow-hidden group">
                <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-purple-500/0 via-purple-500/50 to-purple-500/0 opacity-0 group-hover:opacity-100 transition-opacity" />
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium text-slate-300">Growth Status</CardTitle>
                    <Zap className={`h-4 w-4 ${statusText === "GROWING" ? "text-green-400 animate-pulse" : "text-purple-400"}`} />
                </CardHeader>
                <CardContent>
                    <div className="flex items-center gap-3">
                        <Badge className={`${statusColor} text-white shadow-lg border-white/20 px-3 py-1 font-semibold tracking-wide`}>
                            {statusText}
                        </Badge>
                        <span className="text-sm font-bold text-slate-300 bg-white/5 px-2 py-1 rounded-md">
                            Lvl {pressureLevel}
                        </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-2">
                        Pressure Escalation Tracker
                    </p>
                </CardContent>
            </Card>

            {/* Sharpe Card */}
            <Card className="bg-black/40 backdrop-blur-md border-white/10 relative overflow-hidden group">
                <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-500/0 via-emerald-500/50 to-emerald-500/0 opacity-0 group-hover:opacity-100 transition-opacity" />
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium text-slate-300">Best Sharpe (Test)</CardTitle>
                    <TrendingUp className="h-4 w-4 text-emerald-400" />
                </CardHeader>
                <CardContent>
                    <div className="text-3xl font-bold tracking-tight text-white">
                        {bestSharpe.toFixed(2)}
                    </div>
                    <p className="text-xs text-emerald-400/80 mt-1 font-medium">
                        Train (In-Sample): {currentCycle.train_sharpe?.toFixed(2) || "0.00"}
                    </p>
                </CardContent>
            </Card>

            {/* Population Card */}
            <Card className="bg-black/40 backdrop-blur-md border-white/10 relative overflow-hidden group">
                <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-indigo-500/0 via-indigo-500/50 to-indigo-500/0 opacity-0 group-hover:opacity-100 transition-opacity" />
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium text-slate-300">Population Health</CardTitle>
                    <Users className="h-4 w-4 text-indigo-400" />
                </CardHeader>
                <CardContent>
                    <div className="text-3xl font-bold tracking-tight text-white flex items-baseline gap-2">
                        {status.population?.alive_count ?? 0}
                        <span className="text-lg text-slate-500 font-medium">/ {status.population?.size ?? 0}</span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                        Network Density avg: <span className="text-indigo-300">{status.survival?.avg_health.toFixed(2) ?? "0.00"}</span>
                    </p>
                </CardContent>
            </Card>
        </div>
    );
}
