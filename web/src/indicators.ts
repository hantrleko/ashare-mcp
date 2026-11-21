/** Client-side technical indicators over daily bars. */
import type { Bar } from "./api";

export type Pt = { time: string; value: number };

export function sma(bars: Bar[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= n) sum -= bars[i - n].close;
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

function ema(values: (number | null)[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  const k = 2 / (n + 1);
  let prev: number | null = null;
  let seed = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) continue;
    if (prev == null) {
      if (i >= n - 1) {
        // seed with SMA of first n values
        seed = 0;
        let cnt = 0;
        for (let j = i - n + 1; j <= i; j++) {
          const u = values[j];
          if (u != null) { seed += u; cnt++; }
        }
        prev = cnt === n ? seed / n : v;
      } else {
        continue;
      }
    } else {
      prev = v * k + prev * (1 - k);
    }
    out[i] = prev;
  }
  return out;
}

export interface Macd { dif: (number | null)[]; dea: (number | null)[]; hist: (number | null)[] }

export function macd(bars: Bar[], fast = 12, slow = 26, signal = 9): Macd {
  const closes = bars.map((b) => b.close as number | null);
  const ef = ema(closes, fast);
  const es = ema(closes, slow);
  const dif = closes.map((_, i) =>
    ef[i] != null && es[i] != null ? ef[i]! - es[i]! : null);
  const dea = ema(dif, signal);
  const hist = dif.map((d, i) =>
    d != null && dea[i] != null ? (d - dea[i]!) * 2 : null);
  return { dif, dea, hist };
}

export function rsi(bars: Bar[], n = 14): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let gain = 0, loss = 0;
  for (let i = 1; i < bars.length; i++) {
    const ch = bars[i].close - bars[i - 1].close;
    const g = Math.max(ch, 0), l = Math.max(-ch, 0);
    if (i <= n) {
      gain += g; loss += l;
      if (i === n) {
        gain /= n; loss /= n;
        out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
      }
    } else {
      gain = (gain * (n - 1) + g) / n;
      loss = (loss * (n - 1) + l) / n;
      out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    }
  }
  return out;
}

export interface Boll { mid: (number | null)[]; upper: (number | null)[]; lower: (number | null)[] }

export function boll(bars: Bar[], n = 20, k = 2): Boll {
  const mid = sma(bars, n);
  const upper: (number | null)[] = new Array(bars.length).fill(null);
  const lower: (number | null)[] = new Array(bars.length).fill(null);
  for (let i = n - 1; i < bars.length; i++) {
    if (mid[i] == null) continue;
    let v = 0;
    for (let j = i - n + 1; j <= i; j++) v += (bars[j].close - mid[i]!) ** 2;
    const sd = Math.sqrt(v / n);
    upper[i] = mid[i]! + k * sd;
    lower[i] = mid[i]! - k * sd;
  }
  return { mid, upper, lower };
}

export function toPts(bars: Bar[], vals: (number | null)[]): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < bars.length; i++) {
    if (vals[i] != null) out.push({ time: bars[i].date, value: vals[i]! });
  }
  return out;
}
