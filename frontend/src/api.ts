const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function getBackendMeta() {
  const res = await fetch(`${API_BASE}/api/meta`)
  return res.json()
}

export function getApiBase() {
  return API_BASE
}
