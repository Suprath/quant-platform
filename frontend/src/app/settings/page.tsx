'use client';

import { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Settings, Save, AlertTriangle, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

export default function SettingsPage() {
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

  useEffect(() => {
    const fetchEnv = async () => {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'}/api/v1/config/env`);
        if (!res.ok) throw new Error('Failed to fetch environment configuration');
        const data = await res.json();
        setEnvVars(data.env || {});
      } catch (err: unknown) {
        if (err instanceof Error) {
          setMessage({ type: 'error', text: err.message });
        } else {
          setMessage({ type: 'error', text: 'An unknown error occurred' });
        }
      } finally {
        setLoading(false);
      }
    };
    fetchEnv();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'}/api/v1/config/env`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ env: envVars })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to save configuration');
      }

      setMessage({ type: 'success', text: 'Configuration saved successfully! A container restart may be required for some changes to take effect.' });
    } catch (err: unknown) {
      if (err instanceof Error) {
        setMessage({ type: 'error', text: err.message });
      } else {
        setMessage({ type: 'error', text: 'An unknown error occurred' });
      }
    } finally {
      setSaving(false);
    }
  };

  const handleInputChange = (key: string, value: string) => {
    setEnvVars(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="flex min-h-screen flex-col bg-background p-6 space-y-6">
      <header className="flex items-center gap-4 border-b pb-4">
        <Link href="/">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </Link>
        <div className="flex items-center gap-2">
          <Settings className="h-6 w-6" />
          <h1 className="text-3xl font-bold tracking-tight">System Settings</h1>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto space-y-6 mt-4">

        {message && (
          <Alert variant={message.type === 'error' ? 'destructive' : 'default'} className={message.type === 'success' ? 'border-green-500 text-green-600 bg-green-500/10' : ''}>
            <AlertTriangle className={`h-4 w-4 ${message.type === 'success' ? 'text-green-600' : ''}`} />
            <AlertTitle>{message.type === 'success' ? 'Success' : 'Error'}</AlertTitle>
            <AlertDescription>{message.text}</AlertDescription>
          </Alert>
        )}

        <Card className="shadow-lg">
          <CardHeader className="bg-muted/20 border-b">
            <CardTitle className="text-xl">Environment Variables</CardTitle>
            <CardDescription>
              Manage global application configuration. Modifications are written directly to the host `.env` file.
              <strong> You must restart the Docker containers to apply changes to database connections or message brokers.</strong>
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6 space-y-4">
            {loading ? (
              <div className="text-center text-muted-foreground py-10">Loading configuration...</div>
            ) : Object.keys(envVars).length === 0 ? (
              <div className="text-center text-muted-foreground py-10">No configuration found in .env</div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {Object.entries(envVars).map(([key, value]) => (
                  <div key={key} className="space-y-1">
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      {key.replace(/_/g, ' ')}
                    </label>
                    <div className="flex rounded-md shadow-sm">
                      <span className="inline-flex items-center px-3 rounded-l-md border border-r-0 border-input bg-muted text-muted-foreground sm:text-sm whitespace-nowrap overflow-hidden text-ellipsis max-w-[150px]" title={key}>
                        {key}
                      </span>
                      <Input
                        type={key.includes('PASSWORD') || key.includes('SECRET') || key.includes('TOKEN') ? 'password' : 'text'}
                        value={value}
                        onChange={(e) => handleInputChange(key, e.target.value)}
                        className="rounded-l-none font-mono text-sm"
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
          <CardFooter className="bg-muted/20 border-t px-6 py-4 flex justify-end">
            <Button onClick={handleSave} disabled={loading || saving || Object.keys(envVars).length === 0} className="w-full sm:w-auto">
              <Save className={`mr-2 h-4 w-4 ${saving ? 'animate-spin' : ''}`} />
              {saving ? 'Saving...' : 'Save Configuration'}
            </Button>
          </CardFooter>
        </Card>

      </main>
    </div>
  );
}
