import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface Toast { id: number; kind: "ok" | "err"; text: string }
const ToastCtx = createContext<(kind: "ok" | "err", text: string) => void>(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: "ok" | "err", text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`rounded border px-4 py-2 text-sm shadow-lg ${
              t.kind === "ok"
                ? "border-emerald-800 bg-emerald-950/90 text-emerald-300"
                : "border-red-800 bg-red-950/90 text-red-300"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
