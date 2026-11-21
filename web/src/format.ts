/** Number/formatting helpers. A股: 红涨 #ef5350 / 绿跌 #26a69a. */

export const UP = "#ef5350";
export const DOWN = "#26a69a";

export function pctClass(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "text-slate-400";
  return v > 0 ? "text-up" : v < 0 ? "text-down" : "text-slate-300";
}

export function pctColor(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "#94a3b8";
  return v > 0 ? UP : v < 0 ? DOWN : "#cbd5e1";
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function fmtPrice(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtSigned(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${fmtNum(v, digits)}`;
}

/** 亿/万 shorthand for amounts. */
export function fmtAmount(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(2)}亿`;
  if (a >= 1e4) return `${sign}${(a / 1e4).toFixed(1)}万`;
  return `${sign}${a.toFixed(0)}`;
}

export function todayYmd(): string {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}
