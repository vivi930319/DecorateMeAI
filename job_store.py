"""
Firestore-backed job store shared by BASIC and PRO analyzers.
Replaces in-memory _jobs dict so all Cloud Run instances share state.
"""
import os

try:
    from google.cloud import firestore
except ImportError:
    firestore = None

_client = None
_memory_jobs: dict[str, dict[str, dict]] = {}
DEFAULT_SCAN_LIMIT = int(os.getenv("JOB_STORE_SCAN_LIMIT", "500"))


def _col(collection: str):
    if firestore is None:
        return None
    global _client
    if _client is None:
        _client = firestore.Client(
            project=os.getenv("GOOGLE_CLOUD_PROJECT", "decorate-me")
        )
    return _client.collection(collection)


def create(col: str, job_id: str, data: dict) -> None:
    collection = _col(col)
    if collection is None:
        _memory_jobs.setdefault(col, {})[job_id] = dict(data)
        return
    collection.document(job_id).set(data)


def get(col: str, job_id: str) -> dict | None:
    collection = _col(col)
    if collection is None:
        job = _memory_jobs.get(col, {}).get(job_id)
        return dict(job) if job is not None else None
    doc = collection.document(job_id).get()
    return doc.to_dict() if doc.exists else None


def patch(col: str, job_id: str, updates: dict) -> None:
    collection = _col(col)
    if collection is None:
        _memory_jobs.setdefault(col, {}).setdefault(job_id, {}).update(updates)
        return
    collection.document(job_id).update(updates)


def delete(col: str, job_id: str) -> None:
    collection = _col(col)
    if collection is None:
        _memory_jobs.get(col, {}).pop(job_id, None)
        return
    collection.document(job_id).delete()


def all_jobs(col: str, limit: int | None = None) -> list[dict]:
    max_items = DEFAULT_SCAN_LIMIT if limit is None else limit
    collection = _col(col)
    if collection is None:
        jobs = [dict(job) for job in _memory_jobs.get(col, {}).values()]
        return jobs[:max_items] if max_items else jobs
    query = collection.limit(max_items) if max_items else collection
    return [d.to_dict() for d in query.stream() if d.exists]
