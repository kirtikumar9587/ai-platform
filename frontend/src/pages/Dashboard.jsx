import { useEffect, useState } from "react";
import { api } from "../api";

const n = (v) => (v ?? 0).toLocaleString();

export default function Dashboard() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.stats().then(setS).catch((e) => setErr(e.message));
  }, []);
  if (err) return <div className="error">{err}</div>;
  if (!s) return <p className="muted">Loading…</p>;
  const max = Math.max(1, ...s.tokens_by_day.map((d) => d.tokens));
  const totalTokens = s.llm.prompt_tokens + s.llm.completion_tokens;
  return (
    <>
      <h1>Dashboard</h1>
      <section className="figures">
        <div><span className="fig">{n(s.documents.ready)}</span><span>documents ready<br /><small>{n(s.documents.chunks)} chunks · {s.documents.processing} processing · {s.documents.failed} failed</small></span></div>
        <div><span className="fig">{n(s.conversations)}</span><span>conversations<br /><small>{n(s.messages)} messages</small></span></div>
        <div><span className="fig">{n(totalTokens)}</span><span>tokens used<br /><small>{n(s.llm.prompt_tokens)} in · {n(s.llm.completion_tokens)} out</small></span></div>
        <div><span className="fig">{n(s.llm.avg_latency_ms)}<small> ms</small></span><span>average model latency<br /><small>{s.llm.calls} calls · {s.llm.cached} cached</small></span></div>
        <div><span className={"fig" + (s.llm.errors ? " bad" : "")}>{n(s.llm.errors)}</span><span>model errors<br /><small>{s.llm.fallback_calls} answered by fallback model</small></span></div>
      </section>
      <h2>Tokens per day (last 7 days)</h2>
      <div className="bars">
        {s.tokens_by_day.map((d) => (
          <div key={d.day} className="bar-col" title={`${d.day}: ${n(d.tokens)} tokens`}>
            <div className="bar" style={{ height: `${(d.tokens / max) * 100}%` }} />
            <span>{d.day.slice(5)}</span>
          </div>
        ))}
      </div>
    </>
  );
}
