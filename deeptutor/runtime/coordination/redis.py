"""Redis Streams coordinator for multiple Uvicorn worker processes."""

from __future__ import annotations

import json
import time
from typing import Any

from .types import BackgroundCommand, LeaderLease, TurnCommand, TurnLease


class CoordinationUnavailableError(RuntimeError):
    """Raised when Redis cannot uphold the runtime coordination contract."""


_ACQUIRE_TURN_LUA = """
local session_key = KEYS[1]
local turn_key = KEYS[2]
local fence_key = KEYS[3]
local leases_key = KEYS[4]
local turn_id = ARGV[1]
local session_id = ARGV[2]
local owner_id = ARGV[3]
local ttl_ms = tonumber(ARGV[4])
if redis.call('EXISTS', session_key) == 1 and redis.call('PTTL', session_key) > 0 then
  return nil
end
redis.call('DEL', session_key)
local token = redis.call('INCR', fence_key)
local now = redis.call('TIME')
local expires = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000) + ttl_ms
redis.call('HSET', session_key, 'turn_id', turn_id, 'session_id', session_id,
  'owner_id', owner_id, 'fencing_token', token)
redis.call('HSET', turn_key, 'turn_id', turn_id, 'session_id', session_id,
  'owner_id', owner_id, 'fencing_token', token)
redis.call('PEXPIRE', session_key, ttl_ms)
redis.call('PEXPIRE', turn_key, ttl_ms)
redis.call('ZADD', leases_key, expires, turn_id)
return {token, expires}
"""

_RENEW_TURN_LUA = """
local turn_key = KEYS[1]
local session_key = KEYS[2]
local leases_key = KEYS[3]
local turn_id = ARGV[1]
local session_id = ARGV[2]
local owner_id = ARGV[3]
local token = ARGV[4]
local ttl_ms = tonumber(ARGV[5])
if redis.call('HGET', turn_key, 'owner_id') ~= owner_id or
   redis.call('HGET', turn_key, 'fencing_token') ~= token or
   redis.call('HGET', turn_key, 'session_id') ~= session_id or
   redis.call('HGET', session_key, 'turn_id') ~= turn_id then
  return nil
end
local now = redis.call('TIME')
local expires = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000) + ttl_ms
redis.call('PEXPIRE', turn_key, ttl_ms)
redis.call('PEXPIRE', session_key, ttl_ms)
redis.call('ZADD', leases_key, expires, turn_id)
return expires
"""

_RELEASE_TURN_LUA = """
local turn_key = KEYS[1]
local session_key = KEYS[2]
local leases_key = KEYS[3]
local turn_id = ARGV[1]
local owner_id = ARGV[2]
local token = ARGV[3]
if redis.call('HGET', turn_key, 'owner_id') ~= owner_id or
   redis.call('HGET', turn_key, 'fencing_token') ~= token then
  return 0
end
if redis.call('HGET', session_key, 'turn_id') == turn_id then
  redis.call('DEL', session_key)
end
redis.call('DEL', turn_key)
redis.call('ZREM', leases_key, turn_id)
return 1
"""

_PUBLISH_EVENT_LUA = """
local stream_key = KEYS[1]
local payload_key = KEYS[2]
local seq_key = KEYS[3]
local requested_seq = tonumber(ARGV[1])
local raw_payload = ARGV[2]
local turn_id = ARGV[3]
local retention = tonumber(ARGV[4])
local seq
if requested_seq > 0 then
  seq = requested_seq
  local current = tonumber(redis.call('GET', seq_key) or '0')
  if seq > current then redis.call('SET', seq_key, seq) end
else
  seq = redis.call('INCR', seq_key)
end
local existing = redis.call('HGET', payload_key, tostring(seq))
if existing then return {-1, existing} end
local payload = cjson.decode(raw_payload)
payload['seq'] = seq
if payload['turn_id'] == nil or payload['turn_id'] == '' then payload['turn_id'] = turn_id end
local encoded = cjson.encode(payload)
redis.call('HSET', payload_key, tostring(seq), encoded)
redis.call('XADD', stream_key, '*', 'seq', tostring(seq), 'payload', encoded)
redis.call('EXPIRE', stream_key, retention)
redis.call('EXPIRE', payload_key, retention)
redis.call('EXPIRE', seq_key, retention)
return {seq, encoded}
"""

_SUBMIT_COMMAND_LUA = """
local stream_key = KEYS[1]
local dedupe_key = KEYS[2]
local retention = tonumber(ARGV[1])
local payload = ARGV[2]
if not redis.call('SET', dedupe_key, '1', 'EX', retention, 'NX') then return nil end
local stream_id = redis.call('XADD', stream_key, '*', 'payload', payload)
redis.call('EXPIRE', stream_key, retention)
return stream_id
"""

_ACQUIRE_LEADER_LUA = """
local leader_key = KEYS[1]
local fence_key = KEYS[2]
local owner_id = ARGV[1]
local ttl_ms = tonumber(ARGV[2])
if redis.call('EXISTS', leader_key) == 1 and redis.call('PTTL', leader_key) > 0 then
  return nil
end
redis.call('DEL', leader_key)
local token = redis.call('INCR', fence_key)
local now = redis.call('TIME')
local expires = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000) + ttl_ms
redis.call('HSET', leader_key, 'owner_id', owner_id, 'fencing_token', token)
redis.call('PEXPIRE', leader_key, ttl_ms)
return {token, expires}
"""

_RENEW_LEADER_LUA = """
local leader_key = KEYS[1]
local owner_id = ARGV[1]
local token = ARGV[2]
local ttl_ms = tonumber(ARGV[3])
if redis.call('HGET', leader_key, 'owner_id') ~= owner_id or
   redis.call('HGET', leader_key, 'fencing_token') ~= token then
  return nil
end
local now = redis.call('TIME')
local expires = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000) + ttl_ms
redis.call('PEXPIRE', leader_key, ttl_ms)
return expires
"""

_RELEASE_LEADER_LUA = """
if redis.call('HGET', KEYS[1], 'owner_id') ~= ARGV[1] or
   redis.call('HGET', KEYS[1], 'fencing_token') ~= ARGV[2] then
  return 0
end
redis.call('DEL', KEYS[1])
return 1
"""

_ACK_BACKGROUND_COMMAND_LUA = """
local leader_key = KEYS[1]
local cursor_key = KEYS[2]
local stream_id = ARGV[1]
local owner_id = ARGV[2]
local token = ARGV[3]
if owner_id ~= '' and (
   redis.call('HGET', leader_key, 'owner_id') ~= owner_id or
   redis.call('HGET', leader_key, 'fencing_token') ~= token) then
  return 0
end
redis.call('SET', cursor_key, stream_id)
return 1
"""


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class RedisCoordinator:
    mode = "redis"

    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "deeptutor",
        lease_ttl_seconds: float = 30.0,
        stream_retention_seconds: int = 86_400,
        client: Any | None = None,
    ) -> None:
        if not redis_url and client is None:
            raise ValueError("redis_url is required for Redis coordination")
        self.redis_url = redis_url
        self.key_prefix = key_prefix.strip(":") or "deeptutor"
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.stream_retention_seconds = max(60, int(stream_retention_seconds))
        self._owns_client = client is None
        if client is None:
            from redis.asyncio import Redis  # type: ignore[import-untyped]

            client = Redis.from_url(redis_url, decode_responses=False)
        self.client = client

    def _key(self, *parts: str) -> str:
        return ":".join((self.key_prefix, *parts))

    @property
    def _ttl_ms(self) -> int:
        return max(1, round(self.lease_ttl_seconds * 1000))

    async def acquire_turn(self, turn_id: str, session_id: str, owner_id: str) -> TurnLease | None:
        try:
            result = await self.client.eval(
                _ACQUIRE_TURN_LUA,
                4,
                self._key("lease", "session", session_id),
                self._key("lease", "turn", turn_id),
                self._key("fence", "turn"),
                self._key("leases", "turns"),
                turn_id,
                session_id,
                owner_id,
                self._ttl_ms,
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis turn lease acquisition failed") from exc
        if not result:
            return None
        return TurnLease(
            turn_id,
            session_id,
            owner_id,
            int(result[0]),
            int(result[1]) / 1000,
        )

    async def renew_turn(self, lease: TurnLease) -> TurnLease | None:
        try:
            expires = await self.client.eval(
                _RENEW_TURN_LUA,
                3,
                self._key("lease", "turn", lease.turn_id),
                self._key("lease", "session", lease.session_id),
                self._key("leases", "turns"),
                lease.turn_id,
                lease.session_id,
                lease.owner_id,
                lease.fencing_token,
                self._ttl_ms,
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis turn lease renewal failed") from exc
        return replace_lease_expiry(lease, expires) if expires else None

    async def release_turn(self, lease: TurnLease) -> bool:
        try:
            released = await self.client.eval(
                _RELEASE_TURN_LUA,
                3,
                self._key("lease", "turn", lease.turn_id),
                self._key("lease", "session", lease.session_id),
                self._key("leases", "turns"),
                lease.turn_id,
                lease.owner_id,
                lease.fencing_token,
            )
            return bool(released)
        except Exception as exc:
            raise CoordinationUnavailableError("Redis turn lease release failed") from exc

    async def get_lease(self, turn_id: str) -> TurnLease | None:
        key = self._key("lease", "turn", turn_id)
        try:
            values, ttl = await self.client.hgetall(key), await self.client.pttl(key)
        except Exception as exc:
            raise CoordinationUnavailableError("Redis turn lease lookup failed") from exc
        if not values or int(ttl) <= 0:
            return None
        decoded = {_decode(key): _decode(value) for key, value in values.items()}
        return TurnLease(
            turn_id=decoded.get("turn_id", turn_id),
            session_id=decoded.get("session_id", ""),
            owner_id=decoded.get("owner_id", ""),
            fencing_token=int(decoded.get("fencing_token", 0)),
            expires_at=time.time() + int(ttl) / 1000,
        )

    async def list_expired_turn_ids(self) -> list[str]:
        try:
            turn_ids = await self.client.zrangebyscore(
                self._key("leases", "turns"), "-inf", int(time.time() * 1000)
            )
            expired: list[str] = []
            for raw_turn_id in turn_ids:
                turn_id = _decode(raw_turn_id)
                if not await self.client.exists(self._key("lease", "turn", turn_id)):
                    expired.append(turn_id)
            return sorted(expired)
        except Exception as exc:
            raise CoordinationUnavailableError("Redis recovery scan failed") from exc

    async def acknowledge_expired_turn(self, turn_id: str) -> None:
        try:
            await self.client.zrem(self._key("leases", "turns"), turn_id)
        except Exception as exc:
            raise CoordinationUnavailableError("Redis recovery acknowledgement failed") from exc

    async def publish_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        requested_seq = int(event.get("seq") or 0)
        try:
            result = await self.client.eval(
                _PUBLISH_EVENT_LUA,
                3,
                self._key("events", turn_id),
                self._key("event_payloads", turn_id),
                self._key("event_seq", turn_id),
                requested_seq,
                json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str),
                turn_id,
                self.stream_retention_seconds,
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis event publication failed") from exc
        persisted = json.loads(_decode(result[1]))
        if int(result[0]) == -1:
            candidate = dict(event)
            candidate["turn_id"] = candidate.get("turn_id") or turn_id
            candidate["seq"] = requested_seq
            if candidate != persisted:
                raise ValueError(f"Turn event conflict: {turn_id} seq={requested_seq}")
        return persisted

    async def read_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        try:
            rows = await self.client.xrange(self._key("events", turn_id), min="-", max="+")
        except Exception as exc:
            raise CoordinationUnavailableError("Redis event replay failed") from exc
        events: list[dict[str, Any]] = []
        for _stream_id, fields in rows:
            decoded = {_decode(key): _decode(value) for key, value in fields.items()}
            if int(decoded.get("seq", 0)) > max(0, int(after_seq)):
                events.append(json.loads(decoded["payload"]))
        events.sort(key=lambda event: int(event["seq"]))
        return events

    async def submit_command(
        self,
        turn_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> TurnCommand | None:
        command = TurnCommand.create(turn_id, kind, payload, command_id=command_id)
        encoded = json.dumps(
            {
                "command_id": command.command_id,
                "turn_id": command.turn_id,
                "kind": command.kind,
                "payload": command.payload,
                "created_at": command.created_at,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        try:
            stream_id = await self.client.eval(
                _SUBMIT_COMMAND_LUA,
                2,
                self._key("commands", turn_id),
                self._key("command_dedupe", command.command_id),
                self.stream_retention_seconds,
                encoded,
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis command submission failed") from exc
        return command if stream_id else None

    async def read_commands(
        self, turn_id: str, after_id: str = "0-0"
    ) -> list[tuple[str, TurnCommand]]:
        minimum = "-" if after_id == "0-0" else f"({after_id}"
        try:
            rows = await self.client.xrange(self._key("commands", turn_id), min=minimum, max="+")
        except Exception as exc:
            raise CoordinationUnavailableError("Redis command replay failed") from exc
        commands: list[tuple[str, TurnCommand]] = []
        for raw_stream_id, fields in rows:
            decoded = {_decode(key): _decode(value) for key, value in fields.items()}
            payload = json.loads(decoded["payload"])
            commands.append(
                (
                    _decode(raw_stream_id),
                    TurnCommand(
                        command_id=payload["command_id"],
                        turn_id=payload["turn_id"],
                        kind=payload["kind"],
                        payload=payload.get("payload") or {},
                        created_at=float(payload["created_at"]),
                    ),
                )
            )
        return commands

    async def submit_background_command(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> BackgroundCommand | None:
        command = BackgroundCommand.create(kind, payload, command_id=command_id)
        encoded = json.dumps(
            {
                "command_id": command.command_id,
                "kind": command.kind,
                "payload": command.payload,
                "created_at": command.created_at,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        try:
            stream_id = await self.client.eval(
                _SUBMIT_COMMAND_LUA,
                2,
                self._key("commands", "background"),
                self._key("command_dedupe", command.command_id),
                self.stream_retention_seconds,
                encoded,
            )
        except Exception as exc:
            raise CoordinationUnavailableError(
                "Redis background command submission failed"
            ) from exc
        return command if stream_id else None

    async def read_background_commands(
        self, after_id: str = "0-0"
    ) -> list[tuple[str, BackgroundCommand]]:
        try:
            persisted = await self.client.get(self._key("commands", "background_cursor"))
            cursor = _decode(persisted) if persisted else "0-0"
            minimum_id = cursor if after_id == "0-0" else after_id
            minimum = "-" if minimum_id == "0-0" else f"({minimum_id}"
            rows = await self.client.xrange(
                self._key("commands", "background"), min=minimum, max="+"
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis background command replay failed") from exc
        commands: list[tuple[str, BackgroundCommand]] = []
        for raw_stream_id, fields in rows:
            decoded = {_decode(key): _decode(value) for key, value in fields.items()}
            payload = json.loads(decoded["payload"])
            commands.append(
                (
                    _decode(raw_stream_id),
                    BackgroundCommand(
                        command_id=payload["command_id"],
                        kind=payload["kind"],
                        payload=payload.get("payload") or {},
                        created_at=float(payload["created_at"]),
                    ),
                )
            )
        return commands

    async def acknowledge_background_command(
        self, stream_id: str, lease: LeaderLease | None = None
    ) -> bool:
        try:
            acknowledged = await self.client.eval(
                _ACK_BACKGROUND_COMMAND_LUA,
                2,
                self._key("lease", "leader"),
                self._key("commands", "background_cursor"),
                stream_id,
                lease.owner_id if lease is not None else "",
                lease.fencing_token if lease is not None else "",
            )
        except Exception as exc:
            raise CoordinationUnavailableError(
                "Redis background command acknowledgement failed"
            ) from exc
        return bool(acknowledged)

    async def acquire_leader(self, owner_id: str) -> LeaderLease | None:
        try:
            result = await self.client.eval(
                _ACQUIRE_LEADER_LUA,
                2,
                self._key("lease", "leader"),
                self._key("fence", "leader"),
                owner_id,
                self._ttl_ms,
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis leader acquisition failed") from exc
        if not result:
            return None
        return LeaderLease(owner_id, int(result[0]), int(result[1]) / 1000)

    async def renew_leader(self, lease: LeaderLease) -> LeaderLease | None:
        try:
            expires = await self.client.eval(
                _RENEW_LEADER_LUA,
                1,
                self._key("lease", "leader"),
                lease.owner_id,
                lease.fencing_token,
                self._ttl_ms,
            )
        except Exception as exc:
            raise CoordinationUnavailableError("Redis leader renewal failed") from exc
        return (
            LeaderLease(lease.owner_id, lease.fencing_token, int(expires) / 1000)
            if expires
            else None
        )

    async def release_leader(self, lease: LeaderLease) -> bool:
        try:
            result = await self.client.eval(
                _RELEASE_LEADER_LUA,
                1,
                self._key("lease", "leader"),
                lease.owner_id,
                lease.fencing_token,
            )
            return bool(result)
        except Exception as exc:
            raise CoordinationUnavailableError("Redis leader release failed") from exc

    async def leader_id(self) -> str | None:
        try:
            owner_id = await self.client.hget(self._key("lease", "leader"), "owner_id")
            return _decode(owner_id) if owner_id else None
        except Exception as exc:
            raise CoordinationUnavailableError("Redis leader lookup failed") from exc

    async def health(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


def replace_lease_expiry(lease: TurnLease, expires_ms: Any) -> TurnLease:
    return TurnLease(
        lease.turn_id,
        lease.session_id,
        lease.owner_id,
        lease.fencing_token,
        int(expires_ms) / 1000,
    )


__all__ = [
    "CoordinationUnavailableError",
    "RedisCoordinator",
]
