
"use client";

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { History, Eye, Trash2, Loader2, RefreshCw } from 'lucide-react';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

interface BacktestRun {
    run_id: string;
    final_balance: number;
    initial_equity: number;
    created_at: string;
    trade_count: number;
    total_pnl: number;
    start_date: string | null;
    end_date: string | null;
}

export function BacktestHistory() {
    const [runs, setRuns] = useState<BacktestRun[]>([]);
    const [loading, setLoading] = useState(true);
    const [deleting, setDeleting] = useState<string | null>(null);
    const [expanded, setExpanded] = useState(false);

    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

    const fetchHistory = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_URL}/api/v1/backtest/history`);
            if (res.ok) {
                const data = await res.json();
                setRuns(data);
            }
        } catch (e) {
            console.error("Failed to fetch history:", e);
        }
        setLoading(false);
    }, [API_URL]);

    useEffect(() => {
        if (expanded) fetchHistory();
    }, [expanded, fetchHistory]);

    const deleteRun = async (runId: string) => {
        setDeleting(runId);
        try {
            const res = await fetch(`${API_URL}/api/v1/backtest/${runId}`, { method: 'DELETE' });
            if (res.ok) {
                setRuns(prev => prev.filter(r => r.run_id !== runId));
            }
        } catch (e) {
            console.error("Delete failed:", e);
        }
        setDeleting(null);
    };

    const clearAll = async () => {
        try {
            const res = await fetch(`${API_URL}/api/v1/backtest/history`, { method: 'DELETE' });
            if (res.ok) setRuns([]);
        } catch (e) {
            console.error("Clear failed:", e);
        }
    };

    const viewRun = (runId: string) => {
        window.open(`/dashboard/backtest/${runId}`, '_blank');
    };

    const formatDate = (iso: string | null) => {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
    };



    return (
        <Card className="border-dashed">
            <CardHeader className="cursor-pointer pb-3" onClick={() => setExpanded(!expanded)}>
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <History className="h-5 w-5 text-purple-500" />
                        <CardTitle className="text-base">Backtest History</CardTitle>
                        {runs.length > 0 && (
                            <Badge variant="secondary" className="text-xs">{runs.length} runs</Badge>
                        )}
                    </div>
                    <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>
                        {expanded ? '▲' : '▼'}
                    </Button>
                </div>
            </CardHeader>

            {expanded && (
                <CardContent className="space-y-3">
                    {/* Action Bar */}
                    <div className="flex items-center justify-between">
                        <Button variant="ghost" size="sm" onClick={fetchHistory} disabled={loading}>
                            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
                            Refresh
                        </Button>
                        {runs.length > 0 && (
                            <AlertDialog>
                                <AlertDialogTrigger asChild>
                                    <Button variant="destructive" size="sm">
                                        <Trash2 className="h-4 w-4 mr-1" /> Clear All
                                    </Button>
                                </AlertDialogTrigger>
                                <AlertDialogContent>
                                    <AlertDialogHeader>
                                        <AlertDialogTitle>Clear All Backtest History?</AlertDialogTitle>
                                        <AlertDialogDescription>
                                            This will permanently delete all {runs.length} backtest runs, including trades, positions, and scanner data. This cannot be undone.
                                        </AlertDialogDescription>
                                    </AlertDialogHeader>
                                    <AlertDialogFooter>
                                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                                        <AlertDialogAction onClick={clearAll} className="bg-destructive text-destructive-foreground">
                                            Delete Everything
                                        </AlertDialogAction>
                                    </AlertDialogFooter>
                                </AlertDialogContent>
                            </AlertDialog>
                        )}
                    </div>

                    {/* Loading */}
                    {loading && (
                        <div className="flex items-center justify-center py-8 text-muted-foreground">
                            <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading history...
                        </div>
                    )}

                    {/* Empty */}
                    {!loading && runs.length === 0 && (
                        <div className="text-center py-8 text-muted-foreground">
                            <History className="h-8 w-8 mx-auto mb-2 opacity-50" />
                            <p className="text-sm">No backtest history yet</p>
                            <p className="text-xs">Run a backtest from the editor to see results here</p>
                        </div>
                    )}

                    {/* History List */}
                    {!loading && runs.length > 0 && (
                        <div className="space-y-2 max-h-[350px] overflow-y-auto pr-1">
                            {runs.map((run) => {
                                const pnlPct = ((run.final_balance - run.initial_equity) / run.initial_equity * 100);
                                const isPositive = run.total_pnl >= 0;

                                return (
                                    <div
                                        key={run.run_id}
                                        className="group flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-muted/50 transition-colors"
                                    >
                                        {/* Left: Info */}
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <code className="text-xs text-muted-foreground font-mono truncate max-w-[140px]">
                                                    {run.run_id.slice(0, 8)}...
                                                </code>
                                                <Badge
                                                    variant="secondary"
                                                    className={`text-xs ${isPositive ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'}`}
                                                >
                                                    {isPositive ? '+' : ''}{run.total_pnl.toFixed(2)} PnL
                                                </Badge>
                                                <span className="text-xs text-muted-foreground">
                                                    {run.trade_count} trades
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                                                <span>
                                                    {formatDate(run.start_date)} → {formatDate(run.end_date)}
                                                </span>
                                                <span>•</span>
                                                <span>₹{run.final_balance.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                                                <span className={`font-medium ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
                                                    ({isPositive ? '+' : ''}{pnlPct.toFixed(1)}%)
                                                </span>
                                            </div>
                                        </div>

                                        {/* Right: Actions */}
                                        <div className="flex items-center gap-1 ml-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="h-7 px-2"
                                                onClick={() => viewRun(run.run_id)}
                                            >
                                                <Eye className="h-4 w-4 mr-1" /> View
                                            </Button>
                                            <AlertDialog>
                                                <AlertDialogTrigger asChild>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="h-7 px-2 text-destructive hover:text-destructive"
                                                        disabled={deleting === run.run_id}
                                                    >
                                                        {deleting === run.run_id
                                                            ? <Loader2 className="h-4 w-4 animate-spin" />
                                                            : <Trash2 className="h-4 w-4" />
                                                        }
                                                    </Button>
                                                </AlertDialogTrigger>
                                                <AlertDialogContent>
                                                    <AlertDialogHeader>
                                                        <AlertDialogTitle>Delete this backtest?</AlertDialogTitle>
                                                        <AlertDialogDescription>
                                                            Run <code className="font-mono text-xs">{run.run_id}</code> with {run.trade_count} trades will be permanently deleted.
                                                        </AlertDialogDescription>
                                                    </AlertDialogHeader>
                                                    <AlertDialogFooter>
                                                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                                                        <AlertDialogAction
                                                            onClick={() => deleteRun(run.run_id)}
                                                            className="bg-destructive text-destructive-foreground"
                                                        >
                                                            Delete
                                                        </AlertDialogAction>
                                                    </AlertDialogFooter>
                                                </AlertDialogContent>
                                            </AlertDialog>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </CardContent>
            )}
        </Card>
    );
}
