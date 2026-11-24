"""Offline end-to-end checks for derived style patterns and editor integration."""
from app.database.session import SessionLocal
from app.database.models import ResearchPost, TrackedProfile, PostMetric, StylePattern
from app.marketing.style_lab import rebuild_patterns, rank_patterns, style_guidance
from app.marketing.generator import build_growth_prompt
from app.config import settings


def test_style_pipeline(client, auth, monkeypatch):
    monkeypatch.setenv("THREADS_OWN_USERNAME", "jefro_self")
    # Env-backed properties are read on demand.
    with SessionLocal() as db:
        own = TrackedProfile(username="jefro_self")
        other = TrackedProfile(username="test_analyst_styles")
        db.add_all([own, other]); db.flush()
        self_post = ResearchPost(author_id=own.id, original_text="Почему биткоин так сильно вырос сегодня? Я думаю это всё очень интересно.", language="ru")
        external = ResearchPost(author_id=other.id, original_text="Почему люди покупают мемкоины, когда уже все обсуждают рост? Это странный эффект ленты.", language="ru")
        db.add_all([self_post, external]); db.flush()
        db.add(PostMetric(post_id=external.id, views=3900, likes=51, replies=12, is_estimated=False))
        db.commit()
        external_id = external.id
        self_id = self_post.id
    with SessionLocal() as db:
        first = rebuild_patterns(db)
        db.commit()
        assert first['added'] >= 1
        assert db.query(StylePattern).filter(StylePattern.source_post_id == self_id).count() == 0
        assert db.query(StylePattern).filter(StylePattern.source_post_id == external_id).count() == 1
        again = rebuild_patterns(db)
        assert again['added'] == 0
        ranked = rank_patterns(db, topic='Почему мемкоины покупают слишком поздно?', language='ru')
        assert any(p['source_post_id'] == external_id for p in ranked)
        guidance = style_guidance(ranked)
        assert 'source' not in guidance.lower() or 'research ID' in guidance
        assert 'Почему люди покупают' not in guidance
        prompt = build_growth_prompt(topic='Мемкоины', category='Memecoins', language='ru',
                                    goal='discussion', hook_type='auto', promotion_style='none',
                                    offer=None, link=None, audience='крипто', count=3,
                                    style_guidance=guidance)
        assert 'Style Lab' in prompt
    r = client.get('/api/style-lab/stats', auth=auth)
    assert r.status_code == 200 and r.json()['patterns'] >= 1
    no_auth = client.get('/api/style-lab/patterns')
    assert no_auth.status_code == 401
    preview = client.post('/api/style-lab/preview', auth=auth, json={'topic':'Мемкоины и поздние покупки'})
    assert preview.status_code == 200
    rows = client.get('/api/style-lab/patterns', auth=auth).json()
    p = next(p for p in rows if p['source_post_id'] == external_id)
    changed = client.patch(f"/api/style-lab/patterns/{p['id']}", auth=auth, json={'enabled':False})
    assert changed.status_code == 200
    assert changed.json()['enabled'] is False
    monkeypatch.delenv("THREADS_OWN_USERNAME", raising=False)
