
"use client";

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchSystemHealth, HealthStatus } from '@/lib/api';
import { BadgeCheck, Ban, Activity } from 'lucide-react';
import clsx from 'clsx';

export function ServiceHealth() {
    const [statuses, setStatuses] = useState<HealthStatus[]>([]);
    const [loading, setLoading] = useState(true);

    const refreshHealth = async () => {
        setLoading(true);
        const data = await fetchSystemHealth();
        setStatuses(data);
        setLoading(false);
    };

    useEffect(() => {
        refreshHealth();
        const interval = setInterval(refreshHealth, 30000); // Poll every 30s
        return () => clearInterval(interval);
    }, []);

    return (
        <Card className="w-full">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">
                    System Health
                    {loading && <span className="ml-2 text-xs text-muted-foreground">(Refreshing...)</span>}
                </CardTitle>
                <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
                    {statuses.map((s) => (
                        <div key={s.service} className="flex items-center space-x-2 border p-2 rounded-md">
                            {s.status === 'online' ? (
                                <BadgeCheck className="h-5 w-5 text-green-500" />
                            ) : (
                                <Ban className="h-5 w-5 text-red-500" />
                            )}
                            <div className="flex flex-col">
                                <span className="text-sm font-semibold">{s.service}</span>
                                <span className={clsx(
                                    "text-xs",
                                    s.status === 'online' ? "text-green-600" : "text-red-600"
                                )}>
                                    {s.status.toUpperCase()}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            </CardContent>
        </Card >
    );
}
