"""工作台域（`/api/wb/*`）的本地 Python 实现 —— D-2 strangler fig 的「收编侧」。

为什么单独建模块：
    `api/app.py` 已是 2000+ 行单文件单 app（无 APIRouter 分层）。把工作台域的
    端点继续塞进去只会让它更难维护，故沿用 P1 建 `api/wb_proxy.py` 的同一约定，
    新建本模块独立挂载。

为什么必须注册在 wb_proxy 之前：
    `api/wb_proxy.py` 用 `/api/wb/{path:path}` 兜底转发到 Express(:3456)。
    FastAPI 按注册顺序匹配，故本模块的**具体路径**必须注册在它之前，才能「短路」
    掉已收编的端点——前端契约（`/api/wb/<path>`）与请求体均不变，页面零改动。

本模块收编的端点（均为有真实消费者的路径）：
    GET  /api/wb/health          —— 工作台域存活探针
    POST /api/wb/weather/today   —— 今日天气（Open-Meteo 取数 + 城市级反解）

移植来源（只读参照，逐条对齐；见 docs/V3_INTEGRATION_PLAN.md §3 红线 3）：
    <skill>/app/backend/src/services/weatherService.ts
    <skill>/app/backend/src/services/locationLabelService.ts

隐私边界（DESIGN.md L207，硬规定，不得简化）：
    · 经纬度只取两位小数；不写库、不回传浏览器、不记日志（本模块无任何日志落盘）。
    · 反解失败显示「电脑当前位置」，绝不回退到某个具体城市。
    · 时区由调用方（浏览器）用 Intl 提供，服务端不推断、不默认 Asia/Shanghai。

依赖：标准库 + `tzdata`。`zoneinfo` 在 Windows 上无系统时区库，不装 `tzdata`
时 `available_timezones()` 返回空集，时区校验与「当地日期」都会失真——这是本
模块唯一新增的第三方依赖（已登记到 requirements-web.txt）。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

#: 本模块（工作台域）的版本号，仅用于 /api/wb/health 自述。
_VERSION = "v3-p3a"

# ---------------------------------------------------------------------------
# 上游常量
# ---------------------------------------------------------------------------
_WEATHER_HOST = "api.open-meteo.com"
_WEATHER_PATH = "/v1/forecast"
_WEATHER_TIMEOUT_S = 5.0

_LOCATION_DEFAULT_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
_LOCATION_DEFAULT_LABEL = "电脑当前位置"
_LOCATION_TIMEOUT_S = 5.0

#: 天气缓存：15 分钟内视为新鲜（返回 status=cache）；失败时可回退到 6 小时内的快照（status=stale）。
_FRESH_MS = 15 * 60 * 1000
_STALE_MAX_MS = 6 * 60 * 60 * 1000

#: 反解结果缓存 24 小时；两次外部请求之间至少间隔 1.1s（Nominatim 使用条款）。
_LABEL_TTL_MS = 24 * 60 * 60 * 1000
_LABEL_MIN_INTERVAL_MS = 1_100

#: Nominatim 要求可识别的 User-Agent；可用环境变量覆盖。
_DEFAULT_UA = "BidPricing-Workbench/1.0 (local personal dashboard)"

#: 时区字符串白名单字符集。JS 的 \w 只含 ASCII，这里用 re.ASCII 对齐。
_TZ_ILLEGAL_RE = re.compile(r"[^\w+\-/]", re.ASCII)

#: Open-Meteo WMO 天气码 → 稳定 code + 中文标签。
_CONDITION_BY_CODE: dict[int, tuple[str, str]] = {
    0: ("clear", "晴"),
    1: ("mainly_clear", "大部晴朗"),
    2: ("partly_cloudy", "多云"),
    3: ("overcast", "阴"),
    45: ("fog", "雾"),
    48: ("rime_fog", "雾凇"),
    51: ("drizzle_light", "小毛毛雨"),
    53: ("drizzle", "毛毛雨"),
    55: ("drizzle_dense", "大毛毛雨"),
    56: ("freezing_drizzle", "冻毛毛雨"),
    57: ("freezing_drizzle_dense", "强冻毛毛雨"),
    61: ("rain_light", "小雨"),
    63: ("rain", "雨"),
    65: ("rain_heavy", "大雨"),
    66: ("freezing_rain", "冻雨"),
    67: ("freezing_rain_heavy", "强冻雨"),
    71: ("snow_light", "小雪"),
    73: ("snow", "雪"),
    75: ("snow_heavy", "大雪"),
    77: ("snow_grains", "雪粒"),
    80: ("showers_light", "小阵雨"),
    81: ("showers", "阵雨"),
    82: ("showers_heavy", "强阵雨"),
    85: ("snow_showers", "阵雪"),
    86: ("snow_showers_heavy", "强阵雪"),
    95: ("thunder", "雷阵雨"),
    96: ("thunder_hail", "雷阵雨伴冰雹"),
    99: ("thunder_hail_heavy", "强雷暴冰雹"),
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_ms(dt: datetime) -> str:
    """产出与 JS `Date.prototype.toISOString()` **同形**的字符串。

    对字段对照有意义：JS 固定 3 位毫秒 + `Z`，而 Python 的 isoformat() 会给 6 位
    微秒 + `+00:00`。前端 `new Date(iso)` 两者都能解析，但既然验收要求逐字段对照，
    这里就按 JS 的形态输出。
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _round_half_up(value: float, digits: int) -> float:
    """等价 JS `Math.round(x * 10^d) / 10^d`（半数进位）。

    Python 内建 `round()` 是「半数取偶」，与 JS 在 .5 边界上不同。经纬度与气温
    都走这条路径，故显式实现半进位以免出现 0.1 的偶发偏差。
    """
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor


def _enabled(env_key: str) -> bool:
    """与 TS 侧一致：仅当环境变量**显式**为 'false' 时关闭，缺省即启用。"""
    return str(os.environ.get(env_key, "")).strip() != "false"


def _as_number(value: object) -> float | None:
    """宽松数值转换，对齐 JS `Number(x)` 对真实输入的语义。

    偏离说明：JS 的 `Number(null)` / `Number("")` 均为 0，会把 `{latitude:null}`
    静默当成 (0,0) 这个真实坐标去查询。这里对 None / "" / bool 一律判非法——
    浏览器端只会送数字，收紧不会影响任何真实调用，却能避免「空值→几内亚湾」。
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return num if math.isfinite(num) else None


def _finite(value: object, low: float, high: float) -> float | int | None:
    """取值范围校验；非数值/越界/非有限一律 None（对齐 TS `finiteNumber`）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if value < low or value > high:
        return None
    return value


def _is_valid_timezone(tz: str) -> bool:
    """时区校验：先做字符/长度白名单（防注入上游查询串），再查 IANA 库真值。

    后半段需要 `tzdata`（Windows 无系统时区库）。缺失时 ZoneInfo 抛
    ZoneInfoNotFoundError，等价于「该时区不可用」——前端拿到的会是
    WEATHER_RESPONSE_INVALID，而不是把非法时区透传给上游。
    """
    if not tz or len(tz) > 80 or _TZ_ILLEGAL_RE.search(tz):
        return False
    try:
        ZoneInfo(tz)
        return True
    except Exception:  # noqa: BLE001  未知时区/数据缺失/非法路径统一判不可用
        return False


def _local_date_in_zone(now: datetime, tz: str) -> str:
    """当地日期 YYYY-MM-DD（等价 TS 的 Intl en-CA 格式化）。"""
    return now.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def _http_get(url: str, timeout_s: float, headers: dict[str, str]) -> tuple[int, bytes]:
    """同步 GET，返回 (status, body)。HTTPError 也是合法响应，按响应返回而非抛出。

    urllib 不会自动解压，故调用方统一声明 `accept-encoding: identity`。
    """
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _is_timeout(exc: BaseException) -> bool:
    """识别超时：Windows 上 socket 超时是 TimeoutError，URLError 会把它包在 reason 里。"""
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, TimeoutError):
        return True
    return "timed out" in str(exc).lower()


# ---------------------------------------------------------------------------
# 位置反解（城市级）—— 对齐 locationLabelService.ts
# ---------------------------------------------------------------------------
_label_cache: dict[str, tuple[str, float]] = {}
_label_inflight: dict[str, asyncio.Task] = {}
#: 下一个「可发起请求」的时间戳（毫秒）。在等待前先占位，避免并发调用同时穿透限速。
_label_next_slot_ms = 0.0


def _clean_part(value: object) -> str | None:
    """反解结果片段清洗：压平空白、限长 40 字。"""
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value.replace("\r", " ").replace("\n", " ").replace("\t", " ")).strip()
    if not cleaned or len(cleaned) > 40:
        return None
    return cleaned


def parse_location_label(raw: object) -> str | None:
    """只取城市级标签（绝不下探到街道/门牌）。优先级对齐 TS 侧。"""
    if not isinstance(raw, dict):
        return None
    address = raw.get("address")
    if not isinstance(address, dict):
        return None
    for key in ("city", "town", "municipality", "village", "county", "state"):
        found = _clean_part(address.get(key))
        if found:
            return found
    return None


def _label_cache_key(lat: float, lon: float) -> str:
    return f"{lat:.2f}|{lon:.2f}"


async def _fetch_label(lat: float, lon: float) -> str:
    """向 Nominatim 取城市级标签；任何失败都回落到「电脑当前位置」。"""
    endpoint = os.environ.get("LOCATION_REVERSE_URL") or _LOCATION_DEFAULT_ENDPOINT
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https":
        return _LOCATION_DEFAULT_LABEL
    query = urllib.parse.urlencode({
        "format": "jsonv2",
        "lat": f"{lat:.2f}",
        "lon": f"{lon:.2f}",
        # zoom=7 在中国 OSM 数据下稳定落在「地级市」层级。
        "zoom": "7",
        "addressdetails": "1",
        "accept-language": "zh-CN,zh,en",
    })
    url = f"{endpoint}?{query}"
    headers = {
        "accept": "application/json",
        "user-agent": os.environ.get("LOCATION_REVERSE_USER_AGENT") or _DEFAULT_UA,
    }
    try:
        status, body = await asyncio.to_thread(_http_get, url, _LOCATION_TIMEOUT_S, headers)
        if status != 200:
            return _LOCATION_DEFAULT_LABEL
        return parse_location_label(json.loads(body)) or _LOCATION_DEFAULT_LABEL
    except Exception:  # noqa: BLE001  反解是尽力而为，超时/网络/解析失败一律回落
        return _LOCATION_DEFAULT_LABEL


async def _resolve_location_label(lat: float, lon: float) -> str:
    """带 24h 缓存、in-flight 合并与 1.1s 最小间隔的反解入口。"""
    global _label_next_slot_ms
    if not _enabled("LOCATION_REVERSE_ENABLED"):
        return _LOCATION_DEFAULT_LABEL

    key = _label_cache_key(lat, lon)
    cached = _label_cache.get(key)
    if cached and cached[1] > time.time() * 1000:
        return cached[0]
    pending = _label_inflight.get(key)
    if pending is not None:
        return await pending

    # 限速占位：TS 侧是「先 await 再写 nextRequestAt」，并发时会同时穿透；
    # 这里改为先占坑再等待，语义一致（单请求行为完全相同）且真正起到限速作用。
    now_ms = time.time() * 1000
    wait_ms = max(0.0, _label_next_slot_ms - now_ms)
    _label_next_slot_ms = max(now_ms, _label_next_slot_ms) + _LABEL_MIN_INTERVAL_MS

    async def _run() -> str:
        try:
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)
            label = await _fetch_label(lat, lon)
            _label_cache[key] = (label, time.time() * 1000 + _LABEL_TTL_MS)
            return label
        finally:
            _label_inflight.pop(key, None)

    task = asyncio.create_task(_run())
    _label_inflight[key] = task
    return await task


# ---------------------------------------------------------------------------
# 今日天气 —— 对齐 weatherService.ts
# ---------------------------------------------------------------------------
_weather_cache: dict[str, tuple[dict, float]] = {}
_weather_inflight: dict[str, asyncio.Task] = {}


def _invalid_request() -> dict:
    return {
        "status": "unavailable",
        "locationLabel": _LOCATION_DEFAULT_LABEL,
        "timezone": "",
        "localDate": "",
        "fetchedAt": None,
        "current": None,
        "today": None,
        "errorCode": "WEATHER_RESPONSE_INVALID",
    }


def _unavailable(error_code: str, tz: str, local_date: str) -> dict:
    return {
        "status": "unavailable",
        "locationLabel": _LOCATION_DEFAULT_LABEL,
        "timezone": tz,
        "localDate": local_date,
        "fetchedAt": None,
        "current": None,
        "today": None,
        "errorCode": error_code,
    }


def sanitize_weather_request(body: object) -> dict | None:
    """请求体清洗：经纬度范围校验 + 两位小数 + 时区白名单。非法返回 None。"""
    if not isinstance(body, dict):
        return None
    lat = _as_number(body.get("latitude"))
    lon = _as_number(body.get("longitude"))
    tz_raw = body.get("timezone")
    tz = tz_raw.strip() if isinstance(tz_raw, str) else ""
    if lat is None or not (-90.0 <= lat <= 90.0):
        return None
    if lon is None or not (-180.0 <= lon <= 180.0):
        return None
    if not _is_valid_timezone(tz):
        return None
    return {
        "latitude": _round_half_up(lat, 2),
        "longitude": _round_half_up(lon, 2),
        "timezone": tz,
    }


def _cache_key(query: dict, local_date: str) -> str:
    return f"{query['latitude']:.2f}|{query['longitude']:.2f}|{query['timezone']}|{local_date}"


def _snapshot_unavailable(key: str, error_code: str, tz: str, local_date: str) -> dict:
    """失败时的降级：6 小时内的旧快照降级为 stale，否则彻底 unavailable。"""
    hit = _weather_cache.get(key)
    if hit and (time.time() * 1000 - hit[1]) <= _STALE_MAX_MS:
        return {**hit[0], "status": "stale", "errorCode": error_code}
    return _unavailable(error_code, tz, local_date)


def _parse_upstream(raw: object, tz: str, local_date: str, fetched_at: str, location_label: str) -> dict | None:
    """上游响应严格校验；任一必需字段缺失/越界即判定响应无效。"""
    if not isinstance(raw, dict):
        return None
    current = raw.get("current")
    daily = raw.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        return None

    temp = _finite(current.get("temperature_2m"), -80, 80)
    code = _finite(current.get("weather_code"), 0, 99)
    if temp is None or code is None:
        return None

    max_list = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
    min_list = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
    pop_list = (daily.get("precipitation_probability_max")
                if isinstance(daily.get("precipitation_probability_max"), list) else [])
    date_list = daily.get("time") if isinstance(daily.get("time"), list) else []

    # 上游按请求时区返回当地日期；与本地推得的当地日期不一致说明口径错位，判无效。
    if date_list and str(date_list[0]) != local_date:
        return None

    max_c = _finite(max_list[0] if max_list else None, -80, 80)
    min_c = _finite(min_list[0] if min_list else None, -80, 80)
    if max_c is None or min_c is None:
        return None

    cond_code, cond_label = _CONDITION_BY_CODE.get(int(_round_half_up(float(code), 0)), ("unknown", "天气不明"))
    return {
        "status": "live",
        "locationLabel": location_label,
        "timezone": tz,
        "localDate": local_date,
        "fetchedAt": fetched_at,
        "current": {
            "temperatureC": _round_half_up(float(temp), 1),
            "apparentTemperatureC": _finite(current.get("apparent_temperature"), -80, 80),
            "conditionCode": cond_code,
            "conditionLabel": cond_label,
            "windKph": _finite(current.get("wind_speed_10m"), 0, 400),
        },
        "today": {
            "minC": _round_half_up(float(min_c), 1),
            "maxC": _round_half_up(float(max_c), 1),
            "precipitationProbabilityPct": _finite(pop_list[0] if pop_list else None, 0, 100),
        },
    }


async def _fetch_live(query: dict, key: str, local_date: str) -> dict:
    """真实取数：天气与城市反解并发发起，天气失败时按错误类型降级。"""
    tz = query["timezone"]
    url = f"https://{_WEATHER_HOST}{_WEATHER_PATH}?" + urllib.parse.urlencode({
        "latitude": str(query["latitude"]),
        "longitude": str(query["longitude"]),
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": "1",
        "timezone": tz,
    })
    headers = {"accept": "application/json", "accept-encoding": "identity"}

    # 与 TS 一致：反解与取数并发，避免被反解的 1.1s 限速串行拖长。
    label_task = asyncio.create_task(_resolve_location_label(query["latitude"], query["longitude"]))
    try:
        try:
            status, body = await asyncio.to_thread(_http_get, url, _WEATHER_TIMEOUT_S, headers)
        except Exception as exc:  # noqa: BLE001  连接层故障统一降级
            code = "WEATHER_TIMEOUT" if _is_timeout(exc) else "WEATHER_UPSTREAM_UNAVAILABLE"
            return _snapshot_unavailable(key, code, tz, local_date)

        if status != 200:
            return _snapshot_unavailable(key, "WEATHER_UPSTREAM_UNAVAILABLE", tz, local_date)
        try:
            payload = json.loads(body)
        except Exception:  # noqa: BLE001
            return _snapshot_unavailable(key, "WEATHER_RESPONSE_INVALID", tz, local_date)

        fetched_at = _iso_ms(_now_utc())
        location_label = await label_task
        parsed = _parse_upstream(payload, tz, local_date, fetched_at, location_label)
        if parsed is None:
            return _snapshot_unavailable(key, "WEATHER_RESPONSE_INVALID", tz, local_date)
        _weather_cache[key] = (parsed, time.time() * 1000)
        return parsed
    finally:
        # 提前失败时反解可能仍在飞：主动取消，避免留下悬挂任务告警。
        if not label_task.done():
            label_task.cancel()


async def _get_today(body: object) -> dict:
    """对外主入口：清洗 → 缓存命中 → in-flight 合并 → 真实取数。"""
    query = sanitize_weather_request(body)
    if query is None:
        return _invalid_request()

    now = _now_utc()
    local_date = _local_date_in_zone(now, query["timezone"])
    if not _enabled("WEATHER_ENABLED"):
        return _unavailable("WEATHER_DISABLED", query["timezone"], local_date)

    key = _cache_key(query, local_date)
    fresh = _weather_cache.get(key)
    if fresh and (time.time() * 1000 - fresh[1]) <= _FRESH_MS:
        return {**fresh[0], "status": "cache"}

    existing = _weather_inflight.get(key)
    if existing is not None:
        return await asyncio.shield(existing)

    task = asyncio.create_task(_fetch_live(query, key, local_date))
    _weather_inflight[key] = task
    task.add_done_callback(lambda _t: _weather_inflight.pop(key, None))
    return await asyncio.shield(task)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.get("/api/wb/health", include_in_schema=False)
async def workbench_health() -> dict:
    """工作台域存活探针。

    与 Express 版（`/api/health`）的响应**形态有意不同**：lshu 那几个字段
    （appVersion / buildId / promptVersion / schemaVersion / hubVersion /
    sourceFingerprint）是它的构建指纹，收编后如实填写只能是编造；而唯一消费者
    （run.ps1 的 `Wait-HttpOk`）只判 HTTP 200，不解析任何字段。故此处只报
    真实可核的事实。
    """
    return {
        "ok": True,
        "time": _iso_ms(_now_utc()),
        "domain": "workbench",
        "impl": "python",
        "version": _VERSION,
    }


@router.post("/api/wb/weather/today", include_in_schema=False)
async def weather_today(request: Request) -> JSONResponse:
    """今日天气。契约与 Express 版逐字段一致（见 weatherService.ts 的 DTO）。"""
    try:
        body: object = await request.json()
    except Exception:  # noqa: BLE001  非 JSON 体交给清洗层按非法处理
        body = None
    try:
        payload = await _get_today(body)
    except Exception:  # noqa: BLE001  与 Express 的外层兜底一致：任何意外都返回 200 + unavailable
        payload = {
            "status": "unavailable",
            "locationLabel": _LOCATION_DEFAULT_LABEL,
            "timezone": "",
            "localDate": "",
            "fetchedAt": None,
            "current": None,
            "today": None,
            "errorCode": "WEATHER_UPSTREAM_UNAVAILABLE",
        }
    return JSONResponse(content=payload)
