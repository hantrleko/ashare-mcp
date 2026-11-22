/** Inline SVG sparkline: price line + dashed prev_close baseline + area fill. */
import { DOWN, UP } from "../format";

export function Sparkline({ prices, prevClose, width = 96, height = 28, id }: {
  prices: number[]; prevClose?: number | null;
  width?: number; height?: number; id?: string;
}) {
  const vals = prices.filter((v) => Number.isFinite(v));
  if (vals.length < 2) {
    return <svg width={width} height={height} className="opacity-40" />;
  }
  const lo = Math.min(...vals, prevClose ?? Infinity);
  const hi = Math.max(...vals, prevClose ?? -Infinity);
  const span = hi - lo || 1;
  const pad = 1;
  const x = (i: number) => pad + (i / (vals.length - 1)) * (width - 2 * pad);
  const y = (v: number) => pad + (1 - (v - lo) / span) * (height - 2 * pad);

  const last = vals[vals.length - 1];
  const base = prevClose != null ? prevClose : vals[0];
  const color = last > base ? UP : last < base ? DOWN : "#94a3b8";
  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${line}L${x(vals.length - 1).toFixed(1)},${height}L${x(0).toFixed(1)},${height}Z`;
  const gid = `sp-${id ?? Math.abs(hash(line)).toString(36)}`;

  return (
    <svg width={width} height={height} className="block">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.30" />
          <stop offset="1" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {prevClose != null && (
        <line x1={0} x2={width} y1={y(prevClose)} y2={y(prevClose)}
              stroke="#8b93a7" strokeOpacity="0.55" strokeDasharray="3 3" strokeWidth="0.8" />
      )}
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
