"""
Firestore-backed job store shared by BASIC and PRO analyzers.
Replaces in-memory _jobs dict so all Cloud Run instances share state.
"""
import os
from google.cloud import firestore

_client = None


def _col(collection: str):
    global _client
    if _client is None:
        _client = firestore.Client(
            project=os.getenv("GOOGLE_CLOUD_PROJECT", "decorate-me")
        )
    return _client.collection(collection)


def create(col: str, job_id: str, data: dict) -> None:
    _col(col).document(job_id).set(data)


def get(col: str, job_id: str) -> dict | None:
    doc = _col(col).document(job_id).get()
    return doc.to_dict() if doc.exists else None


def patch(col: str, job_id: str, updates: dict) -> None:
    _col(col).document(job_id).update(updates)


def delete(col: str, job_id: str) -> None:
    _col(col).document(job_id).delete()


def all_jobs(col: str) -> list[dict]:
    return [d.to_dict() for d in _col(col).stream() if d.exists]
