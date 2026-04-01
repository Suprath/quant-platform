"use client";

import { motion } from "framer-motion";
import Link from 'next/link';
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { ServiceHealth } from "@/components/ServiceHealth";
import { TopPerformersTable } from "@/components/dashboard/TopPerformersTable";
import { Code, Terminal, Book, Settings, Activity, Zap, Shield, Layers, TrendingUp } from 'lucide-react';

const fadeIn = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 }
};

const staggerChildren = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1
    }
  }
};

export default function DashboardPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground overflow-x-hidden transition-colors duration-300">
      {/* Navbar Layout */}
      <motion.header
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5 }}
        className="sticky top-0 z-50 flex items-center justify-between border-b bg-background/80 backdrop-blur-md px-6 py-4 shadow-sm"
      >
        <div className="flex items-center gap-2 shrink-0">
          <div className="bg-primary p-1.5 rounded-lg text-primary-foreground shadow-sm shadow-primary/30">
            <Terminal className="h-6 w-6" />
          </div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight bg-gradient-to-r from-primary to-blue-500 bg-clip-text text-transparent">KIRA</h1>
        </div>

        <div className="flex items-center gap-2 md:gap-4 ml-auto">
          <Link href="/terminal" className="hidden lg:block">
            <Button variant="ghost" className="hover:bg-orange-500/10 text-orange-600 dark:text-orange-400 hover:text-orange-700 dark:hover:text-orange-300 transition-colors">
              <Terminal className="mr-2 h-4 w-4" /> Vektor Terminal
            </Button>
          </Link>

          <Link href="/ide" className="hidden lg:block">
            <Button variant="ghost" className="hover:bg-primary/10 transition-colors">
              <Code className="mr-2 h-4 w-4" /> Strategy IDE
            </Button>
          </Link>
          <Link href="/dashboard/live" className="hidden lg:block">
            <Button variant="ghost" className="hover:bg-blue-500/10 text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors">
              <Activity className="mr-2 h-4 w-4" /> Live Trading
            </Button>
          </Link>
          <Link href="/dashboard/orderflow" className="hidden lg:block">
            <Button variant="ghost" className="hover:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors">
              <TrendingUp className="mr-2 h-4 w-4" /> Order Flow
            </Button>
          </Link>
          <Link href="/dashboard/edge" className="hidden sm:block">
            <Button variant="outline" className="border-purple-500/30 text-purple-600 hover:bg-purple-500/10 dark:text-purple-400 dark:hover:text-purple-300 transition-colors shadow-sm">
              <Zap className="mr-2 h-4 w-4 fill-current" /> Edge Scanner
            </Button>
          </Link>
          <Link href="/dashboard/options" className="hidden sm:block">
            <Button variant="outline" className="border-amber-500/30 text-amber-600 hover:bg-amber-500/10 dark:text-amber-400 dark:hover:text-amber-300 transition-colors shadow-sm">
              <Layers className="mr-2 h-4 w-4" /> Options Chain
            </Button>
          </Link>
          <Link href="/docs" className="hidden sm:block">
            <Button variant="ghost">
              <Book className="mr-2 h-4 w-4" /> Docs
            </Button>
          </Link>
          <ThemeToggle />
          <Link href="/settings" className="hidden sm:block">
            <Button variant="ghost" size="icon">
              <Settings className="h-5 w-5" />
            </Button>
          </Link>
        </div>
      </motion.header>

      <main className="flex-1 flex flex-col items-center w-full">
        {/* Hero Section */}
        <section className="relative w-full max-w-6xl mx-auto px-6 py-16 md:py-32 flex flex-col items-center text-center">
          <motion.div
            initial="hidden"
            animate="visible"
            variants={staggerChildren}
            className="space-y-6 max-w-3xl"
          >
            <motion.div variants={fadeIn} className="inline-flex items-center rounded-full border border-blue-500/30 px-3 py-1 text-xs font-semibold bg-blue-500/10 text-blue-700 dark:text-blue-300">
              <span className="flex h-2 w-2 rounded-full bg-blue-500 mr-2 animate-pulse"></span>
              v1.2.0 Vectorized Edge Framework Enabled
            </motion.div>
            <motion.h1 variants={fadeIn} className="text-4xl md:text-6xl font-extrabold tracking-tight leading-[1.1]">
              Kinetic Intelligence for <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-cyan-500 dark:from-blue-400 dark:to-cyan-300">
                Research & Alpha
              </span>
            </motion.h1>
            <motion.p variants={fadeIn} className="text-lg md:text-xl text-muted-foreground px-4">
              Build, backtest, and deploy high-frequency quantitative strategies at lightning speed. Powered by Vectorized Pandas, Fast API, and Next.js.
            </motion.p>
            <motion.div variants={fadeIn} className="flex flex-wrap justify-center gap-4 pt-4 px-4">
              <Link href="/terminal" className="w-full sm:w-auto">
                <Button size="lg" className="w-full h-12 px-8 font-semibold shadow-lg bg-orange-600 hover:bg-orange-700 text-white hover:scale-105 transition-transform text-md">
                   Vektor Terminal <Terminal className="ml-2 h-5 w-5" />
                </Button>
              </Link>

              <Link href="/ide" className="w-full sm:w-auto">
                <Button size="lg" variant="outline" className="w-full h-12 px-8 font-semibold border-border hover:scale-105 transition-transform text-md">
                  Launch Strategy IDE <Code className="ml-2 h-5 w-5" />
                </Button>
              </Link>
            </motion.div>
          </motion.div>

          {/* Decorative background glow */}
          <div className="absolute top-1/2 left-1/2 -z-10 h-[300px] md:h-[500px] w-[300px] md:w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/20 blur-[100px] dark:bg-primary/10"></div>
        </section>

        {/* Bento Grid Features */}
        <section className="w-full max-w-6xl mx-auto px-6 py-12">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-50px" }}
            variants={staggerChildren}
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
          >
            <motion.div variants={fadeIn} className="md:col-span-2 bg-card border text-card-foreground rounded-2xl p-6 md:p-8 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
              <div className="absolute top-0 right-0 -mt-4 -mr-4 h-32 w-32 bg-blue-500/10 rounded-full blur-2xl group-hover:bg-blue-500/20 transition-colors"></div>
              <Activity className="h-10 w-10 text-blue-500 mb-4" />
              <h3 className="text-2xl font-bold mb-2">Vectorized Pandas Engine</h3>
              <p className="text-muted-foreground mb-4 max-w-md">Our new C-compiled backend architecture sweeps millions of rows of OHLCV data to locate highly probable micro-patterns and inefficiencies instantly across temporal horizons.</p>
            </motion.div>

            <motion.div variants={fadeIn} className="bg-card border text-card-foreground rounded-2xl p-6 md:p-8 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group flex flex-col justify-center">
              <div className="absolute top-0 right-0 -mt-4 -mr-4 h-24 w-24 bg-purple-500/10 rounded-full blur-2xl group-hover:bg-purple-500/20 transition-colors"></div>
              <Shield className="h-10 w-10 text-purple-500 mb-4" />
              <h3 className="text-xl font-bold mb-2">Institutional Database</h3>
              <p className="text-sm text-muted-foreground">End-to-end multi-layer architecture integrating QuestDB TimeSeries with Postgres relational metadata maps.</p>
            </motion.div>

            <motion.div variants={fadeIn} className="bg-card border text-card-foreground rounded-2xl p-6 md:p-8 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group flex flex-col justify-center">
              <div className="absolute top-0 right-0 -mt-4 -mr-4 h-24 w-24 bg-green-500/10 rounded-full blur-2xl group-hover:bg-green-500/20 transition-colors"></div>
              <Zap className="h-10 w-10 text-green-500 mb-4" />
              <h3 className="text-xl font-bold mb-2">Kafka Backbone</h3>
              <p className="text-sm text-muted-foreground">Distributed streaming event architecture bypassing typical REST bottlenecks for microsecond execution latency.</p>
            </motion.div>

            <motion.div variants={fadeIn} className="md:col-span-2 bg-card border text-card-foreground rounded-2xl p-6 md:p-8 shadow-sm hover:shadow-md transition-shadow overflow-hidden">
              <h3 className="flex items-center gap-2 text-xl font-bold mb-6">
                <Activity className="h-5 w-5 text-primary" /> Today&apos;s Market Edge
              </h3>
              <div className="bg-background rounded-xl overflow-x-auto border">
                <div className="min-w-[600px]">
                  <TopPerformersTable />
                </div>
              </div>
            </motion.div>
          </motion.div>
        </section>

        {/* Global Architecture / Health */}
        <section className="w-full bg-secondary/30 border-y py-16 mt-12 overflow-hidden">
          <div className="max-w-6xl mx-auto px-6">
            <motion.div
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: "-100px" }}
              variants={staggerChildren}
              className="flex flex-col gap-8"
            >
              <div className="text-center max-w-2xl mx-auto mb-4">
                <h2 className="text-3xl font-bold mb-4 tracking-tight">Infrastructure Health Telemetry</h2>
                <p className="text-muted-foreground">Monitor the isolated containerized microservices operating on the Docker bridge network real-time heartbeat.</p>
              </div>
              <motion.div variants={fadeIn} className="bg-card border rounded-2xl p-4 md:p-8 shadow-lg overflow-x-auto">
                <div className="min-w-[700px]">
                  <ServiceHealth />
                </div>
              </motion.div>
            </motion.div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full border-t bg-background py-8 text-center text-sm text-muted-foreground">
        <p>© 2026 KIRA - Kinetic Intelligence for Research & Alpha. All rights reserved.</p>
      </footer>
    </div>
  );
}
