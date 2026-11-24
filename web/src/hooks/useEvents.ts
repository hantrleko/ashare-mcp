import { useEffect } from "react";
import { api, type AppEvent } from "../api";
import { useToast } from "../components/Toast";

const KEY = "ashare.events.since";
const POLL_MS = 30_000;

function toastText(e: AppEvent): string {
  const side = e.side === "buy" ? "买入" : "卖出";
  const px = e.price != null ? ` @ ${e.price}` : "";
  const base = `${e.account_name} · ${e.name} ${e.symbol} ${side} ${e.shares} 股${px}`;
  return e.kind === "trigger_filled"
    ? `条件单已成交：${base}`
    : `条件单失败：${base}${e.error ? `（${e.error}）` : ""}`;
}

/** 全局条件单事件轮询：新事件弹 toast，并在授权时发系统通知。 */
export function useEventWatcher() {
  const toast = useToast();
  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      let since: string | null = null;
      try {
        since = localStorage.getItem(KEY);
      } catch { /* */ }
      const firstRun = since === null;
      let r: { data: AppEvent[]; now: string };
      try {
        r = await api.events(since ?? "");
      } catch { return; }
      if (stopped) return;
      try { localStorage.setItem(KEY, r.now); } catch { /* */ }
      if (firstRun) return; // seed cursor only — old events never notify
      const inDesktop = typeof window !== "undefined" &&
        Boolean((window as unknown as { pywebview?: unknown }).pywebview);
      for (const e of r.data) {
        const text = toastText(e);
        toast(e.kind === "trigger_filled" ? "ok" : "err", text);
        // 桌面版由程序发送 Windows 通知，不走 WebView2（其通知权限会被自动拒绝）
        if (!inDesktop && typeof Notification !== "undefined" &&
            Notification.permission === "granted") {
          try {
            const n = new Notification(
              e.kind === "trigger_filled" ? "条件单已成交" : "条件单失败",
              { body: text.replace(/^条件单[^：]*：/, ""), tag: e.id });
            n.onclick = () => {
              window.focus();
              location.hash = "#/paper";
            };
          } catch { /* unsupported */ }
        }
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { stopped = true; clearInterval(id); };
  }, [toast]);
}
