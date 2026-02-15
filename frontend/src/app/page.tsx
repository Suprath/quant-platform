
import { ServiceHealth } from "@/components/ServiceHealth";
import { TradingDashboard } from "@/components/TradingDashboard";
import Link from 'next/link';
import { Button } from "@/components/ui/button";
import { Code, Terminal, Book } from 'lucide-react';

export default function DashboardPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background p-6 space-y-6">
      <header className="flex items-center justify-between border-b pb-4">
        <div className="flex items-center gap-2">
          <Terminal className="h-6 w-6" />
          <h1 className="text-3xl font-bold tracking-tight">Quant Platform</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/ide">
            <Button variant="outline">
              <Code className="mr-2 h-4 w-4" /> Strategy IDE
            </Button>
          </Link>
          <Link href="/docs">
            <Button variant="outline">
              <Book className="mr-2 h-4 w-4" /> API Docs
            </Button>
          </Link>
          <div className="text-sm text-muted-foreground ml-4">
            v1.0.0
          </div>
        </div>
      </header>

      <main className="flex-1 space-y-6">
        {/* Row 1: Health */}
        <section>
          <ServiceHealth />
        </section>

        {/* Row 2: Trading Dashboard */}
        <section>
          <h2 className="text-xl font-semibold mb-4">Live Trading Monitor</h2>
          <TradingDashboard />
        </section>
      </main>
    </div>
  );
}
