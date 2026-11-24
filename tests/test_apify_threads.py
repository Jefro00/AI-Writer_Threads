"""Offline tests: no actual Apify charges and no Meta login."""
import asyncio

from app.sources.apify_threads import ApifyThreadsSource, transform_items


def test_apify_normalize_and_exclude_own():
    rows = [
        {"rowType": "post", "status": "ok", "postId": "11", "authorUsername": "web3sergeich", "text": "Own"},
        {"rowType": "post", "status": "ok", "postId": "12", "authorUsername": "cryptoauthor", "text": "Рынок опять развернулся?", "createdAt": "2026-11-20T08:00:00Z", "likeCount": 42, "replyCount": 7, "url": "https://www.threads.com/@cryptoauthor/post/abc"},
        {"rowType": "post", "status": "ok", "authorUsername": "bad", "text": "bad", "url": "https://evil.example/p"},
        {"rowType": "profile", "status": "ok", "username": "cryptoauthor", "followerCount": 5000},
        {"rowType": "post", "status": "failed", "text": "error"},
    ]
    result = transform_items(rows, own_username="web3sergeich")
    assert [p.text for p in result.posts] == ["Рынок опять развернулся?", "bad"]
    assert result.posts[0].views is None
    assert result.posts[0].likes == 42
    assert result.posts[1].post_url is None
    assert result.profiles[0].followers_count == 5000


def test_apify_requires_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    result = asyncio.run(ApifyThreadsSource().collect({"keywords": ["bitcoin"]}))
    assert result.skipped and "APIFY_TOKEN" in result.skipped


def test_apify_collect_uses_bearer_and_caps(monkeypatch):
    import httpx
    monkeypatch.setenv("APIFY_TOKEN", "test_secret")
    monkeypatch.setenv("APIFY_MAX_ITEMS", "7")
    requests = []
    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return httpx.Response(200, json=[{"rowType":"post","status":"ok","postId":"abc","text":"A post","authorUsername":"other"}])
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)
    result = asyncio.run(ApifyThreadsSource().collect({"keywords": ["defi", "solana", "meme", "bitcoin"], "limit": 150}))
    assert len(result.posts) == 1
    assert len(requests) == 1
    assert requests[0][1]["json"] == {"searchQueries": ["defi", "solana", "meme"], "maxItems": 7}
    assert requests[0][1]["headers"]["Authorization"] == "Bearer test_secret"
    assert "token" not in requests[0][1].get("params", {})


def test_apify_failure_does_not_leak_token(monkeypatch):
    import httpx
    monkeypatch.setenv("APIFY_TOKEN", "sensitive_test_secret")
    class MockClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs): return httpx.Response(401, json={"error": "invalid token"})
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)
    result = asyncio.run(ApifyThreadsSource().collect({"keywords":["btc"]}))
    assert result.errors and "401" in result.errors[0]
    assert "sensitive_test_secret" not in str(result)


def test_research_apify_job(client, auth, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test_secret")
    from app.sources.apify_threads import ApifyThreadsSource
    from app.sources.base import SourceResult, RawPost
    async def fake_collect(self, params):
        assert params["mode"] == "search"
        return SourceResult(posts=[RawPost(external_id="test_apify_123", text="Криптовалюта не то, чем кажется", author_username="foreign_author", post_url="https://www.threads.com/@foreign_author/post/test_apify_123")])
    monkeypatch.setattr(ApifyThreadsSource, "collect", fake_collect)
    from app.scheduler.tasks import run_research
    stats = asyncio.run(run_research("apify_search", {"keywords": ["крипта"], "limit": 10}))
    assert stats["apify_search"]["new"] == 1
    posts = client.get("/api/research/posts?exclude_own=true", auth=auth).json()
    assert any(item["author"] and item["author"]["username"] == "foreign_author" for item in posts["items"])
