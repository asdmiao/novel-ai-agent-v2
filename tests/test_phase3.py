import unittest
import tempfile, json
from pathlib import Path
from novel_agent.core.continuity import Continuity, Fact, Possession
from novel_agent.core.constraints import adapt_continuity, ActiveConstraintResolver, ConstraintView
from novel_agent.core.conflicts import ConflictReport, detect_conflicts, confirm, load_governance_state, load_conflicts, load_confirmations
from novel_agent.core.outline import Outline, Volume
from novel_agent.core.chapter import ChapterPlan, ChapterStore
from novel_agent.core.bible import Bible
from novel_agent.core.world import World
from novel_agent.core.memory import Memory

class Phase3Tests(unittest.TestCase):
    def test_adapter_and_resolver(self):
        c=Continuity(project='p', facts=[Fact(id='f1',chapter_id='c001',content='事实')])
        views=adapt_continuity(c); self.assertEqual(views[0].id,'f1')
        self.assertEqual(len(ActiveConstraintResolver().resolve(views,'c001')),1)
    def test_validity_and_supersedes(self):
        cs=[ConstraintView('a','fact','old'),ConstraintView('b','fact','new',supersedes=['a']),ConstraintView('c','fact','later',valid_from='c003')]
        self.assertEqual([x.id for x in ActiveConstraintResolver().resolve(cs,'c002')],['b'])
    def test_conflicts_and_confirmation(self):
        cs=[ConstraintView('a','possession','A',scope=['A','sword']),ConstraintView('b','possession','B',scope=['B','sword'])]
        r=detect_conflicts(cs)[0]; self.assertEqual(r.status,'pending'); self.assertEqual(confirm(r,'resolved_as_exception').status,'resolved_as_exception')

    def test_governance_persistence_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            cs=[ConstraintView('a','possession','A',scope=['A','sword']), ConstraintView('b','possession','B',scope=['B','sword'])]
            report=detect_conflicts(cs)[0]
            confirm(report,'accepted',accepted_constraint_id='a',project_dir=root,constraints=cs)
            state=load_governance_state(root)
            self.assertEqual(state['constraints']['b']['status'],'superseded')
            self.assertEqual(load_conflicts(root)[0].status,'accepted')
            self.assertEqual(load_confirmations(root)[0].action,'accepted')
            # simulate restart: fresh views receive persisted governance
            fresh=[ConstraintView('a','possession','A',scope=['A','sword']), ConstraintView('b','possession','B',scope=['B','sword'])]
            for c in fresh:
                saved=state['constraints'].get(c.id,{})
                c.status=saved.get('status',c.status); c.supersedes=saved.get('supersedes',c.supersedes)
            self.assertEqual([c.id for c in ActiveConstraintResolver().resolve(fresh,'c001')],['a'])

    def test_historical_provenance_snapshot_is_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=root/'chapters'/'provenance'; p.mkdir(parents=True)
            snapshot={'chapter_id':'c004','constraints':[{'constraint_id':'fact_001','status':'active'}],
                      'conflicts':[{'conflict_id':'x','status':'pending'}], 'confirmations':[],
                      'threads':[{'thread_id':'t1'}], 'ideas':[{'source_id':'i1','selected':True,'used':'unknown'}], 'retrieved_sources':[{'source_id':'r1'}]}
            f=p/'c004.json'; f.write_text(json.dumps(snapshot),encoding='utf-8')
            cs=[ConstraintView('fact_001','fact','old'),ConstraintView('fact_002','fact','new')]
            report=ConflictReport('x','fact_001','fact_002','fact')
            confirm(report,'accepted',accepted_constraint_id='fact_002',project_dir=root,constraints=cs)
            loaded=json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(loaded['constraints'][0]['status'],'active')
            self.assertEqual(loaded['conflicts'][0]['status'],'pending')
            self.assertEqual(loaded['ideas'][0]['used'],'unknown')

if __name__=='__main__': unittest.main()
