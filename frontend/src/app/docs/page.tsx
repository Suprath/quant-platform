"use client";

import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ArrowLeft, ExternalLink } from 'lucide-react';
import { Button } from "@/components/ui/button";
import Link from 'next/link';
import { Badge } from "@/components/ui/badge";

export default function DocsPage() {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
    const [guideContent, setGuideContent] = useState('');

    // Helper to safely check children for inline code detection
    const jsonStringify = (data: unknown) => {
        try { return JSON.stringify(data); } catch { return ''; }
    };

    useEffect(() => {
        fetch('/docs/algorithm_guide.md')
            .then(res => res.text())
            .then(text => setGuideContent(text));
    }, []);

    return (
        <div className="flex h-screen flex-col bg-background overflow-hidden">
            <header className="flex-none flex items-center justify-between border-b px-6 py-3 bg-card h-[60px]">
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div>
                        <h1 className="text-xl font-bold">API Documentation</h1>
                        <p className="text-xs text-muted-foreground">Quant Platform Backend API Reference</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" asChild>
                        <a href={`${API_URL}/docs`} target="_blank" rel="noopener noreferrer">
                            Open Swagger <ExternalLink className="ml-2 h-3 w-3" />
                        </a>
                    </Button>
                </div>
            </header>

            <main className="flex-1 relative min-h-0">
                <Tabs defaultValue="swagger" className="h-full flex flex-col overflow-hidden">
                    <div className="flex-none flex justify-between items-center px-4 py-2 bg-muted/20 border-b h-[50px]">
                        <TabsList>
                            <TabsTrigger value="swagger">Swagger UI</TabsTrigger>
                            <TabsTrigger value="redoc">ReDoc</TabsTrigger>
                            <TabsTrigger value="guide">Algorithm Guide</TabsTrigger>
                        </TabsList>
                        <div className="flex gap-2">
                            <Badge variant="secondary">FastAPI</Badge>
                            <Badge variant="outline">v1.0.0</Badge>
                        </div>
                    </div>

                    <TabsContent value="swagger" className="flex-1 m-0 p-0 border-0 relative mt-0 data-[state=inactive]:hidden">
                        <iframe
                            src={`${API_URL}/docs`}
                            className="absolute inset-0 w-full h-full border-0"
                            title="Swagger UI"
                        />
                    </TabsContent>

                    <TabsContent value="redoc" className="flex-1 m-0 p-0 border-0 relative mt-0 data-[state=inactive]:hidden">
                        <iframe
                            src={`${API_URL}/redoc`}
                            className="absolute inset-0 w-full h-full border-0"
                            title="ReDoc Visualization"
                        />
                    </TabsContent>

                    <TabsContent value="guide" className="flex-1 p-8 overflow-y-auto bg-white mt-0 data-[state=inactive]:hidden">
                        <div className="max-w-4xl mx-auto pb-20">
                            <ReactMarkdown
                                components={{
                                    h1: (props) => <h1 className="text-3xl font-bold mt-8 mb-4 pb-2 border-b" {...props} />,
                                    h2: (props) => <h2 className="text-2xl font-semibold mt-8 mb-4" {...props} />,
                                    h3: (props) => <h3 className="text-xl font-medium mt-6 mb-3" {...props} />,
                                    p: (props) => <p className="leading-7 mb-4 text-gray-700" {...props} />,
                                    ul: (props) => <ul className="list-disc pl-6 mb-4 space-y-1" {...props} />,
                                    ol: (props) => <ol className="list-decimal pl-6 mb-4 space-y-1" {...props} />,
                                    li: (props) => <li className="text-gray-700" {...props} />,
                                    code: ({ className, children, ...props }) => {
                                        const match = /language-(\w+)/.exec(className || '')
                                        const isInline = !match && !jsonStringify(children)?.includes('\n')
                                        return isInline
                                            ? <code className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono text-red-500" {...props}>{children}</code>
                                            : <code className="block bg-gray-900 text-gray-100 p-4 rounded-lg text-sm font-mono overflow-x-auto mb-4" {...props}>{children}</code>
                                    },
                                    pre: (props) => <pre className="bg-transparent p-0 mb-4" {...props} />,
                                    table: (props) => <div className="overflow-x-auto mb-4"><table className="min-w-full border border-gray-200" {...props} /></div>,
                                    th: (props) => <th className="border border-gray-200 px-4 py-2 bg-gray-50 text-left font-semibold" {...props} />,
                                    td: (props) => <td className="border border-gray-200 px-4 py-2 text-sm" {...props} />,
                                    blockquote: (props) => <blockquote className="border-l-4 border-blue-500 pl-4 italic my-4 text-gray-600" {...props} />,
                                    a: (props) => <a className="text-blue-600 hover:underline" {...props} />,
                                    hr: (props) => <hr className="my-8 border-gray-200" {...props} />,
                                }}
                            >
                                {guideContent}
                            </ReactMarkdown>
                        </div>
                    </TabsContent>
                </Tabs>
            </main>
        </div>
    );
}
