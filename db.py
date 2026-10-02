"""Хранилище очередей на SQLite.

У каждого предмета своя очередь — на ближайшую (или идущую сейчас) практику.
Когда практика заканчивается (у сдвоенной — после второй пары), записи,
сделанные до её конца, удаляются: дальше идёт запись на следующую практику.

Правило приоритета внутри предмета: сначала тот, кого уже вызвали сдавать,
затем ожидающие по теме (у предметов без тем она всегда 0), потом по номеру
работы (меньший — раньше), а при равенстве — по времени записи.
"""
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Callable

import aiosqlite

from subjects import RENAMED

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id     INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS queue (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,  -- порядок записи
    tg_id     INTEGER NOT NULL REFERENCES users(tg_id),
    subject   TEXT    NOT NULL,
    topic     INTEGER NOT NULL DEFAULT 0,         -- 0 = у предмета нет тем
    work_num  INTEGER NOT NULL,
    called    INTEGER NOT NULL DEFAULT 0,         -- 1 = сейчас сдаёт
    joined_ts INTEGER NOT NULL DEFAULT 0,         -- когда записался (unix-время)
    UNIQUE (tg_id, subject)                       -- одно место на предмет
);
"""

WAITING_ORDER = "ORDER BY topic, work_num, id"
QUEUE_ORDER = "ORDER BY q.called DESC, q.topic, q.work_num, q.id"


class JoinResult(Enum):
    OK = auto()
    ALREADY_IN_QUEUE = auto()


@dataclass
class Entry:
    tg_id: int
    full_name: str
    subject: str
    topic: int
    work_num: int
    called: bool


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        # Хендлеры aiogram выполняются конкурентно — все изменения через один замок,
        # чтобы «проверил → записал» не перемешивалось между пользователями.
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Подтянуть базу, созданную старыми версиями бота."""
        cur = await self._conn.execute("PRAGMA table_info(queue)")
        columns = {row[1] for row in await cur.fetchall()}
        if "joined_ts" not in columns:
            await self._conn.execute(
                "ALTER TABLE queue ADD COLUMN joined_ts INTEGER NOT NULL DEFAULT 0"
            )
            # старым записям ставим «записались сейчас» — очистятся после ближайшей пары
            await self._conn.execute("UPDATE queue SET joined_ts = ?", (int(time.time()),))
        for old_name, new_name in RENAMED.items():  # переименованные предметы
            await self._conn.execute(
                "UPDATE queue SET subject = ? WHERE subject = ?", (new_name, old_name)
            )

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    # ---------- пользователи ----------

    async def upsert_user(self, tg_id: int, full_name: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO users(tg_id, full_name) VALUES (?, ?) "
                "ON CONFLICT(tg_id) DO UPDATE SET full_name = excluded.full_name",
                (tg_id, full_name),
            )
            await self._conn.commit()

    # ---------- очередь ----------

    async def get_queue(self, subject: str) -> list[Entry]:
        cur = await self._conn.execute(
            "SELECT q.tg_id, u.full_name, q.subject, q.topic, q.work_num, q.called "
            "FROM queue q JOIN users u USING(tg_id) "
            f"WHERE q.subject = ? {QUEUE_ORDER}",
            (subject,),
        )
        return [
            Entry(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in await cur.fetchall()
        ]

    async def position(self, tg_id: int, subject: str) -> tuple[int, Entry] | None:
        for i, entry in enumerate(await self.get_queue(subject), start=1):
            if entry.tg_id == tg_id:
                return i, entry
        return None

    async def join(self, tg_id: int, subject: str, topic: int, work_num: int) -> JoinResult:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT 1 FROM queue WHERE tg_id = ? AND subject = ?", (tg_id, subject)
            )
            if await cur.fetchone():
                return JoinResult.ALREADY_IN_QUEUE
            await self._conn.execute(
                "INSERT INTO queue(tg_id, subject, topic, work_num, joined_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (tg_id, subject, topic, work_num, int(time.time())),
            )
            await self._conn.commit()
            return JoinResult.OK

    async def leave(self, tg_id: int, subject: str) -> bool:
        async with self._lock:
            cur = await self._conn.execute(
                "DELETE FROM queue WHERE tg_id = ? AND subject = ?", (tg_id, subject)
            )
            await self._conn.commit()
            return cur.rowcount > 0

    async def purge(self, is_expired: Callable[[str, datetime], bool]) -> dict[str, int]:
        """Удалить записи на уже прошедшие пары.

        is_expired(предмет, когда записался) решает, закончилась ли та пара.
        Возвращает {предмет: сколько записей удалено}.
        """
        async with self._lock:
            cur = await self._conn.execute("SELECT id, subject, joined_ts FROM queue")
            expired = [
                (row_id, subject)
                for row_id, subject, ts in await cur.fetchall()
                if is_expired(subject, datetime.fromtimestamp(ts).astimezone())
            ]
            removed: dict[str, int] = {}
            for row_id, subject in expired:
                await self._conn.execute("DELETE FROM queue WHERE id = ?", (row_id,))
                removed[subject] = removed.get(subject, 0) + 1
            if expired:
                await self._conn.commit()
            return removed

    async def _call_next_unlocked(self, subject: str) -> Entry | None:
        cur = await self._conn.execute(
            f"SELECT id FROM queue WHERE subject = ? AND called = 0 {WAITING_ORDER} LIMIT 1",
            (subject,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await self._conn.execute("UPDATE queue SET called = 1 WHERE id = ?", row)
        await self._conn.commit()
        return (await self.get_queue(subject))[0]

    async def call_next(self, subject: str) -> tuple[Entry | None, Entry | None]:
        """Вызвать следующего. Возвращает (уже_вызванный, новый_вызванный)."""
        async with self._lock:
            queue = await self.get_queue(subject)
            if queue and queue[0].called:
                return queue[0], None
            return None, await self._call_next_unlocked(subject)

    async def finish_current(self, subject: str) -> tuple[Entry | None, Entry | None]:
        """Убрать того, кто сдаёт, и вызвать следующего. Возвращает (закончивший, следующий)."""
        async with self._lock:
            queue = await self.get_queue(subject)
            if not queue or not queue[0].called:
                return None, None
            current = queue[0]
            await self._conn.execute(
                "DELETE FROM queue WHERE tg_id = ? AND subject = ?",
                (current.tg_id, subject),
            )
            await self._conn.commit()
            return current, await self._call_next_unlocked(subject)

    async def my_queues(self, tg_id: int) -> list[str]:
        cur = await self._conn.execute(
            "SELECT subject FROM queue WHERE tg_id = ?", (tg_id,)
        )
        return [r[0] for r in await cur.fetchall()]
