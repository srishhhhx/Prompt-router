import { useState, useCallback, useEffect, useRef } from 'react'
import UploadArea from '../components/UploadArea.jsx'
import { api } from '../api/client.js'
import { usePolling } from '../hooks/usePolling.js'

export default function LandingView({ onReady }) {
  const [file, setFile]         = useState(null)
  const [fileUrl, setFileUrl]   = useState(null)
  const [fileType, setFileType] = useState(null)
  const [prompt, setPrompt]     = useState('')

  // Upload state: idle | uploading | polling | ready | failed
  const [parsePhase, setParsePhase]   = useState('idle')
  const [sessionId, setSessionId]     = useState(null)
  const [parseError, setParseError]   = useState('')

  const [typedTitle, setTypedTitle] = useState('')
  const fullTitle = 'Financial Intelligence'

  useEffect(() => {
    let idx = 0
    let currentText = ''
    const interval = setInterval(() => {
      if (idx < fullTitle.length) {
        currentText += fullTitle[idx]
        setTypedTitle(currentText)
        idx++
      } else {
        clearInterval(interval)
      }
    }, 45)
    return () => clearInterval(interval)
  }, [])

  // ── Trigger upload immediately when file is selected ────────────────────────
  const startUpload = useCallback(async (f) => {
    setParsePhase('uploading')
    setParseError('')
    try {
      const res = await api.upload(f)
      setSessionId(res.session_id)
      setParsePhase('polling')
    } catch (err) {
      setParseError(err.message || 'Upload failed.')
      setParsePhase('failed')
    }
  }, [])

  const handleFile = useCallback((f, url, type) => {
    // If a previous upload was in flight, drop it (new file replaces old)
    setSessionId(null)
    setParsePhase('idle')
    setParseError('')
    setFile(f)
    setFileUrl(url)
    setFileType(type)
    if (f) startUpload(f)
  }, [startUpload])

  // Poll until ready
  const { status: pollStatus, error: pollError } = usePolling(sessionId, parsePhase === 'polling')

  useEffect(() => {
    if (parsePhase !== 'polling') return
    if (pollStatus === 'ready')  setParsePhase('ready')
    if (pollStatus === 'failed') { setParseError(pollError || 'Parsing failed.'); setParsePhase('failed') }
  }, [pollStatus, pollError, parsePhase])

  // ── Analyse handler ─────────────────────────────────────────────────────────
  const handleSubmit = useCallback(async () => {
    if (!prompt.trim()) return

    if (!file) {
      // Text-only: create session then navigate
      try {
        const res = await api.createSession(prompt)
        onReady(res.session_id, prompt, null, null, null, true)
      } catch { /* ignore */ }
      return
    }

    // File: navigate immediately regardless of parse phase
    // If still uploading (very brief window), sessionId may be null → ResultsView will handle
    const isAlreadyReady = parsePhase === 'ready'
    onReady(sessionId, prompt, fileUrl, fileType, file.name, isAlreadyReady)
  }, [prompt, file, fileUrl, fileType, sessionId, parsePhase, onReady])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  // Button enabled: prompt non-empty AND not mid-upload API call
  const canSubmit = prompt.trim().length > 0 && parsePhase !== 'uploading'

  return (
    <main className="landing">
      <p className="landing__wordmark">FDIP</p>
      <h1 className="landing__title">
        {typedTitle}
        <span className="typing-cursor">|</span>
      </h1>
      <p className="landing__subtitle">
        Upload a financial document and ask anything — extract, summarize, or classify.
      </p>

      <div className="landing__card">
        {parseError && (
          <div className="landing__error" role="alert">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }}>
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {parseError}
          </div>
        )}

        <p className="landing__section-label">Document (optional)</p>

        {/* Upload zone with inline parse progress */}
        <UploadArea
          file={file}
          parsePhase={parsePhase}
          onFile={handleFile}
        />

        <div className="prompt-wrap">
          <p className="landing__section-label">Prompt</p>
          <textarea
            id="prompt-input"
            className="prompt-input"
            placeholder="Ex : Summarize the key financial highlights."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={4}
            aria-label="Enter your financial query"
          />
          <p style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6 }}>
            Cmd + Enter to submit
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
      </div>
    </main>
  )
}
