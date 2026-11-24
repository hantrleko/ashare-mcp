import { useState } from "react";
import { api } from "../api";
import { useAccount } from "../account";
import { useToast } from "./Toast";
import { Button } from "@/components/ui/button";

const DEMO_BUYS = ["600519", "000858", "601318", "300750", "600036"];

/** 一键体验：创建/复用「示例账户」并买入 5 只权重股各 100 股。 */
export function useDemoAccount() {
  const { setAccount, refresh } = useAccount();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const list = (await api.accounts()).data;
      let acc = list.find((a) => a.name === "示例账户");
      if (!acc) acc = await api.accountCreate("示例账户", 1_000_000);
      setAccount(acc.id);
      await refresh();
      let ok = 0;
      const failed: string[] = [];
      for (const sym of DEMO_BUYS) {
        try {
          await api.paperBuy(acc.id, sym, 100, "示例买入");
          ok++;
        } catch (e) {
          failed.push(`${sym}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      if (ok) toast("ok", `示例账户已买入 ${ok} 只股票`);
      if (failed.length)
        toast("err", `部分买入被拒绝：${failed.join("；")}`);
    } catch (e) {
      toast("err", e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };
  return { run, busy };
}

export function DemoButton({ className = "" }: { className?: string }) {
  const demo = useDemoAccount();
  return (
    <Button size="sm" variant="secondary" className={className}
            disabled={demo.busy} onClick={demo.run}>
      {demo.busy ? "正在创建…" : "一键体验：创建示例账户"}
    </Button>
  );
}
