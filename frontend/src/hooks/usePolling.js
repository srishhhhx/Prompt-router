import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client.js'

/**
 * Polls GET /status/{sessionId} every 1.5 s until status is 'ready' or 'failed'.
 * Returns { status, metadata, error }.
 */
export function usePolling(sessionId, enabled) {
  const [status, setStatus]     = useState('processing')
  const [metadata, setMetadata] = useState(null)
  const [error, setError]       = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!enabled || !sessionId) return

    const poll = async () => {
      try {
        const data = await api.status(sessionId)
        setStatus(data.status)
        if (data.status === 'ready') {
          setMetadata(data)
          clearInterval(timerRef.current)
        } else if (data.status === 'failed') {
          setError(data.error || 'Processing failed.')
          clearInterval(timerRef.current)
        }
      } catch {
        // Network blip — keep polling
      }
    }

    poll() // immediate first check
    timerRef.current = setInterval(poll, 1500)
    return () => clearInterval(timerRef.current)
  }, [sessionId, enabled])

  return { status, metadata, error }
}
