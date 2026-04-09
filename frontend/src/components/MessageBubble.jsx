import ExtractionCard from './ExtractionCard.jsx'

const INTENT_COLORS = {
  summarization:  'badge--accent',
  extraction:     'badge--green',
  classification: 'badge--muted',
}

const FLAG_LABELS = {
  degraded_parsing:  'Degraded parsing',
  scanned_document:  'Scanned doc',
}

export default function MessageBubble({ message }) {
  const { role, content, isStreaming, isCard, intent, confidence, flags = [] } = message

  const isUser = role === 'user'
  const metaFlags = flags.filter(f => FLAG_LABELS[f] || f.startsWith('non_english'))

  return (
    <div className={`message ${isUser ? 'message--user' : 'message--assistant'} animate-in`}>
      {isCard && !isUser ? (
        <ExtractionCard content={content} intent={intent} />
      ) : (
        <div className="message__bubble">
          {content}
          {isStreaming && <span className="message__cursor" aria-hidden="true" />}
        </div>
      )}

      {/* Metadata row — only for assistant messages that are done */}
      {!isUser && !isStreaming && intent && (
        <div className="message__meta">
          <span className={`badge ${INTENT_COLORS[intent] || 'badge--muted'}`}>
            {intent}
          </span>
          {confidence != null && (
            <span className="badge badge--muted">
              {Math.round(confidence * 100)}% confidence
            </span>
          )}
          {metaFlags.map((f, i) => (
            <span key={i} className="badge badge--amber">
              {FLAG_LABELS[f] ?? f}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
