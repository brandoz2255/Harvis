"use client";
import { createContext, useContext, useState, useCallback } from "react";

type ToastType = "info" | "success" | "error" | "loading";
type Toast = { id: string; text: string; type: ToastType; sticky?: boolean };

type ToastAPI = {
  info: (text: string, ms?: number) => string;
  success: (text: string, ms?: number) => string;
  error: (text: string, ms?: number) => string;
  loading: (text: string) => string; // sticky; returns id
  update: (id: string, next: Partial<Pick<Toast, "text"|"type">>, ms?: number) => void;
  dismiss: (id: string) => void;
  // backward compat
  push?: (t: { text: string; type?: Exclude<ToastType,"loading"> }) => void;
};

const Ctx = createContext<ToastAPI>({
  info: () => "", success: () => "", error: () => "",
  loading: () => "", update: () => {}, dismiss: () => {},
});

export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const remove = useCallback((id: string) => setItems(p => p.filter(t => t.id !== id)), []);
  const add = useCallback((text: string, type: ToastType, sticky=false, ms=3000) => {
    const id = Math.random().toString(36).slice(2,8);
    setItems(p => [...p, { id, text, type, sticky }]);
    if (!sticky) setTimeout(() => remove(id), ms);
    return id;
  }, [remove]);

  const api: ToastAPI = {
    info: (t, ms=2500) => add(t, "info", false, ms),
    success: (t, ms=2000) => add(t, "success", false, ms),
    error: (t, ms=3500) => add(t, "error", false, ms),
    loading: (t) => add(t, "loading", true),
    update: (id, next, ms=2000) => {
      setItems(p => p.map(x => x.id === id ? { ...x, ...next, sticky:false } : x));
      setTimeout(() => remove(id), ms);
    },
    dismiss: (id) => remove(id),
    push: (t) => add(t.text, t.type ?? "info", false),
  };

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="fixed top-3 right-3 z-50 space-y-2">
        {items.map(i => (
          <div
            key={i.id}
            className={[
              "px-3 py-2 rounded-lg text-sm text-white shadow min-w-[220px]",
              i.type==="error"?"bg-red-600"
              : i.type==="success"?"bg-emerald-600"
              : i.type==="loading"?"bg-neutral-700":"bg-neutral-800",
            ].join(" ")}
          >
            {i.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

