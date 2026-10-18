"""MongoDB storage with an in-memory fallback (spec §13: keep the demo running if Mongo is down,
but report `persistent=False` so the UI never claims preferences were saved)."""

import logging
from copy import deepcopy
from typing import Any

from pymongo import AsyncMongoClient

from .config import settings

log = logging.getLogger(__name__)

COLLECTIONS = ["participants", "activities", "sessions", "robot_jobs", "feedback", "messages"]


class MemoryStore:
    persistent = False

    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {c: {} for c in COLLECTIONS}

    async def insert(self, coll: str, doc: dict) -> dict:
        self.data[coll][doc["_id"]] = deepcopy(doc)
        return doc

    async def get(self, coll: str, _id: str) -> dict | None:
        doc = self.data[coll].get(_id)
        return deepcopy(doc) if doc else None

    async def update(self, coll: str, _id: str, fields: dict[str, Any]) -> dict | None:
        doc = self.data[coll].get(_id)
        if doc is None:
            return None
        doc.update(deepcopy(fields))
        return deepcopy(doc)

    async def find(self, coll: str, filt: dict | None = None) -> list[dict]:
        filt = filt or {}
        return [deepcopy(d) for d in self.data[coll].values() if all(d.get(k) == v for k, v in filt.items())]

    async def delete_many(self, coll: str, filt: dict) -> int:
        ids = [d["_id"] for d in await self.find(coll, filt)]
        for i in ids:
            del self.data[coll][i]
        return len(ids)


class MongoStore:
    persistent = True

    def __init__(self, client: AsyncMongoClient) -> None:
        self.client = client
        self.db = client[settings.mongodb_db]

    async def insert(self, coll: str, doc: dict) -> dict:
        await self.db[coll].insert_one(doc)
        return doc

    async def get(self, coll: str, _id: str) -> dict | None:
        return await self.db[coll].find_one({"_id": _id})

    async def update(self, coll: str, _id: str, fields: dict[str, Any]) -> dict | None:
        return await self.db[coll].find_one_and_update({"_id": _id}, {"$set": fields}, return_document=True)

    async def find(self, coll: str, filt: dict | None = None) -> list[dict]:
        return await self.db[coll].find(filt or {}).to_list(length=500)

    async def delete_many(self, coll: str, filt: dict) -> int:
        return (await self.db[coll].delete_many(filt)).deleted_count


Store = MemoryStore | MongoStore


async def connect() -> Store:
    if not settings.mongodb_uri:
        log.warning("MONGODB_URI not set; using in-memory store (nothing persists)")
        return MemoryStore()
    try:
        client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        await client.admin.command("ping")
        store = MongoStore(client)
        await store.db["messages"].create_index("expiresAt", expireAfterSeconds=0)
        log.info("Connected to MongoDB database %r", settings.mongodb_db)
        return store
    except Exception as e:  # noqa: BLE001
        log.error("MongoDB unavailable (%s); falling back to in-memory store", e)
        return MemoryStore()
