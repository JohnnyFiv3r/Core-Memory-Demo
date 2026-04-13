const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  })
  const data = await res.json()
  if (!res.ok) {
    const msg = (data && (data.error || data.message)) || `HTTP ${res.status}`
    throw new Error(String(msg))
  }
  return data as T
}

export function getApiBase() {
  return API_BASE
}

export const api = {
  inspectState: (asOf?: string) => j<any>(`/v1/memory/inspect/state${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`),
  inspectBead: (id: string) => j<any>(`/v1/memory/inspect/beads/${encodeURIComponent(id)}`),
  inspectBeadHydrate: (id: string) => j<any>(`/v1/memory/inspect/beads/${encodeURIComponent(id)}/hydrate`),
  inspectClaimSlot: (subject: string, slot: string, asOf?: string) =>
    j<any>(`/v1/memory/inspect/claim-slots/${encodeURIComponent(subject)}/${encodeURIComponent(slot)}${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`),
  inspectTurns: (limit = 50) => j<any>(`/v1/memory/inspect/turns?limit=${limit}`),

  runtime: () => j<any>('/api/demo/runtime'),
  entities: () => j<any>('/api/demo/entities'),
  benchmarkLast: () => j<any>('/api/demo/benchmark/last'),

  chat: (message: string) => j<any>('/api/chat', { method: 'POST', body: JSON.stringify({ message }) }),
  seed: () => j<any>('/api/seed', { method: 'POST' }),
  flush: () => j<any>('/api/flush', { method: 'POST' }),
  benchmarkRun: (payload: any) => j<any>('/api/benchmark-run', { method: 'POST', body: JSON.stringify(payload) }),
}
