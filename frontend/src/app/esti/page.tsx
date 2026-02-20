"use client";

import React from 'react';
import { ESTIMetrics } from "@/components/esti/ESTIMetrics";
import { ESTICharts } from "@/components/esti/ESTICharts";
import { ESTIControls } from "@/components/esti/ESTIControls";
import { ESTIAgentTable } from "@/components/esti/ESTIAgentTable";
import { ESTIEvents } from "@/components/esti/ESTIEvents";
import { Button } from "@/components/ui/button";
import { ArrowLeft, BrainCircuit } from 'lucide-react';
import Link from 'next/link';

export default function ESTIDashboardPage() {
    return (
        <div className="min-h-screen bg-gradient-to-br from-gray-950 via-slate-900 to-black text-slate-100 p-4 md:p-8 space-y-8">
            {/* Header */}
            <header className="flex items-center justify-between border-b border-white/10 pb-6">
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon" className="hover:bg-white/10">
                            <ArrowLeft className="h-5 w-5" />
                        </Button>
                    </Link>
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-purple-500/20 rounded-lg border border-purple-500/40 shadow-[0_0_15px_rgba(168,85,247,0.4)]">
                            <BrainCircuit className="h-7 w-7 text-purple-400" />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-indigo-300">
                                ESTI AI Dashboard
                            </h1>
                            <div className="text-sm text-slate-400 mt-1">
                                Evolutionary Survival Trading Intelligence
                            </div>
                        </div>
                    </div>
                </div>
            </header>

            <main className="space-y-8 max-w-[1600px] mx-auto">
                {/* Row 1: Key Metrics */}
                <section>
                    <ESTIMetrics />
                </section>

                {/* Row 2: Main Layout (Charts + Controls) */}
                <div className="grid gap-8 lg:grid-cols-3">
                    {/* Left Column: Charts (2/3 width) */}
                    <div className="lg:col-span-2 space-y-8">
                        <ESTICharts />
                        <ESTIAgentTable />
                    </div>

                    {/* Right Column: Controls & Config (1/3 width) */}
                    <div className="space-y-8">
                        <ESTIControls />
                        <ESTIEvents />
                    </div>
                </div>
            </main>
        </div>
    );
}
