"use client";

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

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
            <div className="flex items-center justify-between mb-4">
                <TabsList>
                    <TabsTrigger value="performance">Walk-Forward Performance</TabsTrigger>
                    <TabsTrigger value="population">Population Health</TabsTrigger>
                </TabsList>
            </div>

            <TabsContent value="performance">
                <Card>
                    <CardHeader>
                        <CardTitle>Train vs Backtest Sharpe Ratio</CardTitle>
                    </CardHeader>
                    <CardContent className="h-[400px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={performanceData}>
                                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                                <XAxis dataKey="cycle" label={{ value: 'Cycle', position: 'insideBottomRight', offset: -5 }} />
                                <YAxis />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#1f2937', border: 'none' }}
                                    itemStyle={{ color: '#fff' }}
                                />
                                <Legend />
                                <Line
                                    type="monotone"
                                    dataKey="trainSharpe"
                                    stroke="#10b981"
                                    strokeWidth={2}
                                    name="Train Sharpe (In-Sample)"
                                    dot={false}
                                />
                                <Line
                                    type="monotone"
                                    dataKey="testSharpe"
                                    stroke="#3b82f6"
                                    strokeWidth={2}
                                    name="Backtest Sharpe (Out-of-Sample)"
                                    dot={true}
                                />
                            </LineChart>
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
