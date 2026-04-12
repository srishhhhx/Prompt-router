import { useState, useEffect, useRef, useCallback } from 'react'
import FilePreview from '../components/FilePreview.jsx'
import MessageBubble from '../components/MessageBubble.jsx'
import { usePolling } from '../hooks/usePolling.js'
import { useSSEStream } from '../hooks/useSSEStream.js'

let _uid = 0
const uid = () => String(++_uid)

export default function ResultsView({
  sessionId,
  sessionReady,   // true if parsing was already done when Analyse was clicked
  hasFile,
  filePreviewUrl,
  fileType,
  fileName,
  initialPrompt,
  onReset,
}) {
  const [messages, setMessages]     = useState([])
  const [inputValue, setInputValue] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)

  // True while we're waiting for backend parsing to finish
  const [waitingForParse, setWaitingForParse] = useState(!sessionReady && !!sessionId)

  const messagesEndRef = useRef(null)
  const textareaRef    = useRef(null)
  const hasSentInitial = useRef(false)
  const initialRef     = useRef(initialPrompt)   // stable ref, avoid stale closure

  const { startStream } = useSSEStream()

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Core send function ────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (prompt) => {
    if (!prompt.trim() || isStreaming) return

    const userMsgId = uid()
    const asstMsgId = uid()

    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user',      content: prompt },
      { id: asstMsgId, role: 'assistant', content: '', isStreaming: true, isCard: false },
    ])
    setIsStreaming(true)

    let accumulated = ''

    await startStream(sessionId, prompt, {
      onToken: ({ content, is_card }) => {
        accumulated += content
        setMessages(prev => prev.map(m =>
          m.id === asstMsgId ? { ...m, content: accumulated, isCard: !!is_card } : m
        ))
      },
      onDone: (doneEvent) => {
        setMessages(prev => prev.map(m =>
          m.id === asstMsgId
            ? { ...m, isStreaming: false, intent: doneEvent.intent, confidence: doneEvent.confidence, flags: doneEvent.flags ?? [] }
            : m
        ))
        setIsStreaming(false)
      },
      onError: ({ message }) => {
        setMessages(prev => prev.map(m =>
          m.id === asstMsgId
            ? { ...m, isStreaming: false, content: `Error: ${message}`, isError: true }
            : m
        ))
        setIsStreaming(false)
      },
    })
  }, [sessionId, isStreaming, startStream])

  // ── Fire initial prompt once parsing is done ──────────────────────────────────

  // Case A: session was already ready when view mounted → send immediately
  useEffect(() => {
    if (sessionReady && !hasSentInitial.current) {
      hasSentInitial.current = true
      sendMessage(initialRef.current)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Case B: was still parsing → poll and fire when ready
  const { status: pollStatus, error: pollError } = usePolling(
    sessionId,
    waitingForParse,
  )

  useEffect(() => {
    if (!waitingForParse) return
    if (pollStatus === 'ready') {
      setWaitingForParse(false)
      if (!hasSentInitial.current) {
        hasSentInitial.current = true
        sendMessage(initialRef.current)
      }
    }
    if (pollStatus === 'failed') {
      setWaitingForParse(false)
      // Still attempt — backend will return graceful error via SSE
      if (!hasSentInitial.current) {
        hasSentInitial.current = true
        sendMessage(initialRef.current)
      }
    }
  }, [pollStatus, waitingForParse]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── UI handlers ───────────────────────────────────────────────────────────────
  const handleSend = () => {
    sendMessage(inputValue)
    setInputValue('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleInputChange = (e) => {
    setInputValue(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
  }

  const inputDisabled = isStreaming || waitingForParse

  return (
    <div className="results">
      {/* Top bar */}
      <header className="results__topbar">
        <button className="results__back" onClick={onReset} id="new-query-btn" aria-label="New query">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="19" y1="12" x2="5" y2="12"/>
            <polyline points="12 19 5 12 12 5"/>
          </svg>
          New query
        </button>

        <span className="results__topbar-logo">FDIP</span>

        <div className="results__meta-chips">
          {hasFile && (
            <span className="badge badge--muted">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
              Document
            </span>
          )}
          {waitingForParse && (
            <span className="badge badge--amber">Parsing...</span>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="results__body">
        {hasFile && (
          <FilePreview fileUrl={filePreviewUrl} fileType={fileType} fileName={fileName} />
        )}

        <div className="results__chat">
          {waitingForParse ? (
            /* ── Parsing wait state ── */
            <div className="results__parse-wait">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: 'var(--text-3)' }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
              <p className="results__parse-title">Parsing document</p>
              <p className="results__parse-sub">AI will respond as soon as parsing completes</p>
              <div className="parse-bar parse-bar--wide">
                <div className="parse-bar__fill parse-bar__fill--indeterminate" />
              </div>
            </div>
          ) : (
            /* ── Chat messages ── */
            <div className="results__messages" id="messages-list" role="log" aria-live="polite">
              {messages.map(msg => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}

          {/* Input bar — always visible, disabled while parsing or streaming */}
          <div className="results__input-bar">
            <div className={`results__input-row${inputDisabled ? ' results__input-row--disabled' : ''}`}>
              <textarea
                ref={textareaRef}
                id="followup-input"
                className="results__textarea"
                placeholder={
                  waitingForParse ? 'Waiting for document to parse...' :
                  isStreaming     ? 'Waiting for response...' :
                  'Ask a follow-up'
                }
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                disabled={inputDisabled}
                rows={1}
                aria-label="Follow-up question"
              />
              <button
                id="send-btn"
                className="results__send"
                onClick={handleSend}
                disabled={inputDisabled || !inputValue.trim()}
                aria-label="Send message"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="19" x2="12" y2="5"></line>
                  <polyline points="5 12 12 5 19 12"></polyline>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
