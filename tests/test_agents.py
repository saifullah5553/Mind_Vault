from core.registry import get_agent, list_agents, load_all_agents
from core.schemas import ResearchDossier, ScoredTopic


def setup_module(_):
    load_all_agents()


def test_all_agents_registered():
    load_all_agents()
    names = set(list_agents())
    expected = {"ceo", "trend", "topic", "research", "fact", "hook", "script",
                "visual", "voice", "presenter", "video", "quality", "seo",
                "publishing", "analytics", "competitor", "learning", "thumbnail",
                "review", "documentary"}
    assert expected.issubset(names), expected - names


def test_trend_agent_produces_items():
    res = get_agent("trend").execute({"category": "history"})
    assert res.status == "success"
    assert len(res.output) > 0
    assert res.output[0].category == "history"


def test_topic_agent_selects_scored_topic():
    trends = get_agent("trend").execute({"category": "psychology"}).output
    res = get_agent("topic").execute({"category": "psychology", "trends": trends})
    assert res.status == "success"
    topic = res.output
    assert isinstance(topic, ScoredTopic)
    assert topic.total != 0


def test_fact_checker_gates_low_confidence():
    dossier = ResearchDossier(
        topic="x", category="history",
        facts=[],
    )
    res = get_agent("fact").execute(dossier)
    assert res.status == "success"
    # No facts -> gate should not pass.
    assert res.output["gate_passed"] is False


def test_hook_engine_min_ten():
    res = get_agent("hook").execute({"topic": "fear", "category": "psychology"})
    assert res.status == "success"
    assert len(res.output["hooks"]) >= 10
    assert res.output["selected"].total > 0


def test_agent_run_is_audited():
    from core.database.models import AgentRun
    from core.database.session import session_scope
    get_agent("trend").execute({"category": "history"})
    with session_scope() as s:
        assert s.query(AgentRun).filter_by(agent="trend", status="success").count() >= 1
