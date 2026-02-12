"use client";
import { useState } from "react";
import { FilesAPI } from "../lib/api";
import { useToast } from "./Toast";
import { toAbs, joinRel } from "../lib/paths";

export default function ExplorerNewFile({
  sessionId, currentDir, refreshTree, onOpenFile,
}:{
  sessionId: string | null;
  currentDir: string;
  refreshTree: () => Promise<void>;
  onOpenFile: (path: string) => void;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!sessionId) { toast.error("Select or create a session first"); return; }
    const n = String(name||"").trim();
    if (!n || /[\\:*?"<>|]/.test(n) || n.endsWith("/")) { toast.error("Invalid filename"); return; }

    setBusy(true);
    const tid = toast.loading("Creating file…");
    try {
      // Use FilesAPI with proper relative paths
      const result = await FilesAPI.create(sessionId, currentDir || "", n);
      await refreshTree();
      // Use absolute path for opening the file
      onOpenFile(toAbs(joinRel(currentDir || "", n)));
      toast.update(tid, { text:`Created ${n}`, type:"success" });
      setOpen(false); setName("");
    } catch (e:any) {
      console.error("File creation failed:", e);
      toast.update(tid, { text: e?.message || "Failed to create file", type:"error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button 
        className="rounded px-2 py-1 text-xs border border-gray-600 hover:bg-gray-700 text-gray-300 transition-colors" 
        onClick={()=>setOpen(true)}
        title="New File"
        type="button"
      >
        +
      </button>
      {open && (
        <div className="fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/40" onClick={()=>!busy&&setOpen(false)} />
          <div className="absolute top-1/2 left-1/2 w-[380px] -translate-x-1/2 -translate-y-1/2 bg-gray-900 rounded-xl shadow-lg border border-gray-700">
            <form onSubmit={(e) => e.preventDefault()}>
              <div className="px-4 py-3 border-b border-gray-700 font-semibold text-white">New File</div>
              <div className="p-4">
                <input autoFocus disabled={busy}
                  className="w-full border border-gray-600 rounded px-2 py-1.5 text-sm bg-gray-800 text-white"
                  placeholder="main.py, data.json, script.sh"
                  value={name} onChange={e=>setName(e.target.value)}
                  onKeyDown={e=>e.key==="Enter"&&create()} />
                <p className="text-[11px] text-gray-400 mt-2">Extension determines type (.py, .json, .js, .sh, …)</p>
              </div>
              <div className="px-4 py-3 border-t border-gray-700 flex justify-end gap-2">
                <button 
                  type="button"
                  className="px-3 py-1.5 text-sm rounded border border-gray-600 hover:bg-gray-700 text-gray-300 transition-colors" 
                  onClick={()=>setOpen(false)} 
                  disabled={busy}
                >
                  Cancel
                </button>
                <button 
                  type="button"
                  className="px-3 py-1.5 text-sm rounded bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50 transition-colors" 
                  onClick={create} 
                  disabled={busy}
                >
                  {busy ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

