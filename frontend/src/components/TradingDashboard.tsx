
"use client";

import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ArrowUpRight, ArrowDownRight, DollarSign, Wallet } from 'lucide-react';

export function TradingDashboard() {
    // Mock Data
    const [portfolio] = useState({
        equity: 105430.50,
        pnl_daily: 1250.00,
        pnl_percent: 1.2,
        cash: 45000.00,
        margin_used: 60430.50
    });

    const [positions] = useState([
        { symbol: "NSE_EQ|RELIANCE", qty: 25, avg_price: 2450.00, ltp: 2480.00, pnl: 750.00 },
        { symbol: "NSE_EQ|INFY", qty: -10, avg_price: 1600.00, ltp: 1590.00, pnl: 100.00 },
    ]);

    const [orders] = useState([
        { id: "ORD-123", time: "10:30:00", symbol: "NSE_EQ|RELIANCE", type: "BUY", qty: 25, price: 2450.00, status: "FILLED" },
        { id: "ORD-124", time: "10:35:00", symbol: "NSE_EQ|INFY", type: "SELL", qty: 10, price: 1600.00, status: "FILLED" },
        { id: "ORD-125", time: "11:00:00", symbol: "NSE_EQ|TATASTEEL", type: "BUY", qty: 100, price: 140.00, status: "REJECTED" },
    ]);

    return (
        <div className="space-y-6">
            {/* Metrics Row */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Total Equity</CardTitle>
                        <Wallet className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">₹{portfolio.equity.toLocaleString()}</div>
                        <p className="text-xs text-muted-foreground">+20.1% from start</p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Daily P&L</CardTitle>
                        <DollarSign className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className={`text-2xl font-bold ${portfolio.pnl_daily >= 0 ? "text-green-500" : "text-red-500"}`}>
                            {portfolio.pnl_daily >= 0 ? "+" : ""}₹{portfolio.pnl_daily.toLocaleString()}
                        </div>
                        <p className="text-xs text-muted-foreground flex items-center">
                            {portfolio.pnl_percent >= 0 ? <ArrowUpRight className="h-4 w-4 mr-1" /> : <ArrowDownRight className="h-4 w-4 mr-1" />}
                            {portfolio.pnl_percent}% today
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Margin Used</CardTitle>
                        <Activity className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">₹{portfolio.margin_used.toLocaleString()}</div>
                        <p className="text-xs text-muted-foreground">Cash: ₹{portfolio.cash.toLocaleString()}</p>
                    </CardContent>
                </Card>
            </div>

            {/* Tabs Row */}
            <Tabs defaultValue="positions" className="w-full">
                <TabsList>
                    <TabsTrigger value="positions">Active Positions ({positions.length})</TabsTrigger>
                    <TabsTrigger value="orders">Order History</TabsTrigger>
                </TabsList>

                <TabsContent value="positions">
                    <Card>
                        <CardContent className="p-0">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Symbol</TableHead>
                                        <TableHead className="text-right">Qty</TableHead>
                                        <TableHead className="text-right">Avg Price</TableHead>
                                        <TableHead className="text-right">LTP</TableHead>
                                        <TableHead className="text-right">P&L</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {positions.map((pos) => (
                                        <TableRow key={pos.symbol}>
                                            <TableCell className="font-medium">{pos.symbol}</TableCell>
                                            <TableCell className="text-right">{pos.qty}</TableCell>
                                            <TableCell className="text-right">{pos.avg_price.toFixed(2)}</TableCell>
                                            <TableCell className="text-right">{pos.ltp.toFixed(2)}</TableCell>
                                            <TableCell className={`text-right ${pos.pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                                                {pos.pnl.toFixed(2)}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="orders">
                    <Card>
                        <CardContent className="p-0">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Time</TableHead>
                                        <TableHead>Symbol</TableHead>
                                        <TableHead>Type</TableHead>
                                        <TableHead className="text-right">Qty</TableHead>
                                        <TableHead className="text-right">Price</TableHead>
                                        <TableHead className="text-right">Status</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {orders.map((ord) => (
                                        <TableRow key={ord.id}>
                                            <TableCell>{ord.time}</TableCell>
                                            <TableCell className="font-medium">{ord.symbol}</TableCell>
                                            <TableCell>
                                                <Badge variant={ord.type === "BUY" ? "default" : "destructive"}>{ord.type}</Badge>
                                            </TableCell>
                                            <TableCell className="text-right">{ord.qty}</TableCell>
                                            <TableCell className="text-right">{ord.price.toFixed(2)}</TableCell>
                                            <TableCell className="text-right">
                                                <Badge variant="outline">{ord.status}</Badge>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </CardContent>
                    </Card>
                </TabsContent>

            </Tabs>
        </div>
    );
}

import { Activity } from 'lucide-react';
