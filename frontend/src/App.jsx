import { useState, useCallback } from 'react'
import LandingView from './views/LandingView.jsx'
import ResultsView from './views/ResultsView.jsx'

export default function App() {
  const [view, setView]               = useState('landing')
  const [sessionId, setSessionId]     = useState(null)
  const [sessionReady, setSessionReady] = useState(false)   // was parsing complete when Analyse hit?
  const [hasFile, setHasFile]         = useState(false)
  const [filePreviewUrl, setFilePreviewUrl] = useState(null)
  const [fileType, setFileType]       = useState(null)
  const [fileName, setFileName]       = useState(null)
  const [initialPrompt, setInitialPrompt] = useState('')

  // Called when user clicks Analyse
  // sid may be null (text-only), isReady tells ResultsView whether to start streaming immediately
  const handleReady = useCallback((sid, prompt, fileUrl, fType, fName, isReady) => {
    setSessionId(sid)
    setInitialPrompt(prompt)
    setFilePreviewUrl(fileUrl)
    setFileType(fType)
    setFileName(fName)
    setHasFile(!!fileUrl)
    setSessionReady(isReady)
    setView('results')
  }, [])

  const handleReset = useCallback(() => {
    if (filePreviewUrl) URL.revokeObjectURL(filePreviewUrl)
    setView('landing')
    setSessionId(null)
    setSessionReady(false)
    setHasFile(false)
    setFilePreviewUrl(null)
    setFileType(null)
    setFileName(null)
    setInitialPrompt('')
  }, [filePreviewUrl])

  if (view === 'results') {
    return (
      <ResultsView
        sessionId={sessionId}
        sessionReady={sessionReady}
        hasFile={hasFile}
        filePreviewUrl={filePreviewUrl}
        fileType={fileType}
        fileName={fileName}
        initialPrompt={initialPrompt}
        onReset={handleReset}
      />
    )
  }

  return <LandingView onReady={handleReady} />
}
