export default function FilePreview({ fileUrl, fileType, fileName }) {
  return (
    <div className="results__preview">
      <div className="results__preview-header">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {fileName || 'Document'}
        </span>
      </div>
      <div className="results__preview-frame">
        {fileType === 'pdf' ? (
          <iframe
            src={fileUrl}
            title="Document preview"
            aria-label="PDF document preview"
          />
        ) : (
          <img
            src={fileUrl}
            alt="Uploaded document"
            style={{ padding: '16px' }}
          />
        )}
      </div>
    </div>
  )
}
