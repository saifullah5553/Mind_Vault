from core.database.models import Content, ContentMemory, Topic
from core.database.session import session_scope


def test_content_crud_and_relationship():
    with session_scope() as s:
        c = Content(topic="Why we procrastinate", category="psychology",
                    title="The Hidden Reason You Procrastinate", status="idea")
        s.add(c)
        s.flush()
        s.add(ContentMemory(video_id=c.id, topic=c.topic, hook="One habit rules them all",
                            hook_type="curiosity", duration=62.0))
        cid = c.id

    with session_scope() as s:
        loaded = s.get(Content, cid)
        assert loaded.category == "psychology"
        assert loaded.memory is not None
        assert loaded.memory.hook_type == "curiosity"


def test_topic_scoring_persist():
    with session_scope() as s:
        s.add(Topic(topic="Fall of Rome", category="history", total_score=71.2, status="candidate"))
    with session_scope() as s:
        t = s.query(Topic).filter_by(category="history").one()
        assert t.total_score == 71.2
