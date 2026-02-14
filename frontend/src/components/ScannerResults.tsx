
"use client";

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer
} from 'recharts';
import { Loader2 } from 'lucide-react';

interface ScannerResult {
    date: string;
    symbol: string;
    score: number;
    name: string;
}

interface Trade {
    time: string;
    symbol: string;
    quantity: number;
    price: number;
    side: string;
}

export function ScannerResults({ runId }: { runId: string }) {
    const [scannerData, setScannerData] = useState<ScannerResult[]>([]);
    const [tradesData, setTradesData] = useState<Trade[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

                // Fetch Scanner Results
                const scannerRes = await fetch(`${API_URL}/api/v1/backtest/universe/${runId}`);
                if (scannerRes.ok) {
                    setScannerData(await scannerRes.json());
                }

                // Fetch Trades for Volume
                const tradesRes = await fetch(`${API_URL}/api/v1/backtest/trades/${runId}`);
                if (tradesRes.ok) {
                    setTradesData(await tradesRes.json());
                }

            } catch (error) {
                console.error("Failed to fetch scanner results", error);
            } finally {
                setLoading(false);
            }
        };

        if (runId) fetchData();
    }, [runId]);

    if (loading) return <div className="flex justify-center p-8"><Loader2 className="animate-spin" /></div>;

    // Build symbol -> name map from scanner data
    const symbolToName: Record<string, string> = {};
    scannerData.forEach(item => {
        if (item.name && item.name !== item.symbol) {
            symbolToName[item.symbol] = item.name;
        }
    });
    const getName = (sym: string) => symbolToName[sym] || sym;

    // Process Data for Chart
    // Group trades by Date and Symbol (using stock name) to get Volume
    const volumeByDateSymbol: Record<string, Record<string, number>> = {};
    const allSymbols = new Set<string>();

    tradesData.forEach(trade => {
        const date = trade.time.split('T')[0];
        const name = getName(trade.symbol);
        if (!volumeByDateSymbol[date]) volumeByDateSymbol[date] = {};
        if (!volumeByDateSymbol[date][name]) volumeByDateSymbol[date][name] = 0;

        // Sum quantity (absolute value)
        volumeByDateSymbol[date][name] += Math.abs(trade.quantity);
        allSymbols.add(name);
    });

    // Transform for Recharts
    const chartData = Object.keys(volumeByDateSymbol).sort().map(date => {
        const entry: Record<string, string | number> = { date };
        Object.keys(volumeByDateSymbol[date]).forEach(name => {
            entry[name] = volumeByDateSymbol[date][name];
        });
        return entry;
    });

    // Group Scanner Results by Date
    const scannerByDate: Record<string, ScannerResult[]> = {};
    scannerData.forEach(item => {
        if (!scannerByDate[item.date]) scannerByDate[item.date] = [];
        scannerByDate[item.date].push(item);
    });

    // Colors for bars
    const colors = ["#8884d8", "#82ca9d", "#ffc658", "#ff7300", "#0088fe", "#00C49F", "#FFBB28", "#FF8042"];

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* 1. Daily Volume Chart */}
                <Card className="md:col-span-2">
                    <CardHeader>
                        <CardTitle>Daily Traded Volume by Stock</CardTitle>
                        <CardDescription>Visualizing volume of stocks traded each day.</CardDescription>
                    </CardHeader>
                    <CardContent className="h-[400px]">
                        {chartData.length > 0 ? (
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={chartData}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                                    <XAxis dataKey="date" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                                    <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}`} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#1a1a1a', border: 'none' }}
                                        labelStyle={{ color: '#fff' }}
                                    />
                                    <Legend />
                                    {Array.from(allSymbols).map((sym, i) => (
                                        <Bar key={sym} dataKey={sym} stackId="a" fill={colors[i % colors.length]} />
                                    ))}
                                </BarChart>
                            </ResponsiveContainer>
                        ) : (
                            <div className="flex items-center justify-center h-full text-muted-foreground">
                                No trading volume data available.
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* 2. Scanner Picks Table */}
                <Card className="md:col-span-2">
                    <CardHeader>
                        <CardTitle>Daily Scanner Picks</CardTitle>
                        <CardDescription>Stocks selected by the algorithm&apos;s scanner logic.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="overflow-x-auto">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Date</TableHead>
                                        <TableHead>Scanned Symbols (Ranked by Score)</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {Object.keys(scannerByDate).sort().map(date => (
                                        <TableRow key={date}>
                                            <TableCell className="font-medium">{date}</TableCell>
                                            <TableCell>
                                                <div className="flex flex-wrap gap-2">
                                                    {scannerByDate[date].map((item, i) => (
                                                        <Badge key={i} variant="secondary" className="font-mono">
                                                            {item.name !== item.symbol ? `${item.name}` : item.symbol} <span className="text-xs text-muted-foreground ml-1">({item.score.toFixed(2)})</span>
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                    {scannerData.length === 0 && (
                                        <TableRow>
                                            <TableCell colSpan={2} className="text-center h-24 text-muted-foreground">
                                                No scanner data found.
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </TableBody>
                            </Table>
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}
