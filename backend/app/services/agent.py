"""LangGraph agent: plan -> act (tool) -> plan ... -> finish.
Tools: knowledge_search -> document_analysis -> generate_report (each tool consumes the previous tool's output).
Reliability: parameter validation, step limit, per-tool timeout, global deadline, duplicate-call guard, error recovery."""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, TypedDict
from pydantic import BaseModel, Field, ValidationError
from langgraph.graph import StateGraph, END
from app.config import settings
from app.services import llm, retrieval, vectorstore
from app.services.security import build_context, sanitize_text, UNTRUSTED_RULE

logger = logging.getLogger("app.agent")


# ---------- schemas ----------
class Decision(BaseModel):
    thought: str
    action: str       # knowledge_search | document_analysis | generate_report | final_answer
    query: str        # knowledge_search
    top_k: int        # knowledge_search (1-10)
    document_id: int  # 0 = all documents
    focus: str        # document_analysis / generate_report
    title: str        # generate_report
    answer: str       # final_answer


class SearchArgs(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    top_k: int = Field(ge=1, le=10)
    document_id: int = Field(ge=0)


class AnalysisArgs(BaseModel):
    focus: str = Field(min_length=3, max_length=300)
    document_id: int = Field(ge=0)


class ReportArgs(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    focus: str = Field(max_length=300)


class FinalArgs(BaseModel):
    answer: str = Field(min_length=5)


class Theme(BaseModel):
    theme: str
    summary: str
    evidence_refs: list[int]


class Analysis(BaseModel):
    themes: list[Theme]
    conflicts: list[str]
    missing_info: list[str]


class Finding(BaseModel):
    finding: str
    evidence_refs: list[int]


class Report(BaseModel):
    title: str
    executive_summary: str
    findings: list[Finding]
    recommendations: list[str]
    gaps: list[str]


class AgentState(TypedDict, total=False):
    question: str
    user_id: int
    history: str
    steps: list
    ctx: Any
    decision: Any
    final: str
    iteration: int
    errors_in_row: int
    stop: bool
    deadline: float
    usage: Any


TOOLS_DESC = """Tools:
1. knowledge_search(query, top_k, document_id) - hybrid search over the user's documents. Adds numbered evidence. document_id=0 searches all documents.
2. document_analysis(focus, document_id) - analyses the collected evidence: themes, conflicts, missing information. Needs evidence first (run knowledge_search), or pass a document_id to load that document.
3. generate_report(title, focus) - writes a structured report (summary, findings, recommendations, gaps) from the analysis. Needs document_analysis first.
4. final_answer(answer) - finish. Cite evidence as [n]."""

SYSTEM_PLANNER = f"""You are a planning agent for an enterprise document assistant. Choose ONE next action as JSON.
{TOOLS_DESC}
Guidance:
- Simple factual questions: knowledge_search then final_answer.
- Questions asking to analyse, find common causes, compare, recommend, or "report": knowledge_search -> document_analysis -> generate_report -> final_answer.
- Do not repeat an identical call. If a tool returned an error, fix the arguments or choose another tool.
- Unused fields: use "" for text and 0 for numbers. top_k default 5.
- {UNTRUSTED_RULE}
Return JSON only."""


# ---------- tools ----------
def _add_evidence(ctx: dict, chunks: list[dict]) -> int:
    seen = {(e["document_id"], e["chunk_index"]) for e in ctx["evidence"]}
    added = 0
    for c in chunks:
        key = (c["document_id"], c["chunk_index"])
        if key in seen:
            continue
        seen.add(key)
        ctx["evidence"].append({**c, "n": len(ctx["evidence"]) + 1})
        added += 1
    return added


def _brief(chunks: list[dict], limit: int = 8) -> str:
    lines = []
    for c in chunks[:limit]:
        snippet, _ = sanitize_text(c["content"][:160].replace("\n", " "))
        lines.append(f"[{c['n']}] {c['filename']}: {snippet}")
    return "\n".join(lines)


def tool_knowledge_search(ctx: dict, a: SearchArgs) -> str:
    chunks = retrieval.retrieve(a.query, ctx["user_id"], [a.document_id] if a.document_id else None, a.top_k)
    if not chunks:
        return "No relevant chunks found for this query. Try different keywords or conclude the answer is not in the documents."
    added = _add_evidence(ctx, chunks)
    new = [e for e in ctx["evidence"] if (e["document_id"], e["chunk_index"]) in
           {(c["document_id"], c["chunk_index"]) for c in chunks}]
    return f"Found {len(chunks)} relevant chunks ({added} new). Total evidence: {len(ctx['evidence'])}.\n{_brief(new)}"


def tool_document_analysis(ctx: dict, a: AnalysisArgs) -> str:
    if a.document_id:
        chunks = vectorstore.get_document_chunks(a.document_id, ctx["user_id"])
        for c in chunks:
            c["score"] = 1.0
        if not chunks:
            raise ValueError(f"Document {a.document_id} not found or has no chunks")
        _add_evidence(ctx, chunks)
    if not ctx["evidence"]:
        raise ValueError("No evidence collected yet. Run knowledge_search first.")
    prompt = (f"{build_context(ctx['evidence'])}\n\nFocus: {a.focus}\nUser question: {ctx['question']}\n"
              "Analyse the evidence: key themes (with evidence_refs = source numbers), contradictions between sources, "
              "and information that is missing to fully answer the question.")
    r = llm.generate(prompt, system="You are a careful analyst. " + UNTRUSTED_RULE, schema=Analysis,
                     kind="agent", user_id=ctx["user_id"], usage=ctx["usage"])
    ctx["analysis"] = r.parsed
    a_ = r.parsed
    return (f"Analysis done: {len(a_.themes)} themes, {len(a_.conflicts)} conflicts, {len(a_.missing_info)} gaps. "
            f"Themes: " + "; ".join(t.theme for t in a_.themes[:6]))


def tool_generate_report(ctx: dict, a: ReportArgs) -> str:
    if ctx.get("analysis") is None:
        raise ValueError("No analysis yet. Run document_analysis first.")
    prompt = (f"{build_context(ctx['evidence'])}\n\nAnalysis JSON:\n{ctx['analysis'].model_dump_json()}\n\n"
              f"Write a structured report titled '{a.title}'. Focus: {a.focus or ctx['question']}\n"
              "Findings must cite evidence_refs (source numbers). Recommendations must be practical. List gaps honestly.")
    r = llm.generate(prompt, system="You write precise business reports from evidence only. " + UNTRUSTED_RULE,
                     schema=Report, kind="agent", user_id=ctx["user_id"], usage=ctx["usage"])
    ctx["report"] = r.parsed
    return f"Report generated: {len(r.parsed.findings)} findings, {len(r.parsed.recommendations)} recommendations."


def _with_timeout(fn, timeout: int):
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except FutureTimeout:
        raise TimeoutError(f"Tool timed out after {timeout}s")
    finally:
        ex.shutdown(wait=False)


# ---------- graph nodes ----------
def _steps_text(steps: list) -> str:
    if not steps:
        return "(none yet)"
    return "\n".join(f"Step {s['step']}: {s['action']}({json.dumps(s['args'])}) -> {'OK' if s['ok'] else 'ERROR'}: "
                     f"{s['observation'][:500]}" for s in steps)


def plan_node(state: AgentState) -> dict:
    if state["iteration"] >= settings.AGENT_MAX_STEPS or time.time() > state["deadline"] or state["errors_in_row"] >= 3:
        return {"stop": True}
    prompt = (f"User question: {state['question']}\nConversation context: {state['history'] or '(none)'}\n"
              f"Evidence collected: {len(state['ctx']['evidence'])} chunks. Analysis done: {state['ctx']['analysis'] is not None}. "
              f"Report done: {state['ctx']['report'] is not None}.\n\nSteps so far:\n{_steps_text(state['steps'])}\n\n"
              f"Step budget left: {settings.AGENT_MAX_STEPS - state['iteration']}. Choose the next action.")
    try:
        r = llm.generate(prompt, system=SYSTEM_PLANNER, schema=Decision, kind="agent",
                         user_id=state["user_id"], usage=state["usage"], temperature=0.1)
    except llm.LLMError:
        return {"stop": True}
    return {"decision": r.parsed, "iteration": state["iteration"] + 1}


def route(state: AgentState) -> str:
    if state.get("stop") or state["decision"].action == "final_answer":
        return "finish"
    return "act"


def act_node(state: AgentState) -> dict:
    d: Decision = state["decision"]
    step = {"step": state["iteration"], "thought": d.thought, "action": d.action, "args": {}, "ok": False,
            "observation": "", "ms": 0}
    t0 = time.perf_counter()
    try:
        if d.action == "knowledge_search":
            args = SearchArgs(query=d.query, top_k=d.top_k or 5, document_id=d.document_id)
            fn = lambda: tool_knowledge_search(state['ctx'], args)
        elif d.action == "document_analysis":
            args = AnalysisArgs(focus=d.focus or state["question"], document_id=d.document_id)
            fn = lambda: tool_document_analysis(state['ctx'], args)
        elif d.action == "generate_report":
            args = ReportArgs(title=d.title or "Report", focus=d.focus)
            fn = lambda: tool_generate_report(state['ctx'], args)
        else:
            raise ValueError(f"Unknown action '{d.action}'. Valid: knowledge_search, document_analysis, generate_report, final_answer")
        step["args"] = args.model_dump()
        if any(s["action"] == d.action and s["args"] == step["args"] and s["ok"] for s in state["steps"]):
            raise ValueError("Duplicate call: this exact action was already executed. Choose a different action.")
        step["observation"] = _with_timeout(fn, settings.TOOL_TIMEOUT_S)
        step["ok"] = True
    except ValidationError as e:  # parameter validation failed -> agent sees the error and can recover
        step["observation"] = "Invalid parameters: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
    except Exception as e:
        logger.warning("Tool %s failed: %s", d.action, e)
        step["observation"] = f"Tool error: {str(e)[:300]}"
    step["ms"] = int((time.perf_counter() - t0) * 1000)
    steps = state["steps"] + [step]
    return {"steps": steps, "errors_in_row": 0 if step["ok"] else state["errors_in_row"] + 1}


def finish_node(state: AgentState) -> dict:
    d = state.get("decision")
    if d is not None and d.action == "final_answer":
        try:
            return {"final": FinalArgs(answer=d.answer).answer}
        except ValidationError:
            pass
    # Agent ran out of steps/time or gave an invalid final answer -> synthesize from what we have
    ctx = state["ctx"]
    if not ctx["evidence"] and ctx["analysis"] is None:
        return {"final": "I couldn't find relevant information in your documents to answer this."}
    extra = f"\nAnalysis: {ctx['analysis'].model_dump_json()}" if ctx["analysis"] is not None else ""
    prompt = (f"{build_context(ctx['evidence'])}{extra}\n\nQuestion: {state['question']}\n"
              "Write the best possible answer using ONLY the sources, citing [n]. State clearly what is missing.")
    try:
        r = llm.generate(prompt, system="You answer strictly from sources. " + UNTRUSTED_RULE, kind="agent",
                         user_id=state["user_id"], usage=state["usage"])
        return {"final": r.text.strip()}
    except llm.LLMError as e:
        return {"final": f"The agent could not finish because the language models were unavailable. ({str(e)[:150]})"}


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("act", act_node)
    g.add_node("finish", finish_node)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", route, {"act": "act", "finish": "finish"})
    g.add_edge("act", "plan")
    g.add_edge("finish", END)
    return g.compile()


_graph = None


def run_agent(question: str, user_id: int, history_text: str = "") -> dict:
    global _graph
    if _graph is None:
        _graph = _build_graph()
    usage = llm.Usage()
    # ctx is ONE shared mutable object: tools write evidence/analysis/report into it (survives across graph nodes)
    ctx = {"question": question, "user_id": user_id, "usage": usage, "evidence": [], "analysis": None, "report": None}
    state: AgentState = {"question": question, "user_id": user_id, "history": history_text, "steps": [], "ctx": ctx,
                         "iteration": 0, "errors_in_row": 0, "stop": False,
                         "deadline": time.time() + settings.AGENT_TIMEOUT_S, "usage": usage}
    out = _graph.invoke(state, {"recursion_limit": 60})
    report, analysis = ctx["report"], ctx["analysis"]
    answer = out.get("final") or (report.executive_summary if report is not None else "")
    sources = [{"n": e["n"], "document_id": e["document_id"], "filename": e["filename"], "page": e["page"],
                "score": e.get("score"), "snippet": e["content"][:400], "cited": True} for e in ctx["evidence"]]
    return {"answer": answer, "sufficient": bool(ctx["evidence"]), "conflicts": analysis.conflicts if analysis is not None else [],
            "sources": sources, "steps": out["steps"], "verification": None, "rewritten_question": None,
            "report": report.model_dump() if report is not None else None, "usage": usage.as_dict()}
