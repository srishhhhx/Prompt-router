import ExtractionCard from './ExtractionCard.jsx'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const INTENT_COLORS = {
  summarization:  'badge--accent',
  extraction:     'badge--green',
  classification: 'badge--muted',
}

const FLAG_LABELS = {
  degraded_parsing:  'Degraded parsing',
  scanned_document:  'Scanned doc',
}

function toPascalCase(str) {
  if (!str) return ''
  return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase()
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
          {isUser ? (
            content
          ) : (
            <div className="markdown-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              {isStreaming && <span className="message__cursor" aria-hidden="true" />}
            </div>
          )}
        </div>
      )}

      {/* Metadata row — only for assistant messages that are done */}
      {!isUser && !isStreaming && intent && (
        <div className="message__meta">
          <span className={`badge ${INTENT_COLORS[intent] || 'badge--muted'}`}>
            {toPascalCase(intent)}
          </span>
          {confidence != null && (
            <span className="badge badge--muted">
              {Math.round(confidence * 100)}% Confidence
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
