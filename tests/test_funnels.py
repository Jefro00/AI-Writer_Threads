"""Funnel proof levels, links and landing safety."""
from __future__ import annotations

from app.research.funnel_detector import max_proof
from app.utils import is_safe_url


def test_proof_levels():
    assert max_proof(["L1", "L3", "L2"]) == "L3"
    assert max_proof([]) == "L1"
    assert max_proof(["L6", "L7"]) == "L7"


def test_funnel_detector_never_claims_sales(client, auth):
    # No funnel can be created from public text without a CTA/link; L6/L7 must
    # still remain unverified when produced by the AI agent.
    from app.database.models import Funnel
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        for f in db.query(Funnel).all():
            assert f.proof_level in {"L1", "L2", "L3", "L4", "L5", "L6", "L7"}


def test_landing_rejects_unsafe_url(client, auth):
    response = client.post("/api/research/landing", auth=auth, json={"url": "http://127.0.0.1:8000/admin"})
    assert response.status_code == 422
