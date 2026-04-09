const BASE = '/api'

export const api = {
  upload: async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/upload`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
    return res.json()
  },

  status: async (sessionId) => {
    const res = await fetch(`${BASE}/status/${sessionId}`)
    if (!res.ok) throw new Error(`Status check failed: ${res.status}`)
    return res.json()
  },

  createSession: async () => {
    const res = await fetch(`${BASE}/session`, { method: 'POST' })
    if (!res.ok) throw new Error(`Session creation failed: ${res.status}`)
    return res.json()
  },

  chatStream: (sessionId, prompt) =>
    fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, prompt }),
    }),
}
