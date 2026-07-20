"""
Firestore-backed job store shared by BASIC and PRO analyzers.
Replaces in-memory _jobs dict so all Cloud Run instances share state.
"""
import os
import hashlib
import time
from datetime import datetime, timezone

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


def unset(col: str, job_id: str, fields: list[str] | tuple[str, ...]) -> None:
    """Remove selected fields without replacing the rest of a job document."""
    names = [str(field) for field in fields if str(field)]
    if not names:
        return
    collection = _col(col)
    if collection is None:
        job = _memory_jobs.get(col, {}).get(job_id)
        if job is not None:
            for name in names:
                job.pop(name, None)
        return
    collection.document(job_id).update({name: firestore.DELETE_FIELD for name in names})


def patch_if_status(col: str, job_id: str, expected_statuses: set[str] | tuple[str, ...], updates: dict) -> bool:
    """Atomically transition a job only if it still has an expected status."""
    expected = set(expected_statuses)
    collection = _col(col)
    if collection is None:
        job = _memory_jobs.get(col, {}).get(job_id)
        if job is None or job.get("status") not in expected:
            return False
        job.update(updates)
        return True

    reference = collection.document(job_id)
    transaction = _client.transaction()

    @firestore.transactional
    def _update(transaction):
        snapshot = reference.get(transaction=transaction)
        if not snapshot.exists or snapshot.to_dict().get("status") not in expected:
            return False
        transaction.update(reference, updates)
        return True

    try:
        return bool(_update(transaction))
    except Exception:
        return False


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


def find_by_field(col: str, field: str, value, limit: int = 10) -> list[dict]:
    """Find a small number of jobs by an equality field for durable deduplication."""
    max_items = max(1, int(limit))
    collection = _col(col)
    if collection is None:
        return [
            dict(job)
            for job in _memory_jobs.get(col, {}).values()
            if job.get(field) == value
        ][:max_items]
    query = collection.where(field, "==", value).limit(max_items)
    return [doc.to_dict() for doc in query.stream() if doc.exists]


def consume_window_quota(
    col: str,
    key: str,
    window_seconds: int,
    maximum: int,
    now: float | None = None,
) -> tuple[bool, int, int] | None:
    """Atomically consume a Firestore-backed fixed-window quota.

    Returns ``None`` when Firestore is unavailable so callers can fall back to
    an in-process limiter for local development. The counter document can be
    configured for Firestore TTL using its ``expiresAt`` field.
    """
    collection = _col(col)
    if collection is None:
        return None
    current_time = time.time() if now is None else float(now)
    bucket_start = int(current_time // window_seconds) * window_seconds
    retry_after = max(1, int(bucket_start + window_seconds - current_time))
    doc_id = hashlib.sha256(f"{key}:{bucket_start}".encode("utf-8")).hexdigest()
    reference = collection.document(doc_id)
    transaction = _client.transaction()

    @firestore.transactional
    def _update(transaction):
        snapshot = reference.get(transaction=transaction)
        current = snapshot.to_dict() if snapshot.exists else {}
        count = int(current.get("count") or 0)
        if count >= maximum:
            return False, count, retry_after
        transaction.set(
            reference,
            {
                "count": count + 1,
                "windowStart": bucket_start,
                "expiresAt": datetime.fromtimestamp(bucket_start + window_seconds, timezone.utc),
                "updatedAt": current_time,
            },
            merge=True,
        )
        return True, count + 1, retry_after

    try:
        return _update(transaction)
    except Exception:
        # Credentials, emulator, or transient Firestore failures should not
        # make local development unusable; the caller falls back to memory.
        return None
