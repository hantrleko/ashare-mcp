/** Current paper-account context, persisted in localStorage. */
import {
  createContext, useCallback, useContext, useEffect, useState,
  type ReactNode,
} from "react";
import { api, type AccountInfo } from "./api";

const KEY = "ashare.account";

interface AccountCtx {
  account: string;
  accounts: AccountInfo[];
  setAccount: (id: string) => void;
  refresh: () => Promise<AccountInfo[]>;
}

const Ctx = createContext<AccountCtx>({
  account: "default", accounts: [],
  setAccount: () => {}, refresh: async () => [],
});

export function useAccount() {
  return useContext(Ctx);
}

export function AccountProvider({ children }: { children: ReactNode }) {
  const [account, setAccountState] = useState<string>(
    () => localStorage.getItem(KEY) || "default");
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);

  const refresh = useCallback(async () => {
    const list = (await api.accounts()).data;
    setAccounts(list);
    setAccountState((cur) => {
      if (list.length && !list.some((a) => a.id === cur)) {
        localStorage.setItem(KEY, "default");
        return "default";
      }
      return cur;
    });
    return list;
  }, []);

  useEffect(() => {
    refresh().catch(() => { /* backend down — keep stored id */ });
  }, [refresh]);

  const setAccount = useCallback((id: string) => {
    localStorage.setItem(KEY, id);
    setAccountState(id);
  }, []);

  return (
    <Ctx.Provider value={{ account, accounts, setAccount, refresh }}>
      {children}
    </Ctx.Provider>
  );
}
