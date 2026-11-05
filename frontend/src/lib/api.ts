// The page is normally served by the backend itself, so the API lives on the same origin (works with any port,
// e.g. `python -m texel_paint serve --port 8501`). Only the Next dev server (port 3000) needs the backend on 8500.
// Override at build time to serve the API from another origin: NEXT_PUBLIC_API_BASE=http://localhost:9000/api
const onNextDevServer = typeof window !== "undefined" && window.location.port === "3000";
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? (onNextDevServer ? "http://localhost:8500/api" : "/api");

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers } as any,
    ...opts,
    body: opts.body && typeof opts.body === "string" ? opts.body : opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export function apiRaw(path: string, opts: RequestInit = {}) {
  return fetch(`${API_BASE}${path}`, opts);
}

export const liveUrl = `${API_BASE}/live`;
export const imageUrl = (path: string) => `${API_BASE}/images/${path}`;
export const referenceUrl = (id: string) => `${API_BASE}/reference/${id}`;
export const tilesetUrl = (name: string, file: string) => `${API_BASE}/tileset/${name}/${file}`;
