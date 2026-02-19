import { ServiceHealth } from "@/components/ServiceHealth";
import { TopPerformersTable } from "@/components/dashboard/TopPerformersTable";
import Link from 'next/link';
import { Button } from "@/components/ui/button";
import { Code, Terminal, Book, BrainCircuit, Settings, Activity } from 'lucide-react';

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
          <Link href="/esti">
            <Button variant="outline">
              <BrainCircuit className="mr-2 h-4 w-4 text-purple-500" /> ESTI AI
            </Button>
          </Link>
          <Link href="/dashboard/live">
            <Button variant="outline" className="border-blue-500/20 hover:bg-blue-500/10 hover:text-blue-500 transition-colors">
              <Activity className="mr-2 h-4 w-4 text-blue-500" /> Live Trading
            </Button>
          </Link>
          <Link href="/docs">
            <Button variant="outline">
              <Book className="mr-2 h-4 w-4" /> API Docs
            </Button>
          </Link>
          <Link href="/settings">
            <Button variant="ghost" size="icon" className="ml-2">
              <Settings className="h-5 w-5" />
            </Button>
          </Link>
          <div className="text-sm text-muted-foreground ml-4">
            v1.1.0
          </div>
        </div>
      </header>

      <main className="flex-1 space-y-6 mt-4">
        {/* Row 1: Health */}
        <section>
          <ServiceHealth />
        </section>

        {/* Row 2: Top Performers Dashboard */}
        <section>
          <TopPerformersTable />
        </section>
      </main>
    </div>
  );
}
