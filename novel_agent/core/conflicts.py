"""确定性连续性冲突检测与作者确认记录。"""
from dataclasses import dataclass, asdict
import uuid
import json, time
from pathlib import Path
from .constraints import ConstraintView

@dataclass
class ConflictReport:
    conflict_id: str; constraint_a: str; constraint_b: str; conflict_type: str
    severity: str = "high"; explanation: str = ""; status: str = "pending"
    created_at: float = 0.0; updated_at: float = 0.0

    def __post_init__(self):
        now=time.time(); self.created_at=self.created_at or now; self.updated_at=self.updated_at or now

    def save(self, project_dir: Path):
        p=project_dir/"continuity"/"conflicts"; p.mkdir(parents=True,exist_ok=True)
        (p/f"{self.conflict_id}.json").write_text(json.dumps(asdict(self),ensure_ascii=False,indent=2),encoding="utf-8")
    @classmethod
    def load(cls, project_dir: Path, conflict_id: str):
        p=project_dir/"continuity"/"conflicts"/f"{conflict_id}.json"
        return cls(**json.loads(p.read_text(encoding="utf-8")))

@dataclass
class ConfirmationRecord:
    id: str; conflict_id: str; action: str; timestamp: float; author: str = "user"; note: str = ""
    def save(self, project_dir: Path):
        p=project_dir/"continuity"/"confirmations"; p.mkdir(parents=True,exist_ok=True)
        (p/f"{self.id}.json").write_text(json.dumps(asdict(self),ensure_ascii=False,indent=2),encoding="utf-8")
    @classmethod
    def load(cls, project_dir: Path, record_id: str):
        p=project_dir/"continuity"/"confirmations"/f"{record_id}.json"
        return cls(**json.loads(p.read_text(encoding="utf-8")))

def load_conflicts(project_dir: Path) -> list[ConflictReport]:
    p = project_dir / "continuity" / "conflicts"
    if not p.exists(): return []
    out=[]
    for f in sorted(p.glob("*.json")):
        try: out.append(ConflictReport(**json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError): continue
    return out

def load_confirmations(project_dir: Path) -> list[ConfirmationRecord]:
    p = project_dir / "continuity" / "confirmations"
    if not p.exists(): return []
    out=[]
    for f in sorted(p.glob("*.json")):
        try: out.append(ConfirmationRecord(**json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError): continue
    return out

def load_governance_state(project_dir: Path) -> dict:
    """加载项目级治理快照；旧项目不存在时返回空状态。"""
    p=project_dir/"continuity"/"governance.json"
    if not p.exists(): return {"constraints": {}, "conflicts": [], "confirmations": []}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {"constraints": {}, "conflicts": [], "confirmations": []}

def save_governance_state(project_dir: Path, constraints, conflicts=None, confirmations=None):
    p=project_dir/"continuity"; p.mkdir(parents=True, exist_ok=True)
    state={"constraints": {c.id: {"status": c.status, "supersedes": list(c.supersedes)} for c in constraints},
           "conflicts": [asdict(x) for x in (conflicts or load_conflicts(project_dir))],
           "confirmations": [asdict(x) for x in (confirmations or load_confirmations(project_dir))]}
    (p/"governance.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def detect_conflicts(constraints: list[ConstraintView]) -> list[ConflictReport]:
    out=[]
    for i,a in enumerate(constraints):
        for b in constraints[i+1:]:
            if a.status != "active" or b.status != "active": continue
            if a.type == b.type == "possession" and a.scope and b.scope and a.scope[1] == b.scope[1] and a.scope[0] != b.scope[0]:
                out.append(ConflictReport("conflict_"+uuid.uuid5(uuid.NAMESPACE_URL, f"possession:{a.id}:{b.id}").hex[:8],a.id,b.id,"possession",explanation="同一物品存在多个持有者"))
            elif a.type == b.type == "character_state" and a.scope and a.scope == b.scope and a.content != b.content:
                out.append(ConflictReport("conflict_"+uuid.uuid5(uuid.NAMESPACE_URL, f"character_state:{a.id}:{b.id}").hex[:8],a.id,b.id,"character_state",explanation="同一角色存在不同状态"))
            elif a.type == b.type == "fact" and a.scope and a.scope == b.scope and a.content != b.content:
                out.append(ConflictReport("conflict_"+uuid.uuid5(uuid.NAMESPACE_URL, f"fact:{a.id}:{b.id}").hex[:8],a.id,b.id,"fact",explanation="事实内容互斥"))
    return out

def confirm(report: ConflictReport, action: str, *, accepted_constraint_id: str | None = None, author="user", note="", project_dir: Path | None = None, constraints: list[ConstraintView] | None = None):
    if action not in {"accepted","rejected","resolved_as_exception"}: raise ValueError(action)
    if action == "accepted" and accepted_constraint_id not in {report.constraint_a, report.constraint_b}: raise ValueError("accepted_constraint_id must identify a conflicting constraint")
    report.status = action; report.updated_at=time.time()
    if action == "accepted" and constraints is not None:
        chosen=next(c for c in constraints if c.id==accepted_constraint_id); other=report.constraint_b if accepted_constraint_id==report.constraint_a else report.constraint_a
        chosen.supersedes.append(other) if other not in chosen.supersedes else None
        for c in constraints:
            if c.id==other: c.status="superseded"
    rec=ConfirmationRecord("confirmation_"+uuid.uuid4().hex[:8], report.conflict_id, action, time.time(), author, note)
    if project_dir:
        report.save(project_dir); rec.save(project_dir)
        if constraints is not None: save_governance_state(project_dir, constraints)
    return report
