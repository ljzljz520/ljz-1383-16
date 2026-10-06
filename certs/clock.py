"""服务器时钟校正.

服务器本地时钟可能漂移。本模块维护一个持久化的偏移量(offset_ms),
所有状态判断与事件记录都使用校正后的时间, 并把当时使用的偏移量
写入事件, 便于审计与追溯重放。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone


class Clock:
    """带偏移校正的可注入时钟。"""

    def __init__(self, offset_ms: int = 0):
        self._offset_ms = int(offset_ms)

    @property
    def offset_ms(self) -> int:
        return self._offset_ms

    def set_offset_ms(self, offset_ms: int) -> None:
        self._offset_ms = int(offset_ms)

    def now(self) -> datetime:
        """校正后的当前 UTC 时间(aware)。"""
        epoch_ms = time.time() * 1000.0 + self._offset_ms
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """把任意 datetime 归一为 aware UTC。naive 视为 UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_instant(text: str) -> datetime:
    """解析 ISO 日期时间(可带偏移)为 aware UTC。"""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return to_utc(dt)


def iso(dt: datetime) -> str:
    """aware UTC -> 规范 ISO 字符串(秒级, Z 结尾)。"""
    return to_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")
