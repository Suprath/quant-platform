
"use client";

import React, { useState, useCallback, useEffect } from 'react';
import { CodeEditor } from "@/components/editor/CodeEditor";
import {
    Save, ArrowLeft, FilePlus, FolderPlus, Trash2, Edit2,
    ChevronRight, ChevronDown, FileCode2, Folder, FolderOpen,
    X, Terminal, PanelBottomClose, PanelBottom
} from 'lucide-react';
import { Button } from "@/components/ui/button";
import { BacktestRunner } from "@/components/BacktestRunner";
import { DataBackfill } from "@/components/DataBackfill";
import { BacktestHistory } from "@/components/BacktestHistory";
import { Input } from "@/components/ui/input";
import Link from 'next/link';
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel,
    AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
    AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
    Dialog, DialogContent, DialogHeader, DialogTitle,
    DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";


// ============================================================
// Types
// ============================================================

interface ProjectFile {
    id: string;
    name: string;
    content: string;
}

interface Project {
    id: string;
    name: string;
    files: ProjectFile[];
    expanded: boolean;
}

// ============================================================
// Starter Projects
// ============================================================

const DEFAULT_PROJECTS: Project[] = [
    {
        id: 'proj_demo',
        name: 'demo_strategy',
        expanded: true,
        files: [
            {
                id: 'f_demo_main',
                name: 'main.py',
                content: `from quant_sdk.algorithm import QCAlgorithm

class DemoStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.AddEquity("NSE_EQ|INE002A01018")

    def OnData(self, data):
        for symbol in data.Keys:
            tick = data[symbol]
            if not self.Portfolio.get(symbol) or not self.Portfolio[symbol].Invested:
                self.SetHoldings(symbol, 0.5)
                self.Log(f"BUY {symbol} @ {tick.Price}")
`
            }
        ]
    },
    {
        id: 'proj_mean_rev',
        name: 'mean_reversion',
        expanded: false,
        files: [
            {
                id: 'f_mr_main',
                name: 'main.py',
                content: `from quant_sdk.algorithm import QCAlgorithm
from .indicators_helper import BollingerBands

class MeanReversion(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.AddUniverse(self.SelectUniverse)
        self.bands = {}

    def SelectUniverse(self, coarse):
        return coarse

    def OnData(self, data):
        for symbol in data.Keys:
            tick = data[symbol]
            price = tick.Price

            if symbol not in self.bands:
                self.bands[symbol] = BollingerBands(period=20)

            self.bands[symbol].update(price)

            if not self.bands[symbol].ready:
                continue

            upper, lower, mean = self.bands[symbol].values()
            holding = self.Portfolio.get(symbol)
            qty = holding.Quantity if holding else 0

            if price < lower and qty <= 0:
                self.SetHoldings(symbol, 0.1)
                self.Log(f"BUY {symbol} @ {price:.2f} (Below lower band)")
            elif price > upper and qty > 0:
                self.Liquidate(symbol)
                self.Log(f"SELL {symbol} @ {price:.2f} (Above upper band)")
`
            },
            {
                id: 'f_mr_indicators',
                name: 'indicators_helper.py',
                content: `"""
Custom indicators module for the Mean Reversion strategy.
This file demonstrates multi-file project support.
"""
import statistics
from collections import deque


class BollingerBands:
    """Simple Bollinger Bands calculator."""

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std
        self.history: deque = deque(maxlen=period)

    def update(self, price: float):
        self.history.append(price)

    @property
    def ready(self) -> bool:
        return len(self.history) >= self.period

    def values(self):
        """Returns (upper, lower, mean)."""
        mean = statistics.mean(self.history)
        std = statistics.stdev(self.history)
        upper = mean + (self.num_std * std)
        lower = mean - (self.num_std * std)
        return upper, lower, mean
`
            }
        ]
    },
];


// ============================================================
// Main IDE Page
// ============================================================

export default function IdePage() {
    // --- State ---
    const [projects, setProjects] = useState<Project[]>(DEFAULT_PROJECTS);
    const [activeProjectId, setActiveProjectId] = useState<string>(DEFAULT_PROJECTS[0].id);
    const [activeFileId, setActiveFileId] = useState<string>(DEFAULT_PROJECTS[0].files[0].id);
    const [openTabs, setOpenTabs] = useState<{ projectId: string; fileId: string }[]>([
        { projectId: DEFAULT_PROJECTS[0].id, fileId: DEFAULT_PROJECTS[0].files[0].id }
    ]);

    // Dialog state
    const [isCreateProjectOpen, setIsCreateProjectOpen] = useState(false);
    const [newProjectName, setNewProjectName] = useState("");
    const [isCreateFileOpen, setIsCreateFileOpen] = useState(false);
    const [newFileName, setNewFileName] = useState("");
    const [isRenameOpen, setIsRenameOpen] = useState(false);
    const [renameValue, setRenameValue] = useState("");
    const [renameTarget, setRenameTarget] = useState<{ type: 'project' | 'file'; projectId: string; fileId?: string } | null>(null);

    // Terminal panel
    const [showTerminal, setShowTerminal] = useState(false);

    // Save feedback
    const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

    // --- Load from LocalStorage ---
    useEffect(() => {
        const saved = localStorage.getItem('quant_ide_projects_v2');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                if (parsed.length > 0) {
                    setProjects(parsed);
                    setActiveProjectId(parsed[0].id);
                    if (parsed[0].files.length > 0) {
                        setActiveFileId(parsed[0].files[0].id);
                        setOpenTabs([{ projectId: parsed[0].id, fileId: parsed[0].files[0].id }]);
                    }
                }
            } catch (e) { console.error("Failed to load projects", e); }
        }
    }, []);

    const saveToStorage = useCallback((newProjects: Project[]) => {
        localStorage.setItem('quant_ide_projects_v2', JSON.stringify(newProjects));
    }, []);

    // --- Derived State ---
    const activeProject = projects.find(p => p.id === activeProjectId) || projects[0];
    const activeFile = activeProject?.files.find(f => f.id === activeFileId);
    const code = activeFile?.content || "";

    // --- Helpers ---
    const updateFileContent = useCallback((value: string | undefined) => {
        setProjects(prev => {
            const updated = prev.map(p => {
                if (p.id === activeProjectId) {
                    return {
                        ...p,
                        files: p.files.map(f =>
                            f.id === activeFileId ? { ...f, content: value || "" } : f
                        )
                    };
                }
                return p;
            });
            return updated;
        });
    }, [activeProjectId, activeFileId]);

    // --- Tab Management ---
    const openFileInTab = (projectId: string, fileId: string) => {
        setActiveProjectId(projectId);
        setActiveFileId(fileId);
        if (!openTabs.find(t => t.projectId === projectId && t.fileId === fileId)) {
            setOpenTabs(prev => [...prev, { projectId, fileId }]);
        }
    };

    const closeTab = (projectId: string, fileId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        const newTabs = openTabs.filter(t => !(t.projectId === projectId && t.fileId === fileId));
        setOpenTabs(newTabs);
        if (activeFileId === fileId && newTabs.length > 0) {
            const last = newTabs[newTabs.length - 1];
            setActiveProjectId(last.projectId);
            setActiveFileId(last.fileId);
        }
    };

    const getFileForTab = (projectId: string, fileId: string) => {
        const proj = projects.find(p => p.id === projectId);
        return proj?.files.find(f => f.id === fileId);
    };

    // --- Project/File CRUD ---
    const handleCreateProject = () => {
        if (!newProjectName.trim()) return;
        const safeName = newProjectName.trim().replace(/[^a-zA-Z0-9_]/g, '_');
        const newProject: Project = {
            id: `proj_${Date.now()}`,
            name: safeName,
            expanded: true,
            files: [{
                id: `f_${Date.now()}_main`,
                name: 'main.py',
                content: `from quant_sdk.algorithm import QCAlgorithm\n\nclass ${safeName.charAt(0).toUpperCase() + safeName.slice(1)}Strategy(QCAlgorithm):\n    def Initialize(self):\n        self.SetCash(100000)\n\n    def OnData(self, data):\n        pass\n`
            }]
        };
        const updated = [...projects, newProject];
        setProjects(updated);
        saveToStorage(updated);
        setActiveProjectId(newProject.id);
        setActiveFileId(newProject.files[0].id);
        openFileInTab(newProject.id, newProject.files[0].id);
        setNewProjectName("");
        setIsCreateProjectOpen(false);
    };

    const handleCreateFile = () => {
        if (!newFileName.trim()) return;
        let fname = newFileName.trim();
        if (!fname.endsWith('.py')) fname += '.py';
        const newFile: ProjectFile = {
            id: `f_${Date.now()}`,
            name: fname,
            content: `# ${fname}\n`
        };
        const updated = projects.map(p =>
            p.id === activeProjectId ? { ...p, files: [...p.files, newFile] } : p
        );
        setProjects(updated);
        saveToStorage(updated);
        openFileInTab(activeProjectId, newFile.id);
        setNewFileName("");
        setIsCreateFileOpen(false);
    };

    const handleDeleteFile = (projectId: string, fileId: string) => {
        const updated = projects.map(p =>
            p.id === projectId ? { ...p, files: p.files.filter(f => f.id !== fileId) } : p
        );
        setProjects(updated);
        saveToStorage(updated);
        // Close tab if open
        setOpenTabs(prev => prev.filter(t => !(t.projectId === projectId && t.fileId === fileId)));
        if (activeFileId === fileId) {
            const proj = updated.find(p => p.id === projectId);
            if (proj && proj.files.length > 0) {
                setActiveFileId(proj.files[0].id);
            }
        }
    };

    const handleDeleteProject = (projectId: string) => {
        const updated = projects.filter(p => p.id !== projectId);
        setProjects(updated);
        saveToStorage(updated);
        setOpenTabs(prev => prev.filter(t => t.projectId !== projectId));
        if (activeProjectId === projectId && updated.length > 0) {
            setActiveProjectId(updated[0].id);
            if (updated[0].files.length > 0) {
                setActiveFileId(updated[0].files[0].id);
            }
        }
    };

    const toggleProjectExpand = (projectId: string) => {
        setProjects(prev => prev.map(p =>
            p.id === projectId ? { ...p, expanded: !p.expanded } : p
        ));
    };

    const startRename = (type: 'project' | 'file', projectId: string, fileId?: string, currentName?: string) => {
        setRenameTarget({ type, projectId, fileId });
        setRenameValue(currentName || "");
        setIsRenameOpen(true);
    };

    const handleRename = () => {
        if (!renameTarget || !renameValue.trim()) return;
        if (renameTarget.type === 'project') {
            const updated = projects.map(p =>
                p.id === renameTarget.projectId ? { ...p, name: renameValue.trim() } : p
            );
            setProjects(updated);
            saveToStorage(updated);
        } else if (renameTarget.fileId) {
            const updated = projects.map(p =>
                p.id === renameTarget.projectId ? {
                    ...p,
                    files: p.files.map(f => f.id === renameTarget.fileId ? { ...f, name: renameValue.trim() } : f)
                } : p
            );
            setProjects(updated);
            saveToStorage(updated);
        }
        setIsRenameOpen(false);
        setRenameTarget(null);
    };

    // --- Save ---
    const handleSave = async () => {
        // Save to localStorage
        saveToStorage(projects);
        setSaveStatus('saving');

        try {
            const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

            // Build files dict for the active project
            const filesDict: Record<string, string> = {};
            activeProject.files.forEach(f => {
                filesDict[f.name] = f.content;
            });

            const res = await fetch(`${API_URL}/api/v1/strategies/save-project`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_name: activeProject.name,
                    files: filesDict
                })
            });

            if (res.ok) {
                setSaveStatus('saved');
                setTimeout(() => setSaveStatus('idle'), 2000);
            } else {
                setSaveStatus('error');
                setTimeout(() => setSaveStatus('idle'), 3000);
            }
        } catch (e) {
            console.error("Backend save error", e);
            setSaveStatus('error');
            setTimeout(() => setSaveStatus('idle'), 3000);
        }
    };

    // --- Get all project files for backtest ---
    const getAllProjectFiles = (): Record<string, string> => {
        const files: Record<string, string> = {};
        activeProject.files.forEach(f => {
            files[f.name] = f.content;
        });
        return files;
    };

    // ============================================================
    // RENDER
    // ============================================================

    return (
        <div className="flex flex-col h-screen bg-[#0a0a0f] text-zinc-100 overflow-hidden">
            {/* ===== Top Bar ===== */}
            <header className="flex items-center justify-between border-b border-zinc-800/60 px-4 py-2 bg-[#0d0d14]">
                <div className="flex items-center gap-3">
                    <Link href="/">
                        <Button variant="ghost" size="icon" className="h-8 w-8 text-zinc-400 hover:text-white hover:bg-zinc-800">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                        <span className="font-bold text-sm tracking-wide text-zinc-200">QUANT IDE</span>
                    </div>
                    <span className="text-zinc-600 text-xs hidden sm:inline">|</span>
                    <span className="text-zinc-500 text-xs hidden sm:inline font-mono">
                        {activeProject?.name}/{activeFile?.name || '—'}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        size="sm"
                        variant="ghost"
                        className={`text-xs h-7 px-3 transition-all duration-300 ${saveStatus === 'saved'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                            : saveStatus === 'error'
                                ? 'bg-red-500/10 text-red-400 border border-red-500/30'
                                : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
                            }`}
                        onClick={handleSave}
                        disabled={saveStatus === 'saving'}
                    >
                        <Save className="mr-1.5 h-3 w-3" />
                        {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? '✓ Synced' : saveStatus === 'error' ? '✗ Error' : 'Save All'}
                    </Button>
                    <div className="w-px h-5 bg-zinc-800" />
                    <BacktestRunner
                        strategyName={activeFile?.name || 'main.py'}
                        strategyCode={code}
                        projectFiles={getAllProjectFiles()}
                    />
                </div>
            </header>

            {/* ===== Main Content ===== */}
            <div className="flex flex-1 overflow-hidden">
                {/* ===== File Explorer Sidebar ===== */}
                <aside className="w-56 border-r border-zinc-800/60 bg-[#0d0d14] flex flex-col flex-shrink-0">
                    <div className="px-3 py-2.5 border-b border-zinc-800/40 flex items-center justify-between">
                        <span className="text-[10px] font-semibold text-zinc-500 uppercase tracking-[0.15em]">Explorer</span>
                        <div className="flex items-center gap-0.5">
                            <Dialog open={isCreateProjectOpen} onOpenChange={setIsCreateProjectOpen}>
                                <DialogTrigger asChild>
                                    <Button variant="ghost" size="icon" className="h-6 w-6 text-zinc-500 hover:text-white hover:bg-zinc-800" title="New Project">
                                        <FolderPlus className="h-3.5 w-3.5" />
                                    </Button>
                                </DialogTrigger>
                                <DialogContent className="bg-zinc-900 border-zinc-700">
                                    <DialogHeader>
                                        <DialogTitle className="text-zinc-100">New Strategy Project</DialogTitle>
                                    </DialogHeader>
                                    <div className="grid gap-4 py-4">
                                        <Input
                                            value={newProjectName}
                                            onChange={(e) => setNewProjectName(e.target.value)}
                                            className="bg-zinc-800 border-zinc-700 text-zinc-100"
                                            placeholder="my_strategy"
                                            onKeyDown={(e) => e.key === 'Enter' && handleCreateProject()}
                                        />
                                        <p className="text-xs text-zinc-500">Creates a project folder with a starter main.py</p>
                                    </div>
                                    <DialogFooter>
                                        <Button onClick={handleCreateProject} size="sm" className="bg-emerald-600 hover:bg-emerald-700">Create</Button>
                                    </DialogFooter>
                                </DialogContent>
                            </Dialog>
                        </div>
                    </div>

                    <div className="flex-1 overflow-y-auto py-1 scrollbar-thin">
                        {projects.map(project => (
                            <div key={project.id} className="select-none">
                                {/* Project folder header */}
                                <div
                                    className={`group flex items-center gap-1.5 px-2 py-1.5 cursor-pointer text-xs transition-colors hover:bg-zinc-800/50 ${activeProjectId === project.id ? 'bg-zinc-800/30' : ''}`}
                                    onClick={() => {
                                        toggleProjectExpand(project.id);
                                        setActiveProjectId(project.id);
                                    }}
                                >
                                    {project.expanded ? (
                                        <ChevronDown className="h-3 w-3 text-zinc-500 flex-shrink-0" />
                                    ) : (
                                        <ChevronRight className="h-3 w-3 text-zinc-500 flex-shrink-0" />
                                    )}
                                    {project.expanded ? (
                                        <FolderOpen className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />
                                    ) : (
                                        <Folder className="h-3.5 w-3.5 text-amber-400/60 flex-shrink-0" />
                                    )}
                                    <span className={`flex-1 truncate font-medium ${activeProjectId === project.id ? 'text-zinc-200' : 'text-zinc-400'}`}>
                                        {project.name}
                                    </span>
                                    <div className="hidden group-hover:flex items-center gap-0.5">
                                        <Button variant="ghost" size="icon" className="h-5 w-5 text-zinc-600 hover:text-zinc-300"
                                            onClick={(e) => { e.stopPropagation(); setActiveProjectId(project.id); setIsCreateFileOpen(true); }}>
                                            <FilePlus className="h-3 w-3" />
                                        </Button>
                                        <Button variant="ghost" size="icon" className="h-5 w-5 text-zinc-600 hover:text-zinc-300"
                                            onClick={(e) => { e.stopPropagation(); startRename('project', project.id, undefined, project.name); }}>
                                            <Edit2 className="h-3 w-3" />
                                        </Button>
                                        <AlertDialog>
                                            <AlertDialogTrigger asChild>
                                                <Button variant="ghost" size="icon" className="h-5 w-5 text-zinc-600 hover:text-red-400"
                                                    onClick={(e) => e.stopPropagation()}>
                                                    <Trash2 className="h-3 w-3" />
                                                </Button>
                                            </AlertDialogTrigger>
                                            <AlertDialogContent className="bg-zinc-900 border-zinc-700">
                                                <AlertDialogHeader>
                                                    <AlertDialogTitle className="text-zinc-100">Delete project &quot;{project.name}&quot;?</AlertDialogTitle>
                                                    <AlertDialogDescription>All files in this project will be permanently deleted.</AlertDialogDescription>
                                                </AlertDialogHeader>
                                                <AlertDialogFooter>
                                                    <AlertDialogCancel className="bg-zinc-800 border-zinc-700 text-zinc-300">Cancel</AlertDialogCancel>
                                                    <AlertDialogAction onClick={() => handleDeleteProject(project.id)} className="bg-red-600 hover:bg-red-700">Delete</AlertDialogAction>
                                                </AlertDialogFooter>
                                            </AlertDialogContent>
                                        </AlertDialog>
                                    </div>
                                </div>

                                {/* Files in project */}
                                {project.expanded && project.files.map(file => (
                                    <div
                                        key={file.id}
                                        className={`group flex items-center gap-1.5 pl-8 pr-2 py-1 cursor-pointer text-xs transition-all hover:bg-zinc-800/40 ${activeFileId === file.id && activeProjectId === project.id
                                            ? 'bg-blue-500/10 text-blue-300 border-l-2 border-blue-500'
                                            : 'text-zinc-500 border-l-2 border-transparent'
                                            }`}
                                        onClick={() => openFileInTab(project.id, file.id)}
                                    >
                                        <FileCode2 className="h-3.5 w-3.5 text-blue-400/60 flex-shrink-0" />
                                        <span className="flex-1 truncate">{file.name}</span>
                                        <div className="hidden group-hover:flex items-center gap-0.5">
                                            <Button variant="ghost" size="icon" className="h-5 w-5 text-zinc-600 hover:text-zinc-300"
                                                onClick={(e) => { e.stopPropagation(); startRename('file', project.id, file.id, file.name); }}>
                                                <Edit2 className="h-2.5 w-2.5" />
                                            </Button>
                                            <Button variant="ghost" size="icon" className="h-5 w-5 text-zinc-600 hover:text-red-400"
                                                onClick={(e) => { e.stopPropagation(); handleDeleteFile(project.id, file.id); }}>
                                                <Trash2 className="h-2.5 w-2.5" />
                                            </Button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ))}
                    </div>

                    {/* Sidebar Footer */}
                    <div className="border-t border-zinc-800/40 px-3 py-2">
                        <div className="text-[10px] text-zinc-600">
                            {projects.length} projects · {projects.reduce((a, p) => a + p.files.length, 0)} files
                        </div>
                    </div>
                </aside>

                {/* ===== Editor Area ===== */}
                <div className="flex-1 flex flex-col min-w-0">
                    {/* Tab Bar */}
                    <div className="flex items-center bg-[#0d0d14] border-b border-zinc-800/40 overflow-x-auto scrollbar-none">
                        {openTabs.map(tab => {
                            const tabFile = getFileForTab(tab.projectId, tab.fileId);
                            const tabProject = projects.find(p => p.id === tab.projectId);
                            const isActive = tab.fileId === activeFileId && tab.projectId === activeProjectId;
                            return (
                                <div
                                    key={`${tab.projectId}-${tab.fileId}`}
                                    className={`group flex items-center gap-1.5 px-3 py-2 cursor-pointer text-xs border-r border-zinc-800/30 transition-colors min-w-0 flex-shrink-0 ${isActive
                                        ? 'bg-[#0a0a0f] text-zinc-200 border-t-2 border-t-blue-500'
                                        : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/30 border-t-2 border-t-transparent'
                                        }`}
                                    onClick={() => {
                                        setActiveProjectId(tab.projectId);
                                        setActiveFileId(tab.fileId);
                                    }}
                                >
                                    <FileCode2 className="h-3 w-3 text-blue-400/50 flex-shrink-0" />
                                    <span className="truncate max-w-[120px]">
                                        {tabProject && openTabs.filter(t => {
                                            const f = getFileForTab(t.projectId, t.fileId);
                                            return f?.name === tabFile?.name;
                                        }).length > 1
                                            ? `${tabProject.name}/${tabFile?.name}`
                                            : tabFile?.name}
                                    </span>
                                    <button
                                        className="ml-1 opacity-0 group-hover:opacity-100 hover:bg-zinc-700 rounded p-0.5 transition-opacity"
                                        onClick={(e) => closeTab(tab.projectId, tab.fileId, e)}
                                    >
                                        <X className="h-3 w-3" />
                                    </button>
                                </div>
                            );
                        })}
                        <div className="flex-1" />
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 mx-1 text-zinc-500 hover:text-zinc-200"
                            onClick={() => setShowTerminal(prev => !prev)}
                            title="Toggle Terminal"
                        >
                            {showTerminal ? <PanelBottomClose className="h-3.5 w-3.5" /> : <PanelBottom className="h-3.5 w-3.5" />}
                        </Button>
                    </div>

                    {/* Editor */}
                    <div className={`flex-1 ${showTerminal ? 'h-[60%]' : 'h-full'}`}>
                        {activeFile ? (
                            <CodeEditor
                                key={`${activeProjectId}-${activeFileId}`}
                                initialValue={code}
                                language="python"
                                onChange={updateFileContent}
                            />
                        ) : (
                            <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
                                Select a file to start editing
                            </div>
                        )}
                    </div>

                    {/* Terminal / Logs Panel */}
                    {showTerminal && (
                        <div className="h-[200px] border-t border-zinc-800/60 bg-[#080810] flex flex-col">
                            <div className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800/40 bg-[#0a0a12]">
                                <div className="flex items-center gap-2">
                                    <Terminal className="h-3 w-3 text-zinc-500" />
                                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">Output</span>
                                </div>
                                <Button variant="ghost" size="icon" className="h-5 w-5 text-zinc-600 hover:text-zinc-300"
                                    onClick={() => setShowTerminal(false)}>
                                    <X className="h-3 w-3" />
                                </Button>
                            </div>
                            <div className="flex-1 p-3 font-mono text-xs text-emerald-400/80 overflow-y-auto">
                                <div className="text-zinc-600">$ Ready. Click &quot;Run Backtest&quot; to see output here.</div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* ===== Bottom Panels ===== */}
            <div className="border-t border-zinc-800/60 bg-[#0a0a0f]">
                <div className="px-4 py-3 grid grid-cols-1 lg:grid-cols-2 gap-3 max-h-[300px] overflow-y-auto">
                    <DataBackfill />
                    <BacktestHistory />
                </div>
            </div>

            {/* ===== Status Bar ===== */}
            <footer className="flex items-center justify-between px-4 py-1 bg-[#1a1a2e] border-t border-zinc-800/40 text-[10px] text-zinc-500">
                <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        Connected
                    </span>
                    <span>Python 3.11</span>
                </div>
                <div className="flex items-center gap-3">
                    <span>{activeProject?.name}/{activeFile?.name || '—'}</span>
                    <span>UTF-8</span>
                </div>
            </footer>

            {/* ===== Create File Dialog ===== */}
            <Dialog open={isCreateFileOpen} onOpenChange={setIsCreateFileOpen}>
                <DialogContent className="bg-zinc-900 border-zinc-700">
                    <DialogHeader>
                        <DialogTitle className="text-zinc-100">New File in {activeProject?.name}</DialogTitle>
                    </DialogHeader>
                    <div className="grid gap-4 py-4">
                        <Input
                            value={newFileName}
                            onChange={(e) => setNewFileName(e.target.value)}
                            className="bg-zinc-800 border-zinc-700 text-zinc-100"
                            placeholder="helpers.py"
                            onKeyDown={(e) => e.key === 'Enter' && handleCreateFile()}
                        />
                    </div>
                    <DialogFooter>
                        <Button onClick={handleCreateFile} size="sm" className="bg-emerald-600 hover:bg-emerald-700">Create</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* ===== Rename Dialog ===== */}
            <Dialog open={isRenameOpen} onOpenChange={setIsRenameOpen}>
                <DialogContent className="bg-zinc-900 border-zinc-700">
                    <DialogHeader>
                        <DialogTitle className="text-zinc-100">
                            Rename {renameTarget?.type === 'project' ? 'Project' : 'File'}
                        </DialogTitle>
                    </DialogHeader>
                    <div className="grid gap-4 py-4">
                        <Input
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            className="bg-zinc-800 border-zinc-700 text-zinc-100"
                            onKeyDown={(e) => e.key === 'Enter' && handleRename()}
                        />
                    </div>
                    <DialogFooter>
                        <Button onClick={handleRename} size="sm" className="bg-emerald-600 hover:bg-emerald-700">Rename</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
