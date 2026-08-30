"""
metupy_core.database
~~~~~~~~~~~~~~~

Lightweight database layer using Peewee ORM.
All models use UUID v4 as primary key — consistent across system & user data.
Default: SQLite (embedded, zero-config, works everywhere).

Usage:
    from metupy.database import db, Content
    content = Content.get(Content.uuid == "550e8400-e29b-41d4-a716-446655440000")
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

from peewee import (
    SqliteDatabase,
    Model,
    CharField,
    TextField,
    IntegerField,
    BooleanField,
    FloatField,
    DateTimeField,
    ForeignKeyField,
    CompositeKey,
    fn,
    chunked,
)

from .logging import log


__all__ = [
    "db",
    "Content",
    "Asset",
    "Setting",
    "Cache",
    "Tag",
    "ContentTag",
    "init_database",
    "sync_content_directory",
    "query_content",
    "generate_uuid",
]


# ─── Helpers ───

def generate_uuid() -> str:
    """Generate UUID v4 string — used as primary key for all models."""
    return str(uuid.uuid4())


# ─── Database Instance ───

DEFAULT_DB_PATH = Path.cwd() / ".metupy" / "db.sqlite3"
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

db = SqliteDatabase(
    str(DEFAULT_DB_PATH),
    pragmas={
        "journal_mode": "wal",
        "cache_size": -1024 * 32,
        "foreign_keys": "ON",
        "synchronous": "NORMAL",
    },
)


# ─── Base Model ───

class BaseModel(Model):
    """Base class for all Metupy models — uses UUID v4 as primary key."""

    uuid = CharField(max_length=36, primary_key=True, default=generate_uuid)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        database = db
        legacy_table_names = False


# ─── Core Models ───

class Content(BaseModel):
    """Stores pages, posts, documents — all content files."""

    slug = CharField(max_length=255, unique=True, index=True)
    title = CharField(max_length=500, null=True)
    description = TextField(null=True)
    content_html = TextField(null=True)
    content_raw = TextField(null=True)
    format = CharField(max_length=50)
    path = CharField(max_length=500, unique=True, index=True)

    metadata = TextField(default="{}")
    is_published = BooleanField(default=True, index=True)
    is_draft = BooleanField(default=False, index=True)
    priority = FloatField(default=0.5)

    published_at = DateTimeField(null=True, index=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "content"
        indexes = (
            ("is_published", "published_at"),
            ("format", "is_published"),
        )

    def get_metadata(self) -> Dict[str, Any]:
        try:
            return json.loads(self.metadata)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_metadata(self, data: Dict[str, Any]) -> None:
        self.metadata = json.dumps(data, ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "content_html": self.content_html,
            "format": self.format,
            "path": self.path,
            "metadata": self.get_metadata(),
            "is_published": self.is_published,
            "is_draft": self.is_draft,
            "priority": self.priority,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Tag(BaseModel):
    """Tags for content categorization."""

    name = CharField(max_length=100, unique=True, index=True)
    slug = CharField(max_length=100, unique=True)

    class Meta:
        table_name = "tags"

    @classmethod
    def get_or_create(cls, name: str) -> "Tag":
        slug = name.lower().strip().replace(" ", "-")
        obj, _ = cls.get_or_create(slug=slug, defaults={"name": name})
        return obj

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "slug": self.slug,
            "created_at": self.created_at.isoformat(),
        }

class ContentTag(BaseModel):
    content = ForeignKeyField(Content, backref="content_tags", on_delete="CASCADE")
    tag = ForeignKeyField(Tag, backref="content_tags", on_delete="CASCADE")

    class Meta:
        table_name = "content_tags"
        primary_key = CompositeKey("content", "tag")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_uuid": self.content_id,
            "tag_uuid": self.tag_id,
            "created_at": self.created_at.isoformat(),
        }

# ─── Setting ───
    @classmethod
    def set_value(cls, key: str, value: Any) -> None:
        stored = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        obj, _ = cls.get_or_create(key=key, defaults={"value": stored})
        if obj.value != stored:
            obj.value = stored
            obj.updated_at = datetime.utcnow()
            obj.save()

# ─── sync_content_directory ───
def sync_content_directory(content_dir: Path) -> Dict[str, int]:
    from .readers import read_and_parse, is_supported

    stats = {"added": 0, "updated": 0, "skipped": 0, "errors": 0}
    patterns = ["*.pym", "*.md", "*.rst", "*.py"]
    files = []
    for pat in patterns:
        files.extend(content_dir.rglob(pat))

    for file_path in files:
        if not is_supported(file_path):
            continue
        try:
            parsed = read_and_parse(file_path)
            meta = parsed.metadata
            slug = meta.get("slug", file_path.stem)
            
            # Data
            data = {
                "slug": slug,
                "title": meta.get("title", file_path.stem),
                "description": meta.get("description", ""),
                "content_html": parsed.content,
                "content_raw": parsed.raw_content,
                "format": parsed.format,
                "path": str(file_path.relative_to(content_dir.parent)),
                "metadata": json.dumps(meta, ensure_ascii=False),
                "is_published": meta.get("published", True),
                "is_draft": meta.get("draft", False),
                "priority": meta.get("weight", 0.5),
                "published_at": meta.get("date"),
                "updated_at": datetime.utcnow(),
            }

            existing = Content.select().where(Content.slug == slug).first()
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
                existing.save()
                stats["updated"] += 1
                # Hapus tag lama dengan benar
                ContentTag.delete().where(ContentTag.content == existing).execute()
                content_obj = existing
            else:
                content_obj = Content.create(**data)
                stats["added"] += 1

            # Tambah tag baru
            tags = meta.get("tags", [])
            if isinstance(tags, list):
                for tag_name in tags:
                    tag = Tag.get_or_create(tag_name)
                    ContentTag.get_or_create(content=content_obj, tag=tag)

        except Exception as e:
            log.error(f"Sync error {file_path}: {e}")
            stats["errors"] += 1

    log.info(f"Content sync complete: {stats}")
    return stats


class Asset(BaseModel):
    """Static assets: images, CSS, JS, fonts."""

    path = CharField(max_length=500, unique=True, index=True)
    mime_type = CharField(max_length=100)
    size = IntegerField()
    hash = CharField(max_length=64, null=True)
    uploaded_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "assets"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "path": self.path,
            "mime_type": self.mime_type,
            "size": self.size,
            "hash": self.hash,
            "uploaded_at": self.uploaded_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }


class Setting(BaseModel):
    """Site configuration & global settings."""

    key = CharField(max_length=100, unique=True, index=True)
    value = TextField(null=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "settings"

    @classmethod
    def get_value(cls, key: str, default: Any = None) -> Any:
        try:
            obj = cls.get(cls.key == key)
            if obj.value is None:
                return default
            try:
                return json.loads(obj.value)
            except (json.JSONDecodeError, TypeError):
                return obj.value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_value(cls, key: str, value: Any) -> None:
        stored = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        cls.replace(uuid=generate_uuid(), key=key, value=stored, updated_at=datetime.utcnow()).execute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }


class Cache(BaseModel):
    """Build cache & rendered content cache."""

    key = CharField(max_length=255, unique=True, index=True)
    value = TextField(null=True)
    etag = CharField(max_length=64, null=True)
    expires_at = DateTimeField(index=True)

    class Meta:
        table_name = "cache"

    @classmethod
    def get_valid(cls, key: str) -> Optional[Any]:
        try:
            obj = cls.get((cls.key == key) & (cls.expires_at > datetime.utcnow()))
            return json.loads(obj.value) if obj.value else None
        except cls.DoesNotExist:
            return None

    @classmethod
    def set_ttl(cls, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        from datetime import timedelta
        expires = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        cls.replace(
            uuid=generate_uuid(),
            key=key,
            value=json.dumps(value, ensure_ascii=False),
            expires_at=expires,
        ).execute()

    @classmethod
    def clear_expired(cls) -> int:
        return cls.delete().where(cls.expires_at < datetime.utcnow()).execute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "key": self.key,
            "value": self.value,
            "etag": self.etag,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }


# ─── Database Initialization ───

def init_database(db_path: Optional[Path | str] = None) -> None:
    """Initialize database connection and create tables."""
    global db

    if db_path:
        db_path = Path(db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db.init(str(db_path))

    if db.is_closed():
        db.connect()

    db.create_tables([Content, Tag, ContentTag, Asset, Setting, Cache], safe=True)
    log.debug(f"Database initialized: {db.database}")


def close_database() -> None:
    """Close database connection gracefully."""
    if not db.is_closed():
        db.close()
        log.debug("Database connection closed")


@contextmanager
def db_transaction():
    """Context manager for safe transactions."""
    with db.atomic():
        yield


# ─── Content Sync & Query ───

def sync_content_directory(content_dir: Path) -> Dict[str, int]:
    """Scan content directory and sync to database."""
    from .readers import read_and_parse, is_supported

    stats = {"added": 0, "updated": 0, "skipped": 0, "errors": 0}

    patterns = ["*.pym", "*.md", "*.rst", "*.py"]
    files = []
    for pat in patterns:
        files.extend(content_dir.rglob(pat))

    for file_path in files:
        if not is_supported(file_path):
            continue

        try:
            parsed = read_and_parse(file_path)
            meta = parsed.metadata

            slug = meta.get("slug", file_path.stem)
            existing = Content.select().where(Content.slug == slug).first()

            data = {
                "slug": slug,
                "title": meta.get("title", file_path.stem),
                "description": meta.get("description", ""),
                "content_html": parsed.content,
                "content_raw": parsed.raw_content,
                "format": parsed.format,
                "path": str(file_path.relative_to(content_dir.parent)),
                "metadata": json.dumps(meta, ensure_ascii=False),
                "is_published": meta.get("published", True),
                "is_draft": meta.get("draft", False),
                "priority": meta.get("weight", 0.5),
                "published_at": meta.get("date"),
                "updated_at": datetime.utcnow(),
            }

            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
                existing.save()
                stats["updated"] += 1
            else:
                Content.create(**data)
                stats["added"] += 1

            ContentTag.delete().where(ContentTag.content == existing.uuid if existing else None).execute()
            tags = meta.get("tags", [])
            if isinstance(tags, list):
                content_obj = Content.get(Content.slug == slug)
                for tag_name in tags:
                    tag = Tag.get_or_create(tag_name)
                    ContentTag.create(content=content_obj, tag=tag)

        except Exception as e:
            log.error(f"Sync error {file_path}: {e}")
            stats["errors"] += 1

    log.info(f"Content sync complete: {stats}")
    return stats


def query_content(
    limit: int = 50,
    offset: int = 0,
    published_only: bool = True,
    draft: Optional[bool] = None,
    format: Optional[str] = None,
    tag: Optional[str] = None,
    order_by: str = "published_at DESC",
) -> List[Dict[str, Any]]:
    """Query content with filters — returns list of dictionaries."""
    query = Content.select()

    if published_only:
        query = query.where(Content.is_published == True)
    if draft is not None:
        query = query.where(Content.is_draft == draft)
    if format:
        query = query.where(Content.format == format)
    if tag:
        query = (
            query
            .join(ContentTag)
            .join(Tag)
            .where(Tag.slug == tag.lower())
        )

    if order_by == "published_at DESC":
        query = query.order_by(Content.published_at.desc(), Content.created_at.desc())
    elif order_by == "priority":
        query = query.order_by(Content.priority.desc())
    elif order_by == "title":
        query = query.order_by(Content.title)

    query = query.limit(limit).offset(offset)
    return [row.to_dict() for row in query]


# ─── Maintenance ───

def vacuum() -> None:
    """Optimize database file size."""
    if not db.is_closed():
        db.execute_sql("VACUUM")
        log.info("Database optimized")


def clear_all_cache() -> None:
    """Clear all cache entries."""
    Cache.delete().execute()
    log.info("Cache cleared")
