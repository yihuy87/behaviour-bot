# behaviour/features.py
from __future__ import annotations

from typing import Dict, List, Literal, Tuple

from binance.ohlc_buffer import Candle
from behaviour.behaviour_settings import behaviour_settings


Number = float
Side = Literal["bull", "bear"]


def _safe_mean(values: List[Number]) -> Number:
    return sum(values) / len(values) if values else 0.0


def _window(candles: List[Candle], length: int) -> List[Candle]:
    if len(candles) <= length:
        return candles
    return candles[-length:]


def _body(c: Candle) -> Number:
    return abs(c["close"] - c["open"])


def _range(c: Candle) -> Number:
    return c["high"] - c["low"]


def _upper_wick(c: Candle) -> Number:
    return c["high"] - max(c["open"], c["close"])


def _lower_wick(c: Candle) -> Number:
    return min(c["open"], c["close"]) - c["low"]


def _leg_flow(segment: List[Candle]) -> Dict[str, Number]:
    bull_body = 0.0
    bear_body = 0.0
    bull_count = 0
    bear_count = 0

    for c in segment:
        b = c["close"] - c["open"]
        if b > 0:
            bull_body += b
            bull_count += 1
        elif b < 0:
            bear_body += abs(b)
            bear_count += 1

    net_flow = bull_body - bear_body
    return {
        "bull_body_sum": bull_body,
        "bear_body_sum": bear_body,
        "bull_count": float(bull_count),
        "bear_count": float(bear_count),
        "net_flow": net_flow,
    }


def _trend_from_halves(values: List[Number]) -> Number:
    """
    trend kasar: rata2 second half / first half - 1
    >0  → naik, <0 → turun, 0 → flat
    """
    n = len(values)
    if n < 4:
        return 0.0
    mid = n // 2
    first = _safe_mean(values[:mid])
    second = _safe_mean(values[mid:])
    if first <= 0:
        return 0.0
    return (second / first) - 1.0


def _wick_bias(avg_up: Number, avg_down: Number) -> str:
    if avg_up <= 0 and avg_down <= 0:
        return "mixed"
    # pakai rasio sederhana
    if avg_down > 1.3 * avg_up:
        return "buy"
    if avg_up > 1.3 * avg_down:
        return "sell"
    return "mixed"


def _compute_basic_stats(segment: List[Candle]) -> Dict[str, Number]:
    bodies = [_body(c) for c in segment]
    ranges = [_range(c) for c in segment]
    up_wicks = [_upper_wick(c) for c in segment]
    dn_wicks = [_lower_wick(c) for c in segment]

    avg_body = _safe_mean(bodies)
    avg_range = _safe_mean(ranges)
    avg_up_wick = _safe_mean(up_wicks)
    avg_dn_wick = _safe_mean(dn_wicks)

    body_trend = _trend_from_halves(bodies)
    range_trend = _trend_from_halves(ranges)

    return {
        "avg_body": avg_body,
        "avg_range": avg_range,
        "avg_up_wick": avg_up_wick,
        "avg_down_wick": avg_dn_wick,
        "body_trend": body_trend,
        "range_trend": range_trend,
    }


def _detect_flush(
    candles: List[Candle],
    avg_range: Number,
    lookback: int,
) -> Dict[str, object]:
    """
    Deteksi flush up/down pada candle terakhir dibanding history.
    """
    n = len(candles)
    if n < lookback + 2 or avg_range <= 0:
        return {
            "has_flush_down": False,
            "has_flush_up": False,
            "flush_depth_down": 0.0,
            "flush_depth_up": 0.0,
        }

    last = candles[-1]
    src = candles[-(lookback + 1):-1]  # history sebelum terakhir

    prev_lows = [c["low"] for c in src]
    prev_highs = [c["high"] for c in src]
    if not prev_lows or not prev_highs:
        return {
            "has_flush_down": False,
            "has_flush_up": False,
            "flush_depth_down": 0.0,
            "flush_depth_up": 0.0,
        }

    prev_min_low = min(prev_lows)
    prev_max_high = max(prev_highs)

    flush_min_depth_ratio = behaviour_settings.flush_min_depth_ratio

    # flush down
    depth_down_abs = max(0.0, prev_min_low - last["low"])
    depth_down_ratio = depth_down_abs / avg_range

    has_flush_down = depth_down_ratio >= flush_min_depth_ratio

    # flush up
    depth_up_abs = max(0.0, last["high"] - prev_max_high)
    depth_up_ratio = depth_up_abs / avg_range

    has_flush_up = depth_up_ratio >= flush_min_depth_ratio

    return {
        "has_flush_down": bool(has_flush_down),
        "has_flush_up": bool(has_flush_up),
        "flush_depth_down": float(depth_down_ratio),
        "flush_depth_up": float(depth_up_ratio),
    }


def _compute_chop_score(segment: List[Candle], avg_body: Number) -> Number:
    """
    Skor chop 0–100 (semakin tinggi = semakin racun).
    Kombinasi:
      - color flip (ganti hijau/merah)
      - small body ratio
      - two-sided wick ratio
    """
    n = len(segment)
    if n < 5 or avg_body <= 0:
        return 0.0

    # 1) color flips
    flips = 0
    prev_sign = 0
    for c in segment:
        diff = c["close"] - c["open"]
        sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            flips += 1
        if sign != 0:
            prev_sign = sign
    color_flip_ratio = flips / max(n - 1, 1)

    # 2) small body ratio
    small_body_factor = behaviour_settings.small_body_factor
    small_body_count = 0
    for c in segment:
        if _body(c) < small_body_factor * avg_body:
            small_body_count += 1
    small_body_ratio = small_body_count / n

    # 3) two-sided wick ratio
    big_wick_ratio_threshold = behaviour_settings.big_wick_ratio
    two_sided_count = 0
    for c in segment:
        r = _range(c)
        if r <= 0:
            continue
        up = _upper_wick(c) / r
        dn = _lower_wick(c) / r
        if up >= big_wick_ratio_threshold and dn >= big_wick_ratio_threshold:
            two_sided_count += 1
    two_sided_ratio = two_sided_count / n

    w1 = behaviour_settings.chop_weight_color_flip
    w2 = behaviour_settings.chop_weight_small_body
    w3 = behaviour_settings.chop_weight_two_sided_wick

    raw = (w1 * color_flip_ratio) + (w2 * small_body_ratio) + (w3 * two_sided_ratio)
    # normalisasi ke 0–100
    chop_score = max(0.0, min(raw * 100.0, 100.0))
    return chop_score


def _compute_micro_range(segment: List[Candle]) -> Tuple[Number, Number, Number]:
    highs = [c["high"] for c in segment]
    lows = [c["low"] for c in segment]
    closes = [c["close"] for c in segment]
    if not highs or not lows or not closes:
        return 0.0, 0.0, 0.5
    micro_high = max(highs)
    micro_low = min(lows)
    last_price = closes[-1]

    if micro_high <= micro_low:
        pos = 0.5
    else:
        pos = (last_price - micro_low) / (micro_high - micro_low)
        if pos < 0.0:
            pos = 0.0
        elif pos > 1.0:
            pos = 1.0

    return micro_low, micro_high, pos


def _compute_htf_virtual(candles: List[Candle]) -> Dict[str, object]:
    """
    HTF virtual dari 5m: pakai ~1 jam terakhir (12 candle) untuk drift/dominance.
    """
    htf_len = behaviour_settings.htf_window
    seg = _window(candles, htf_len)
    if len(seg) < 4:
        return {
            "htf_dom": "none",
            "htf_drift": "flat",
            "htf_vol_mode": "normal",
            "htf_wick_bias": "mixed",
        }

    flow = _leg_flow(seg)
    bull_body = flow["bull_body_sum"]
    bear_body = flow["bear_body_sum"]
    net_flow = flow["net_flow"]

    if net_flow > max(bull_body, bear_body) * 0.25:
        dom = "bull"
    elif net_flow < -max(bull_body, bear_body) * 0.25:
        dom = "bear"
    else:
        dom = "none"

    closes = [c["close"] for c in seg]
    first_close = closes[0]
    last_close = closes[-1]
    drift_tol = behaviour_settings.htf_drift_tolerance_pct

    drift = "flat"
    if first_close > 0:
        pct = (last_close - first_close) / first_close * 100.0
        if pct > drift_tol:
            drift = "up"
        elif pct < -drift_tol:
            drift = "down"

    # vol mode
    ranges = [_range(c) for c in seg]
    if len(ranges) >= 4:
        mid = len(ranges) // 2
        r1 = _safe_mean(ranges[:mid])
        r2 = _safe_mean(ranges[mid:])
        if r1 > 0:
            ratio = r2 / r1
            if ratio > 1.15:
                vol_mode = "expand"
            elif ratio < 0.85:
                vol_mode = "contract"
            else:
                vol_mode = "normal"
        else:
            vol_mode = "normal"
    else:
        vol_mode = "normal"

    # wick bias
    up_wicks = [_upper_wick(c) for c in seg]
    dn_wicks = [_lower_wick(c) for c in seg]
    avg_up = _safe_mean(up_wicks)
    avg_dn = _safe_mean(dn_wicks)
    wick_bias = _wick_bias(avg_up, avg_dn)

    return {
        "htf_dom": dom,
        "htf_drift": drift,
        "htf_vol_mode": vol_mode,
        "htf_wick_bias": wick_bias,
    }


def compute_features(candles_5m: List[Candle]) -> Dict[str, object]:
    """
    Hitung semua fitur behaviour dari candles 5m.
    Dipanggil sekali per candle close.
    """
    if not candles_5m:
        return {}

    window_len = behaviour_settings.feature_window
    segment = _window(candles_5m, window_len)

    basic = _compute_basic_stats(segment)
    avg_body = basic["avg_body"]
    avg_range = basic["avg_range"]
    avg_up = basic["avg_up_wick"]
    avg_dn = basic["avg_down_wick"]

    wick_bias = _wick_bias(avg_up, avg_dn)

    flow = _leg_flow(segment)
    micro_low, micro_high, pos_in_range = _compute_micro_range(segment)
    chop_score = _compute_chop_score(segment, avg_body)
    flush = _detect_flush(segment, avg_range, behaviour_settings.flush_lookback)
    htf = _compute_htf_virtual(candles_5m)

    last_close = segment[-1]["close"]

    features: Dict[str, object] = {
        # leg & flow
        "bull_body_sum": float(flow["bull_body_sum"]),
        "bear_body_sum": float(flow["bear_body_sum"]),
        "bull_count": float(flow["bull_count"]),
        "bear_count": float(flow["bear_count"]),
        "net_flow": float(flow["net_flow"]),

        # body & range
        "avg_body": float(avg_body),
        "avg_range": float(avg_range),
        "body_trend": float(basic["body_trend"]),
        "range_trend": float(basic["range_trend"]),

        # wick behaviour
        "avg_up_wick": float(avg_up),
        "avg_down_wick": float(avg_dn),
        "wick_bias": wick_bias,  # "buy"/"sell"/"mixed"

        # micro range
        "micro_low": float(micro_low),
        "micro_high": float(micro_high),
        "pos_in_range": float(pos_in_range),
        "last_price": float(last_close),

        # flush / extreme
        "has_flush_down": bool(flush["has_flush_down"]),
        "has_flush_up": bool(flush["has_flush_up"]),
        "flush_depth_down": float(flush["flush_depth_down"]),
        "flush_depth_up": float(flush["flush_depth_up"]),

        # chop
        "chop_score": float(chop_score),

        # HTF virtual
        "htf_dom": htf["htf_dom"],               # "bull"/"bear"/"none"
        "htf_drift": htf["htf_drift"],           # "up"/"down"/"flat"
        "htf_vol_mode": htf["htf_vol_mode"],     # "expand"/"contract"/"normal"
        "htf_wick_bias": htf["htf_wick_bias"],   # "buy"/"sell"/"mixed"
    }

    return features
