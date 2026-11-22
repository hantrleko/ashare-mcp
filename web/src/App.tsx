import { useState } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { AccountProvider } from "./account";
import { AccountSwitcher } from "./components/AccountSwitcher";
import { SearchBox } from "./components/SearchBox";
import { ToastProvider } from "./components/Toast";
import { MarketStatusPill } from "./components/liveness";
import { getTheme, setTheme } from "./theme";
import Home from "./pages/Home";
import Stock from "./pages/Stock";
import Paper from "./pages/Paper";
import Backtest from "./pages/Backtest";
import Market from "./pages/Market";

const LINKS = [
  { to: "/", label: "首页" },
  { to: "/market", label: "市场" },
  { to: "/paper", label: "模拟盘" },
  { to: "/backtest", label: "回测" },
];

function ThemeToggle() {
  const [t, setT] = useState(getTheme());
  return (
    <button
      onClick={() => { const n = t === "dark" ? "light" : "dark"; setTheme(n); setT(n); }}
      className="rounded border border-line px-2 py-1 text-sm text-slate-400 hover:bg-panel2"
      title="切换主题"
    >
      {t === "dark" ? "☾" : "☀"}
    </button>
  );
}

export default function App() {
  const [searchOpen, setSearchOpen] = useState(false);
  return (
    <ToastProvider>
      <AccountProvider>
      <HashRouter>
        <div className="flex min-h-full flex-col">
          <header className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
              <NavLink to="/" className="flex items-center gap-2 text-base font-semibold text-slate-100">
                <span className="text-up">▲</span>A股研究台
              </NavLink>
              <MarketStatusPill />
              <nav className="hidden items-center gap-1 sm:flex">
                {LINKS.map((l) => (
                  <NavLink
                    key={l.to}
                    to={l.to}
                    end={l.to === "/"}
                    className={({ isActive }) =>
                      `rounded px-3 py-1.5 text-sm ${
                        isActive ? "bg-panel2 text-slate-100" : "text-slate-400 hover:text-slate-200"
                      }`
                    }
                  >
                    {l.label}
                  </NavLink>
                ))}
              </nav>
              <div className="ml-auto flex items-center gap-2 sm:gap-3">
                <AccountSwitcher />
                <SearchBox className="hidden w-56 sm:block sm:w-72" />
                <button
                  onClick={() => setSearchOpen(!searchOpen)}
                  className="rounded border border-line px-2 py-1 text-sm text-slate-400 hover:bg-panel2 sm:hidden"
                  aria-label="搜索"
                >
                  ⌕
                </button>
                <ThemeToggle />
              </div>
            </div>
            {searchOpen && (
              <div className="border-t border-line px-4 py-2 sm:hidden">
                <SearchBox className="w-full" onPick={() => setSearchOpen(false)} />
              </div>
            )}
          </header>

          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5 pb-20 sm:pb-5">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/stock/:code" element={<Stock />} />
              <Route path="/market" element={<Market />} />
              <Route path="/paper" element={<Paper />} />
              <Route path="/backtest" element={<Backtest />} />
            </Routes>
          </main>

          <footer className="border-t border-line py-4 text-center text-xs text-slate-500 max-sm:hidden">
            仅供研究与模拟交易，非投资建议 · ashare-mcp
          </footer>

          <nav className="fixed bottom-0 z-30 flex w-full border-t border-line bg-bg/95 pb-safe backdrop-blur sm:hidden">
            {LINKS.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive }) =>
                  `flex-1 py-2.5 text-center text-xs ${
                    isActive ? "text-slate-100" : "text-slate-500"
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </HashRouter>
      </AccountProvider>
    </ToastProvider>
  );
}
