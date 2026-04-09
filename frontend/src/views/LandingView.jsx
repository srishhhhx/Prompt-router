import { useState, useEffect, useCallback, useRef } from 'react'
import UploadArea from '../components/UploadArea.jsx'
import { api } from '../api/client.js'
import { usePolling } from '../hooks/usePolling.js'

const STATUS_MESSAGES = [
  'Scanning document structure…',
  'Running parser cascade…',
  'Scrubbing sensitive data…',
  'Assembling context…',
  'Almost ready…',
]

export default function LandingView({ onReady }) {
  const [file, setFile]         = useState(null)
  const [fileUrl, setFileUrl]   = useState(null)
  const [fileType, setFileType] = useState(null)
  const [prompt, setPrompt]     = useState('')
  const [phase, setPhase]       = useState('idle')   // idle | uploading | polling | error
  const [sessionId, setSessionId] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [statusIdx, setStatusIdx] = useState(0)
  const timerRef = useRef(null)

  // Cycle status messages during polling
  useEffect(() => {
    if (phase === 'polling') {
      timerRef.current = setInterval(() => {
        setStatusIdx(i => Math.min(i + 1, STATUS_MESSAGES.length - 1))
      }, 2200)
      return () => clearInterval(timerRef.current)
    } else {
      setStatusIdx(0)
    }
  }, [phase])

  const { status: pollStatus, error: pollError } = usePolling(sessionId, phase === 'polling')

  useEffect(() => {
    if (phase !== 'polling') return
    if (pollStatus === 'ready')  onReady(sessionId, prompt, fileUrl, fileType, file?.name)
    if (pollStatus === 'failed') { setErrorMsg(pollError || 'Document processing failed.'); setPhase('error') }
  }, [pollStatus, pollError, phase])

  const handleFile = useCallback((f, url, type) => {
    setFile(f); setFileUrl(url); setFileType(type)
  }, [])

  const handleSubmit = async () => {
    if (!prompt.trim()) return
    setErrorMsg(''); setPhase('uploading')

    try {
      if (file) {
        const res = await api.upload(file)
        setSessionId(res.session_id)
        setPhase('polling')
      } else {
        const res = await api.createSession()
        onReady(res.session_id, prompt, null, null, null)
      }
    } catch (err) {
      setErrorMsg(err.message || 'Upload failed.'); setPhase('error')
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  const isProcessing = phase === 'uploading' || phase === 'polling'
  const canSubmit = prompt.trim().length > 0 && !isProcessing

  return (
    <main className="landing">
      <p className="landing__wordmark">FDIP</p>

      <h1 className="landing__title">Financial Intelligence</h1>
      <p className="landing__subtitle">
        Upload a financial document and ask anything — extract, summarize, or classify.
      </p>

      <div className="landing__card">
        {isProcessing ? (
          <div className="landing__status">
            <div className="landing__status-spinner" aria-label="Processing" />
            <p className="landing__status-msg">
              {STATUS_MESSAGES[statusIdx]}
            </p>
          </div>
        ) : (
          <>
            {errorMsg && (
              <div className="landing__error" role="alert">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}>
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>
                  <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                {errorMsg}
              </div>
            )}

            <p className="landing__section-label">Document (optional)</p>
            <UploadArea file={file} onFile={handleFile} />

            <div className="prompt-wrap">
              <p className="landing__section-label">Prompt</p>
              <textarea
                id="prompt-input"
                className="prompt-input"
                placeholder="e.g. Summarize the key financial highlights…"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={4}
                aria-label="Enter your financial query"
              />
              <p style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6 }}>
                ⌘ + Enter to submit
              </p>
            </div>

            <button
              id="analyse-btn"
              className="btn btn--primary btn--primary-full"
              onClick={handleSubmit}
              disabled={!canSubmit}
            >
              Analyse
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="5" y1="12" x2="19" y2="12"/>
                <polyline points="12 5 19 12 12 19"/>
              </svg>
            </button>
          </>
        )}
      </div>
    </main>
  )
}
