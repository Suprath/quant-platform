'use client';

import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { TrendingUp, TrendingDown, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface TopPerformer {
  symbol: string;
  name: string;
  open: number;
  close: number;
  change_pct: number;
  volume: number;
  date: string;
}

export function TopPerformersTable() {
  const [performers, setPerformers] = useState<TopPerformer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPerformers = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'}/api/v1/market/top-performers?limit=10`);
      if (!res.ok) throw new Error('Failed to fetch top performers');
      const data = await res.json();
      setPerformers(data);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('An unknown error occurred');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPerformers();
    // Auto refresh every minute
    const interval = setInterval(fetchPerformers, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Card className="w-full shadow-lg border-muted">
      <CardHeader className="flex flex-row items-center justify-between bg-muted/20 pb-4">
        <div>
          <CardTitle className="text-xl flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-green-500" />
            Yesterday&apos;s Top Performers
          </CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            Highest intraday % movers from the latest market close
          </p>
        </div>
        <Button variant="outline" size="icon" onClick={fetchPerformers} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader className="bg-muted/40">
            <TableRow>
              <TableHead className="pl-6 font-semibold">Symbol / Name</TableHead>
              <TableHead className="text-right font-semibold">Open</TableHead>
              <TableHead className="text-right font-semibold">Close</TableHead>
              <TableHead className="text-right font-semibold">Change %</TableHead>
              <TableHead className="text-right pr-6 font-semibold">Volume (Units)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && performers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center h-32 text-muted-foreground">
                  Analyzing market data...
                </TableCell>
              </TableRow>
            ) : error ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center h-32 text-red-400">
                  {error}
                </TableCell>
              </TableRow>
            ) : performers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center h-32 text-muted-foreground">
                  No market data available for yesterday.
                </TableCell>
              </TableRow>
            ) : (
              performers.map((stock) => {
                const isPositive = stock.change_pct >= 0;
                return (
                  <TableRow key={stock.symbol} className="hover:bg-muted/20 transition-colors">
                    <TableCell className="pl-6">
                      <div className="font-medium text-primary">{stock.name}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{stock.symbol}</div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">₹{stock.open.toFixed(2)}</TableCell>
                    <TableCell className="text-right tabular-nums font-medium">₹{stock.close.toFixed(2)}</TableCell>
                    <TableCell className="text-right">
                      <div className={`inline-flex items-center gap-1 font-semibold px-2 py-1 rounded-md text-sm ${isPositive ? 'text-green-500 bg-green-500/10' : 'text-red-500 bg-red-500/10'
                        }`}>
                        {isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                        {isPositive ? '+' : ''}{stock.change_pct.toFixed(2)}%
                      </div>
                    </TableCell>
                    <TableCell className="text-right pr-6 tabular-nums text-muted-foreground">
                      {stock.volume.toLocaleString()}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
