import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

const size = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const input = useRef();

  const load = useCallback(() => api.documents().then(setDocs).catch((e) => setMsg({ bad: true, text: e.message })), []);
  useEffect(() => { load(); }, [load]);
  const active = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [active, load]);

  const upload = async (files) => {
    setBusy(true);
    setMsg(null);
    for (const f of files) {
      try {
        await api.upload(f);
        setMsg({ text: `Uploaded ${f.name}. Processing in the background.` });
      } catch (e) {
        setMsg({ bad: true, text: `${f.name}: ${e.message}` });
      }
    }
    if (input.current) input.current.value = "";
    setBusy(false);
    load();
  };

  const act = async (fn, id) => {
    try { await fn(id); } catch (e) { setMsg({ bad: true, text: e.message }); }
    load();
  };

  return (
    <>
      <h1>Documents</h1>
      <div className="upload">
        <input ref={input} type="file" multiple accept=".pdf,.txt,.md,.markdown,.csv" />
        <button className="primary" disabled={busy} onClick={() => input.current.files.length && upload([...input.current.files])}>
          {busy ? "Uploading…" : "Upload"}
        </button>
        <span className="muted small">PDF, TXT, Markdown or CSV, up to 10 MB each</span>
      </div>
      {msg && <div className={msg.bad ? "error" : "note"}>{msg.text}</div>}
      {docs.length === 0 ? (
        <p className="muted">No documents yet. Upload a file to start asking questions about it.</p>
      ) : (
        <table>
          <thead><tr><th>Name</th><th>Size</th><th>Status</th><th>Chunks</th><th>Uploaded</th><th /></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td>{d.filename}<div className="mono muted small">{d.file_type} · id {d.id}</div></td>
                <td>{size(d.size_bytes)}</td>
                <td><span className={`pill ${d.status}`}>{d.status}</span>{d.error && <div className="small bad-text">{d.error}</div>}</td>
                <td>{d.chunk_count}</td>
                <td>{d.created_at ? new Date(d.created_at + "Z").toLocaleString() : ""}</td>
                <td className="actions">
                  {d.status === "failed" && <button className="link" onClick={() => act(api.reprocess, d.id)}>Retry</button>}
                  <button className="link danger" disabled={d.status === "processing"} onClick={() => confirm(`Delete ${d.filename}?`) && act(api.deleteDoc, d.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
