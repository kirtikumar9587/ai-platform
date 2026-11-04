import { useEffect, useRef, useState } from "react";
import { api } from "../api";

function Badges({ meta }) {
  const v = meta.verification;
  return (
    <div className="badges">
      {meta.sufficient === false && <span className="pill failed">Not enough information</span>}
      {v && v.supported === true && <span className="pill ready">Verified against sources</span>}
      {v && v.supported === false && <span className="pill failed" title={(v.unsupported_claims || []).join("\n")}>Some claims not supported</span>}
      {meta.conflicts?.length > 0 && <span className="pill processing">Sources conflict</span>}
    </div>
  );
}

function Report({ r }) {
  return (
    <div className="report">
      <h3>{r.title}</h3>
      <p>{r.executive_summary}</p>
      <h4>Findings</h4>
      <ul>{r.findings.map((f, i) => <li key={i}>{f.finding} <span className="mono muted">{f.evidence_refs.map((n) => `[${n}]`).join("")}</span></li>)}</ul>
      <h4>Recommendations</h4>
      <ul>{r.recommendations.map((x, i) => <li key={i}>{x}</li>)}</ul>
      {r.gaps.length > 0 && (<><h4>Gaps</h4><ul>{r.gaps.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
    </div>
  );
}

function Message({ m }) {
  const meta = m.meta || {};
  return (
    <div className={`msg ${m.role}`}>
      <div className="bubble">{m.content}</div>
      {m.role === "assistant" && (
        <>
          <Badges meta={meta} />
          {meta.conflicts?.length > 0 && <ul className="conflicts">{meta.conflicts.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          {meta.report && <Report r={meta.report} />}
          {m.agent_steps?.length > 0 && (
            <details open>
              <summary>Agent steps ({m.agent_steps.length})</summary>
              <ol className="steps">
                {m.agent_steps.map((s) => (
                  <li key={s.step} className={s.ok ? "" : "failed-step"}>
                    <b className="mono">{s.action}</b> <span className="muted small">{s.ms} ms</span>
                    <div className="small muted">{s.thought}</div>
                    <div className="small mono">{JSON.stringify(s.args)}</div>
                    <div className="small">{s.observation}</div>
                  </li>
                ))}
              </ol>
            </details>
          )}
          {m.sources?.length > 0 && (
            <details>
              <summary>Sources ({m.sources.length})</summary>
              <ul className="sources">
                {m.sources.map((s) => (
                  <li key={s.n}>
                    <b>[{s.n}] {s.filename}</b>{s.page ? ` · page ${s.page}` : ""} <span className="muted small">relevance {s.score}{s.cited ? " · cited" : ""}</span>
                    <div className="small">{s.snippet}</div>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {meta.total_tokens != null && (
            <div className="meta small muted mono">
              {meta.mode} · {(meta.models || []).join(", ")}{meta.fallback_used ? " (fallback used)" : ""} · {meta.total_tokens} tokens · {meta.latency_ms} ms
              {meta.rewritten_question && meta.rewritten_question !== "" ? ` · searched: “${meta.rewritten_question}”` : ""}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function Chat() {
  const [convs, setConvs] = useState([]);
  const [active, setActive] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [mode, setMode] = useState("rag");
  const [verify, setVerify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const end = useRef();

  const loadConvs = () => api.conversations().then(setConvs).catch((e) => setErr(e.message));
  useEffect(() => { loadConvs(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  const open = async (id) => {
    setActive(id);
    setErr("");
    setMsgs(await api.messages(id).catch((e) => { setErr(e.message); return []; }));
  };

  const create = async () => {
    const c = await api.newConversation();
    await loadConvs();
    setActive(c.id);
    setMsgs([]);
    return c.id;
  };

  const remove = async (id) => {
    if (!confirm("Delete this conversation?")) return;
    await api.deleteConversation(id);
    if (active === id) { setActive(null); setMsgs([]); }
    loadConvs();
  };

  const send = async (e) => {
    e.preventDefault();
    const content = text.trim();
    if (!content || busy) return;
    setErr("");
    setBusy(true);
    setText("");
    try {
      const id = active ?? (await create());
      setMsgs((m) => [...m, { id: "tmp", role: "user", content }]);
      const reply = await api.send(id, { content, mode, verify });
      setMsgs((m) => [...m, reply]);
      loadConvs();
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chat">
      <aside className="convs">
        <button className="primary" onClick={create}>New conversation</button>
        {convs.map((c) => (
          <div key={c.id} className={"conv" + (c.id === active ? " on" : "")}>
            <button className="link" onClick={() => open(c.id)}>{c.title}</button>
            <button className="link danger small" onClick={() => remove(c.id)} aria-label="Delete conversation">✕</button>
          </div>
        ))}
        {convs.length === 0 && <p className="muted small">No conversations yet.</p>}
      </aside>
      <section className="thread">
        <div className="msgs">
          {msgs.length === 0 && !busy && (
            <div className="empty">
              <h2>Ask about your documents</h2>
              <p className="muted">“Rag” answers a question with citations. “Agent” plans several steps: search, analyse, then write a report. Try: <i>Analyse the most common causes of system failures and recommend solutions.</i></p>
            </div>
          )}
          {msgs.map((m, i) => <Message key={m.id + "-" + i} m={m} />)}
          {busy && <div className="muted">{mode === "agent" ? "The agent is working through its steps…" : "Searching your documents…"}</div>}
          <div ref={end} />
        </div>
        {err && <div className="error">{err}</div>}
        <form className="composer" onSubmit={send}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="Ask a question…"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }} />
          <div className="opts">
            <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Mode">
              <option value="rag">Rag: answer with sources</option>
              <option value="agent">Agent: multi-step analysis</option>
            </select>
            <label className="check"><input type="checkbox" checked={verify} disabled={mode === "agent"} onChange={(e) => setVerify(e.target.checked)} />Verify answer</label>
            <button className="primary" disabled={busy || !text.trim()}>Send</button>
          </div>
        </form>
      </section>
    </div>
  );
}
