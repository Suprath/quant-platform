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
        <Card>
            <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>Population Analysis</CardTitle>
                <div className="text-sm text-muted-foreground">
                    Total: {agents.length} | Dead: {agents.filter(a => !a.alive).length}
                </div>
            </CardHeader>
            <CardContent>
                <div className="rounded-md border max-h-[500px] overflow-y-auto">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead onClick={() => handleSort('agent_id')} className="cursor-pointer hover:bg-muted/50">
                                    Agent ID <ArrowUpDown className="ml-2 h-4 w-4 inline" />
                                </TableHead>
                                <TableHead className="w-[100px]">Status</TableHead>
                                <TableHead onClick={() => handleSort('sharpe')} className="cursor-pointer hover:bg-muted/50 text-right">
                                    Sharpe <ArrowUpDown className="ml-2 h-4 w-4 inline" />
                                </TableHead>
                                <TableHead onClick={() => handleSort('capital')} className="cursor-pointer hover:bg-muted/50 text-right">
                                    Capital (₹) <ArrowUpDown className="ml-2 h-4 w-4 inline" />
                                </TableHead>
                                <TableHead className="w-[150px]">Health</TableHead>
                                <TableHead onClick={() => handleSort('growth')} className="cursor-pointer hover:bg-muted/50 text-right">
                                    Growth (20d) <ArrowUpDown className="ml-2 h-4 w-4 inline" />
                                </TableHead>
                                <TableHead className="text-right">Actions</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {sortedAgents.map((agent) => (
                                <TableRow key={agent.agent_id} className={!agent.alive ? "opacity-50 bg-muted/20" : ""}>
                                    <TableCell className="font-medium">
                                        Agent-{agent.agent_id.toString().padStart(3, '0')}
                                    </TableCell>
                                    <TableCell>
                                        {agent.alive ? (
                                            <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">Alive</Badge>
                                        ) : (
                                            <Badge variant="secondary">Dead</Badge>
                                        )}
                                    </TableCell>
                                    <TableCell className="text-right font-mono">
                                        {agent.sharpe.toFixed(2)}
                                    </TableCell>
                                    <TableCell className="text-right font-mono">
                                        ₹{agent.capital.toLocaleString()}
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex items-center gap-2">
                                            <Progress value={agent.health * 100} className="h-2"
                                                indicatorClassName={agent.health < 0.3 ? "bg-red-500" : agent.health < 0.7 ? "bg-yellow-500" : "bg-green-500"}
                                            />
                                            <span className="text-xs text-muted-foreground">{(agent.health * 100).toFixed(0)}%</span>
                                        </div>
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-xs">
                                        {(agent.growth * 100).toFixed(2)}%
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Button variant="ghost" size="sm">
                                            <Brain className="h-3 w-3" />
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
