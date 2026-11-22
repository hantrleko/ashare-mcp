import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { AccountProvider } from "./account";
import { AccountSwitcher } from "./components/AccountSwitcher";
import { SearchBox } from "./components/SearchBox";
import { ToastProvider } from "./components/Toast";
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

export default function App() {
  return (
    <ToastProvider>
      <AccountProvider>
      <HashRouter>
        <div className="flex min-h-full flex-col">
          <header className="sticky top-0 z-30 border-b border-line bg-[#0b0e14]/95 backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2.5">
              <NavLink to="/" className="flex items-center gap-2 text-base font-semibold text-slate-100">
                <span className="text-up">▲</span>A股研究台
              </NavLink>
              <nav className="flex items-center gap-1">
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
              <div className="ml-auto flex items-center gap-3">
                <AccountSwitcher />
                <SearchBox className="w-56 sm:w-72" />
              </div>
            </div>
          </header>

          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/stock/:code" element={<Stock />} />
              <Route path="/market" element={<Market />} />
              <Route path="/paper" element={<Paper />} />
              <Route path="/backtest" element={<Backtest />} />
            </Routes>
          </main>

          <footer className="border-t border-line py-4 text-center text-xs text-slate-500">
            仅供研究与模拟交易，非投资建议 · ashare-mcp
          </footer>
        </div>
      </HashRouter>
      </AccountProvider>
    </ToastProvider>
  );
}
