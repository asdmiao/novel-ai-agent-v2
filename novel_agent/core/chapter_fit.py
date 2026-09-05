"""确定性的 Idea 当前章节适配判定。"""
from dataclasses import dataclass, field
import re

def _num(value):
    m = re.search(r"(\d+)$", str(value or ""))
    return int(m.group(1)) if m else None

@dataclass
class ChapterFitResult:
    idea_id: str
    chapter_fit: float
    decision: str
    reasons: list[str] = field(default_factory=list)

class ChapterFitResolver:
    def resolve(self, idea, current_chapter_id, threads=None, link=None):
        reasons=[]; score=.5
        status = getattr(idea.status, "value", idea.status)
        if status in {"dropped", "archived", "rejected", "inactive"}:
            return ChapterFitResult(idea.id, 0.0, "deferred", ["inactive idea"])
        if getattr(idea, "used_chapter", ""):
            return ChapterFitResult(idea.id, .1, "deferred", ["already used in previous chapter"])
        planned=getattr(idea, "placed_chapter", "")
        cur=_num(current_chapter_id); target=_num(planned)
        if planned and planned == current_chapter_id:
            score += .45; reasons.append("planned chapter matches current chapter")
        elif target is not None and cur is not None:
            distance=target-cur
            if distance > 0 and distance <= 2:
                score += .12; reasons.append("planned chapter is nearby")
            elif distance > 2:
                score -= .35; reasons.append("planned for a later chapter")
        idea_threads=set()
        if link is not None: idea_threads.update(getattr(link, "thread_ids", []) or [])
        for t in (getattr(threads, "threads", []) if threads else []):
            for n in t.nodes:
                if getattr(n, "from_idea", "") == idea.id: idea_threads.add(t.id)
        current_threads={t.id for t in (getattr(threads, "threads", []) if threads else [])
                         if any(getattr(n, "chapter_id", "") == current_chapter_id for n in t.nodes)}
        if idea_threads & current_threads:
            score += .2; reasons.append("same thread as current chapter")
        score=max(0.0,min(1.0,score))
        decision="recommended" if score >= .75 else ("deferred" if score < .3 else "candidate")
        return ChapterFitResult(idea.id, score, decision, reasons or ["no exact chapter fit"])
