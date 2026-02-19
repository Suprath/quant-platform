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
        <div className="min-h-screen bg-background p-6 space-y-6">
            {/* Header */}
            <header className="flex items-center justify-between border-b pb-4">
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-5 w-5" />
                        </Button>
                    </Link>
                    <div className="flex items-center gap-2">
                        <BrainCircuit className="h-6 w-6 text-purple-500" />
                        <h1 className="text-2xl font-bold tracking-tight">ESTI AI Dashboard</h1>
                    </div>
                </div>
                <div className="text-sm text-muted-foreground">
                    Evolutionary Survival Trading Intelligence
                </div>
            </header>

            <main className="space-y-6">
                {/* Row 1: Key Metrics */}
                <section>
                    <ESTIMetrics />
                </section>

                {/* Row 2: Main Layout (Charts + Controls) */}
                <div className="grid gap-6 lg:grid-cols-3">
                    {/* Left Column: Charts (2/3 width) */}
                    <div className="lg:col-span-2 space-y-6">
                        <ESTICharts />
                        <ESTIAgentTable />
                    </div>

                    {/* Right Column: Controls & Config (1/3 width) */}
                    <div className="space-y-6">
                        <ESTIControls />
                        <ESTIEvents />
                    </div>
                </div>
            </main>
        </div>
    );
}
