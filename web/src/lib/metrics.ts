/** Display labels for raw metric keys produced by the house agents and
 *  embedded in order reasons (e.g. "pe_ttm=6.13 pb=1.22"). Display only —
 *  stored data keeps the raw keys. */
export const METRIC_LABEL: Record<string, [label: string, isPct: boolean]> = {
  pe_ttm: ["市盈率TTM", false],
  pb: ["市净率", false],
  roe_est: ["估算ROE", true],
  ret_20d: ["20日涨幅", true],
  ret_60d: ["60日涨幅", true],
  ret20: ["20日涨幅", true],
  ret60: ["60日涨幅", true],
  ma20: ["20日均线", false],
  ma60: ["60日均线", false],
  mkt_cap: ["总市值", false],
};

export function metricLabel(k: string): string {
  return METRIC_LABEL[k]?.[0] ?? k;
}

export function fmtMetric(k: string, v: unknown): string {
  const [label, isPct] = METRIC_LABEL[k] ?? [k, false];
  return `${label} ${v}${isPct ? "%" : ""}`;
}

/** Rewrite raw `key=value` fragments inside a reason/note string. */
export function fmtReason(s: string): string {
  return s.replace(
    /\b(pe_ttm|pb|roe_est|ret_20d|ret_60d|ret20|ret60|ma20|ma60|mkt_cap)=/gi,
    (_m, k: string) => `${metricLabel(k)}=`,
  );
}
