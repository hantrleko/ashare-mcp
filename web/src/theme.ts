/** Theme: "dark" (default) | "light", persisted as localStorage ashare.theme.
 *  Applied as data-theme on <html>. ?theme=light|dark overrides once. */

export type Theme = "dark" | "light";
const KEY = "ashare.theme";
const EVT = "ashare:theme";

function initial(): Theme {
  const q = new URLSearchParams(location.search).get("theme");
  if (q === "light" || q === "dark") {
    localStorage.setItem(KEY, q);
    return q;
  }
  return localStorage.getItem(KEY) === "light" ? "light" : "dark";
}

let current: Theme = initial();
document.documentElement.dataset.theme = current;

export function getTheme(): Theme {
  return current;
}

export function setTheme(t: Theme) {
  current = t;
  localStorage.setItem(KEY, t);
  document.documentElement.dataset.theme = t;
  window.dispatchEvent(new Event(EVT));
}

export function onThemeChange(cb: () => void): () => void {
  window.addEventListener(EVT, cb);
  return () => window.removeEventListener(EVT, cb);
}

/** Read a theme css var (--color-*) for chart options. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
}

/** "#rrggbb" + alpha → "rgba(...)", for canvas contexts that can't resolve var()/color-mix. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(color.trim());
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
