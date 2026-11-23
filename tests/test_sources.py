"""Unavailable sources are skipped, not reported as failures."""
from __future__ import annotations

import asyncio

from app.scheduler import run_research


def test_unavailable_sources_are_skipped(client, auth):
    stats = asyncio.run(run_research("all", {"limit": 5}))
    assert stats
    jobs = client.get("/api/research/jobs?limit=20", auth=auth).json()
    failed = [j for j in jobs if j["status"] == "failed"]
    assert failed == []


def test_empty_media_posts_are_ignored(client, auth):
    from app.database.session import SessionLocal
    from app.research.collector import collect_from_source
    from app.sources.base import RawPost, SourceAdapter, SourceResult

    class FakeSource(SourceAdapter):
        name = "fake_media"
        source_type = "api"

        def is_enabled(self):
            return True

        async def collect(self, params):
            return SourceResult(posts=[RawPost(external_id="1", text=""), RawPost(external_id="2", text="   ")])

    with SessionLocal() as db:
        stats = collect_from_source_sync(db, FakeSource())
    assert stats["errors"] == 0
    assert stats["new"] == 0


def collect_from_source_sync(db, adapter):
    import asyncio

    from app.research.collector import collect_from_source

    return asyncio.run(collect_from_source(db, adapter, {}))


def test_keyword_search_skipped_without_meta_scope(monkeypatch):
    from app.sources.base import SourceResult
    from app.sources.threads_api import ThreadsApiSource

    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "dummy")
    monkeypatch.setenv("THREADS_KEYWORD_SEARCH_ENABLED", "false")
    result = SourceResult()
    asyncio.run(ThreadsApiSource()._keyword_search(None, {"query": "solana"}, result))
    assert result.skipped and "threads_keyword_search" in result.skipped


def test_monitored_handles_include_usernames_without_ids(client, auth):
    from app.database.models import TrackedProfile
    from app.database.session import SessionLocal
    from app.research.account_monitor import monitored_handles

    with SessionLocal() as db:
        if not db.query(TrackedProfile).filter(TrackedProfile.username == "no_id_author").first():
            db.add(TrackedProfile(username="no_id_author"))
            db.commit()
        handles = monitored_handles(db)
    assert "no_id_author" in handles
    assert handles["no_id_author"] is None


def test_account_monitor_skips_without_authors(monkeypatch):
    from app.sources.account_monitor import AccountMonitorSource

    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "dummy")
    monkeypatch.setenv("THREADS_PROFILE_DISCOVERY_ENABLED", "true")
    result = asyncio.run(AccountMonitorSource().collect({"handles": {}}))
    assert result.skipped and "No monitored authors" in result.skipped


def test_bulk_profile_import(client, auth):
    content = b'[{"username":"bulk_author","external_profile_id":"999","followers_count":1200,"niches":"Crypto|DeFi"}]'
    response = client.post(
        "/api/research/profiles/import",
        auth=auth,
        files={"file": ("authors.json", content, "application/json")},
    )
    assert response.status_code == 200
    assert response.json()["added"] >= 1
    profiles = client.get("/api/research/profiles", auth=auth).json()
    author = next(p for p in profiles if p["username"] == "bulk_author")
    assert author["external_profile_id"] == "999"
    assert author["niches"] == ["Crypto", "DeFi"]


def test_source_can_be_toggled(client, auth):
    sources = client.get("/api/research/sources", auth=auth).json()
    assert sources
    source = next(s for s in sources if s["name"] == "content_library")
    response = client.patch(
        f"/api/research/sources/{source['id']}",
        auth=auth,
        json={"enabled": False, "config_json": {"note": "test"}},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["config"]["note"] == "test"
    # Restore for other tests.
    client.patch(
        f"/api/research/sources/{source['id']}",
        auth=auth,
        json={"enabled": True, "config_json": {}},
    )


def test_public_search_does_not_treat_own_posts_as_competitors(monkeypatch):
    """Meta can respond 200 but search only the current account before App Review."""
    from app.sources.base import SourceResult
    from app.sources.threads_api import ThreadsApiSource

    monkeypatch.setenv('THREADS_ACCESS_TOKEN', 'dummy')
    monkeypatch.setenv('THREADS_KEYWORD_SEARCH_ENABLED', 'true')
    monkeypatch.setenv('THREADS_OWN_USERNAME', 'web3sergeich')

    class FakeThreads(ThreadsApiSource):
        async def _get(self, client, path, params, result):
            if path == '/keyword_search':
                return {'data': [{'id': '1', 'text': 'мой пост', 'username': 'web3sergeich'}]}
            raise AssertionError(path)

    result = SourceResult()
    posts = asyncio.run(FakeThreads()._keyword_search(None, {'query': 'crypto'}, result))
    assert posts == []
    assert 'только публикации' in (result.skipped or '')
    assert 'App Review' in result.skipped


def test_public_search_accepts_only_external_posts(monkeypatch):
    from app.sources.base import SourceResult
    from app.sources.threads_api import ThreadsApiSource

    monkeypatch.setenv('THREADS_ACCESS_TOKEN', 'dummy')
    monkeypatch.setenv('THREADS_KEYWORD_SEARCH_ENABLED', 'true')
    monkeypatch.setenv('THREADS_OWN_USERNAME', 'web3sergeich')

    class FakeThreads(ThreadsApiSource):
        async def _get(self, client, path, params, result):
            return {'data': [
                {'id': '1', 'text': 'мой пост', 'username': 'web3sergeich'},
                {'id': '2', 'text': 'конкурент', 'username': 'some_trader'},
            ]}

    result = SourceResult()
    posts = asyncio.run(FakeThreads()._keyword_search(None, {'query': 'crypto'}, result))
    assert [p.author_username for p in posts] == ['some_trader']
    assert result.skipped is None


def test_keyword_scope_denial_is_not_a_name_error(monkeypatch):
    from app.sources.base import SourceResult
    from app.sources.threads_api import ThreadsApiSource

    monkeypatch.setenv('THREADS_ACCESS_TOKEN', 'dummy')
    monkeypatch.setenv('THREADS_KEYWORD_SEARCH_ENABLED', 'true')

    class DeniedThreads(ThreadsApiSource):
        async def _get(self, client, path, params, result):
            result.errors.append('Threads API /keyword_search HTTP 400: (#200) permission denied 4279067')
            return {}

    result = SourceResult()
    posts = asyncio.run(DeniedThreads()._keyword_search(None, {'query': 'crypto'}, result))
    assert posts == []
    assert result.skipped and 'App Review' in result.skipped


def test_external_only_posts_filter(client, auth, monkeypatch):
    """Old posts remain in DB; UI can filter own account without deleting history."""
    monkeypatch.setenv('THREADS_OWN_USERNAME', 'web3sergeich')
    for author in ['web3sergeich', 'competitor_test']:
        res = client.post('/api/research/posts/manual', auth=auth, json={
            'text': f'Unique post from {author} for competitor visibility test',
            'author': author,
        })
        assert res.status_code == 200
    data = client.get('/api/research/posts?limit=200&exclude_own=true', auth=auth).json()
    authors = [p['author']['username'] for p in data['items'] if p['author']]
    assert 'web3sergeich' not in authors
    assert 'competitor_test' in authors
