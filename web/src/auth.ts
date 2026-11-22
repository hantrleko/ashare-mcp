/** Cached /api/auth/me lookup. `canMutate` is false only in public mode
 * with an anonymous (missing/invalid) key — used to grey out mutating
 * controls; the backend still enforces auth as the source of truth. */
import { useEffect, useState } from "react";
import { api, type AuthMe } from "./api";

let cached: AuthMe | null = null;
let inflight: Promise<AuthMe | null> | null = null;

function fetchMe(): Promise<AuthMe | null> {
  if (!inflight) {
    inflight = api.authMe()
      .then((m) => { cached = m; return m; })
      .catch(() => null)
      .finally(() => { inflight = null; });
  }
  return inflight;
}

export function useAuth(): AuthMe | null {
  const [me, setMe] = useState<AuthMe | null>(cached);
  useEffect(() => { fetchMe().then(setMe); }, []);
  return me;
}

/** False only when the server is public and we hold no valid key. */
export function useCanMutate(): boolean {
  const me = useAuth();
  return !(me?.public && me.role === "anonymous");
}

export const NEED_KEY = "需要 API Key";
