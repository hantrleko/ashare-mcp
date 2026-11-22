/** Top-bar paper-account switcher: dropdown + create-account modal. */
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { useAccount } from "../account";
import { useToast } from "./Toast";
import { fmtAmount } from "../format";

export function AccountSwitcher() {
  const { account, accounts, setAccount, refresh } = useAccount();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [modal, setModal] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const cur = accounts.find((a) => a.id === account);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => { refresh().catch(() => {}); setOpen(!open); }}
        className="flex items-center gap-1.5 rounded border border-line bg-panel px-2.5 py-1.5 text-sm text-slate-300 hover:bg-panel2"
        title="切换模拟账户"
      >
        <span className="text-slate-500">账户</span>
        <span className="max-w-24 truncate text-slate-100">
          {cur?.name ?? account}
        </span>
        <span className="text-xs text-slate-500">▾</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-1 w-64 overflow-hidden rounded-lg border border-line bg-panel shadow-xl">
          {accounts.map((a) => (
            <button
              key={a.id}
              onClick={() => { setAccount(a.id); setOpen(false); }}
              className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-panel2 ${
                a.id === account ? "bg-panel2 text-slate-100" : "text-slate-300"
              }`}
            >
              <span className="truncate">{a.name}
                <span className="ml-1.5 text-xs text-slate-500">{a.id}</span>
              </span>
              <span className="num text-xs text-slate-400">
                {a.last_equity != null ? fmtAmount(a.last_equity) : "—"}
              </span>
            </button>
          ))}
          <button
            onClick={() => { setOpen(false); setModal(true); }}
            className="w-full border-t border-line px-3 py-2 text-left text-sm text-up hover:bg-panel2"
          >
            ＋ 新建账户
          </button>
        </div>
      )}
      {modal && <CreateModal onClose={() => setModal(false)} toast={toast} />}
    </div>
  );
}

function CreateModal({ onClose, toast }: {
  onClose: () => void;
  toast: (k: "ok" | "err", t: string) => void;
}) {
  const { setAccount, refresh } = useAccount();
  const [name, setName] = useState("");
  const [capital, setCapital] = useState("1000000");
  const [id, setId] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr("");
    if (!name.trim()) { setErr("请输入账户名称"); return; }
    const cap = Number(capital);
    if (!Number.isFinite(cap) || cap <= 0) { setErr("初始资金必须为正数"); return; }
    setBusy(true);
    try {
      const acc = await api.accountCreate(name.trim(), cap, id.trim() || undefined);
      await refresh();
      setAccount(acc.id);
      toast("ok", `已创建账户「${acc.name}」`);
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
         onClick={onClose}>
      <div className="w-80 rounded-lg border border-line bg-panel p-4 shadow-2xl"
           onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-3 text-sm font-medium text-slate-200">新建模拟账户</h3>
        <label className="mb-2 block text-xs text-slate-400">
          名称 <span className="text-up">*</span>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
                 className="mt-1 w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-slate-500" />
        </label>
        <label className="mb-2 block text-xs text-slate-400">
          初始资金
          <input value={capital} onChange={(e) => setCapital(e.target.value)}
                 inputMode="decimal"
                 className="num mt-1 w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-slate-500" />
        </label>
        <label className="mb-3 block text-xs text-slate-400">
          账户 ID（可选，留空自动生成；a-z 0-9 _ - 最长32位）
          <input value={id} onChange={(e) => setId(e.target.value)}
                 className="mt-1 w-full rounded border border-line bg-panel2 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-slate-500" />
        </label>
        {err && <div className="mb-2 text-xs text-up">{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose}
                  className="rounded border border-line px-3 py-1.5 text-sm text-slate-400 hover:bg-panel2">
            取消
          </button>
          <button onClick={submit} disabled={busy}
                  className="rounded bg-up/90 px-3 py-1.5 text-sm text-white hover:bg-up disabled:opacity-50">
            {busy ? "创建中…" : "创建"}
          </button>
        </div>
      </div>
    </div>
  );
}
