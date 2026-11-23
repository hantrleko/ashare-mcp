import { Suspense, lazy, useState } from "react";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import {
  ArrowLeftRight, Ellipsis, FlaskConical, House, LineChart, Moon,
  Search, Sun, Trophy, Wallet, type LucideIcon,
} from "lucide-react";
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

const MBAR: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/", label: "首页", icon: House },
  { to: "/screener", label: "选股", icon: FlaskConical },
  { to: "/paper", label: "模拟盘", icon: Wallet },
  { to: "/backtest", label: "回测", icon: ArrowLeftRight },
  { to: "/arena", label: "竞技场", icon: Trophy },
];

const MORE: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/market", label: "市场", icon: LineChart },
  { to: "/factor", label: "因子", icon: FlaskConical },
];

function Logo({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path d="M3 17 9 11l4 4 8-9" fill="none" stroke="var(--color-up)"
            strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M15 6h6v6" fill="none" stroke="var(--color-up)"
            strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ThemeToggle() {
  const [t, setT] = useState(getTheme());
  const Icon = t === "dark" ? Moon : Sun;
  return (
    <button
      onClick={() => { const n = t === "dark" ? "light" : "dark"; setTheme(n); setT(n); }}
      className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      aria-label="切换主题"
      title="切换主题"
    >
      <Icon className="size-4" />
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
          <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
              <NavLink to="/" className="flex items-center gap-2 whitespace-nowrap text-base font-semibold text-foreground">
                <Logo className="h-5 w-5" />
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
                      `rounded-md px-3 py-1.5 text-sm transition-colors ${
                        isActive
                          ? "bg-muted font-medium text-foreground shadow-[inset_0_-2px_0_var(--color-accent)]"
                          : "text-muted-foreground hover:text-foreground"
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
                  className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:hidden"
                  aria-label="搜索"
                >
                  <Search className="size-4" />
                </button>
                <KeyButton />
                <ThemeToggle />
              </div>
            </div>
            {searchOpen && (
              <div className="border-t border-border px-4 py-2 sm:hidden">
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

          <footer className="border-t border-border py-4 text-center text-xs text-muted-foreground max-sm:hidden">
            仅供研究与模拟交易，非投资建议 · ashare-mcp
          </footer>

          <nav className="fixed bottom-0 z-30 flex w-full border-t border-border bg-background/95 pb-safe backdrop-blur sm:hidden">
            {MBAR.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive }) =>
                  `flex flex-1 flex-col items-center gap-0.5 py-1.5 text-[11px] transition-colors ${
                    isActive ? "text-foreground" : "text-muted-foreground"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <l.icon className={`size-4 ${isActive ? "text-accent" : ""}`} />
                    {l.label}
                  </>
                )}
              </NavLink>
            ))}
            <button
              onClick={() => setMoreOpen(!moreOpen)}
              className="flex flex-1 cursor-pointer flex-col items-center gap-0.5 py-1.5 text-[11px] text-muted-foreground"
              aria-label="更多"
            >
              <Ellipsis className="size-4" />
              更多
            </button>
          </nav>
          {moreOpen && (
            <div className="fixed bottom-14 right-3 z-40 w-32 rounded-xl border border-border bg-popover py-1 shadow-xl sm:hidden">
              {MORE.map((l) => (
                <NavLink
                  key={l.to}
                  to={l.to}
                  onClick={() => setMoreOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-4 py-2.5 text-sm transition-colors ${
                      isActive ? "text-foreground" : "text-muted-foreground"
                    }`
                  }
                >
                  <l.icon className="size-4" />
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
