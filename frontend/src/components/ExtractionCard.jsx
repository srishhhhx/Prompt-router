/**
 * ExtractionCard — renders either:
 *   - Extraction result (has `extraction_confidence` field)
 *   - Classification result (has `key_signals` field)
 */

const INTENT_LABEL = {
  extraction:     'Data Extraction',
  classification: 'Document Classification',
  summarization:  'Summary',
}

export default function ExtractionCard({ content, intent }) {
  let data
  try { data = typeof content === 'string' ? JSON.parse(content) : content }
  catch { return <p style={{ color: 'var(--red)', fontSize: 13 }}>Could not parse structured result.</p> }

  const isClassification = 'key_signals' in data && !('extraction_confidence' in data)

  return (
    <div className="card animate-in">
      <div className="card__header">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: 'var(--accent-text)' }}>
          {isClassification
            ? <><path d="M4 6h16M4 10h16M4 14h8"/></>
            : <><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></>
          }
        </svg>
        <span className="card__title">{INTENT_LABEL[intent] || intent}</span>
        {isClassification
          ? <span className="badge badge--accent">{data.document_type?.replace(/_/g, ' ')}</span>
          : <span className="badge badge--muted" title="Extraction confidence">
              {Math.round((data.extraction_confidence ?? 0) * 100)}% confident
            </span>
        }
      </div>

      <div className="card__body">
        {isClassification
          ? <ClassificationBody data={data} />
          : <ExtractionBody data={data} />
        }
      </div>
    </div>
  )
}

function ClassificationBody({ data }) {
  const conf = Math.round((data.confidence ?? 0) * 100)
  return (
    <>
      <div className="card__field">
        <span className="card__field-label">Confidence</span>
        <div className="card__confidence-bar-wrap">
          <div className="card__confidence-bar-track">
            <div className="card__confidence-bar-fill" style={{ width: `${conf}%` }} />
          </div>
          <span className="card__confidence-pct">{conf}%</span>
        </div>
      </div>
      {data.key_signals?.length > 0 && (
        <div className="card__field">
          <span className="card__field-label">Key signals</span>
          <div className="card__signals" style={{ marginTop: 6 }}>
            {data.key_signals.map((s, i) => (
              <span key={i} className="card__signal">{s}</span>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function ExtractionBody({ data }) {
  const fields = [
    ['Document Type',    data.document_type?.replace(/_/g, ' ')],
    ['Period',           data.date_range],
    ['Revenue',          data.revenue],
    ['Net Profit',       data.net_profit],
    ['Total Assets',     data.total_assets],
    ['Total Liabilities',data.total_liabilities],
  ]
  const hasLineItems = data.key_line_items?.length > 0
  const hasAnomalies = data.flagged_anomalies?.length > 0

  return (
    <>
      <div className="card__grid">
        {fields.map(([label, val]) => (
          <div className="card__field" key={label}>
            <span className="card__field-label">{label}</span>
            <span className={`card__field-value${!val ? ' card__field-value--null' : ''}`}>
              {val ?? '—'}
            </span>
          </div>
        ))}
      </div>

      {hasLineItems && (
        <div className="card__field">
          <span className="card__field-label">Key Line Items</span>
          <div className="card__list" style={{ marginTop: 6 }}>
            {data.key_line_items.map((item, i) => (
              <div key={i} className="card__list-item">
                <span className="card__list-item-label">{item.label}</span>
                <span className="card__list-item-value">{item.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasAnomalies && (
        <div className="card__field">
          <span className="card__field-label" style={{ color: 'var(--amber)' }}>⚠ Flagged</span>
          <div className="card__anomalies" style={{ marginTop: 4 }}>
            {data.flagged_anomalies.map((a, i) => (
              <span key={i} className="card__anomaly">· {a}</span>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
