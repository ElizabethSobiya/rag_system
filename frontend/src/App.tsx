import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, FormEvent } from 'react'
import './App.css'

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type Document = { id: string; filename: string; file_type: string; file_size: number; collection_name: string; chunk_count: number; status: string; error_msg?: string }
type Citation = { index: number; filename: string; page_number?: number; excerpt: string; similarity: number; referenced: boolean }
type Answer = { answer: string; citations: Citation[]; confidence: number; evidence_status: string; retrieval_debug: Array<{ filename: string; page_number?: number; similarity: number; semantic_rank?: number; lexical_rank?: number; fusion_score: number }> }
type Message = { role: 'user' | 'assistant'; text: string; result?: Answer }

const fileIcon = (type: string) => type === 'pdf' ? 'PDF' : type === 'docx' ? 'DOC' : type.toUpperCase()
const statusLabel: Record<string, string> = { strongly_supported: 'Strong evidence', partially_supported: 'Partial evidence', insufficient_evidence: 'Needs more evidence' }

export default function App() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [question, setQuestion] = useState('')
  const [collection, setCollection] = useState('General')
  const [filterCollection, setFilterCollection] = useState('All collections')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [dark, setDark] = useState(false)
  const [showInspector, setShowInspector] = useState(false)
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null)
  const streamRenderFrame = useRef<number | null>(null)

  const collections = useMemo(() => [...new Set(documents.map(d => d.collection_name))], [documents])
  const visibleDocs = filterCollection === 'All collections' ? documents : documents.filter(d => d.collection_name === filterCollection)

  const loadDocuments = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/v1/documents/`)
      if (response.ok) {
        setDocuments(await response.json())
        return
      }
      const body = await response.json().catch(() => null)
      setError(body?.detail ?? `The API returned ${response.status}.`)
    } catch {
      setError('Cannot connect to the API at http://localhost:8000.')
    }
  }, [])

  useEffect(() => { void loadDocuments() }, [loadDocuments])
  useEffect(() => {
    if (!documents.some(document => document.status === 'processing')) return
    const timer = window.setTimeout(() => { void loadDocuments() }, 2500)
    return () => window.clearTimeout(timer)
  }, [documents, loadDocuments])
  useEffect(() => () => { if (streamRenderFrame.current) cancelAnimationFrame(streamRenderFrame.current) }, [])

  async function uploadFiles(files: FileList | File[]) {
    if (!files.length) return
    setUploading(true); setError('')
    try {
      await Promise.all(Array.from(files).map(async file => {
        const body = new FormData(); body.append('file', file); body.append('collection_name', collection || 'General')
        const response = await fetch(`${API}/api/v1/documents/upload`, { method: 'POST', body })
        if (!response.ok) throw new Error((await response.json()).detail ?? `Could not upload ${file.name}`)
      }))
      await loadDocuments()
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed.') } finally { setUploading(false) }
  }
  function onDrop(event: DragEvent<HTMLDivElement>) { event.preventDefault(); setDragging(false); uploadFiles(event.dataTransfer.files) }
  function chooseFiles(event: ChangeEvent<HTMLInputElement>) { if (event.target.files) uploadFiles(event.target.files); event.target.value = '' }
  async function removeDocument(id: string) {
    const response = await fetch(`${API}/api/v1/documents/${id}`, { method: 'DELETE' })
    if (!response.ok) { setError('Unable to delete this document.'); return }
    setSelectedIds(ids => ids.filter(item => item !== id)); void loadDocuments()
  }

  async function ask(event: FormEvent) {
    event.preventDefault(); const query = question.trim(); if (!query || loading) return
    setMessages(old => [...old, { role: 'user', text: query }, { role: 'assistant', text: '' }]); setQuestion(''); setLoading(true); setError('')
    try {
      const payload = { query, top_k: 6, document_ids: selectedIds, collection_name: filterCollection === 'All collections' ? null : filterCollection }
      const response = await fetch(`${API}/api/v1/query/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      if (!response.ok || !response.body) { const data = await response.json(); throw new Error(data.detail ?? 'Unable to answer this question.') }
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let fullAnswer = ''
      const updateAnswer = (result?: Answer) => setMessages(old => [...old.slice(0, -1), { ...old[old.length - 1], text: fullAnswer, result: result ?? old[old.length - 1].result }])
      const scheduleAnswerRender = () => {
        if (streamRenderFrame.current !== null) return
        streamRenderFrame.current = requestAnimationFrame(() => { streamRenderFrame.current = null; updateAnswer() })
      }
      while (true) {
        const { value, done } = await reader.read(); if (done) break
        buffer += decoder.decode(value, { stream: true }); const events = buffer.split('\n\n'); buffer = events.pop() ?? ''
        events.forEach(raw => { const line = raw.split('\n').find(item => item.startsWith('data: ')); if (!line) return; const item = JSON.parse(line.slice(6)); if (item.type === 'delta') { fullAnswer += item.text; scheduleAnswerRender() } else if (item.type === 'complete') { if (streamRenderFrame.current !== null) { cancelAnimationFrame(streamRenderFrame.current); streamRenderFrame.current = null }; updateAnswer({ answer: item.answer, citations: item.citations, confidence: item.confidence, evidence_status: item.evidence_status, retrieval_debug: item.retrieval_debug }) } })
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Request failed.') } finally { setLoading(false) }
  }

  return <main className={dark ? 'app dark' : 'app'}>
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">◇</span><span>TraceRAG</span></div>
      <button className="new-chat" onClick={() => setMessages([])}>＋ New investigation</button>
      <nav><button className="nav-active">▣ Evidence workspace</button><button onClick={() => setShowInspector(!showInspector)}>⌘ Retrieval lab</button></nav>
      <div className="sidebar-bottom"><button onClick={() => setDark(!dark)}>{dark ? '☀ Light theme' : '◐ Dark theme'}</button><span>Grounded answers, inspectable evidence.</span></div>
    </aside>
    <section className="library">
      <header><div><p className="eyebrow">KNOWLEDGE BASE</p><h1>Evidence library</h1></div><button className="refresh" onClick={loadDocuments}>↻ Refresh</button></header>
      <div className={`dropzone ${dragging ? 'dragging' : ''}`} onDrop={onDrop} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}>
        <input id="file-upload" type="file" multiple accept=".pdf,.docx,.html,.htm,.txt,.md" onChange={chooseFiles} />
        <label htmlFor="file-upload"><strong>{uploading ? 'Uploading documents…' : 'Drop documents here'}</strong><span>or browse files · PDF, DOCX, HTML, MD, TXT · 25 MB max</span></label>
        <input aria-label="Collection name" value={collection} onChange={e => setCollection(e.target.value)} placeholder="Collection name" />
      </div>
      <div className="library-toolbar"><select value={filterCollection} onChange={e => setFilterCollection(e.target.value)}><option>All collections</option>{collections.map(name => <option key={name}>{name}</option>)}</select><span>{visibleDocs.length} documents</span></div>
      <div className="documents">{visibleDocs.length === 0 ? <p className="empty">Add a source to begin investigating.</p> : visibleDocs.map(doc => <article className="document" key={doc.id}><input aria-label={`Select ${doc.filename}`} type="checkbox" checked={selectedIds.includes(doc.id)} onChange={() => setSelectedIds(ids => ids.includes(doc.id) ? ids.filter(item => item !== doc.id) : [...ids, doc.id])}/><span className="file-type">{fileIcon(doc.file_type)}</span><div><strong>{doc.filename}</strong><p>{doc.collection_name} · {doc.chunk_count} chunks</p>{doc.error_msg && <small>{doc.error_msg}</small>}</div><span className={`doc-status ${doc.status}`}>{doc.status}</span><button className="delete" onClick={() => removeDocument(doc.id)} aria-label={`Delete ${doc.filename}`}>×</button></article>)}</div>
    </section>
    <section className="chat">
      <header><div><p className="eyebrow">RESEARCH CONSOLE</p><h2>Ask your evidence</h2></div><span className="scope">{selectedIds.length ? `${selectedIds.length} selected sources` : filterCollection}</span></header>
      <div className="messages">{messages.length === 0 && <div className="welcome"><span>✦</span><h3>Turn documents into defensible answers.</h3><p>Ask a question, open every source, and inspect how retrieval chose its evidence.</p><div className="suggestions"><button onClick={() => setQuestion('What are the main conclusions across these documents?')}>Summarize the conclusions</button><button onClick={() => setQuestion('Where do these documents disagree?')}>Find disagreements</button></div></div>}
      {messages.map((message, index) => <article className={`message ${message.role}`} key={index}><div className="avatar">{message.role === 'user' ? 'You' : '◇'}</div><div className="message-body"><p>{message.text}</p>{message.result && <><div className={`evidence-status ${message.result.evidence_status}`}><span>{statusLabel[message.result.evidence_status]}</span><b>{Math.round(message.result.confidence * 100)}% confidence</b></div><div className="citations">{message.result.citations.filter(c => c.referenced).map(c => <button key={c.index} onClick={() => setActiveCitation(c)}>[{c.index}] {c.filename}{c.page_number ? ` · p.${c.page_number}` : ''}</button>)}</div>{showInspector && <details className="inspector" open><summary>Retrieval trail</summary>{message.result.retrieval_debug.map((item, i) => <div key={i}><strong>{item.filename}</strong><span>semantic #{item.semantic_rank ?? '—'} · keyword #{item.lexical_rank ?? '—'} · {Math.round(item.similarity * 100)}% similar</span></div>)}</details>}</>}</div></article>)}{loading && <article className="message assistant"><div className="avatar">◇</div><div className="typing"><i></i><i></i><i></i> Retrieving evidence…</div></article>}</div>
      <form className="composer" onSubmit={ask}><textarea value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask a question about your evidence…" rows={2}/><button type="submit" disabled={loading || !question.trim()}>Send ↑</button><small>Answers cite supplied evidence only.</small></form>
      {error && <p className="error">{error}</p>}
    </section>
    {activeCitation && <div className="modal-backdrop" onClick={() => setActiveCitation(null)}><aside className="citation-modal" onClick={e => e.stopPropagation()}><button onClick={() => setActiveCitation(null)}>×</button><p className="eyebrow">SOURCE EVIDENCE</p><h3>{activeCitation.filename}{activeCitation.page_number ? ` · page ${activeCitation.page_number}` : ''}</h3><p>{activeCitation.excerpt}</p><footer>Semantic similarity: {Math.round(activeCitation.similarity * 100)}%</footer></aside></div>}
  </main>
}
