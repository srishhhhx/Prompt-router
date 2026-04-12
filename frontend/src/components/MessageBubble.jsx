import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const INTENT_COLORS = {
  summarization:  'badge--accent',
  extraction:     'badge--green',
  classification: 'badge--accent',
}

const FLAG_LABELS = {
  degraded_parsing: 'Degraded parsing',
  scanned_document: 'Scanned doc',
}

function toPascalCase(str) {
  if (!str) return ''
  return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase()
}

const DOC_TYPE_META = {
  financial_statements: {
    label: 'Financial Statements', category: 'Individual / Proprietorship',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>),
  },
  balance_sheet: {
    label: 'Balance Sheet', category: 'Financial Position',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="12" y1="9" x2="12" y2="21"/></svg>),
  },
  profit_loss: {
    label: 'Profit & Loss', category: 'Income Statement',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>),
  },
  cash_flow_statement: {
    label: 'Cash Flow Statement', category: 'Financial Statement',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 1 0 0 7h5a3.5 3.5 0 1 1 0 7H6"/></svg>),
  },
  annual_report: {
    label: 'Annual Report', category: 'Corporate Disclosure',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>),
  },
  audit_report: {
    label: 'Audit Report', category: "Independent Auditor's Report",
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>),
  },
  commercial_invoice: {
    label: 'Commercial Invoice', category: 'Trade / Export Document',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>),
  },
  bank_statement: {
    label: 'Bank Statement', category: 'Transaction History',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>),
  },
  legal_agreement: {
    label: 'Legal Agreement', category: 'Contract / MOU',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>),
  },
  other: {
    label: 'Other', category: 'Financial Document',
    icon: (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>),
  },
}

function AnimatedBar({ targetPct }) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const t = setTimeout(() => setWidth(targetPct), 80)
    return () => clearTimeout(t)
  }, [targetPct])
  return (
    <div className="card__confidence-bar-track">
      <div className="card__confidence-bar-fill" style={{ width: `${width}%`, transition: 'width 900ms cubic-bezier(0.4,0,0.2,1)' }} />
    </div>
  )
}

function ClassificationCard({ content, confidence: routerConfidence }) {
  let data = null
  try { data = typeof content === 'string' ? JSON.parse(content) : content } catch { return null }
  if (!data) return null
  const { document_type, confidence: dataConfidence, key_signals = [] } = data
  const pct  = Math.round((dataConfidence ?? routerConfidence ?? 0) * 100)
  const meta = DOC_TYPE_META[document_type] ?? DOC_TYPE_META.other

  return (
    <div className="card" style={{ minWidth: 380, maxWidth: 560 }}>
      <div className="card__header" style={{ gap: 12 }}>
        <div style={{ width: 36, height: 36, borderRadius: 8, flexShrink: 0, background: 'var(--accent-subtle)', color: 'var(--accent-text)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {meta.icon}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-3)', marginBottom: 1 }}>Document Classification</div>
          <div style={{ fontSize: 11, color: 'var(--accent-text)', fontWeight: 500 }}>{meta.category}</div>
        </div>
      </div>
      <div className="card__body">
        <div className="card__field">
          <span className="card__field-label">Identified Document Type</span>
          <span style={{ fontSize: 22, fontFamily: "'Google Sans','Product Sans','Outfit','Inter',sans-serif", fontWeight: 700, color: 'var(--accent-text)', letterSpacing: '-0.02em', lineHeight: 1.2, marginTop: 2, display: 'block' }}>
            {meta.label}
          </span>
        </div>
        <div className="card__field">
          <span className="card__field-label">Confidence Score</span>
          <div className="card__confidence-bar-wrap">
            <AnimatedBar targetPct={pct} />
            <span className="card__confidence-pct">{pct}%</span>
          </div>
        </div>
        {key_signals.length > 0 && (
          <div className="card__field">
            <span className="card__field-label">Key Signals Found</span>
            <ul style={{ margin: '6px 0 0 0', paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {key_signals.map((s, i) => (
                <li key={i} style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.55, listStyleType: 'disc' }}>{s}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

export default function MessageBubble({ message }) {
  const { role, content, isStreaming, isCard, intent, confidence, flags = [] } = message
  const isUser = role === 'user'
  const isClassification = isCard && intent === 'classification'
  const metaFlags = flags.filter(f => FLAG_LABELS[f] || f.startsWith('non_english'))

  return (
    <div className={`message ${isUser ? 'message--user' : 'message--assistant'} animate-in`}>
      {isClassification ? (
        <ClassificationCard content={content} confidence={confidence} />
      ) : (
        <div className="message__bubble">
          {isUser ? content : (
            <div className="markdown-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              {isStreaming && <span className="message__cursor" aria-hidden="true" />}
            </div>
          )}
        </div>
      )}
      {!isUser && !isStreaming && intent && (
        <div className="message__meta">
          <span className={`badge ${INTENT_COLORS[intent] || 'badge--muted'}`}>{toPascalCase(intent)}</span>
          {confidence != null && <span className="badge badge--muted">{Math.round(confidence * 100)}% Confidence</span>}
          {metaFlags.map((f, i) => <span key={i} className="badge badge--amber">{FLAG_LABELS[f] ?? f}</span>)}
        </div>
      )}
    </div>
  )
}
