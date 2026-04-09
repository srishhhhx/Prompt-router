import { useRef, useCallback } from 'react'
import { api } from '../api/client.js'

/**
 * Hook for consuming SSE streams from POST /chat.
 *
 * Usage:
 *   const { startStream, isStreaming } = useSSEStream()
 *   startStream(sessionId, prompt, { onToken, onDone, onError })
 *
 * Handles chunk boundaries: incomplete SSE events are buffered
 * across network packets so a split `data: {...}` never causes a JSON error.
 */
export function useSSEStream() {
  const isStreamingRef = useRef(false)
  const bufferRef      = useRef('')

  const startStream = useCallback(async (sessionId, prompt, callbacks) => {
    const { onToken, onDone, onError } = callbacks
    isStreamingRef.current = true
    bufferRef.current = ''

    try {
      const response = await api.chatStream(sessionId, prompt)
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Unknown error' }))
        onError?.({ message: err.detail || `HTTP ${response.status}` })
        return
      }

      const reader  = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        bufferRef.current += decoder.decode(value, { stream: true })

        // Split on double-newline SSE event boundaries
        const parts = bufferRef.current.split('\n\n')
        bufferRef.current = parts.pop() ?? ''   // keep trailing incomplete event

        for (const part of parts) {
          for (const line of part.split('\n')) {
            if (!line.startsWith('data: ')) continue
            const raw = line.slice(6).trim()
            if (!raw) continue
            try {
              const event = JSON.parse(raw)
              if (event.type === 'token')  onToken?.(event)
              else if (event.type === 'done')  onDone?.(event)
              else if (event.type === 'error') onError?.(event)
            } catch {
              // Partial JSON — will be handled on next packet
            }
          }
        }
      }
    } catch (err) {
      onError?.({ message: err.message ?? 'Stream connection error' })
    } finally {
      isStreamingRef.current = false
    }
  }, [])

  return { startStream, isStreaming: isStreamingRef }
}
