const API_BASE = "http://localhost:8500/api";

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

export const imageUrl = (path: string) => `${API_BASE}/images/${path}`;
export const referenceUrl = (id: string) => `${API_BASE}/reference/${id}`;
export const tilesetUrl = (name: string, file: string) => `${API_BASE}/tileset/${name}/${file}`;
