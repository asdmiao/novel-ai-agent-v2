import tempfile
import unittest
from pathlib import Path
from novel_agent.core.idea_retrieval import IdeaRetriever
from novel_agent.core.ideas import IdeaBank
from novel_agent.core.outline import ChapterPlan
from novel_agent.core.threads import ThreadNetwork
from novel_agent.core.search import SearchEngine
from novel_agent.core.bible import Bible
from novel_agent.core.world import World
from novel_agent.core.continuity import Continuity
from novel_agent.core.chapter import ChapterStore
from novel_agent.core.memory import Memory

class Hit:
    def __init__(self, idea_id, score):
        self.doc=type('Doc', (), {'ref': idea_id, 'id': 'idea:'+idea_id, 'kind':'idea'})
        self.score=score
class FakeSearch:
    def __init__(self, keyword=None, semantic=None): self.keyword=keyword or []; self.semantic=semantic or []
    def search_keyword(self, *a, **k): return self.keyword
    def search_semantic(self, *a, **k): return self.semantic

class Phase2Tests(unittest.TestCase):
    def test_semantic_only(self):
        ideas=IdeaBank(project='p'); i=ideas.add('废弃建筑墙后隐藏空间 夜间调查', priority=2)
        plan=ChapterPlan(chapter_id='c002', title='地下室异响', beat='调查废弃建筑中的异常声音')
        r=IdeaRetriever().retrieve(plan=plan, ideas=ideas, threads=ThreadNetwork(project='p'), search_engine=FakeSearch(semantic=[Hit(i.id,.95)]), embedder=object())
        self.assertEqual(r[0].idea.id,i.id); self.assertIn('semantic',r[0].retrieval_channels)

    def test_reranking_not_priority(self):
        ideas=IdeaBank(project='p'); a=ideas.add('无关风景', priority=5); b=ideas.add('林尘调查地下室异常声音', priority=3, related_chars=['林尘'])
        plan=ChapterPlan(chapter_id='c001', title='地下室', beat='调查异常声音', characters=['林尘'])
        se=FakeSearch(semantic=[Hit(a.id,.05),Hit(b.id,.95)], keyword=[Hit(b.id,3)])
        rs=IdeaRetriever().retrieve(plan=plan, ideas=ideas, threads=ThreadNetwork(project='p'), search_engine=se, embedder=object())
        self.assertEqual(rs[0].idea.id,b.id)

    def test_contextbundle_integration_fields(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); ideas=IdeaBank(project='p'); i=ideas.add('地下室调查', related_chars=['林尘']); plan=ChapterPlan(chapter_id='c001', title='地下室', characters=['林尘'])
            outline=__import__('novel_agent.core.outline',fromlist=['Outline']).Outline(project='p', volumes=[__import__('novel_agent.core.outline',fromlist=['Volume']).Volume(volume_id='v1',chapters=[plan])])
            mem=Memory(root,outline,Bible(project='p',characters=[__import__('novel_agent.core.bible',fromlist=['Character']).Character(id='c',name='林尘')]),ChapterStore(),Continuity(project='p'),world=World(project='p'),ideas=ideas,threads=ThreadNetwork(project='p'))
            b=mem.build_context_bundle('c001'); self.assertTrue(b.selected_ideas)
            for k in ('source_id','score','status','retrieval_channels','reasons'): self.assertIn(k,b.selected_ideas[0])

    def test_snapshot_fields_and_selected_not_used(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); ideas=IdeaBank(project='p'); i=ideas.add('地下室调查', related_chars=['林尘']); plan=ChapterPlan(chapter_id='c001', title='地下室', characters=['林尘'])
            from novel_agent.core.outline import Outline, Volume
            from novel_agent.core.bible import Character
            outline=Outline(project='p', volumes=[Volume(volume_id='v1',chapters=[plan])])
            mem=Memory(root,outline,Bible(project='p',characters=[Character(id='c',name='林尘')]),ChapterStore(),Continuity(project='p'),world=World(project='p'),ideas=ideas,threads=ThreadNetwork(project='p'))
            b=mem.build_context_bundle('c001'); self.assertTrue(hasattr(b,'threads')); self.assertTrue(hasattr(b,'conflicts'))
            self.assertTrue(b.selected_ideas[0]['selected']); self.assertEqual(b.selected_ideas[0]['used'],'unknown')
    def test_multichannel_dedup_and_ranking(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); ideas=IdeaBank(project='p'); a=ideas.add('地下室传来异常声音', title='调查', priority=3, related_chars=['林尘']); ideas.mark_planned(a.id,'c001')
            ideas.add('完全无关的风景', title='风景', priority=5)
            plan=ChapterPlan(chapter_id='c001', title='地下室', beat='调查异常声音', characters=['林尘'])
            threads=ThreadNetwork(project='p'); t=threads.add_thread(name='调查线'); threads.add_node_to(t.id, from_idea=a.id, chapter_id='c001')
            se=SearchEngine(root); se.index_project(bible=Bible(project='p'), continuity=Continuity(project='p'), world=World(project='p'), ideas=ideas, store=ChapterStore(), project_dir=root)
            rs=IdeaRetriever().retrieve(plan=plan, ideas=ideas, threads=threads, search_engine=se, top_k=8)
            r=next(x for x in rs if x.idea.id==a.id)
            self.assertEqual(len({x.idea.id for x in rs}), len(rs)); self.assertGreater(r.entity_score,0); self.assertGreater(r.thread_score,0); self.assertIn('chapter_fit',r.retrieval_channels)

if __name__=='__main__': unittest.main()
