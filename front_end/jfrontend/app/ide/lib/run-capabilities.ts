"use client"

export type Caps = { 
  python?: boolean; 
  bash?: boolean; 
  node?: boolean; 
  tsnode?: boolean;
};

const NON_RUNNABLE = new Set(["json","yaml","yml","toml","ini","md","txt","csv"]);

export function extOf(path: string) {
  const i = path.lastIndexOf(".");
  return i >= 0 ? path.slice(i+1).toLowerCase() : "";
}

export function runnableReason(path: string, caps: Caps) {
  const ext = extOf(path);
  if (!ext || NON_RUNNABLE.has(ext)) return { runnable: false, reason: "Non-executable file type" };
  if (["js","mjs","ts"].includes(ext) && !caps.node) return { runnable: false, reason: "Requires Node runtime" };
  if (["py","sh","bash"].includes(ext)) return { runnable: true };
  if (["js","mjs","ts"].includes(ext)) return { runnable: true };
  return { runnable: false, reason: "Unsupported file type" };
}

