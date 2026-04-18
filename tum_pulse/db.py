"""S3-backed persistent storage for TUM Pulse.

Key layout inside the bucket:
  deadlines/{md5(title|course|date|source)}.json   — idempotent per unique deadline
  profile/{key}.json                                — one blob per profile key
  content/{source}/{md5(source|url)}.json           — idempotent per scraped URL
  alerts/{utc_ts}_{uuid8}.json                      — one per alert event
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from tum_pulse.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    S3_BUCKET_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _md5(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _ts() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Low-level S3 client
# ---------------------------------------------------------------------------

class S3Store:
    """Thin boto3 wrapper — put / get / list / delete JSON objects."""

    def __init__(self, bucket: str = S3_BUCKET_NAME) -> None:
        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        kwargs: dict = {"Bucket": self.bucket}
        if AWS_REGION != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": AWS_REGION}
        try:
            self._s3.create_bucket(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in (
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            ):
                raise

    def put(self, key: str, data: Any) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False, default=str),
            ContentType="application/json",
        )

    def get(self, key: str) -> Optional[Any]:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp["Body"].read())
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def list_prefix(self, prefix: str) -> list[str]:
        paginator = self._s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=key)


# ---------------------------------------------------------------------------
# High-level memory API (drop-in for SQLiteMemory)
# ---------------------------------------------------------------------------

class S3Memory:
    """Persistent memory for TUM Pulse agents, backed by S3.

    Identical public interface to SQLiteMemory so agents can swap without changes.
    All writes are idempotent — re-saving the same logical record is a no-op.
    """

    def __init__(self, bucket: str = S3_BUCKET_NAME) -> None:
        self._store = S3Store(bucket)

    # ── deadlines ──────────────────────────────────────────────────────────────

    def save_deadline(
        self,
        title: str,
        course: str,
        deadline_date: str,
        source: str,
    ) -> str:
        key = f"deadlines/{_md5(title, course, deadline_date, source)}.json"
        self._store.put(
            key,
            {
                "id": key,
                "title": title,
                "course": course,
                "deadline_date": deadline_date,
                "source": source,
                "created_at": _ts(),
            },
        )
        return key

    def clear_deadlines(self, source: Optional[str] = None) -> int:
        """Delete all deadline objects, optionally filtered by source. Returns count deleted."""
        deleted = 0
        for key in self._store.list_prefix("deadlines/"):
            if source is not None:
                obj = self._store.get(key)
                if obj and obj.get("source") != source:
                    continue
            self._store.delete(key)
            deleted += 1
        return deleted

    def get_upcoming_deadlines(self, days: int = 7) -> list[dict]:
        today = datetime.utcnow().date()
        cutoff = today + timedelta(days=days)
        results: list[dict] = []
        for key in self._store.list_prefix("deadlines/"):
            obj = self._store.get(key)
            if obj is None:
                continue
            try:
                dl = datetime.strptime(obj["deadline_date"], "%Y-%m-%d").date()
                if today <= dl <= cutoff:
                    results.append(obj)
            except (ValueError, KeyError):
                pass
        return sorted(results, key=lambda x: x["deadline_date"])

    # ── student profile ────────────────────────────────────────────────────────

    def save_profile(self, key: str, value: Any) -> None:
        self._store.put(f"profile/{key}.json", {"key": key, "value": value})

    def get_profile(self, key: str) -> Optional[Any]:
        obj = self._store.get(f"profile/{key}.json")
        return obj["value"] if obj else None

    # ── scraped content ────────────────────────────────────────────────────────

    def save_content(self, source: str, url: str, content: str) -> str:
        key = f"content/{source}/{_md5(source, url)}.json"
        self._store.put(
            key,
            {
                "id": key,
                "source": source,
                "url": url,
                "content": content,
                "scraped_at": _ts(),
            },
        )
        return key

    def get_content_by_source(self, source: str) -> list[dict]:
        results: list[dict] = []
        for key in self._store.list_prefix(f"content/{source}/"):
            obj = self._store.get(key)
            if obj:
                results.append(obj)
        return sorted(results, key=lambda x: x.get("scraped_at", ""), reverse=True)

    # ── alerts ─────────────────────────────────────────────────────────────────

    def create_alert(self, message: str, deadline_date: str) -> str:
        key = f"alerts/{_ts()}_{uuid.uuid4().hex[:8]}.json"
        self._store.put(
            key,
            {
                "id": key,
                "message": message,
                "deadline_date": deadline_date,
                "sent": False,
                "created_at": _ts(),
            },
        )
        return key

    def get_pending_alerts(self) -> list[dict]:
        results: list[dict] = []
        for key in self._store.list_prefix("alerts/"):
            obj = self._store.get(key)
            if obj and not obj.get("sent"):
                results.append(obj)
        return sorted(results, key=lambda x: x.get("deadline_date", ""))

    def mark_alert_sent(self, alert_id: str) -> None:
        obj = self._store.get(alert_id)
        if obj:
            obj["sent"] = True
            self._store.put(alert_id, obj)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mem = S3Memory()
    k = mem.save_deadline("Exam Reg: Analysis 2", "Analysis 2", "2026-04-30", "test")
    print("Saved deadline key:", k)
    print("Upcoming (30d):", mem.get_upcoming_deadlines(30))
    mem.save_profile("name", "Max Mustermann")
    print("Profile name:", mem.get_profile("name"))
    print("Bucket:", S3_BUCKET_NAME)
