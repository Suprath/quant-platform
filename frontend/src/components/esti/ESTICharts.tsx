"use client";

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const API_URL = "http://localhost:8002";

interface CycleMetric {
    cycle: number;
    train_sharpe: number;
    test_sharpe: number;
    pressure_level: number;
}

interface MetricsResponse {
    history: unknown[]; // history is still part of the response, but not used in state
    cycles: CycleMetric[];
}

export function ESTICharts() {
    const [cycles, setCycles] = useState<CycleMetric[]>([]);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await fetch(`${API_URL}/metrics/history?limit=500`);
                const data: MetricsResponse = await res.json();
                setCycles(data.cycles || []);
            } catch (err) {
                console.error("Failed to fetch metrics history", err);
            }
        };

        const interval = setInterval(fetchData, 2000);
        fetchData();
        return () => clearInterval(interval);
    }, []);

    // Filter data for charts
    const performanceData = cycles.map(c => ({
        cycle: c.cycle,
        trainSharpe: c.train_sharpe,
        testSharpe: c.test_sharpe,
        pressure: c.pressure_level
    }));

    return (
        <Tabs defaultValue="performance" className="w-full">
            <div className="flex items-center justify-between mb-6">
                <TabsList className="bg-black/40 border border-white/10">
                    <TabsTrigger value="performance" className="data-[state=active]:bg-white/10 data-[state=active]:text-white">Walk-Forward Performance</TabsTrigger>
                    <TabsTrigger value="population" className="data-[state=active]:bg-white/10 data-[state=active]:text-white">Population Health</TabsTrigger>
                </TabsList>
            </div>

            <TabsContent value="performance">
                <Card className="bg-black/40 backdrop-blur-md border-white/10 shadow-2xl">
                    <CardHeader>
                        <CardTitle className="text-slate-200 font-semibold tracking-wide flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                            Live Sharpe Ratio Tracking
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="h-[450px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={performanceData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                                <defs>
                                    <linearGradient id="colorTrain" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                                    </linearGradient>
                                    <linearGradient id="colorTest" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff15" vertical={false} />
                                <XAxis
                                    dataKey="cycle"
                                    stroke="#cbd5e1"
                                    tick={{ fill: '#94a3b8' }}
                                    tickLine={false}
                                    axisLine={false}
                                    dy={10}
                                />
                                <YAxis
                                    stroke="#cbd5e1"
                                    tick={{ fill: '#94a3b8' }}
                                    tickLine={false}
                                    axisLine={false}
                                    dx={-10}
                                />
                                <Tooltip
                                    contentStyle={{
                                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                                        border: '1px solid rgba(255,255,255,0.1)',
                                        borderRadius: '8px',
                                        backdropFilter: 'blur(8px)',
                                        boxShadow: '0 4px 20px rgba(0,0,0,0.5)'
                                    }}
                                    itemStyle={{ color: '#f8fafc', fontWeight: 500 }}
                                    labelStyle={{ color: '#94a3b8', marginBottom: '4px' }}
                                />
                                <Legend wrapperStyle={{ paddingTop: '20px' }} />
                                <Area
                                    type="monotone"
                                    dataKey="trainSharpe"
                                    stroke="#10b981"
                                    strokeWidth={2}
                                    fillOpacity={1}
                                    fill="url(#colorTrain)"
                                    name="Train Sharpe (In-Sample)"
                                    activeDot={{ r: 6, fill: "#10b981", stroke: "#fff" }}
                                />
                                <Area
                                    type="monotone"
                                    dataKey="testSharpe"
                                    stroke="#8b5cf6"
                                    strokeWidth={2}
                                    fillOpacity={1}
                                    fill="url(#colorTest)"
                                    name="Backtest Sharpe (Out-of-Sample)"
                                    activeDot={{ r: 6, fill: "#8b5cf6", stroke: "#fff" }}
                                />
                            </AreaChart>
                        </ResponsiveContainer>
                    </CardContent>
                </Card>
            </TabsContent>

            <TabsContent value="population">
                <Card>
                    <CardHeader>
                        <CardTitle>Population Dynamics</CardTitle>
                    </CardHeader>
                    <CardContent className="h-[400px]">
                        <div className="flex items-center justify-center h-full text-muted-foreground">
                            Coming soon: Detailed population stacking chart
                        </div>
                    </CardContent>
                </Card>
            </TabsContent>
        </Tabs>
    );
}
