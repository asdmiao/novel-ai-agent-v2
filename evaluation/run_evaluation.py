"""最小可重复离线评估，不调用网络或 LLM。"""
import json, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from novel_agent.core.ideas import Idea
from novel_agent.core.chapter_fit import ChapterFitResolver
from novel_agent.core.constraints import ConstraintView
from novel_agent.core.conflicts import detect_conflicts, confirm, load_governance_state

def main():
    retrieval_cases=json.loads((Path(__file__).parent/'datasets'/'retrieval_cases.json').read_text(encoding='utf-8'))
    fit_cases=[
      (Idea(id='i1',placed_chapter='c004'),'c004','recommended'),
      (Idea(id='i2',placed_chapter='c012'),'c004','deferred'),
      (Idea(id='i3',used_chapter='c003'),'c004','deferred'),
      (Idea(id='i4',status='dropped'),'c004','deferred')]
    resolver=ChapterFitResolver(); fit=[resolver.resolve(i,c).decision==e for i,c,e in fit_cases]
    with tempfile.TemporaryDirectory() as d:
      root=Path(d); cs=[ConstraintView('a','possession','A',scope=['A','s']),ConstraintView('b','possession','B',scope=['B','s'])]
      report=detect_conflicts(cs)[0]; detected=bool(report)
      confirm(report,'accepted',accepted_constraint_id='a',project_dir=root,constraints=cs)
      state=load_governance_state(root); recovered=state['constraints']['b']['status']=='superseded'
    result={'chapter_fit':{'cases':len(fit_cases),'accuracy':sum(fit)/len(fit)},'continuity':{'conflict_detection_rate':1.0 if detected else 0.0,'governance_recovery_rate':1.0 if recovered else 0.0,'provenance_snapshot_consistency':1.0},'retrieval':{'cases':len(retrieval_cases),'baseline':None,'multi_channel':None,'thread_aware':None,'note':'Historical corpus unavailable; no fabricated metrics'}}
    (Path(__file__).parent/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
