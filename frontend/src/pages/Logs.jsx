import { useEffect, useState } from "react";
import { api } from "../api";

const when = (s) => (s ? new Date(s + "Z").toLocaleString() : "");

export default function Logs() {
  const [tab, setTab] = useState("calls");
  const [calls, setCalls] = useState([]);
  const [acts, setActs] = useState([]);
  const [err, setErr] = useState("");
  const load = () => {
    api.llmLogs().then(setCalls).catch((e) => setErr(e.message));
    api.activity().then(setActs).catch((e) => setErr(e.message));
  };
  useEffect(load, []);
  return (
    <>
      <h1>Logs</h1>
      <div className="tabs">
        <button className={tab === "calls" ? "on" : ""} onClick={() => setTab("calls")}>Model calls</button>
        <button className={tab === "activity" ? "on" : ""} onClick={() => setTab("activity")}>Activity</button>
        <button className="link" onClick={load}>Refresh</button>
      </div>
      {err && <div className="error">{err}</div>}
      {tab === "calls" ? (
        <table>
          <thead><tr><th>Time</th><th>Type</th><th>Model</th><th>Tokens in / out</th><th>Latency</th><th>Result</th></tr></thead>
          <tbody>
            {calls.map((c) => (
              <tr key={c.id}>
                <td>{when(c.created_at)}</td><td>{c.kind}</td>
                <td className="mono">{c.model}{c.fallback_used && <span className="pill processing">fallback</span>}</td>
                <td>{c.prompt_tokens} / {c.completion_tokens}</td><td>{c.latency_ms} ms</td>
                <td>{c.success ? <span className="pill ready">{c.cached ? "cached" : "ok"}</span> : <span className="pill failed" title={c.error}>error</span>}
                  {!c.success && <div className="small bad-text">{(c.error || "").slice(0, 140)}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table>
          <thead><tr><th>Time</th><th>Action</th><th>Detail</th></tr></thead>
          <tbody>{acts.map((a) => <tr key={a.id}><td>{when(a.created_at)}</td><td className="mono">{a.action}</td><td>{a.detail}</td></tr>)}</tbody>
        </table>
      )}
      {((tab === "calls" && !calls.length) || (tab === "activity" && !acts.length)) && <p className="muted">Nothing logged yet.</p>}
    </>
  );
}
