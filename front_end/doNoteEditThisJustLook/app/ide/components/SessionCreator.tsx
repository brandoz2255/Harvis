"use client";
import { useState, useEffect } from "react";
import { SessionsAPI, ContainerAPI, SessionInfo } from "../lib/api";
import { useToast } from "./Toast";

export default function SessionCreator({ onReady }:{ onReady:(sessionId:string)=>void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  useEffect(() => { SessionsAPI.list().then(setSessions).catch(()=>setSessions([])); }, []);

  async function createAndStart() {
    const n = String(name||"").trim();
    if (!n) { toast.error("Enter a session name"); return; }
    setBusy(true);
    const id = toast.loading("Creating session…");
    try {
      const { session_id } = await SessionsAPI.create(n);
      toast.update(id, { text:"Starting container…" });
      await ContainerAPI.start(session_id);
      toast.update(id, { text:"Waiting for ready…" });
      for (let i=0;i<60;i++) {
        const s = await ContainerAPI.status(session_id);
        if (s.status === "ready") {
          toast.update(id, { text:"Session ready", type:"success" });
          onReady(session_id);
          setOpen(false);
          setName("");
          return;
        }
        if (s.status === "error") throw new Error(s.message || "Container error");
        await new Promise(r=>setTimeout(r,1000));
      }
      throw new Error("Timeout waiting for ready");
    } catch (e:any) {
      toast.update(id, { text: e?.message || "Failed to create/start", type:"error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border border-gray-700 rounded-lg p-3 bg-gray-800">
      <div className="flex items-center justify-between">
        <div className="font-semibold text-white">Sessions</div>
        <button 
          className="text-sm rounded border border-purple-500 bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 transition-colors" 
          onClick={()=>setOpen(true)}
        >
          + New
        </button>
      </div>
      {open && (
        <div className="mt-3 flex gap-2">
          <input 
            className="border border-gray-600 rounded px-2 py-1 text-sm flex-1 bg-gray-700 text-white"
            placeholder="e.g., Lab 1 – Intro" 
            value={name}
            onChange={e=>setName(e.target.value)} 
            disabled={busy}
            onKeyDown={e=>e.key==="Enter"&&createAndStart()}
            autoFocus
          />
          <button 
            className="px-3 py-1 rounded bg-purple-600 hover:bg-purple-700 text-white text-sm disabled:opacity-50 transition-colors"
            onClick={createAndStart} 
            disabled={busy}
          >
            {busy ? "Working…" : "Create"}
          </button>
          <button 
            className="px-3 py-1 rounded border border-gray-600 text-gray-300 hover:bg-gray-700 text-sm transition-colors" 
            onClick={()=>setOpen(false)} 
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

