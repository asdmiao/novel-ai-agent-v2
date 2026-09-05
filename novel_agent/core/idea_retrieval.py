"""多通道 Idea 召回与确定性重排。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IdeaRetrievalResult:
    idea: Any
    source_id: str
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    entity_score: float = 0.0
    thread_score: float = 0.0
    chapter_fit_score: float = 0.0
    priority_score: float = 0.0
    penalty: float = 0.0
    final_score: float = 0.0
    retrieval_channels: list[str] = field(default_factory=list)
    status: str = "candidate"
    reasons: list[str] = field(default_factory=list)


class IdeaRetriever:
    WEIGHTS = {"semantic": .30, "keyword": .15, "entity": .20, "thread": .15, "chapter_fit": .10, "priority": .10}

    def retrieve(self, *, plan, ideas, threads, search_engine, embedder=None, project_dir=None, top_k=8):
        available = ideas.available()
        query = " ".join(x for x in [plan.title, plan.beat, plan.goal, plan.conflict, plan.ending, plan.pov, plan.setting] if x)
        by_id: dict[str, IdeaRetrievalResult] = {}
        def add(i, channel, score=0.0, reason=""):
            r = by_id.setdefault(i.id, IdeaRetrievalResult(i, f"idea:{i.id}"))
            if channel not in r.retrieval_channels: r.retrieval_channels.append(channel)
            setattr(r, f"{channel}_score", max(getattr(r, f"{channel}_score"), score))
            if reason and reason not in r.reasons: r.reasons.append(reason)
        for i in available:
            if i.placed_chapter == plan.chapter_id: add(i, "chapter_fit", 1.0, "placed_chapter matches")
            chars = (plan.characters or []) + ([plan.pov] if plan.pov else [])
            if any(any(a in b or b in a for a in i.related_chars) for b in chars for a in [b]):
                add(i, "entity", 1.0, "character match")
        for h in search_engine.search_keyword(query, kinds=["idea"], limit=max(top_k * 3, 12)):
            i = ideas.get(h.doc.ref)
            if i and i in available: add(i, "keyword", min(h.score / 4.0, 1.0), f"keyword={h.score:.2f}")
        if embedder is not None and query:
            try:
                for h in search_engine.search_semantic(query, embedder, kinds=["idea"], top_k=max(top_k * 3, 12)):
                    i = ideas.get(h.doc.ref)
                    if i and i in available: add(i, "semantic", max(0.0, min(h.score, 1.0)), f"semantic={h.score:.2f}")
            except Exception:
                pass
        active_ids = {t.id for t in threads.threads if not t.resolved}
        for t in threads.threads:
            if t.id not in active_ids: continue
            for n in t.nodes:
                i = ideas.get(n.from_idea) if n.from_idea else None
                if i and i in available: add(i, "thread", 1.0, f"active thread={t.name}")
        for r in by_id.values():
            r.priority_score = (max(1, min(5, int(r.idea.priority))) - 1) / 4
            r.chapter_fit_score = max(r.chapter_fit_score, 1.0 if r.idea.placed_chapter == plan.chapter_id else 0.0)
            r.penalty = 0.35 if r.idea.status.value == "used" else 0.0
            r.final_score = sum(self.WEIGHTS[k] * getattr(r, f"{k}_score") for k in self.WEIGHTS) - r.penalty
            r.status = "recommended" if r.final_score >= .45 else "candidate"
        return sorted(by_id.values(), key=lambda x: -x.final_score)[:top_k]
