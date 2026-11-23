"""Collection, normalization, deduplication and journal."""
from __future__ import annotations

from app.database.models import CollectionJob, ResearchPost, ResearchSource
from app.database.session import SessionLocal


def test_manual_import_and_dedup(client, auth):
    payload = {
        "text": "Building in public: our new AI tool automates Solana DevOps.",
        "author": "testauthor",
        "views": 1200,
    }
    first = client.post("/api/research/posts/manual", auth=auth, json=payload)
    assert first.status_code == 200
    assert first.json()["new"] == 1

    second = client.post("/api/research/posts/manual", auth=auth, json=payload)
    assert second.status_code == 409  # duplicate rejected

    with SessionLocal() as db:
        posts = db.query(ResearchPost).filter(ResearchPost.original_text == payload["text"]).all()
        assert len(posts) == 1
        jobs = db.query(CollectionJob).all()
        assert any(j.duplicate_count >= 1 for j in jobs)
        assert any(j.status == "success" for j in jobs)


def test_import_json_file(client, auth):
    content = b'[{"text":"Post A","views":10},{"text":"Post B","views":20}]'
    response = client.post(
        "/api/research/import",
        auth=auth,
        files={"file": ("data.json", content, "application/json")},
    )
    assert response.status_code == 200
    assert response.json()["imported"] == 2


def test_manual_product_and_mechanic_are_stored(client, auth):
    response = client.post("/api/research/posts/manual", auth=auth, json={
        "text": "Manual product test with a real public link https://example.com/product",
        "product": "TestProduct", "mechanic": "Lead Magnet", "niche": "AI / SaaS",
    })
    assert response.status_code == 200
    products = client.get("/api/research/products", auth=auth).json()
    assert any(p["name"] == "TestProduct" for p in products)
    links = client.get("/api/research/links", auth=auth).json()
    assert any(l["domain"] == "example.com" for l in links)


def test_backup_endpoint(client, auth):
    response = client.get("/api/research/backup", auth=auth)
    assert response.status_code == 200
    assert b"CREATE TABLE" in response.content


def test_import_too_large_is_rejected(client, auth):
    # 5 MB limit by default; 6 MB payload must be refused before parsing.
    content = b"x" * (6 * 1024 * 1024)
    response = client.post(
        "/api/research/import",
        auth=auth,
        files={"file": ("big.json", content, "application/json")},
    )
    assert response.status_code == 413
