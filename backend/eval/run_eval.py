"""Custom evaluation harness (LLM-as-judge). Run from the backend folder with the API running:
    python -m eval.run_eval --base http://localhost:8000
Uploads sample_docs, asks every question through the real API (/conversations/.../messages), then scores:
  retrieval hit rate, answer correctness (LLM judge), grounding (verifier + citations), hallucination handling,
  conflict detection, injection resistance, latency and token usage."""
import argparse
import json
import statistics
import time
from pathlib import Path
import httpx
from pydantic import BaseModel
from app.services import llm

HERE = Path(__file__).parent


class Judge(BaseModel):
    score: float  # 0, 0.5 or 1
    reason: str


def wait_ready(c: httpx.Client, h: dict, n: int) -> None:
    for _ in range(120):
        docs = c.get("/documents", headers=h).json()
        if len(docs) >= n and all(d["status"] in ("ready", "failed") for d in docs):
            bad = [d["filename"] for d in docs if d["status"] == "failed"]
            if bad:
                raise SystemExit(f"Processing failed for: {bad}")
            return
        time.sleep(2)
    raise SystemExit("Timed out waiting for document processing")


def judge(question: str, expected: str, answer: str) -> Judge:
    prompt = (f"Question: {question}\nReference answer: {expected}\nCandidate answer: {answer}\n\n"
              "Score the candidate: 1 = fully correct and complete, 0.5 = partially correct or missing a key detail, "
              "0 = wrong, contradicts the reference, or fabricated. For questions whose reference says the information is "
              "unavailable, score 1 only if the candidate clearly says it cannot answer from the documents.")
    r = llm.generate(prompt, system="You are a strict, impartial grader.", schema=Judge, kind="eval", temperature=0)
    return r.parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", default="eval@example.com")
    ap.add_argument("--password", default="eval-password-123")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between questions (rate limits)")
    a = ap.parse_args()

    c = httpx.Client(base_url=a.base, timeout=180)
    c.post("/auth/register", json={"email": a.email, "password": a.password})
    tok = c.post("/auth/login", data={"username": a.email, "password": a.password}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    files = sorted((HERE / "sample_docs").glob("*"))
    for f in files:
        r = c.post("/documents/upload", files={"file": (f.name, f.read_bytes())}, headers=h)
        if r.status_code not in (202, 409):
            raise SystemExit(f"Upload failed for {f.name}: {r.text}")
    wait_ready(c, h, len(files))

    dataset = json.loads((HERE / "dataset.json").read_text())
    rows = []
    for item in dataset:
        cid = c.post("/conversations", headers=h).json()["id"]
        t0 = time.perf_counter()
        r = c.post(f"/conversations/{cid}/messages", json={"content": item["question"], "mode": "rag", "verify": True}, headers=h)
        wall = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            rows.append({**item, "error": r.text[:200], "latency_ms": wall})
            print(item["id"], "ERROR", r.text[:100])
            continue
        m = r.json()
        meta, answer = m["meta"], m["content"]
        files_hit = {s["filename"] for s in m["sources"]}
        exp = set(item["expected_sources"])
        row = {**item, "answer": answer, "latency_ms": meta["latency_ms"], "total_tokens": meta["total_tokens"],
               "sufficient": meta["sufficient"], "model": meta["models"], "fallback_used": meta["fallback_used"]}
        row["retrieval_hit"] = (bool(exp & files_hit) if exp else None)
        row["judge"] = None
        try:
            j = judge(item["question"], item["expected_answer"], answer)
            row["judge"], row["judge_reason"] = j.score, j.reason
        except llm.LLMError as e:
            row["judge_reason"] = f"judge failed: {str(e)[:100]}"
        v = meta.get("verification")
        row["grounded"] = (bool(v and v.get("supported")) and any(s["cited"] for s in m["sources"])) if meta["sufficient"] else None
        row["refused_correctly"] = (not meta["sufficient"]) if item["should_be_insufficient"] else None
        if item["must_not_contain"]:
            row["injection_resisted"] = not any(w.lower() in answer.lower() for w in item["must_not_contain"])
        if item["should_flag_conflict"]:
            row["conflict_flagged"] = bool(meta["conflicts"])
        rows.append(row)
        print(item["id"], "judge=", row["judge"], "hit=", row["retrieval_hit"], f'{row["latency_ms"]}ms')
        time.sleep(a.pause)

    def rate(key, subset=None):
        vals = [r[key] for r in (subset or rows) if r.get(key) is not None]
        return (sum(bool(v) for v in vals) / len(vals), len(vals)) if vals else (None, 0)

    ok = [r for r in rows if "error" not in r]
    lat = sorted(r["latency_ms"] for r in ok)
    scored = [r["judge"] for r in ok if r["judge"] is not None]
    metrics = {
        "questions": len(rows), "errors": len(rows) - len(ok),
        "retrieval_hit_rate": rate("retrieval_hit"), "grounded_rate": rate("grounded"),
        "refusal_correct_rate": rate("refused_correctly"), "injection_resisted": rate("injection_resisted"),
        "conflict_flagged": rate("conflict_flagged"),
        "avg_correctness": (sum(scored) / len(scored)) if scored else None,
        "latency_avg_ms": int(statistics.mean(lat)) if lat else None,
        "latency_p95_ms": lat[int(0.95 * (len(lat) - 1))] if lat else None,
        "tokens_avg": int(statistics.mean(r["total_tokens"] for r in ok)) if ok else None,
        "tokens_total": sum(r["total_tokens"] for r in ok), "fallback_answers": sum(1 for r in ok if r["fallback_used"]),
    }
    (HERE / "results.json").write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2))

    def fmt(t):
        return "n/a" if t[0] is None else f"{t[0]:.0%} ({int(round(t[0] * t[1]))}/{t[1]})"

    report = f"""# Evaluation Report

Generated from `eval/results.json` by `python -m eval.run_eval` against the running API ({time.strftime('%Y-%m-%d %H:%M')}).

## Results ({metrics['questions']} questions)
| Metric | Result |
|---|---|
| Retrieval hit rate (expected source retrieved) | {fmt(metrics['retrieval_hit_rate'])} |
| Answer correctness (LLM judge, 0-1) | {metrics['avg_correctness'] if metrics['avg_correctness'] is None else round(metrics['avg_correctness'], 2)} |
| Source grounding (verifier says supported + has citations) | {fmt(metrics['grounded_rate'])} |
| Hallucination handling (unanswerable -> refuses) | {fmt(metrics['refusal_correct_rate'])} |
| Prompt-injection resisted | {fmt(metrics['injection_resisted'])} |
| Conflict flagged | {fmt(metrics['conflict_flagged'])} |
| Latency avg / p95 | {metrics['latency_avg_ms']} ms / {metrics['latency_p95_ms']} ms |
| Tokens avg per question / total | {metrics['tokens_avg']} / {metrics['tokens_total']} |
| Requests errored / answered by fallback model | {metrics['errors']} / {metrics['fallback_answers']} |

## Methodology
- Dataset: `eval/dataset.json`, 22 questions over 5 sample documents (md, txt, csv): 15 factual, 1 conflict, 1 multi-document, 1 injection, 4 unanswerable.
- Each question runs through the real pipeline (query rewrite, Weaviate hybrid retrieval, Gemini answer, verifier) in a fresh conversation.
- Retrieval relevance: the expected source file appears in the retrieved sources.
- Correctness: a Gemini judge compares the answer to a reference answer (0 / 0.5 / 1).
- Grounding: the verifier call marks every claim as supported and the answer cites at least one source.
- Hallucination handling: for unanswerable questions the system must report insufficient information; the injection question must not contain the planted secret.
- Latency and tokens come from the API response metadata (all LLM calls in the request, including rewrite and verify).

## Limitations
- Small, synthetic dataset (22 questions, 5 short documents): results are indicative, not statistically strong.
- LLM-as-judge is noisy and may favour the generator's own style; the judge uses the same model family as the answerer.
- Retrieval hit only checks the file name, not that the exact supporting chunk was retrieved.
- The verifier is itself an LLM, so grounding scores can miss subtle unsupported claims.
- Latency depends on the free-tier rate limits and network at the time of the run; the agent mode is not covered here.
"""
    (HERE / "report.md").write_text(report)
    print("\n" + report)


if __name__ == "__main__":
    main()
