import { Suspense, lazy, useState } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { AccountProvider } from "./account";
import { AccountSwitcher } from "./components/AccountSwitcher";
import { KeyButton } from "./components/KeyButton";
import { SearchBox } from "./components/SearchBox";
import { ToastProvider } from "./components/Toast";
import { MarketStatusPill } from "./components/liveness";
import { getTheme, setTheme } from "./theme";
import Home from "./pages/Home";
import { Skeleton } from "./components/ui";

const Stock = lazy(() => import("./pages/Stock"));
const Paper = lazy(() => import("./pages/Paper"));
const Backtest = lazy(() => import("./pages/Backtest"));
const Market = lazy(() => import("./pages/Market"));
const Screener = lazy(() => import("./pages/Screener"));
const Arena = lazy(() => import("./pages/Arena"));
const ArenaAgent = lazy(() => import("./pages/ArenaDetail"));
const Factor = lazy(() => import("./pages/Factor"));

const LINKS = [
  { to: "/", label: "首页" },
  { to: "/market", label: "市场" },
  { to: "/screener", label: "选股" },
  { to: "/paper", label: "模拟盘" },
  { to: "/backtest", label: "回测" },
  { to: "/factor", label: "因子" },
  { to: "/arena", label: "竞技场" },
];

const MBAR = [
  { to: "/", label: "首页" },
  { to: "/screener", label: "选股" },
  { to: "/paper", label: "模拟盘" },
  { to: "/backtest", label: "回测" },
  { to: "/arena", label: "竞技场" },
];

const MORE = [
  { to: "/market", label: "市场" },
  { to: "/factor", label: "因子" },
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
  const [moreOpen, setMoreOpen] = useState(false);
  return (
    <ToastProvider>
      <AccountProvider>
      <HashRouter>
        <div className="flex min-h-full flex-col">
          <header className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
              <NavLink to="/" className="flex items-center gap-2 whitespace-nowrap text-base font-semibold text-slate-100">
                <span className="text-up">▲</span>
                <span className="sm:hidden">A股</span>
                <span className="hidden sm:inline">A股研究台</span>
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
                <KeyButton />
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
            <Suspense fallback={<Skeleton rows={6} />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/stock/:code" element={<Stock />} />
              <Route path="/market" element={<Market />} />
              <Route path="/screener" element={<Screener />} />
              <Route path="/paper" element={<Paper />} />
              <Route path="/backtest" element={<Backtest />} />
              <Route path="/arena" element={<Arena />} />
              <Route path="/arena/:id" element={<ArenaAgent />} />
              <Route path="/factor" element={<Factor />} />
            </Routes>
            </Suspense>
          </main>

          <footer className="border-t border-line py-4 text-center text-xs text-slate-500 max-sm:hidden">
            仅供研究与模拟交易，非投资建议 · ashare-mcp
          </footer>

          <nav className="fixed bottom-0 z-30 flex w-full border-t border-line bg-bg/95 pb-safe backdrop-blur sm:hidden">
            {MBAR.map((l) => (
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
            <button
              onClick={() => setMoreOpen(!moreOpen)}
              className="flex-1 py-2.5 text-center text-xs text-slate-500"
            >
              更多
            </button>
          </nav>
          {moreOpen && (
            <div className="fixed bottom-12 right-0 z-40 m-3 w-32 rounded-lg border border-line bg-panel py-1 shadow-xl sm:hidden">
              {MORE.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  onClick={() => setMoreOpen(false)}
                  className={({ isActive }) =>
                    `block px-4 py-2.5 text-sm ${
                      isActive ? "text-slate-100" : "text-slate-400"
                    }`
                  }
                >
                  {l.label}
                </NavLink>
              ))}
            </div>
          )}
        </div>
      </HashRouter>
      </AccountProvider>
    </ToastProvider>
  );
}
