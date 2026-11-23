"""Growth Studio integration tests: no external AI, Threads or affiliate calls."""
from __future__ import annotations

from fastapi import HTTPException

from app.marketing.generator import _finish_text, _parse_json


def test_ai_json_with_markdown_wrapper():
    assert _parse_json('```json\n{"hooks": [], "variants": []}\n```')["variants"] == []


def test_approved_link_and_disclosure_added_and_length_limited():
    s = _finish_text("Пожалуй, это плохой момент входа?\n" + "Входить по чужой рекламе опасно. " * 30,
                     language="ru", promotion_style="soft", goal="clicks",
                     link="https://fomo.family/r/jefrocrypto")
    assert len(s) <= 500
    assert s.count("https://fomo.family/r/jefrocrypto") == 1
    assert "Партнёрская ссылка" in s


def test_promoless_posts_never_get_affiliate_url():
    s = _finish_text("Обсудим мемкоины?", language="ru", promotion_style="none",
                     goal="clicks", link="https://fomo.family/r/jefrocrypto")
    assert "http" not in s
    assert "комиссию" not in s


def test_admin_required_and_public_health(client):
    assert client.get('/api/growth/offers').status_code == 401
    assert client.get('/api/growth/analytics').status_code == 401
    assert client.get('/healthz').json() == {'ok': True}


def test_create_generate_and_track_campaign(client, auth, monkeypatch):
    import app.api.growth as growth
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://jefrocrypto.onrender.com')

    async def fake_generate(**kwargs):
        assert kwargs['language'] == 'ru'
        assert kwargs['goal'] == 'clicks'
        assert 'go/fomo?c=' in kwargs['link']
        return {'hooks': [{'hook_type':'curiosity', 'text': 'Как ты узнаёшь о монетах?'}],
                'variants':[{'text': 'Почему в ленте уже поздно?\n\n' + kwargs['link'] + '\nПартнёрская ссылка. Могу получить комиссию.',
                             'hook_type':'curiosity', 'score': 90.0},
                            {'text': 'Кто вошёл до хайпа?\n\n' + kwargs['link'] + '\nПартнёрская ссылка. Могу получить комиссию.',
                             'hook_type':'debate', 'score': 85.0}],
                'prompt_version':'growth-v1', 'ai_model':'fake'}

    monkeypatch.setattr(growth, 'generate_growth_variants', fake_generate)
    response = client.post('/api/growth/generate', auth=auth,
                           json={'topic':'Почему поздно покупают мемкоины', 'variants': 2})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['tracking_enabled'] is True
    assert len(data['posts']) == 2
    for idx, p in enumerate(data['posts'], 1):
        assert f'&v={idx}' in p['text']
        assert '{variant_index}' not in p['text']
        assert p['language'] == 'ru'

    url = f"/go/fomo?c={data['campaign_id']}&v=1"
    redirect = client.get(url, follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers['location'] == 'https://fomo.family/r/jefrocrypto'
    views = client.get('/api/growth/analytics', auth=auth).json()
    post = next(x for x in views['posts'] if x['id'] == data['posts'][0]['id'])
    assert post['clicks'] == 1
    assert post['views'] is None and post['ctr_percent'] is None

    metrics = client.put(f"/api/growth/posts/{data['posts'][0]['id']}/metrics", auth=auth,
                         json={'views': 1000, 'registrations': 3, 'revenue': 9.5})
    assert metrics.status_code == 200, metrics.text
    updated = client.get('/api/growth/analytics', auth=auth).json()
    post = next(x for x in updated['posts'] if x['id'] == data['posts'][0]['id'])
    assert post['ctr_percent'] == 0.1
    assert post['registrations'] == 3
    assert post['signup_rate_percent'] is None  # cannot attribute 3 signups to 1 tracked click
    from app.database.session import SessionLocal
    from app.database.models import Post
    with SessionLocal() as db:
        for p in data['posts']:
            db.get(Post, p['id']).status = 'rejected'
        db.commit()


def test_disallow_open_redirects_and_wrong_post(client, auth):
    payload = {'slug':'testpromo', 'name':'Test promo',
               'referral_url':'http://127.0.0.1/secret', 'description':'test'}
    assert client.post('/api/growth/offers',auth=auth,json=payload).status_code == 422
    payload['referral_url'] = 'https://example.org/ref/safe'
    assert client.post('/api/growth/offers',auth=auth,json=payload).status_code == 200
    assert client.get('/go/testpromo?post=99999', follow_redirects=False).status_code == 404
    assert client.get('/go/testpromo?c=99999&v=1', follow_redirects=False).status_code == 404
    assert client.get('/go/testpromo?url=https://evil.com',follow_redirects=False).headers['location'] == payload['referral_url']


def test_publish_claim_prevents_retries(client, auth, monkeypatch):
    import app.publisher as publisher
    from app.database.models import Post
    from app.database.session import SessionLocal

    async def fake_publish(text):
        return publisher.PublishResult('test-post-1')
    monkeypatch.setattr(publisher, 'publish_text', fake_publish)
    with SessionLocal() as db:
        p = Post(text='Первый реальный пост', status='approved', language='ru')
        db.add(p); db.commit(); pid = p.id
    assert client.post(f'/api/posts/{pid}/publish', auth=auth).status_code == 200
    assert client.post(f'/api/posts/{pid}/publish', auth=auth).status_code == 409


def test_ambiguous_publish_requires_manual_reset(client, auth, monkeypatch):
    import app.publisher as publisher
    from app.database.models import Post
    from app.database.session import SessionLocal

    async def failed(text):
        raise publisher.ThreadsPublishError('network error')
    monkeypatch.setattr(publisher, 'publish_text', failed)
    with SessionLocal() as db:
        p=Post(text='Дублировать нельзя', status='approved', language='ru')
        db.add(p);db.commit();pid=p.id
    assert client.post(f'/api/posts/{pid}/publish',auth=auth).status_code == 502
    assert client.post(f'/api/posts/{pid}/publish',auth=auth).status_code == 409
    assert client.post(f'/api/posts/{pid}/reset-publish',auth=auth).status_code == 200
    assert client.get('/api/posts',auth=auth).json()[0]['status']=='pending_review'
    with SessionLocal() as db:
        db.get(Post, pid).status = 'rejected'
        db.commit()
