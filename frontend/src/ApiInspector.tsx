import { useEffect, useState, type ReactNode } from 'react';
import { Braces, Copy, Trash2, X } from 'lucide-react';
import { apiLog, type ApiLogEntry } from './api';

const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)/gi;

// Pretty-printed JSON with keys, strings, numbers and literals distinguished; plain text, no HTML injection.
export function JsonView({ value }: { value: unknown }) {
  const text = value === undefined ? '(no body)' : JSON.stringify(value, null, 2);
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(<span key={`t${last}`}>{text.slice(last, index)}</span>);
    const kind = match[1] ? (match[2] ? 'key' : 'string') : match[3] ? 'literal' : 'number';
    parts.push(<span key={index} className={`json-${kind}`}>{match[1] ?? match[0]}</span>);
    if (match[2]) parts.push(<span key={`c${index}`}>{match[2]}</span>);
    last = index + match[0].length;
  }
  parts.push(<span key="end">{text.slice(last)}</span>);
  return <pre className="json-view">{parts}</pre>;
}

function CopyButton({ value, label }: { value: unknown; label: string }) {
  const [done, setDone] = useState(false);
  return <button className="inspector-copy" onClick={() => {
    navigator.clipboard?.writeText(JSON.stringify(value, null, 2)).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1500); }).catch(() => undefined);
  }}><Copy size={12}/> {done ? 'Copied' : label}</button>;
}

const tone = (status: ApiLogEntry['status']) => typeof status === 'number'
  ? status < 300 ? 'ok' : status < 500 ? 'warn' : 'bad' : status === 'network error' ? 'bad' : status;

function Entry({ entry, open, onToggle }: { entry: ApiLogEntry; open: boolean; onToggle: () => void }) {
  const label = `${entry.method} ${entry.endpoint}`;
  return <li className={open ? 'inspector-entry open' : 'inspector-entry'}>
    <button className="inspector-row" onClick={onToggle} aria-expanded={open}>
      <span className={`method method-${entry.method.toLowerCase()}`}>{entry.method}</span>
      <code>{entry.endpoint}</code>
      <span className={`status status-${tone(entry.status)}`}>{entry.status}</span>
      <span className="inspector-meta">{entry.ms !== undefined ? `${entry.ms} ms · ` : ''}{new Date(entry.at).toLocaleTimeString()}</span>
    </button>
    {open && <div className="inspector-body">
      {entry.note && <p className="inspector-note">{entry.note}</p>}
      {entry.request !== undefined && <section>
        <header><strong>Request body</strong><span>{label}</span><CopyButton value={entry.request} label="Copy request"/></header>
        <JsonView value={entry.request}/>
      </section>}
      <section>
        <header><strong>Response</strong><span>{entry.status === 'pending' ? 'waiting…' : `${entry.status} from ${entry.endpoint}`}</span>
          {entry.response !== undefined && <CopyButton value={entry.response} label="Copy response"/>}</header>
        {entry.status === 'pending' ? <p className="inspector-note">Request in progress.</p> : <JsonView value={entry.response}/>}
      </section>
    </div>}
  </li>;
}

export function ApiInspector() {
  const [entries, setEntries] = useState(apiLog.entries());
  const [visible, setVisible] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  useEffect(() => apiLog.subscribe(next => { setEntries(next); setOpenId(next[0]?.id ?? null); }), []);
  return <>
    <button className="inspector-toggle" onClick={() => setVisible(!visible)} aria-expanded={visible}>
      <Braces size={15}/> API log <span>{entries.length}</span>
    </button>
    {visible && <aside className="inspector" aria-label="API request log">
      <header className="inspector-head">
        <div><strong>API log</strong><small>Every call this page makes, newest first. Responses are shown exactly as the server returned them.</small></div>
        <button className="icon-button" title="Clear log" onClick={() => apiLog.clear()}><Trash2 size={15}/></button>
        <button className="icon-button" title="Close" onClick={() => setVisible(false)}><X size={16}/></button>
      </header>
      {entries.length === 0 ? <p className="inspector-empty">No API calls yet. Import a listing to see its request and response.</p>
        : <ol className="inspector-list">{entries.map(entry =>
            <Entry key={entry.id} entry={entry} open={openId === entry.id} onToggle={() => setOpenId(openId === entry.id ? null : entry.id)}/>)}</ol>}
    </aside>}
  </>;
}
