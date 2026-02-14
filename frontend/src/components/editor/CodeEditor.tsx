
"use client";

import React from 'react';
import Editor, { OnMount } from "@monaco-editor/react";
import { useTheme } from "next-themes";

interface CodeEditorProps {
    initialValue?: string;
    language?: string;
    onChange?: (value: string | undefined) => void;
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
    initialValue = "# Write your strategy here...",
    language = "python",
    onChange
}) => {
    const { theme } = useTheme();

    const handleEditorDidMount: OnMount = (editor) => {
        // Custom configuration if needed
        editor.focus();
    };

    return (
        <div className="h-full w-full border rounded-md overflow-hidden">
            <Editor
                height="100%"
                defaultLanguage={language}
                defaultValue={initialValue}
                theme={theme === "dark" ? "vs-dark" : "light"}
                onMount={handleEditorDidMount}
                onChange={onChange}
                options={{
                    minimap: { enabled: false },
                    fontSize: 14,
                    scrollBeyondLastLine: false,
                    wordWrap: "on",
                    automaticLayout: true,
                }}
            />
        </div>
    );
};
