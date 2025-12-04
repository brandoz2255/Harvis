import * as React from "react";
import { Folder } from "lucide-react";
import "@vscode/codicons/dist/codicon.css";

export function FolderIcon({ size = 18, className = "text-gray-400" }: { size?: number; className?: string }) {
    return <Folder size={size} className={className} />;
}

// Map file extensions to VSCode codicon names
function getCodiconForExtension(ext: string): string {
    const extensionMap: Record<string, string> = {
        // Code files
        js: "file-code",
        jsx: "file-code",
        ts: "file-code",
        tsx: "file-code",
        py: "file-code",
        java: "file-code",
        c: "file-code",
        cpp: "file-code",
        cxx: "file-code",
        cc: "file-code",
        cs: "file-code",
        go: "file-code",
        rs: "file-code",
        php: "file-code",
        rb: "file-code",
        swift: "file-code",
        kt: "file-code",
        scala: "file-code",
        clj: "file-code",
        sh: "file-code",
        bash: "file-code",
        zsh: "file-code",
        fish: "file-code",
        ps1: "file-code",
        
        // Data formats
        json: "json",
        yaml: "file-code",
        yml: "file-code",
        xml: "file-code",
        toml: "file-code",
        ini: "file-code",
        cfg: "file-code",
        conf: "file-code",
        
        // Markup
        html: "file-code",
        htm: "file-code",
        css: "file-code",
        scss: "file-code",
        sass: "file-code",
        less: "file-code",
        md: "markdown",
        markdown: "markdown",
        
        // Database
        sql: "file-code",
        db: "database",
        sqlite: "database",
        
        // Images
        png: "file-media",
        jpg: "file-media",
        jpeg: "file-media",
        gif: "file-media",
        svg: "file-media",
        webp: "file-media",
        ico: "file-media",
        bmp: "file-media",
        
        // Audio
        mp3: "file-media",
        wav: "file-media",
        ogg: "file-media",
        flac: "file-media",
        m4a: "file-media",
        
        // Video
        mp4: "file-media",
        avi: "file-media",
        mov: "file-media",
        mkv: "file-media",
        webm: "file-media",
        
        // Archives
        zip: "file-zip",
        tar: "file-zip",
        gz: "file-zip",
        bz2: "file-zip",
        xz: "file-zip",
        rar: "file-zip",
        "7z": "file-zip",
        
        // Documents
        pdf: "file-pdf",
        doc: "file",
        docx: "file",
        xls: "file",
        xlsx: "file",
        ppt: "file",
        pptx: "file",
        
        // Text
        txt: "file",
        log: "file",
        readme: "file",
        
        // Config
        gitignore: "file",
        dockerfile: "file-code",
        env: "file",
        lock: "file",
    };
    
    return extensionMap[ext] || "file";
}

export function FileIcon({
    fileName,
    size = 18,
    className = "shrink-0"
}: { fileName: string; size?: number; className?: string }) {
    const ext = (fileName.split(".").pop() || "").toLowerCase();
    const codiconClass = getCodiconForExtension(ext);
    
    return (
        <span 
            className={`codicon codicon-${codiconClass} ${className}`}
            style={{ 
                fontSize: `${size}px`,
                width: `${size}px`,
                height: `${size}px`,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'inherit'
            }}
            aria-hidden
        />
    );
}
