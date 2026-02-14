
"use client";

import React, { useState } from 'react';
import { CodeEditor } from "@/components/editor/CodeEditor";
import { Save, ArrowLeft, FilePlus, Trash2, Edit2 } from 'lucide-react';
import { Button } from "@/components/ui/button";
import { BacktestRunner } from "@/components/BacktestRunner";
import { Input } from "@/components/ui/input";
import Link from 'next/link';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

// Mock initial files
const INITIAL_FILES = [
    { id: '1', name: 'demo_strategy.py', content: 'class DemoStrategy(QCAlgorithm):\n    def Initialize(self):\n        self.SetCash(10000)\n        self.AddEquity("NSE_EQ|RELIANCE")\n' },
    { id: '2', name: 'momentum.py', content: '# Momentum Strategy\n# Buy when price > SMA(50)\n' },
    { id: '3', name: 'mean_reversion.py', content: '# Mean Reversion\n# Buy when RSI < 30\n' },
];

export default function IdePage() {
    const [files, setFiles] = useState(INITIAL_FILES);
    const [activeFileId, setActiveFileId] = useState(INITIAL_FILES[0].id);
    const [code, setCode] = useState(INITIAL_FILES[0].content);

    // Dialog States
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const [newFileName, setNewFileName] = useState("");
    const [isRenameOpen, setIsRenameOpen] = useState(false);
    const [renameFileName, setRenameFileName] = useState("");
    const [fileToRename, setFileToRename] = useState<string | null>(null);

    const activeFile = files.find(f => f.id === activeFileId) || files[0];

    // Load from LocalStorage on Mount
    React.useEffect(() => {
        const saved = localStorage.getItem('quant_ide_files');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                setFiles(parsed);
                if (parsed.length > 0) {
                    setActiveFileId(parsed[0].id);
                    setCode(parsed[0].content);
                }
            } catch (e) { console.error("Failed to load files", e); }
        }
    }, []);

    // Helper to save to LS
    const saveToStorage = (newFiles: typeof files) => {
        localStorage.setItem('quant_ide_files', JSON.stringify(newFiles));
    };

    const handleFileSelect = (file: typeof files[0]) => {
        // Save current code to previous file state before switching
        const updatedFiles = files.map(f => f.id === activeFileId ? { ...f, content: code } : f);
        setFiles(updatedFiles);
        saveToStorage(updatedFiles);

        setActiveFileId(file.id);
        setCode(file.content);
    };

    const handleCreateFile = () => {
        if (!newFileName) return;
        const newFile = {
            id: Date.now().toString(),
            name: newFileName.endsWith('.py') ? newFileName : `${newFileName}.py`,
            content: '# New Strategy\n'
        };
        const updatedFiles = [...files, newFile];
        setFiles(updatedFiles);
        saveToStorage(updatedFiles);

        setNewFileName("");
        setIsCreateOpen(false);
        // Switch to new file
        setActiveFileId(newFile.id);
        setCode(newFile.content);
    };

    const handleDeleteFile = (id: string) => {
        const newFiles = files.filter(f => f.id !== id);
        setFiles(newFiles);
        saveToStorage(newFiles);

        if (activeFileId === id && newFiles.length > 0) {
            setActiveFileId(newFiles[0].id);
            setCode(newFiles[0].content);
        }
    };

    const handleRenameFile = () => {
        if (!fileToRename || !renameFileName) return;
        const updatedFiles = files.map(f => f.id === fileToRename ? { ...f, name: renameFileName } : f);
        setFiles(updatedFiles);
        saveToStorage(updatedFiles);

        setIsRenameOpen(false);
        setFileToRename(null);
    };

    const handleSave = () => {
        const updatedFiles = files.map(f => f.id === activeFileId ? { ...f, content: code } : f);
        setFiles(updatedFiles);
        saveToStorage(updatedFiles);
        // Optional: Show toast
        alert("File Saved!");
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
                <aside className="w-64 border-r bg-muted/20 flex flex-col">
                    <div className="p-4 border-b flex items-center justify-between">
                        <span className="font-semibold text-sm text-muted-foreground uppercase tracking-wider">Explorer</span>
                        <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
                            <DialogTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-6 w-6">
                                    <FilePlus className="h-4 w-4" />
                                </Button>
                            </DialogTrigger>
                            <DialogContent>
                                <DialogHeader>
                                    <DialogTitle>Create New Strategy</DialogTitle>
                                </DialogHeader>
                                <div className="grid gap-4 py-4">
                                    <div className="grid grid-cols-4 items-center gap-4">
                                        <Label htmlFor="filename" className="text-right">Name</Label>
                                        <Input
                                            id="filename"
                                            value={newFileName}
                                            onChange={(e) => setNewFileName(e.target.value)}
                                            className="col-span-3"
                                            placeholder="my_strategy.py"
                                        />
                                    </div>
                                </div>
                                <DialogFooter>
                                    <Button onClick={handleCreateFile}>Create</Button>
                                </DialogFooter>
                            </DialogContent>
                        </Dialog>
                    </div>

                    <ul className="flex-1 overflow-y-auto p-2 space-y-1">
                        {files.map((file) => (
                            <li key={file.id} className="group flex items-center justify-between rounded-md hover:bg-muted pr-1">
                                <button
                                    onClick={() => handleFileSelect(file)}
                                    className={`flex-1 text-left px-3 py-2 text-sm truncate ${activeFileId === file.id
                                        ? 'text-primary font-medium'
                                        : 'text-foreground'
                                        }`}
                                >
                                    {file.name}
                                </button>
                                <div className="hidden group-hover:flex items-center gap-1 opacity-100">
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6"
                                        onClick={(e) => { e.stopPropagation(); startRename(file.id, file.name); }}
                                    >
                                        <Edit2 className="h-3 w-3 text-muted-foreground" />
                                    </Button>

                                    <AlertDialog>
                                        <AlertDialogTrigger asChild>
                                            <Button variant="ghost" size="icon" className="h-6 w-6 hover:bg-destructive/10 hover:text-destructive">
                                                <Trash2 className="h-3 w-3" />
                                            </Button>
                                        </AlertDialogTrigger>
                                        <AlertDialogContent>
                                            <AlertDialogHeader>
                                                <AlertDialogTitle>Delete {file.name}?</AlertDialogTitle>
                                                <AlertDialogDescription>
                                                    This action cannot be undone.
                                                </AlertDialogDescription>
                                            </AlertDialogHeader>
                                            <AlertDialogFooter>
                                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                                <AlertDialogAction onClick={() => handleDeleteFile(file.id)} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                                                    Delete
                                                </AlertDialogAction>
                                            </AlertDialogFooter>
                                        </AlertDialogContent>
                                    </AlertDialog>
                                </div>
                            </li>
                        ))}
                    </ul>
                </aside>

                {/* Main Editor */}
                <main className="flex-1 p-0 relative">
                    <CodeEditor
                        key={activeFileId} // Force remount on file change to clear history if needed, or remove to keep history
                        initialValue={code}
                        language="python"
                        onChange={(value) => setCode(value || "")}
                    />
                </main>
            </div>

            {/* Rename Dialog */}
            <Dialog open={isRenameOpen} onOpenChange={setIsRenameOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Rename File</DialogTitle>
                    </DialogHeader>
                    <div className="grid gap-4 py-4">
                        <div className="grid grid-cols-4 items-center gap-4">
                            <Label htmlFor="rename" className="text-right">Name</Label>
                            <Input
                                id="rename"
                                value={renameFileName}
                                onChange={(e) => setRenameFileName(e.target.value)}
                                className="col-span-3"
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button onClick={handleRenameFile}>Save</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
