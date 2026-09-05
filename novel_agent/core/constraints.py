"""统一约束视图与活动约束解析（兼容旧 JSON）。"""
from dataclasses import dataclass, field
from enum import Enum

class ConstraintStatus(str, Enum):
    active="active"; inactive="inactive"; superseded="superseded"; pending="pending"
class ConstraintStrength(str, Enum):
    hard="hard"; soft="soft"; informational="informational"

@dataclass
class ConstraintView:
    id: str; type: str; content: str
    scope: list[str] = field(default_factory=list)
    source_type: str = ""; source_id: str = ""; source_chapter: str = ""; source_quote: str = ""
    valid_from: str = ""; valid_until: str = ""
    strength: str = "hard"; status: str = "active"
    supersedes: list[str] = field(default_factory=list); conflicts_with: list[str] = field(default_factory=list)
    author_confirmed: bool = False; confidence: float = 1.0

def _chapter_num(value: str) -> int | None:
    try: return int(value[1:]) if value.startswith("c") else int(value)
    except (ValueError, AttributeError): return None

class ActiveConstraintResolver:
    def resolve(self, constraints: list[ConstraintView], current_chapter: str) -> list[ConstraintView]:
        now = _chapter_num(current_chapter)
        superseded = {x for c in constraints if c.status == "active" for x in c.supersedes}
        out=[]
        for c in constraints:
            if c.status != "active" or c.id in superseded: continue
            lo, hi = _chapter_num(c.valid_from), _chapter_num(c.valid_until)
            if now is not None and ((lo is not None and now < lo) or (hi is not None and now > hi)): continue
            out.append(c)
        return out

def adapt_continuity(continuity, bible=None, world=None) -> list[ConstraintView]:
    out=[]
    for x in continuity.facts:
        out.append(ConstraintView(x.id,"fact",x.content,source_type="continuity",source_id=x.id,source_chapter=x.chapter_id))
    for x in continuity.foreshadows:
        out.append(ConstraintView(x.id,"foreshadow",x.description,status="active" if x.status.value=="planted" else "inactive",source_type="continuity",source_id=x.id,source_chapter=x.chapter_id,strength="soft"))
    for x in continuity.promises:
        out.append(ConstraintView(x.id,"promise",x.content,status="active" if not x.fulfilled else "inactive",source_type="continuity",source_id=x.id,source_chapter=x.chapter_id,strength="soft"))
    for x in continuity.possessions:
        out.append(ConstraintView(x.id,"possession",f"{x.owner} 持有 {x.item}",status="active" if not x.lost else "inactive",scope=[x.owner,x.item],source_type="continuity",source_id=x.id,source_chapter=x.chapter_id))
    for x in continuity.timeline:
        out.append(ConstraintView(f"timeline:{x.chapter_id}:{len(out)}","timeline",x.event,source_type="continuity",source_chapter=x.chapter_id,strength="hard"))
    if bible:
        for c in bible.characters:
            if c.status_history:
                h=c.status_history[-1]; out.append(ConstraintView(f"state:{c.id}:{h.get('chapter','')}","character_state",h.get("text",""),scope=[c.name],source_type="bible",source_id=c.id,source_chapter=h.get("chapter","")))
    if world:
        for e in world.elements:
            for i, text in enumerate(e.constraints): out.append(ConstraintView(f"world:{e.id}:{i}","world_rule",text,source_type="world",source_id=e.id,strength="hard"))
    return out
