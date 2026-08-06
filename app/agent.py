import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from langgraph.graph import END, StateGraph
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.mesh import MeshClient
from app.models import Event, Product, Recommendation
from app.vector_store import ProductVectorStore


WEIGHTS = {"page_view": 1, "product_view": 2, "search": 3, "product_click": 3, "dwell": 2, "add_to_cart": 6}
HEAVY_VIEW_THRESHOLD = 3


class AgentState(TypedDict, total=False):
    user_id: int
    profile: dict
    query: str
    candidates: list[dict]
    result: dict
    fingerprint: str
    trace: list[dict]
    excluded_ids: list[int]


def _append_trace(state: AgentState, node: str, detail: str, data: dict | None = None) -> list[dict]:
    steps = list(state.get("trace") or [])
    steps.append({"node": node, "detail": detail, "data": data or {}})
    return steps


def _analyze(state: AgentState, config):
    db: Session = config["configurable"]["db"]
    events = db.scalars(select(Event).where(Event.user_id == state["user_id"]).order_by(desc(Event.occurred_at)).limit(100)).all()
    searches = [e.query for e in events if e.query]
    viewed_ids = [e.product_id for e in events if e.product_id]
    view_counts = Counter(viewed_ids)
    products = db.scalars(select(Product).where(Product.id.in_(viewed_ids))).all() if viewed_ids else []
    categories: dict[str, int] = {}
    levels: dict[str, int] = {}
    score = 0
    for event in events:
        score += WEIGHTS.get(event.event_type, 1)
    for product in products:
        weight = view_counts.get(product.id, 1)
        categories[product.category] = categories.get(product.category, 0) + weight
        levels[product.level] = levels.get(product.level, 0) + weight
    excluded_ids = [pid for pid, count in view_counts.items() if pid and count >= HEAVY_VIEW_THRESHOLD]
    profile = {
        "recent_searches": searches[:8],
        "category_signals": categories,
        "level_signals": levels,
        "behavior_score": score,
        "view_counts": {str(k): v for k, v in view_counts.items() if k},
        "excluded_heavy_views": excluded_ids,
    }
    query = " ".join(searches[:5] + [p.title for p in products[:8]]) or "popular practical courses"
    fingerprint = hashlib.sha256(json.dumps([(e.event_id, e.event_type) for e in events[:30]]).encode()).hexdigest()
    top_category = max(categories, key=categories.get) if categories else None
    detail = f"score={score}; searches={len(searches)}; top_category={top_category or 'none'}; exclude_heavy={len(excluded_ids)}"
    return {
        "profile": profile,
        "query": query,
        "fingerprint": fingerprint,
        "excluded_ids": excluded_ids,
        "trace": _append_trace(state, "analyze_behavior", detail, {"top_category": top_category, "behavior_score": score}),
    }


def _retrieve(state: AgentState, config):
    db: Session = config["configurable"]["db"]
    store = ProductVectorStore()
    categories = state["profile"].get("category_signals") or {}
    top_category = max(categories, key=categories.get) if categories else None
    semantic = store.search(state["query"], limit=12, category=None)
    category_hits = store.search(state["query"], limit=8, category=top_category) if top_category else []
    keyword_hits = _keyword_search(db, state["query"], limit=8)

    merged: dict[int, dict] = {}
    for pid, score in semantic:
        merged[pid] = {"id": pid, "semantic_score": score, "keyword_score": 0.0, "sources": ["semantic"]}
    for pid, score in category_hits:
        row = merged.setdefault(pid, {"id": pid, "semantic_score": 0.0, "keyword_score": 0.0, "sources": []})
        row["semantic_score"] = max(row["semantic_score"], score + 0.05)
        if "category_filter" not in row["sources"]:
            row["sources"].append("category_filter")
    for pid, score in keyword_hits:
        row = merged.setdefault(pid, {"id": pid, "semantic_score": 0.0, "keyword_score": 0.0, "sources": []})
        row["keyword_score"] = max(row["keyword_score"], score)
        if "keyword" not in row["sources"]:
            row["sources"].append("keyword")

    candidates = list(merged.values())
    detail = f"merged={len(candidates)} semantic={len(semantic)} keyword={len(keyword_hits)} category={top_category or 'n/a'}"
    return {
        "candidates": candidates,
        "trace": _append_trace(state, "retrieve_catalog", detail, {"top_category": top_category, "candidate_ids": [c["id"] for c in candidates[:10]]}),
    }


def _keyword_search(db: Session, query: str, limit: int = 8) -> list[tuple[int, float]]:
    terms = [t.strip() for t in query.lower().split() if len(t.strip()) > 2][:6]
    if not terms:
        return []
    filters = []
    for term in terms:
        like = f"%{term}%"
        filters.append(or_(Product.title.ilike(like), Product.description.ilike(like), Product.category.ilike(like)))
    rows = db.scalars(select(Product).where(Product.active.is_(True), or_(*filters)).limit(40)).all()
    scored = []
    for p in rows:
        blob = f"{p.title} {p.description} {p.category} {p.level}".lower()
        hits = sum(1 for t in terms if t in blob)
        if hits:
            scored.append((p.id, min(0.35, 0.08 * hits)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


def _rerank(state: AgentState, config):
    db: Session = config["configurable"]["db"]
    category_signals = state["profile"].get("category_signals") or {}
    level_signals = state["profile"].get("level_signals") or {}
    excluded = set(state.get("excluded_ids") or [])
    ranked = []
    for hit in state["candidates"]:
        p = db.get(Product, hit["id"])
        if not p or not p.active:
            continue
        if p.id in excluded:
            continue
        score = hit.get("semantic_score", 0) + hit.get("keyword_score", 0)
        score += min(category_signals.get(p.category, 0) * 0.05, 0.25)
        score += min(level_signals.get(p.level, 0) * 0.03, 0.12)
        ranked.append({
            "id": p.id,
            "title": p.title,
            "description": p.description[:350],
            "category": p.category,
            "level": p.level,
            "price": p.price,
            "score": round(score, 4),
            "sources": hit.get("sources", []),
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    diverse = _diversify(ranked, limit=5, max_per_category=2)
    detail = f"ranked={len(ranked)} diversified={len(diverse)} excluded_heavy={len(excluded)}"
    return {
        "candidates": diverse,
        "trace": _append_trace(state, "rerank_grounded", detail, {"selected": [{"id": c["id"], "score": c["score"], "category": c["category"]} for c in diverse]}),
    }


def _diversify(ranked: list[dict], limit: int = 5, max_per_category: int = 2) -> list[dict]:
    selected: list[dict] = []
    per_category: Counter = Counter()
    for item in ranked:
        if per_category[item["category"]] >= max_per_category:
            continue
        selected.append(item)
        per_category[item["category"]] += 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_ids = {s["id"] for s in selected}
        for item in ranked:
            if item["id"] in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
    return selected


def _generate(state: AgentState):
    result = MeshClient().persuasive_copy(state["profile"], state["candidates"])
    detail = f"narrative_chars={len(result.get('narrative', ''))}; product_ids={result.get('product_ids', [])}"
    return {
        "result": result,
        "trace": _append_trace(state, "generate_copy", detail, {"product_ids": result.get("product_ids", [])}),
    }


graph = StateGraph(AgentState)
graph.add_node("analyze_behavior", _analyze)
graph.add_node("retrieve_catalog", _retrieve)
graph.add_node("rerank_grounded", _rerank)
graph.add_node("generate_copy", _generate)
graph.set_entry_point("analyze_behavior")
graph.add_edge("analyze_behavior", "retrieve_catalog")
graph.add_edge("retrieve_catalog", "rerank_grounded")
graph.add_edge("rerank_grounded", "generate_copy")
graph.add_edge("generate_copy", END)
reco_graph = graph.compile()


def maybe_generate(db: Session, user_id: int, force: bool = False) -> Recommendation | None:
    s = get_settings()
    latest = db.scalar(select(Recommendation).where(Recommendation.user_id == user_id).order_by(desc(Recommendation.created_at)))
    recent_events = db.scalars(select(Event).where(Event.user_id == user_id, Event.occurred_at >= datetime.now(timezone.utc) - timedelta(hours=24))).all()
    score = sum(WEIGHTS.get(e.event_type, 1) for e in recent_events)
    if not force and (score < s.reco_min_score or (latest and latest.created_at >= datetime.now(timezone.utc) - timedelta(minutes=s.reco_cooldown_minutes))):
        return latest
    state = reco_graph.invoke({"user_id": user_id, "trace": []}, config={"configurable": {"db": db}})
    if latest and latest.behavior_fingerprint == state["fingerprint"]:
        return latest
    valid_ids = {p.id for p in db.scalars(select(Product).where(Product.id.in_(state["result"].get("product_ids", [])), Product.active.is_(True))).all()}
    ranked_ids = [p["id"] for p in state["candidates"] if p["id"] in valid_ids] or [p["id"] for p in state["candidates"][:3]]
    why = []
    searches = state["profile"].get("recent_searches") or []
    if searches:
        why.append(f"Recent searches: {', '.join(searches[:3])}.")
    cats = state["profile"].get("category_signals") or {}
    if cats:
        top = max(cats, key=cats.get)
        why.append(f"Strongest category signal: {top}.")
    if state.get("excluded_ids"):
        why.append("Skipped heavily viewed items to surface fresh next steps.")
    evidence = {
        "profile": state["profile"],
        "trace": state.get("trace") or [],
        "why": " ".join(why) or "Based on your recent browsing and search activity.",
        "selected": [{"id": c["id"], "title": c["title"], "score": c["score"], "category": c["category"]} for c in state["candidates"] if c["id"] in ranked_ids],
        "query": state.get("query"),
    }
    reco = Recommendation(
        user_id=user_id,
        behavior_fingerprint=state["fingerprint"],
        narrative=state["result"].get("narrative", "Here are strong next steps based on your recent interests."),
        product_ids=ranked_ids,
        evidence=evidence,
        model=s.mesh_chat_model,
    )
    db.add(reco)
    db.commit()
    db.refresh(reco)
    return reco
