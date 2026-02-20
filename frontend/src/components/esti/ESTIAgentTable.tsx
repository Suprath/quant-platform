"use client";

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { ArrowUpDown, Brain } from 'lucide-react';

const API_URL = "http://localhost:8002";

interface Agent {
    agent_id: number;
    alive: boolean;
    sharpe: number;
    capital: number;
    health: number;
    growth: number;
    rank: number;
    survival_score: number;
    death_cause?: string;
    lifetime: number;
}

interface SortConfig {
    key: keyof Agent;
    direction: 'asc' | 'desc';
}

export function ESTIAgentTable() {
    const [agents, setAgents] = useState<Agent[]>([]);
    const [sortConfig, setSortConfig] = useState<SortConfig>({ key: 'sharpe', direction: 'desc' });

    useEffect(() => {
        const fetchAgents = async () => {
            try {
                const res = await fetch(`${API_URL}/agents`);
                const data = await res.json();
                setAgents(data.agents || []);
            } catch (err) {
                console.error("Failed to fetch agents", err);
            }
        };

        const interval = setInterval(fetchAgents, 3000);
        fetchAgents();
        return () => clearInterval(interval);
    }, []);

    const handleSort = (key: keyof Agent) => {
        let direction: 'asc' | 'desc' = 'desc';
        if (sortConfig.key === key && sortConfig.direction === 'desc') {
            direction = 'asc';
        }
        setSortConfig({ key, direction });
    };

    const sortedAgents = [...agents].sort((a, b) => {
        const aValue = a[sortConfig.key];
        const bValue = b[sortConfig.key];

        if (aValue === undefined || bValue === undefined) return 0;

        if (aValue < bValue) return sortConfig.direction === 'asc' ? -1 : 1;
        if (aValue > bValue) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });

    return (
        <Card className="bg-black/40 backdrop-blur-md border-white/10 shadow-2xl">
            <CardHeader className="flex flex-row items-center justify-between pb-4 border-b border-white/10">
                <CardTitle className="text-slate-200 font-semibold tracking-wide flex items-center gap-2">
                    <Brain className="w-5 h-5 text-indigo-400" />
                    Population Analysis
                </CardTitle>
                <div className="text-sm font-medium text-slate-400 bg-white/5 px-3 py-1.5 rounded-full border border-white/10">
                    Active: <span className="text-emerald-400">{agents.filter(a => a.alive).length}</span>
                    <span className="mx-2 text-slate-600">|</span>
                    Extinct: <span className="text-red-400/80">{agents.filter(a => !a.alive).length}</span>
                </div>
            </CardHeader>
            <CardContent className="p-0">
                <div className="max-h-[500px] overflow-y-auto custom-scrollbar">
                    <Table>
                        <TableHeader className="bg-black/20 sticky top-0 z-10 backdrop-blur-sm">
                            <TableRow className="border-white/10 hover:bg-transparent">
                                <TableHead onClick={() => handleSort('agent_id')} className="cursor-pointer hover:text-white transition-colors text-slate-400">
                                    Agent ID <ArrowUpDown className="ml-1 h-3 w-3 inline" />
                                </TableHead>
                                <TableHead className="w-[100px] text-slate-400">Status</TableHead>
                                <TableHead onClick={() => handleSort('sharpe')} className="cursor-pointer hover:text-white transition-colors text-right text-slate-400">
                                    Sharpe <ArrowUpDown className="ml-1 h-3 w-3 inline" />
                                </TableHead>
                                <TableHead onClick={() => handleSort('capital')} className="cursor-pointer hover:text-white transition-colors text-right text-slate-400">
                                    Capital (₹) <ArrowUpDown className="ml-1 h-3 w-3 inline" />
                                </TableHead>
                                <TableHead className="w-[180px] text-slate-400">Network Health</TableHead>
                                <TableHead onClick={() => handleSort('growth')} className="cursor-pointer hover:text-white transition-colors text-slate-400 w-[150px]">
                                    Growth (20d) <ArrowUpDown className="ml-1 h-3 w-3 inline" />
                                </TableHead>
                                <TableHead className="text-right text-slate-400">Actions</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {sortedAgents.map((agent) => (
                                <TableRow
                                    key={agent.agent_id}
                                    className={`border-white/5 transition-colors ${!agent.alive ? "opacity-40 bg-red-950/10 hover:bg-red-950/20" : "hover:bg-white/5"
                                        }`}
                                >
                                    <TableCell className="font-mono text-sm text-slate-300">
                                        ID-{agent.agent_id.toString().padStart(3, '0')}
                                    </TableCell>
                                    <TableCell>
                                        {agent.alive ? (
                                            <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 animate-pulse-slow">
                                                Active
                                            </Badge>
                                        ) : (
                                            <Badge variant="outline" className="bg-red-500/10 text-red-400/80 border-red-500/20">
                                                Extinct
                                            </Badge>
                                        )}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-slate-200 font-medium">
                                        {agent.sharpe.toFixed(2)}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-slate-300">
                                        ₹{agent.capital.toLocaleString()}
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex items-center gap-3">
                                            <Progress
                                                value={agent.health * 100}
                                                className="h-1.5 bg-slate-800"
                                                indicatorClassName={agent.health < 0.3 ? "bg-red-500" : agent.health < 0.7 ? "bg-yellow-500" : "bg-emerald-500"}
                                            />
                                            <span className="text-xs text-slate-400 font-mono w-8">
                                                {(agent.health * 100).toFixed(0)}%
                                            </span>
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex items-center gap-3">
                                            <Progress
                                                value={Math.min(Math.max(agent.growth * 100, 0), 100)}
                                                className="h-1.5 bg-slate-800"
                                                indicatorClassName={agent.growth < 0 ? "bg-red-500" : "bg-blue-500"}
                                            />
                                            <span className={`text-xs font-mono w-12 ${agent.growth < 0 ? "text-red-400" : "text-blue-400"}`}>
                                                {(agent.growth * 100).toFixed(1)}%
                                            </span>
                                        </div>
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-slate-400 hover:text-white hover:bg-white/10">
                                            <Brain className="h-4 w-4" />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            </CardContent>
        </Card>
    );
}
