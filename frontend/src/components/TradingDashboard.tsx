
"use client";
import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ArrowUpRight, ArrowDownRight, DollarSign, Wallet, Activity } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

interface Portfolio {
  equity: number;
  pnl_daily: number;
  pnl_percent: number;
  cash: number;
  margin_used: number;
}

interface Position {
  symbol: string;
  qty: number;
  avg_price: number;
  ltp: number;
  pnl: number;
}

interface Order {
  id: string;
  time: string;
  symbol: string;
  type: string;
  qty: number;
  price: number;
  status: string;
}

const EMPTY_PORTFOLIO: Portfolio = {
  equity: 0, pnl_daily: 0, pnl_percent: 0, cash: 0, margin_used: 0,
};

export function TradingDashboard() {
  const [portfolio, setPortfolio] = useState<Portfolio>(EMPTY_PORTFOLIO);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/live/status`);
        if (res.ok) {
          const data = await res.json();
          if (data.equity !== undefined) {
            setPortfolio({
              equity: data.equity ?? 0,
              pnl_daily: data.pnl_daily ?? 0,
              pnl_percent: data.pnl_percent ?? 0,
              cash: data.cash ?? 0,
              margin_used: data.margin_used ?? 0,
            });
          }
          if (Array.isArray(data.holdings)) {
            setPositions(
              data.holdings.map((h: Record<string, unknown>) => ({
                symbol: String(h.symbol ?? ''),
                qty: Number(h.quantity ?? 0),
                avg_price: Number(h.avg_price ?? 0),
                ltp: Number(h.current_price ?? 0),
                pnl: Number(h.unrealized_pnl ?? 0),
              }))
            );
          }
        }
      } catch { /* API unavailable */ }

      try {
        const res = await fetch(`${API_URL}/api/v1/live/trades`);
        if (res.ok) {
          const data: Order[] = await res.json();
          setOrders(data);
        }
      } catch { /* ignore */ }
    };

    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Equity</CardTitle>
            <Wallet className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">₹{portfolio.equity.toLocaleString()}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Daily P&amp;L</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${portfolio.pnl_daily >= 0 ? "text-green-500" : "text-red-500"}`}>
              {portfolio.pnl_daily >= 0 ? "+" : ""}₹{portfolio.pnl_daily.toLocaleString()}
            </div>
            <p className="text-xs text-muted-foreground flex items-center">
              {portfolio.pnl_percent >= 0 ? <ArrowUpRight className="h-4 w-4 mr-1" /> : <ArrowDownRight className="h-4 w-4 mr-1" />}
              {portfolio.pnl_percent.toFixed(2)}% today
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

      <Tabs defaultValue="positions" className="w-full">
        <TabsList>
          <TabsTrigger value="positions">Active Positions ({positions.length})</TabsTrigger>
          <TabsTrigger value="orders">Order History</TabsTrigger>
        </TabsList>
        <TabsContent value="positions">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>Avg Price</TableHead>
                <TableHead>LTP</TableHead>
                <TableHead>P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p) => (
                <TableRow key={p.symbol}>
                  <TableCell className="font-mono text-sm">{p.symbol}</TableCell>
                  <TableCell>{p.qty}</TableCell>
                  <TableCell>₹{p.avg_price.toFixed(2)}</TableCell>
                  <TableCell>₹{p.ltp.toFixed(2)}</TableCell>
                  <TableCell className={p.pnl >= 0 ? "text-green-500" : "text-red-500"}>
                    {p.pnl >= 0 ? "+" : ""}₹{p.pnl.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
              {positions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">No open positions</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TabsContent>
        <TabsContent value="orders">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.map((o, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs">{String(o.time)}</TableCell>
                  <TableCell className="font-mono text-sm">{o.symbol}</TableCell>
                  <TableCell>{o.type ?? (o as unknown as Record<string, unknown>).side}</TableCell>
                  <TableCell>{o.qty ?? (o as unknown as Record<string, unknown>).quantity}</TableCell>
                  <TableCell>₹{Number(o.price).toFixed(2)}</TableCell>
                  <TableCell>
                    <Badge variant={String(o.status) === 'FILLED' ? 'default' : 'secondary'}>
                      {String(o.status)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>
    </div>
  );
}
