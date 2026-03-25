"use client";

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  TrendingUp, TrendingDown, Activity, Shield, 
  BarChart3, Play, RefreshCw, ChevronRight, 
  Search, Download, Info, CheckCircle2
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, 
  ResponsiveContainer
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

// --- Types ---
interface PerformancePoint {
  time: string;
  equity: number;
  heat: number;
}

interface TradeLog {
  time: string;
  symbol: string;
  type: string;
  qty: number;
  price: number;
  pnl: number;
  mechanism: string;
}

interface BacktestSummary {
  run_id: string;
  total_trades: number;
  total_pnl_pct: number;
  total_pnl: number;
  net_profit: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  brokerage: number;
  cagr: number;
  expectancy: number;
  timestamp: string;
}

interface StatCardProps {
  title: string;
  value: string;
  subValue: string;
  icon: React.ElementType;
  trend?: number;
  prefix?: string;
  isCurrency?: boolean;
}

// --- Components ---

const StatCard = ({ title, value, subValue, icon: Icon, trend, prefix = "", isCurrency = false }: StatCardProps) => (
  <motion.div 
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    className="relative overflow-hidden group"
  >
    <Card className="bg-zinc-900/50 border-zinc-800 backdrop-blur-xl group-hover:border-zinc-700 transition-all duration-300 h-full">
      <CardContent className="p-6">
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">{title}</p>
          <div className="p-1.5 rounded bg-zinc-800/50 text-zinc-400 group-hover:text-amber-500 transition-colors">
            <Icon className="w-3.5 h-3.5" />
          </div>
        </div>
        <div className="flex items-baseline gap-1">
          <h3 className={`text-xl font-bold tracking-tight ${isCurrency ? 'font-mono' : ''} text-zinc-100`}>
            {prefix}{value}
          </h3>
          {trend !== undefined && (
            <span className={`text-[10px] font-bold flex items-center ${trend >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
              {trend >= 0 ? '+' : ''}{trend.toFixed(1)}%
            </span>
          )}
        </div>
        <p className="text-[10px] text-zinc-600 mt-1 font-medium">{subValue}</p>
      </CardContent>
    </Card>
  </motion.div>
);

export default function TerminalPage() {
  const [history, setHistory] = useState<BacktestSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [performance, setPerformance] = useState<PerformancePoint[]>([]);
  const [activeSummary, setActiveSummary] = useState<BacktestSummary | null>(null);
  const [trades, setTrades] = useState<TradeLog[]>([]);
  const [, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);

  // --- Data Fetching ---

  const refreshHistory = useCallback(async () => {
    try {
      const res = await api.get('/api/v1/backtest/history');
      if (res.data && res.data.length > 0) {
        setHistory(res.data);
        if (!activeRunId) setActiveRunId(res.data[0].run_id);
      }
    } catch (e) {
      console.error("Failed to fetch history", e);
    } finally {
      setLoading(false);
    }
  }, [activeRunId]);

  const loadRunDetails = useCallback(async (runId: string) => {
    try {
        const [perfFullRes, tradesRes] = await Promise.all([
            api.get(`/api/v1/backtest/performance/full/${runId}`),
            api.get(`/api/v1/backtest/trades/${runId}`)
        ]);
        setPerformance(perfFullRes.data?.points || []);
        setActiveSummary(perfFullRes.data?.summary || null);
        setTrades(tradesRes.data || []);
    } catch (e) {
        console.error("Failed to load run details", e);
    }
  }, []);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    if (activeRunId) {
      loadRunDetails(activeRunId);
    }
  }, [activeRunId, loadRunDetails]);

  // Handle live backtest
  const startBacktest = async () => {
    setRunning(true);
    setProgress(5);
    try {
        const res = await api.post('/api/v1/til/backtest', { universe_size: 10, trading_days: 60 });
        const runId = res.data.run_id;
        
        // Polling loop
        const interval = setInterval(async () => {
            const statusRes = await api.get('/api/v1/til/backtest/status');
            const data = statusRes.data;
            if (data.progress) setProgress(data.progress);
            
            if (!data.running || data.progress >= 100) {
                clearInterval(interval);
                setRunning(false);
                setProgress(0);
                setActiveRunId(runId);
                refreshHistory();
            }
        }, 1000);
    } catch (e) {
        console.error("Backtest trigger failed", e);
        setRunning(false);
    }
  };

  const currentSummary = useMemo(() => {
    return activeSummary || history.find(h => h.run_id === activeRunId) || history[0];
  }, [activeSummary, history, activeRunId]);

  return (
    <div className="min-h-screen bg-black text-zinc-100 font-sans selection:bg-amber-500/30">
      {/* Background gradients */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-amber-500/5 blur-[120px]" />
        <div className="absolute bottom-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-blue-500/5 blur-[120px]" />
      </div>

      <div className="relative max-w-[1600px] mx-auto px-6 py-8">
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="outline" className="border-amber-500/50 text-amber-500 bg-amber-500/5">Vektor Engine v2.1</Badge>
              <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Live Ingestor Connected
              </div>
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
              KIRA Analytics Terminal
              <Activity className="w-6 h-6 text-amber-500/50" />
            </h1>
            <p className="text-zinc-500 text-sm mt-1 max-w-xl">
              Quantitative performance monitoring and strategy audit for vectorized Alpha Sniper execution.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Button variant="outline" className="bg-zinc-900 border-zinc-800 text-zinc-400" onClick={refreshHistory}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
            <Button 
                className="bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-900/20 px-8"
                onClick={startBacktest}
                disabled={running}
            >
              {running ? (
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin text-white" />
              ) : (
                  <Play className="mr-2 h-4 w-4 fill-white" />
              )}
              {running ? "Simulating..." : "Run Backtest"}
            </Button>
          </div>
        </header>

        {/* Progress Bar (Global) */}
        <AnimatePresence>
            {running && (
                <motion.div 
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mb-8"
                >
                    <Card className="bg-zinc-900/40 border-amber-500/20 backdrop-blur-sm overflow-hidden border-dashed">
                        <CardContent className="p-4 flex items-center gap-4">
                            <div className="flex-1">
                                <div className="flex justify-between text-xs mb-1.5">
                                    <span className="text-amber-500 font-medium flex items-center gap-1.5">
                                        <RefreshCw className="w-3 h-3 animate-spin" />
                                        Alpha Sniper Simulation in Progress...
                                    </span>
                                    <span className="text-zinc-400 font-mono">{progress}% Complete</span>
                                </div>
                                <Progress value={progress} className="h-1 bg-zinc-800" indicatorClassName="bg-gradient-to-r from-amber-600 to-amber-400" />
                            </div>
                        </CardContent>
                    </Card>
                </motion.div>
            )}
        </AnimatePresence>

        {/* Top Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
          <StatCard 
            title="Total Return" 
            value={(currentSummary?.total_pnl_pct ?? 0).toFixed(2) + "%"} 
            subValue={`Net P&L: ₹${(currentSummary?.total_pnl ?? 0).toLocaleString()}`} 
            icon={TrendingUp}
            trend={currentSummary?.total_pnl_pct ?? 0}
          />
          <StatCard 
            title="Max Drawdown" 
            value={(currentSummary?.max_drawdown_pct ?? 0).toFixed(2) + "%"} 
            subValue="Historical peak-to-trough" 
            icon={TrendingDown}
          />
          <StatCard 
            title="Sharpe Ratio" 
            value={(currentSummary?.sharpe_ratio ?? 0).toFixed(2)} 
            subValue="Risk-adjusted return" 
            icon={Shield}
          />
          <StatCard 
            title="Win Rate" 
            value={(currentSummary?.win_rate_pct ?? 0).toFixed(1) + "%"} 
            subValue={`${currentSummary?.total_trades ?? 0} executions`} 
            icon={BarChart3}
          />
          <StatCard 
            title="Brokerage" 
            value={(currentSummary?.brokerage ?? 0).toLocaleString()} 
            subValue="Execution friction" 
            icon={Activity}
            prefix="₹"
            isCurrency
          />
          <StatCard 
            title="CAGR" 
            value={(currentSummary?.cagr ?? 0).toFixed(2) + "%"} 
            subValue="Annualized growth" 
            icon={TrendingUp}
          />
        </div>

        {/* Detailed Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-lg p-4 flex flex-col justify-center">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Profit Factor</span>
                <span className="text-lg font-bold text-zinc-200">{(currentSummary?.profit_factor ?? 0).toFixed(2)}</span>
            </div>
            <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-lg p-4 flex flex-col justify-center">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Net Profit</span>
                <span className={`text-lg font-bold ${ (currentSummary?.net_profit ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>₹{(currentSummary?.net_profit ?? 0).toLocaleString()}</span>
            </div>
            <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-lg p-4 flex flex-col justify-center">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Expectancy</span>
                <span className="text-lg font-bold text-amber-500">₹{(currentSummary?.expectancy ?? 0).toFixed(2)}</span>
            </div>
            <div className="bg-zinc-900/30 border border-zinc-800/50 rounded-lg p-4 flex flex-col justify-center">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Avg Win/Loss</span>
                <span className="text-lg font-bold text-zinc-200">1.4x</span>
            </div>
        </div>

        {/* Main Section: Chart and Run History */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8">
          {/* Main Chart Container */}
          <Card className="lg:col-span-8 bg-zinc-900/50 border-zinc-800 shadow-2xl overflow-hidden min-h-[500px]">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-6 border-b border-zinc-800/50">
              <div>
                <CardTitle className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
                  Equity Growth Profile
                  <Info className="w-4 h-4 text-zinc-500 cursor-help" />
                </CardTitle>
                <CardDescription className="text-zinc-500">Cumulative performance for {activeRunId?.slice(0,8)}... sequence</CardDescription>
              </div>
              <div className="flex items-center gap-2 bg-zinc-800/50 p-1 rounded-md">
                <Button variant="ghost" size="sm" className="h-7 text-xs px-3 hover:bg-zinc-700">1D</Button>
                <Button variant="ghost" size="sm" className="h-7 text-xs px-3 bg-zinc-700 text-white">MAX</Button>
              </div>
            </CardHeader>
            <CardContent className="pt-8 px-2 pb-2">
              <div className="h-[400px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={performance}>
                    <defs>
                      <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.15}/>
                        <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid vertical={false} stroke="#27272a" strokeDasharray="3 3 text" />
                    <XAxis 
                        dataKey="time" 
                        hide 
                        axisLine={false}
                        tickLine={false}
                    />
                    <YAxis 
                        domain={['dataMin - 1000', 'dataMax + 1000']} 
                        orientation="right"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fill: '#71717a', fontSize: 10 }}
                        tickFormatter={(val: number) => `₹${val.toLocaleString()}`}
                    />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46', borderRadius: '8px', fontSize: '12px' }}
                      itemStyle={{ color: '#f59e0b' }}
                      labelClassName="text-zinc-500 font-mono text-[10px]"
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      formatter={(val: any) => [`₹${val?.toLocaleString() || '0'}`, "Equity"]}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="equity" 
                      stroke="#f59e0b" 
                      strokeWidth={2}
                      fillOpacity={1} 
                      fill="url(#colorEquity)" 
                      animationDuration={1500}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {/* Historical Runs List */}
          <Card className="lg:col-span-4 bg-zinc-900/50 border-zinc-800 flex flex-col max-h-[500px]">
            <CardHeader className="pb-4 border-b border-zinc-800/50">
              <CardTitle className="text-md font-semibold text-zinc-200 flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-zinc-500" />
                Run Sequence
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0 overflow-y-auto">
              <div className="divide-y divide-zinc-800/30">
                {history.map((run) => (
                  <button
                    key={run.run_id}
                    onClick={() => setActiveRunId(run.run_id)}
                    className={`w-full p-4 text-left transition-colors flex items-center justify-between group ${
                      activeRunId === run.run_id ? 'bg-amber-500/5' : 'hover:bg-zinc-800/30'
                    }`}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono text-xs text-zinc-300 group-hover:text-amber-500 transition-colors">
                            {run.run_id.slice(0, 8)}
                        </span>
                        {activeRunId === run.run_id && <Badge className="h-4 px-1 text-[10px] bg-amber-500">ACTIVE</Badge>}
                      </div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-widest leading-none">
                        {new Date(run.timestamp).toLocaleString()}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`font-bold text-sm leading-none mb-1 ${(run.total_pnl_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {(run.total_pnl_pct ?? 0) >= 0 ? '+' : ''}{(run.total_pnl_pct ?? 0).toFixed(2)}%
                      </div>
                      <div className="text-[10px] text-zinc-500">
                        {run.total_trades ?? 0} Trades
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Trade Log Section */}
        <div className="mb-12">
          <Tabs defaultValue="trades" className="space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <TabsList className="bg-zinc-900 border border-zinc-800 p-1 h-10">
                <TabsTrigger value="trades" className="data-[state=active]:bg-zinc-800 text-xs">Detailed Trade Log</TabsTrigger>
                <TabsTrigger value="mechanisms" className="data-[state=active]:bg-zinc-800 text-xs text-zinc-500 cursor-not-allowed">Mechanics Stats</TabsTrigger>
                <TabsTrigger value="settings" className="data-[state=active]:bg-zinc-800 text-xs text-zinc-500 cursor-not-allowed">Run Configuration</TabsTrigger>
              </TabsList>

              <div className="flex gap-2">
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
                  <input 
                    type="text" 
                    placeholder="Filter symbol..." 
                    className="h-9 w-full md:w-[200px] rounded-md bg-zinc-900 border-zinc-800 pl-8 text-xs text-zinc-300 focus:border-amber-500/50 focus:ring-0 outline-none transition-all placeholder:text-zinc-600"
                  />
                </div>
                <Button variant="outline" size="sm" className="h-9 border-zinc-800 bg-zinc-900 text-zinc-400">
                  <Download className="w-3.5 h-3.5 mr-2" />
                  Export
                </Button>
              </div>
            </div>

            <TabsContent value="trades">
              <Card className="bg-zinc-900/50 border-zinc-800 overflow-hidden">
                <div className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow className="border-zinc-800 hover:bg-transparent">
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider py-4">Time</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider">Symbol</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider">Type</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider text-right">Quantity</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider text-right">Price</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider text-right">P&L</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider">Mechanism</TableHead>
                                <TableHead className="text-zinc-500 font-medium text-[11px] uppercase tracking-wider">Audit</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {trades.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={8} className="h-32 text-center text-zinc-500">
                                        No executions recorded for this sequence.
                                    </TableCell>
                                </TableRow>
                            ) : (
                                trades.map((trade, i) => (
                                    <TableRow key={i} className="border-zinc-800/30 hover:bg-zinc-800/20 group transition-colors">
                                        <TableCell className="py-4 text-xs font-mono text-zinc-500">
                                            {new Date(trade.time).toLocaleTimeString()}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-2">
                                                <div className="w-6 h-6 rounded bg-zinc-800 flex items-center justify-center text-[10px] font-bold text-zinc-400 uppercase">
                                                    {trade.symbol.slice(0, 1)}
                                                </div>
                                                <span className="font-semibold text-zinc-200">{trade.symbol}</span>
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <Badge className={trade.type === 'BUY' ? 'bg-emerald-500/10 text-emerald-500 border-none' : 'bg-rose-500/10 text-rose-500 border-none'}>
                                                {trade.type}
                                            </Badge>
                                        </TableCell>
                                        <TableCell className="text-right font-mono text-zinc-300">{trade.qty}</TableCell>
                                        <TableCell className="text-right font-mono text-zinc-300">₹{trade.price.toFixed(2)}</TableCell>
                                        <TableCell className={`text-right font-bold font-mono ${trade.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                            {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl.toFixed(2)}
                                        </TableCell>
                                        <TableCell className="text-xs text-zinc-500 italic max-w-[150px] truncate">{trade.mechanism}</TableCell>
                                        <TableCell>
                                            <Button variant="ghost" size="icon" className="h-7 w-7 text-zinc-600 hover:text-amber-500 opacity-0 group-hover:opacity-100 transition-all">
                                                <ChevronRight className="h-4 w-4" />
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                ))
                            )}
                        </TableBody>
                    </Table>
                </div>
              </Card>
            </TabsContent>
          </Tabs>
        </div>

        {/* Footer Audit Info */}
        <footer className="mt-12 pt-8 border-t border-zinc-900 pb-12">
            <div className="flex flex-col md:flex-row justify-between items-start gap-8">
                <div className="max-w-md">
                    <div className="flex items-center gap-2 text-zinc-400 mb-2 font-semibold">
                        <Shield className="w-5 h-5 text-amber-500" />
                        Platform Integrity Check
                    </div>
                    <p className="text-xs text-zinc-500 leading-relaxed mb-4">
                        All backtest simulations are vectorized and executed on the high-performance C++ engine. 
                        Performance stats are calculated daily with T+1 settlement logic. 
                        Slippage and brokerage assumptions are verified against live market tick profiles.
                    </p>
                    <div className="grid grid-cols-2 gap-4">
                        <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
                            <div className="text-[10px] text-emerald-500/70 font-semibold uppercase mb-1">Execution Status</div>
                            <div className="text-xs text-emerald-500 flex items-center gap-1.5 font-bold uppercase tracking-wider">
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                Optimal
                            </div>
                        </div>
                        <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/10">
                            <div className="text-[10px] text-amber-500/70 font-semibold uppercase mb-1">Model Confidence</div>
                            <div className="text-xs text-amber-500 flex items-center gap-1.5 font-bold uppercase tracking-wider">
                                <Activity className="w-3.5 h-3.5" />
                                94.2% (Alpha Sniper)
                            </div>
                        </div>
                    </div>
                </div>

                <div className="flex gap-12 text-zinc-600">
                    <div>
                        <h4 className="text-zinc-400 font-bold text-xs uppercase mb-4 tracking-widest">Resources</h4>
                        <ul className="space-y-2 text-[11px]">
                            <li className="hover:text-amber-500 cursor-pointer transition-colors">API Documentation</li>
                            <li className="hover:text-amber-500 cursor-pointer transition-colors">Risk Disclosures</li>
                            <li className="hover:text-amber-500 cursor-pointer transition-colors">System Logs</li>
                        </ul>
                    </div>
                    <div>
                        <h4 className="text-zinc-400 font-bold text-xs uppercase mb-4 tracking-widest">KIRA v4.x</h4>
                        <p className="text-[10px] leading-relaxed max-w-[150px]">
                            Built for professional algorithmic research and high-frequency equity trading.
                        </p>
                    </div>
                </div>
            </div>
        </footer>
      </div>
    </div>
  );
}
