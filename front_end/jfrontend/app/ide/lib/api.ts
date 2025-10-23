"use client"

import { toRel, joinRel } from './paths'

export type SessionInfo = { id:string; name:string; status:string };

export const SessionsAPI = {
  list: () => fetch("/api/vibecoding/sessions").then(r => r.json() as Promise<SessionInfo[]>),
  create: (name:string) => fetch("/api/vibecoding/sessions",{
    method:"POST", headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ name: String(name||"").trim() })
  }).then(async r => { if(!r.ok) throw new Error(await r.text()); return r.json() as Promise<{session_id:string}>; }),
};

export const ContainerAPI = {
  start: (id:string) => fetch(`/api/vibecoding/start/${id}`, { method:"POST" })
    .then(async r => { if(!r.ok) throw new Error(await r.text()); return r.json(); }),
  status: (id:string) => fetch(`/api/vibecoding/status/${id}`).then(r => r.json() as Promise<{status:string;message?:string;capabilities?:any}>),
};

export const FilesAPI = {
  create: (sessionId:string, dir:string, name:string) => {
    const relativePath = joinRel(dir, name)
    return fetch("/api/vibecode/files/create", {
      method:"POST", headers:{ 
        "Content-Type":"application/json",
        "Authorization": `Bearer ${localStorage.getItem('token')}`
      },
      body: JSON.stringify({ session_id: sessionId, path: relativePath, type:"file" })
    }).then(async r => { if(!r.ok) throw new Error(await r.text()); return r.json(); })
  },
  tree: (sessionId:string, path="", depth=2) => fetch("/api/vibecode/files/tree",{
    method:"POST", headers:{ 
      "Content-Type":"application/json",
      "Authorization": `Bearer ${localStorage.getItem('token')}`
    },
    body: JSON.stringify({ session_id: sessionId, path: toRel(path), depth })
  }).then(r => r.json()),
  read: (sessionId:string, path:string) => fetch(`/api/vibecode/files/read?session_id=${sessionId}&path=${encodeURIComponent(toRel(path))}`, {
    method:"GET", headers:{ 
      "Authorization": `Bearer ${localStorage.getItem('token')}`
    }
  }).then(async r => { if(!r.ok) throw new Error(await r.text()); return r.json(); }),
};
