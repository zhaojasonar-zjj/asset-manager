"""腾讯财经行情接口

实时行情：http://qt.gtimg.cn/q=sh600000,sz000001
历史K线：http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600000,day,...
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


def fetch_realtime_prices(stock_codes: list[str]) -> dict:
    """批量获取实时行情

    返回: {stock_code: {"name": str, "price": float, "prev_close": float, "change_pct": float}}
    """
    if not stock_codes:
        return {}

    tencent_codes = [_to_tencent_code(c) for c in stock_codes]
    results = {}

    # 每批最多 50 个
    for i in range(0, len(tencent_codes), 50):
        batch = tencent_codes[i : i + 50]
        url = f"http://qt.gtimg.cn/q={','.join(batch)}"
        try:
            resp = requests.get(url, timeout=10, headers={"Referer": "http://qt.gtimg.cn/"})
            resp.encoding = "gbk"
            text = resp.text
        except Exception:
            continue

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
                results[stock_code] = {
                    "name": stock_name,
                    "price": current_price,
                    "prev_close": prev_close,
                    "change_pct": round(change_pct, 2),
                }
            except (ValueError, IndexError):
                continue

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
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,{start_date},{end_date},{count},{fq}"

    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception:
        return []

    result = []
    stock_data = data.get("data", {}).get(tencent_code, {})

    # 优先取 qfq（前复权）数据
    kline = stock_data.get("qfqday") or stock_data.get("day") or []

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
