/** Header 🔑 button — paste an API key (localStorage `ashare.key`),
 * shows the role reported by /api/auth/me. */
import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { api, getApiKey, setApiKey, type AuthMe } from "../api";
import { useToast } from "./Toast";

export function KeyButton() {
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState<AuthMe | null>(null);
  const [draft, setDraft] = useState(getApiKey());
  const toast = useToast();

  const refresh = () =>
    api.authMe().then(setMe).catch(() => setMe(null));
  useEffect(() => { refresh(); }, []);
  useEffect(() => { if (open) refresh(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const roleLabel = !me?.public ? "本地" :
    me.role === "admin" ? "管理员" :
    me.role === "agent" ? `Agent:${me.account}` : "匿名";

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={`inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border transition-colors hover:bg-muted ${
          me?.public && me.role === "anonymous"
            ? "border-up/60 text-up" : "border-border text-muted-foreground hover:text-foreground"}`}
        title={`API Key — ${roleLabel}`}
        aria-label={`API Key — ${roleLabel}`}
      >
        <KeyRound className="size-4" />
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
             onClick={() => setOpen(false)}>
          <div className="w-full max-w-sm rounded-xl border border-line bg-panel p-5"
               onClick={(e) => e.stopPropagation()}>
            <div className="mb-1 text-sm font-semibold">API Key</div>
            <div className="mb-3 text-xs text-slate-500">
              状态：{me?.public ? "公开模式" : "本地模式"} · 角色 {roleLabel}
            </div>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="ak_…"
              className="num mb-3 w-full rounded border border-line bg-panel2 px-3 py-2 text-sm outline-none"
            />
            <div className="flex justify-end gap-2">
              {getApiKey() && (
                <button
                  className="rounded border border-line px-3 py-1.5 text-sm text-slate-400"
                  onClick={() => { setApiKey(""); setDraft(""); refresh();
                                   toast("ok", "已清除 API Key"); }}
                >
                  清除
                </button>
              )}
              <button
                className="rounded bg-up px-3 py-1.5 text-sm font-medium text-white"
                onClick={() => {
                  setApiKey(draft);
                  refresh().then(() => setOpen(false));
                  toast("ok", draft.trim() ? "已保存 API Key" : "已清除 API Key");
                }}
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
