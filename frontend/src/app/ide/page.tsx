
"use client";

import React, { useState } from 'react';
import { CodeEditor } from "@/components/editor/CodeEditor";
import { Save, ArrowLeft } from 'lucide-react';
import { Button } from "@/components/ui/button";
import { BacktestRunner } from "@/components/BacktestRunner";
import Link from 'next/link';

// Mock implementation of File Explorer for now
const FILES = [
    { name: 'demo_strategy.py', content: 'class DemoStrategy(QCAlgorithm):\n    def Initialize(self):\n        self.SetCash(10000)\n        self.AddEquity("NSE_EQ|RELIANCE")\n' },
    { name: 'momentum.py', content: '# Momentum Strategy\n# Buy when price > SMA(50)\n' },
    { name: 'mean_reversion.py', content: '# Mean Reversion\n# Buy when RSI < 30\n' },
];

export default function IdePage() {
    const [activeFile, setActiveFile] = useState(FILES[0]);
    const [code, setCode] = useState(FILES[0].content);

    const handleFileSelect = (file: typeof FILES[0]) => {
        setActiveFile(file);
        setCode(file.content);
    };

    const handleSave = () => {
        console.log("Saving file:", activeFile.name, code);
        // TODO: POST /api/strategies/save
    };

    return (
        <div className="flex h-screen flex-col bg-background">
            <header className="flex items-center justify-between border-b px-6 py-3">
                <div className="flex items-center gap-2">
                    <Link href="/">
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <span className="font-bold text-lg">Strategy IDE</span>
                    <span className="text-muted-foreground">/ {activeFile.name}</span>
                </div>
                <div className="flex items-center gap-2">
                    <Button size="sm" variant="secondary" onClick={handleSave}>
                        <Save className="mr-2 h-4 w-4" /> Save
                    </Button>
                    <BacktestRunner strategyName={activeFile.name} strategyCode={code} />
                </div>
            </header>

            <div className="flex flex-1 overflow-hidden">
                {/* Sidebar */}
                <aside className="w-64 border-r bg-muted/20 p-4 overflow-y-auto">
                    <h3 className="font-semibold mb-4 text-sm text-muted-foreground uppercase tracking-wider">Explorer</h3>
                    <ul className="space-y-1">
                        {FILES.map((file) => (
                            <li key={file.name}>
                                <button
                                    onClick={() => handleFileSelect(file)}
                                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${activeFile.name === file.name
                                        ? 'bg-primary/10 text-primary font-medium'
                                        : 'hover:bg-muted text-foreground'
                                        }`}
                                >
                                    {file.name}
                                </button>
                            </li>
                        ))}
                    </ul>
                </aside>

                {/* Main Editor */}
                <main className="flex-1 p-0 relative">
                    <CodeEditor
                        initialValue={code}
                        language="python"
                        onChange={(value) => setCode(value || "")}
                    />
                </main>
            </div>
        </div>
    );
}
