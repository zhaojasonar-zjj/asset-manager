"""腾讯财经 + 新浪财经 行情接口

实时行情（腾讯）：http://qt.gtimg.cn/q=sh600000,sz000001
实时行情（新浪）：http://hq.sinajs.cn/list=sh600000
历史K线（腾讯）：http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600000,day,...
"""
import re
import requests
from datetime import datetime, timedelta


def _to_tencent_code(code: str) -> str:
    """将 A 股代码转为腾讯格式：sh600000 / sz000001 / bj830799"""
    code = str(code).strip().zfill(6)
    if code.startswith(("6", "5", "9", "11", "13")):
        return f"sh{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    else:
        return f"sz{code}"


def _to_sina_code(code: str) -> str:
    """将 A 股代码转为新浪格式（与腾讯相同）"""
    return _to_tencent_code(code)


def _fetch_via_tencent(tencent_codes: list[str]) -> dict:
    """通过腾讯接口获取行情"""
    results = {}
    url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
    try:
        resp = requests.get(url, timeout=8, headers={"Referer": "http://qt.gtimg.cn/"})
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return results

    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        m = re.match(r'v_(\w+)="(.*)"', line)
        if not m:
            continue
        parts = m.group(2).split("~")
        if len(parts) < 5:
            continue
        try:
            stock_code = parts[2]
            current_price = float(parts[3]) if parts[3] else 0
            prev_close = float(parts[4]) if parts[4] else 0
            stock_name = parts[1]
            change_pct = (
                (current_price - prev_close) / prev_close * 100
                if prev_close > 0
                else 0
            )
            if current_price > 0:
                results[stock_code] = {
                    "name": stock_name,
                    "price": current_price,
                    "prev_close": prev_close,
                    "change_pct": round(change_pct, 2),
                }
        except (ValueError, IndexError):
            continue
    return results


def _fetch_via_sina(sina_codes: list[str]) -> dict:
    """通过新浪接口获取行情（备用）"""
    results = {}
    url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"Referer": "http://finance.sina.com.cn/"},
        )
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return results

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        m = re.match(r'var hq_str_(\w+)="(.*)"', line)
        if not m:
            continue
        code = m.group(1)
        parts = m.group(2).split(",")
        if len(parts) < 4:
            continue
        try:
            stock_name = parts[0]
            today_open = float(parts[1]) if parts[1] else 0
            prev_close = float(parts[2]) if parts[2] else 0
            current_price = float(parts[3]) if parts[3] else 0
            # 新浪格式：code 是 sh600000，提取纯数字
            pure_code = re.sub(r'^[a-z]+', '', code)
            if current_price <= 0:
                current_price = prev_close
            change_pct = (
                (current_price - prev_close) / prev_close * 100
                if prev_close > 0
                else 0
            )
            if current_price > 0:
                results[pure_code] = {
                    "name": stock_name,
                    "price": current_price,
                    "prev_close": prev_close,
                    "change_pct": round(change_pct, 2),
                }
        except (ValueError, IndexError):
            continue
    return results


def fetch_realtime_prices(stock_codes: list[str]) -> dict:
    """批量获取实时行情（腾讯优先，新浪备用）

    返回: {stock_code: {"name": str, "price": float, "prev_close": float, "change_pct": float}}
    """
    if not stock_codes:
        return {}

    pure_codes = [str(c).strip().zfill(6) for c in stock_codes]
    tencent_codes = [_to_tencent_code(c) for c in pure_codes]
    sina_codes = [_to_sina_code(c) for c in pure_codes]

    results = {}

    # 每批最多 50 个
    for i in range(0, len(tencent_codes), 50):
        batch_tx = tencent_codes[i : i + 50]
        batch_sn = sina_codes[i : i + 50]
        batch_pure = pure_codes[i : i + 50]

        # 先用腾讯
        batch_result = _fetch_via_tencent(batch_tx)
        results.update(batch_result)

        # 找出未获取到的，用新浪补
        missing = [c for c in batch_pure if c not in results]
        if missing:
            missing_sina = [_to_sina_code(c) for c in missing]
            sina_result = _fetch_via_sina(missing_sina)
            results.update(sina_result)

    return results


def fetch_realtime_price(stock_code: str) -> dict | None:
    """获取单只股票实时行情"""
    result = fetch_realtime_prices([stock_code])
    code = str(stock_code).strip().zfill(6)
    return result.get(code)


def fetch_history_kline(
    stock_code: str,
    start_date: str = "",
    end_date: str = "",
    count: int = 365,
    fq: str = "qfq",
) -> list[dict]:
    """获取历史日K线数据

    返回: [{"date": "YYYY-MM-DD", "open": float, "close": float, "high": float, "low": float, "volume": float}]
    """
    tencent_code = _to_tencent_code(stock_code)
    # 腾讯接口要求日期格式为 YYYY-MM-DD（带横杠）
    sd = start_date.replace("-", "") if start_date else ""
    ed = end_date.replace("-", "") if end_date else ""
    if sd:
        sd = f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}"
    if ed:
        ed = f"{ed[:4]}-{ed[4:6]}-{ed[6:8]}"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,{sd},{ed},{count},{fq}"

    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception:
        return []

    result = []
    # 腾讯接口返回格式可能为 {data: {code: {qfqday: [...]}}} 或 {code: {qfqday: [...]}}
    stock_data = data.get("data", data) if isinstance(data, dict) else {}
    if isinstance(stock_data, dict):
        # 尝试多种 key
        stock_data = stock_data.get(tencent_code, stock_data)
    
    # 优先取 qfq（前复权）数据
    if isinstance(stock_data, dict):
        kline = stock_data.get("qfqday") or stock_data.get("day") or []
    else:
        kline = []

    for item in kline:
        if len(item) >= 6:
            result.append(
                {
                    "date": item[0],
                    "open": float(item[1]) if item[1] else 0,
                    "close": float(item[2]) if item[2] else 0,
                    "high": float(item[3]) if item[3] else 0,
                    "low": float(item[4]) if item[4] else 0,
                    "volume": float(item[5]) if item[5] else 0,
                }
            )

    return result


def fetch_history_close_prices(
    stock_code: str, dates: list[str], count: int = 400
) -> dict:
    """获取指定日期的收盘价

    返回: {"YYYY-MM-DD": close_price}
    """
    if not dates:
        return {}

    start = min(dates).replace("-", "")
    end = max(dates).replace("-", "")
    kline = fetch_history_kline(stock_code, start, end, count)

    close_map = {item["date"]: item["close"] for item in kline}

    # 对 dates 中没有直接匹配的，找最近的交易日
    kline_dates = sorted(close_map.keys())
    result = {}
    for d in dates:
        if d in close_map:
            result[d] = close_map[d]
        else:
            # 找最近的日期
            for kd in kline_dates:
                if kd <= d:
                    result[d] = close_map[kd]
                    break
            else:
                if kline_dates:
                    result[d] = close_map[kline_dates[0]]

    return result
