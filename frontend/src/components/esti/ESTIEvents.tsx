"use client";

import React, { useEffect, useState, useRef } from 'react';

const API_URL = "http://localhost:8002";

interface EventData {
    timestamp: number;
    category: 'cycle' | 'epoch' | 'backtest' | 'pressure' | string;
    data: {
        cycle?: number;
        train_date?: string;
        epoch?: number;
        brain_norm?: number;
        alive?: number;
        sharpe?: number;
        total_return?: number;
        level?: number;
        status?: string;
        mutation_multiplier?: number;
        injection_rate?: number;
        [key: string]: unknown;
    };
}

export function ESTIEvents() {
    const [events, setEvents] = useState<EventData[]>([]);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // SSE connection
        const eventSource = new EventSource(`${API_URL}/metrics/stream`);

        eventSource.onmessage = (event) => {
            try {
                const parsed = JSON.parse(event.data);
                setEvents((prev) => {
                    const newEvents = [...prev, parsed];
                    return newEvents.slice(-50); // Keep last 50 events
                });
            } catch (err) {
                console.error("Failed to parse event data", err);
            }
        };

        eventSource.onerror = (err) => {
            console.error("SSE connection error", err);
            // Browser will usually retry automatically, but we can close if needed
        };

        return () => {
            eventSource.close();
        };
    }, []);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [events]);

    const formatMessage = (ev: EventData) => {
        const d = ev.data;
        switch (ev.category) {
            case 'cycle':
                return `🚀 Cycle ${d.cycle} started: Training ${d.train_date}`;
            case 'epoch':
                return `✨ Epoch ${d.epoch} completed | Brain Norm: ${d.brain_norm?.toFixed(2) || "N/A"} | Alive: ${d.alive}`;
            case 'backtest':
                return `📊 OOS Backtest complete: Sharpe ${d.sharpe?.toFixed(2) || "0.00"} | Return ${((d.total_return || 0) * 100).toFixed(2)}%`;
            case 'pressure':
                return `🔥 Pressure level ${d.level} (${d.status}) | Mut: ${d.mutation_multiplier}x | Inj: ${d.injection_rate}`;
            case 'error':
                return `🚫 ERROR: ${d.message}`;
            default:
                return JSON.stringify(d);
        }
    };

    const getCategoryColor = (cat: string) => {
        switch (cat) {
            case 'cycle': return 'text-blue-400';
            case 'backtest': return 'text-green-400';
            case 'pressure': return 'text-orange-400';
            case 'epoch': return 'text-zinc-400';
            case 'error': return 'text-red-500';
            default: return 'text-zinc-500';
        }
    };

    return (
        <div className="rounded-lg border bg-card text-card-foreground shadow-sm flex flex-col overflow-hidden">
            <div className="px-4 py-2 bg-muted/40 border-b flex items-center justify-between">
                <span className="font-semibold text-xs tracking-tight uppercase">System Events</span>
                <div className="flex items-center gap-1.5">
                    <div className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                    <span className="text-[10px] text-muted-foreground uppercase font-medium">Live</span>
                </div>
            </div>

            <div
                ref={scrollRef}
                className="p-4 h-[300px] overflow-y-auto font-mono text-[10px] space-y-1 scroll-smooth"
            >
                {events.length === 0 && (
                    <div className="text-muted-foreground italic h-full flex items-center justify-center text-xs">
                        Waiting for evolutionary signals...
                    </div>
                )}
                {events.map((ev, i) => (
                    <div key={i} className="leading-relaxed border-b border-white/5 pb-1 last:border-0">
                        <span className="text-muted-foreground mr-2 font-light">
                            {new Date(ev.timestamp * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </span>
                        <span className={`font-bold mr-2 uppercase text-[9px] ${getCategoryColor(ev.category)} px-1 py-0.5 rounded bg-white/5`}>
                            {ev.category}
                        </span>
                        <span className="text-zinc-300">
                            {formatMessage(ev)}
                        </span>
                    </div>
                ))}
            </div>
        </div>
    );
}
