import { useRef, useState } from 'react'

const ACCEPT = '.pdf,.png,.jpg,.jpeg'
const VALID_TYPES = new Set(['application/pdf', 'image/png', 'image/jpeg', 'image/jpg'])

function fmt(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// parsePhase: idle | uploading | polling | ready | failed
export default function UploadArea({ file, parsePhase, onFile }) {
  const [isDrag, setIsDrag] = useState(false)
  const inputRef = useRef(null)

  const process = (f) => {
    if (!f) return
    const validPdf = f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
    const validImg = VALID_TYPES.has(f.type)
    if (!validPdf && !validImg) {
      alert('Unsupported file type. Please upload a PDF, PNG, or JPG.')
      return
    }
    const fileType = validPdf ? 'pdf' : 'image'
    const fileUrl  = URL.createObjectURL(f)
    onFile(f, fileUrl, fileType)
  }

  const onDrop = (e) => {
    e.preventDefault(); setIsDrag(false)
    process(e.dataTransfer.files[0])
  }

  // ── No file selected ─────────────────────────────────────────────────────────
  if (!file) {
    const cls = ['upload-zone', isDrag ? 'upload-zone--drag' : ''].filter(Boolean).join(' ')
    return (
      <div
        className={cls}
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setIsDrag(true) }}
        onDragLeave={() => setIsDrag(false)}
        onClick={() => inputRef.current?.click()}
        role="button" tabIndex={0}
        aria-label="Click or drag to upload a PDF or image"
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      >
        <input
          ref={inputRef} type="file" accept={ACCEPT} hidden
          onChange={(e) => process(e.target.files[0])}
          id="upload-input"
        />
        <div className="upload-zone__icon-wrap">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p className="upload-zone__title">Drop file or <strong>browse</strong></p>
        <p className="upload-zone__hint">PDF · PNG · JPG · Max 50 MB</p>
      </div>
    )
  }

  // ── File selected: show chip + parse progress ─────────────────────────────────
  const isReady   = parsePhase === 'ready'
  const isFailed  = parsePhase === 'failed'
  const isParsing = parsePhase === 'uploading' || parsePhase === 'polling'

  const chipColor = isReady ? 'var(--green)' : isFailed ? 'var(--red)' : 'var(--text-2)'

  return (
    <div className={`upload-zone upload-zone--has-file${isReady ? ' upload-zone--ready' : ''}`}>
      {/* File chip */}
      <div className="upload-zone__file-chip">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: chipColor, flexShrink: 0 }}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <span className="upload-zone__file-name">{file.name}</span>
        <span className="upload-zone__file-size">{fmt(file.size)}</span>
        {/* Remove button — always available */}
        <button
          className="btn btn--icon"
          onClick={() => onFile(null, null, null)}
          aria-label="Remove file"
          title="Remove"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* Parse status row */}
      <div className="upload-zone__parse-status">
        {isParsing && (
          <>
            <div className="parse-bar">
              <div className="parse-bar__fill parse-bar__fill--indeterminate" />
            </div>
            <p className="parse-bar__label">
              {parsePhase === 'uploading' ? 'Uploading...' : 'Parsing document...'}
            </p>
          </>
        )}
        {isReady && (
          <div className="parse-bar__ready">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            Ready to analyse
          </div>
        )}
        {isFailed && (
          <p className="parse-bar__label" style={{ color: 'var(--red)' }}>
            Parse failed — will use fallback
          </p>
        )}
      </div>
    </div>
  )
}
