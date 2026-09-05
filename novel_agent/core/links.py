from dataclasses import dataclass

@dataclass
class IdeaLinkView:
    idea_id: str
    thread_ids: list[str]
    planned_chapters: list[str]
    used_chapters: list[str]

class IdeaLinkResolver:
    def __init__(self, ideas, threads):
        self.ideas, self.threads = ideas, threads
    def resolve(self, idea_id: str) -> IdeaLinkView:
        i=self.ideas.get(idea_id)
        planned=[i.placed_chapter] if i and i.placed_chapter else []
        used=[i.used_chapter] if i and i.used_chapter else []
        tids=[t.id for t in self.threads.threads if any(n.from_idea==idea_id for n in t.nodes)]
        return IdeaLinkView(idea_id,tids,planned,used)
    def all(self): return [self.resolve(i.id) for i in self.ideas.ideas]
    def thread_chapters(self, thread_id):
        t=self.threads.get(thread_id); return sorted({n.chapter_id for n in t.nodes if n.chapter_id}) if t else []
