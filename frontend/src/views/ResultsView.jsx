import { useState, useEffect, useRef, useCallback } from 'react'
import FilePreview from '../components/FilePreview.jsx'
import MessageBubble from '../components/MessageBubble.jsx'
import { useSSEStream } from '../hooks/useSSEStream.js'

let _uid = 0
const uid = () => String(++_uid)

export default function ResultsView({ sessionId, hasFile, filePreviewUrl, fileType, fileName, initialPrompt, onReset }) {
  const [messages, setMessages]       = useState([])
  const [inputValue, setInputValue]   = useState('')
  const [isStreaming, setIsStreaming]  = useState(false)
  const messagesEndRef = useRef(null)
  const textareaRef    = useRef(null)
  const { startStream } = useSSEStream()

  // Auto-scroll to bottom whenever messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async (prompt) => {
    if (!prompt.trim() || isStreaming) return

    const userMsgId = uid()
    const asstMsgId = uid()

    // Add user + placeholder assistant messages
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', content: prompt },
      { id: asstMsgId, role: 'assistant', content: '', isStreaming: true, isCard: false },
    ])
    setIsStreaming(true)

    let accumulated = ''

    await startStream(sessionId, prompt, {
      onToken: ({ content, is_card }) => {
        accumulated += content
        setMessages(prev => prev.map(m =>
          m.id === asstMsgId
            ? { ...m, content: accumulated, isCard: !!is_card }
            : m
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
            ? { ...m, isStreaming: false, content: `⚠ Error: ${message}`, isError: true }
            : m
        ))
        setIsStreaming(false)
      },
    })
  }, [sessionId, isStreaming, startStream])

  // Send initial prompt when view mounts
  useEffect(() => {
    if (initialPrompt) sendMessage(initialPrompt)
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const handleSend = () => {
    sendMessage(inputValue)
    setInputValue('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault(); handleSend()
    }
  }

  // Auto-resize textarea
  const handleInputChange = (e) => {
    setInputValue(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
  }

  return (
    <div className="results">
      {/* Top bar */}
      <header className="results__topbar">
        <button className="results__back" onClick={onReset} id="new-query-btn" aria-label="Start new query">
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
        </div>
      </header>

      {/* Body: split or full */}
      <div className="results__body">
        {hasFile && (
          <FilePreview fileUrl={filePreviewUrl} fileType={fileType} fileName={fileName} />
        )}

        <div className="results__chat">
          {/* Messages */}
          <div className="results__messages" id="messages-list" role="log" aria-live="polite">
            {messages.map(msg => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <div className="results__input-bar">
            <div className="results__input-row">
              <textarea
                ref={textareaRef}
                id="followup-input"
                className="results__textarea"
                placeholder={isStreaming ? 'Waiting for response…' : 'Ask a follow-up…'}
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                disabled={isStreaming}
                rows={1}
                aria-label="Follow-up question"
              />
              <button
                id="send-btn"
                className="results__send"
                onClick={handleSend}
                disabled={isStreaming || !inputValue.trim()}
                aria-label="Send message"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <line x1="22" y1="2" x2="11" y2="13"/>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
