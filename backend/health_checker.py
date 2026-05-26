import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx
import db

log = logging.getLogger("devfleet.health_checker")

_checker_task = None
_client: httpx.AsyncClient | None = None
_last_check: dict[str, datetime] = {}
_prune_counter = 0


async def start_checker():
    global _checker_task, _client
    _client = httpx.AsyncClient(follow_redirects=True, verify=False, timeout=10)
    _checker_task = asyncio.create_task(_check_loop())
    log.info("Health checker started")


async def stop_checker():
    global _checker_task, _client
    if _checker_task:
        _checker_task.cancel()
        try:
            await _checker_task
        except asyncio.CancelledError:
            pass
    if _client:
        await _client.aclose()
    log.info("Health checker stopped")


async def _check_loop():
    global _prune_counter
    while True:
        try:
            conn = await db.get_db()
            try:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM monitored_services WHERE enabled=1"
                )
            finally:
                await conn.close()

            now = datetime.now(timezone.utc)
            tasks = []
            for row in rows:
                svc = dict(row)
                sid = svc["id"]
                interval = svc.get("check_interval") or 30
                last = _last_check.get(sid)
                if not last or (now - last).total_seconds() >= interval:
                    _last_check[sid] = now
                    tasks.append(_check_service(svc))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Prune old data every ~100 loops (~100 seconds)
            _prune_counter += 1
            if _prune_counter >= 100:
                _prune_counter = 0
                await _prune_old_checks()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("Check loop error: %s", e)

        await asyncio.sleep(1)


async def _check_service(svc: dict):
    timeout_s = (svc.get("timeout_ms") or 5000) / 1000
    try:
        resp = await _client.get(svc["url"], timeout=timeout_s)
        elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
        expected = svc.get("expected_status") or 200

        if resp.status_code == expected and elapsed_ms < 2000:
            status = "up"
        elif resp.status_code == expected:
            status = "degraded"
        else:
            status = "down"

        await _record_check(svc["id"], status, elapsed_ms, resp.status_code, "")
        log.debug("Check %s: %s (%dms, HTTP %d)", svc["name"], status, elapsed_ms, resp.status_code)

    except Exception as e:
        await _record_check(svc["id"], "down", None, None, str(e)[:500])
        log.debug("Check %s: down (%s)", svc["name"], str(e)[:100])


async def _record_check(service_id: str, status: str, response_time_ms: int | None,
                         status_code: int | None, error: str):
    conn = await db.get_db()
    try:
        await conn.execute(
            """INSERT INTO health_checks (service_id, status, response_time_ms, status_code, error_message)
               VALUES (?, ?, ?, ?, ?)""",
            (service_id, status, response_time_ms, status_code, error),
        )
        await conn.commit()
    finally:
        await conn.close()


async def _prune_old_checks():
    conn = await db.get_db()
    try:
        await conn.execute(
            "DELETE FROM health_checks WHERE checked_at < datetime('now', '-90 days')"
        )
        await conn.commit()
        log.debug("Pruned health checks older than 90 days")
    finally:
        await conn.close()


async def get_service_status(service_id: str) -> dict:
    """Get current status + uptime stats for a single service."""
    conn = await db.get_db()
    try:
        # Latest check
        rows = await conn.execute_fetchall(
            """SELECT status, response_time_ms, status_code, error_message, checked_at
               FROM health_checks WHERE service_id=? ORDER BY checked_at DESC LIMIT 1""",
            (service_id,),
        )
        latest = dict(rows[0]) if rows else None

        # Average response time (last 10)
        avg_rows = await conn.execute_fetchall(
            """SELECT AVG(response_time_ms) as avg_rt FROM (
                SELECT response_time_ms FROM health_checks
                WHERE service_id=? AND response_time_ms IS NOT NULL
                ORDER BY checked_at DESC LIMIT 10
            )""",
            (service_id,),
        )
        avg_rt = dict(avg_rows[0])["avg_rt"] if avg_rows else None

        # Uptime percentages
        uptime_24h = await _calc_uptime(conn, service_id, 1)
        uptime_7d = await _calc_uptime(conn, service_id, 7)
        uptime_30d = await _calc_uptime(conn, service_id, 30)

        return {
            "status": latest["status"] if latest else "unknown",
            "response_time_ms": latest["response_time_ms"] if latest else None,
            "avg_response_time_ms": round(avg_rt, 1) if avg_rt else None,
            "last_checked": latest["checked_at"] if latest else None,
            "status_code": latest["status_code"] if latest else None,
            "error_message": latest["error_message"] if latest else None,
            "uptime_24h": uptime_24h,
            "uptime_7d": uptime_7d,
            "uptime_30d": uptime_30d,
        }
    finally:
        await conn.close()


async def _calc_uptime(conn, service_id: str, days: int) -> float | None:
    rows = await conn.execute_fetchall(
        f"""SELECT
              COUNT(*) as total,
              SUM(CASE WHEN status='up' THEN 1 ELSE 0 END) as up_count
            FROM health_checks
            WHERE service_id=? AND checked_at >= datetime('now', '-{days} days')""",
        (service_id,),
    )
    if not rows:
        return None
    r = dict(rows[0])
    if r["total"] == 0:
        return None
    return round((r["up_count"] / r["total"]) * 100, 2)


async def get_service_status_bulk(service_ids: list[str]) -> dict[str, dict]:
    """Batch variant of get_service_status — 5 queries total for N services.

    Returns a dict keyed by service_id.  Missing IDs get an 'unknown' entry.
    Use this in loop-over-services endpoints to avoid N * 5 DB round-trips.
    """
    if not service_ids:
        return {}

    placeholders = ",".join("?" * len(service_ids))
    conn = await db.get_db()
    try:
        # Latest check per service (window-function approach via MAX rowid trick)
        latest_rows = await conn.execute_fetchall(
            f"""SELECT h.service_id, h.status, h.response_time_ms, h.status_code,
                       h.error_message, h.checked_at
                FROM health_checks h
                JOIN (
                  SELECT service_id, MAX(checked_at) AS max_at
                  FROM health_checks WHERE service_id IN ({placeholders})
                  GROUP BY service_id
                ) mx ON h.service_id = mx.service_id AND h.checked_at = mx.max_at""",
            service_ids,
        )
        latest_map = {r["service_id"]: dict(r) for r in latest_rows}

        # Average response time per service (last 10 checks each)
        avg_rows = await conn.execute_fetchall(
            f"""SELECT service_id, AVG(response_time_ms) AS avg_rt
                FROM (
                  SELECT service_id, response_time_ms,
                         ROW_NUMBER() OVER (PARTITION BY service_id ORDER BY checked_at DESC) AS rn
                  FROM health_checks
                  WHERE service_id IN ({placeholders}) AND response_time_ms IS NOT NULL
                )
                WHERE rn <= 10
                GROUP BY service_id""",
            service_ids,
        )
        avg_map = {r["service_id"]: r["avg_rt"] for r in avg_rows}

        # Uptime for 1d, 7d, 30d in one pass each (3 queries total instead of N*3)
        def _uptime_bulk(rows_) -> dict[str, float | None]:
            out = {}
            for r in rows_:
                sid = r["service_id"]
                total = r["total"]
                if total == 0:
                    out[sid] = None
                else:
                    out[sid] = round((r["up_count"] / total) * 100, 2)
            return out

        def _uptime_query(days: int):
            return conn.execute_fetchall(
                f"""SELECT service_id,
                           COUNT(*) AS total,
                           SUM(CASE WHEN status='up' THEN 1 ELSE 0 END) AS up_count
                    FROM health_checks
                    WHERE service_id IN ({placeholders})
                      AND checked_at >= datetime('now', '-{days} days')
                    GROUP BY service_id""",
                service_ids,
            )

        uptime_24h_map = _uptime_bulk(await _uptime_query(1))
        uptime_7d_map  = _uptime_bulk(await _uptime_query(7))
        uptime_30d_map = _uptime_bulk(await _uptime_query(30))

        result = {}
        for sid in service_ids:
            latest = latest_map.get(sid)
            result[sid] = {
                "status": latest["status"] if latest else "unknown",
                "response_time_ms": latest["response_time_ms"] if latest else None,
                "avg_response_time_ms": round(avg_map[sid], 1) if sid in avg_map and avg_map[sid] else None,
                "last_checked": latest["checked_at"] if latest else None,
                "status_code": latest["status_code"] if latest else None,
                "error_message": latest["error_message"] if latest else None,
                "uptime_24h": uptime_24h_map.get(sid),
                "uptime_7d": uptime_7d_map.get(sid),
                "uptime_30d": uptime_30d_map.get(sid),
            }
        return result
    finally:
        await conn.close()


async def get_uptime_bars(service_id: str, segments: int = 90) -> list[dict]:
    """Get uptime data for N segments (default 90 days, 1 day each)."""
    conn = await db.get_db()
    try:
        bars = []
        now = datetime.now(timezone.utc)
        for i in range(segments - 1, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            rows = await conn.execute_fetchall(
                """SELECT
                      COUNT(*) as total,
                      SUM(CASE WHEN status='up' THEN 1 ELSE 0 END) as up_count,
                      SUM(CASE WHEN status='degraded' THEN 1 ELSE 0 END) as degraded_count,
                      SUM(CASE WHEN status='down' THEN 1 ELSE 0 END) as down_count
                   FROM health_checks
                   WHERE service_id=? AND checked_at >= ? AND checked_at < ?""",
                (service_id, day_start.isoformat(), day_end.isoformat()),
            )
            r = dict(rows[0]) if rows else {"total": 0}

            if r["total"] == 0:
                bar_status = "no_data"
                uptime_pct = None
            else:
                uptime_pct = round((r["up_count"] / r["total"]) * 100, 1)
                if r["down_count"] > 0:
                    bar_status = "down"
                elif r["degraded_count"] > 0:
                    bar_status = "degraded"
                else:
                    bar_status = "up"

            bars.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "status": bar_status,
                "uptime_pct": uptime_pct,
                "checks": r["total"],
            })
        return bars
    finally:
        await conn.close()
