# behaviour/levels.py
# Bangun Entry / SL / TP dinamis berdasarkan behaviour.

from __future__ import annotations

from typing import Dict, List, Literal, Tuple

from binance.ohlc_buffer import Candle
from behaviour.behaviour_settings import behaviour_settings


Side = Literal["long", "short"]


def _dynamic_rr_factors(score: float) -> Tuple[float, float, float]:
    """
    Faktor RR (TP1, TP2, TP3) dinamis berdasarkan skor peluang.
    Score tinggi → TP2/TP3 boleh lebih jauh.
    """
    # normalisasi ke 0–1
    s_norm = max(0.0, min(score, 100.0)) / 100.0

    min_rr2 = behaviour_settings.min_rr_tp2
    max_rr2 = min_rr2 + 0.8  # misal 1.6 → 2.4

    rr2 = min_rr2 + (max_rr2 - min_rr2) * s_norm
    rr1 = 0.7 * rr2
    rr3 = rr2 + 0.8

    return rr1, rr2, rr3


def _adjust_sl_to_bounds(side: Side, entry: float, sl_raw: float) -> Tuple[float, float]:
    """
    Sesuaikan SL supaya SL% tidak terlalu kecil/terlalu besar:
    - min_sl_pct <= SL% <= max_sl_pct
    """
    if entry <= 0:
        return sl_raw, 0.0

    risk = abs(entry - sl_raw)
    sl_pct = (risk / entry) * 100.0 if entry != 0 else 0.0

    min_sl = behaviour_settings.min_sl_pct
    max_sl = behaviour_settings.max_sl_pct

    # terlalu kecil → longgarkan SL
    if sl_pct < min_sl:
        risk_target = entry * min_sl / 100.0
        if side == "long":
            sl = entry - risk_target
        else:
            sl = entry + risk_target
        sl_pct = min_sl
        return sl, sl_pct

    # terlalu besar → SL didekatkan ke entry
    if sl_pct > max_sl:
        risk_target = entry * max_sl / 100.0
        if side == "long":
            sl = entry - risk_target
        else:
            sl = entry + risk_target
        sl_pct = max_sl
        return sl, sl_pct

    return sl_raw, sl_pct


def build_levels(
    side: Side,
    candles_5m: List[Candle],
    features: Dict[str, object],
    opp: Dict[str, object],
) -> Dict[str, float]:
    """
    Bangun Entry / SL / TP berdasarkan behaviour:
    - Entry pakai struktur candle terakhir (dan sedikit anti-FOMO)
    - SL di luar low/high candle + buffer → disesuaikan ke min/max SL%
    - TP dinamis dari RR + skor peluang
    """
    last = candles_5m[-1]
    open_ = last["open"]
    close = last["close"]
    high = last["high"]
    low = last["low"]

    rng = max(high - low, 1e-9)
    last_price = close
    avg_range = float(features.get("avg_range", rng))

    # Entry:
    if side == "long":
        # entry dekat bagian bawah tubuh/low candle
        raw_entry = low + 0.25 * rng
        entry = min(raw_entry, last_price)  # jangan di atas harga sekarang
        # SL sedikit di bawah low, awalnya gunakan 15% range + sedikit noise dari avg_range
        base_buffer = 0.15 * rng + 0.10 * avg_range
        sl_raw = low - base_buffer
    else:
        raw_entry = high - 0.25 * rng
        entry = max(raw_entry, last_price)  # jangan di bawah harga sekarang
        base_buffer = 0.15 * rng + 0.10 * avg_range
        sl_raw = high + base_buffer

    if entry == 0:
        # fallback ekstrem (jarang terjadi)
        entry = last_price

    # Sesuaikan SL agar SL% berada di [min_sl_pct, max_sl_pct]
    sl, sl_pct = _adjust_sl_to_bounds(side, entry, sl_raw)

    # Hitung risk & RR dinamis
    risk = abs(entry - sl)
    if risk <= 0:
        # fallback kecil
        risk = abs(entry) * 0.003
        if side == "long":
            sl = entry - risk
        else:
            sl = entry + risk
        sl_pct = (risk / entry) * 100.0 if entry != 0 else 0.0

    rr1, rr2, rr3 = _dynamic_rr_factors(float(opp.get("score", 0.0)))

    if side == "long":
        tp1 = entry + rr1 * risk
        tp2 = entry + rr2 * risk
        tp3 = entry + rr3 * risk
    else:
        tp1 = entry - rr1 * risk
        tp2 = entry - rr2 * risk
        tp3 = entry - rr3 * risk

    # rekomendasi leverage
    lev_min, lev_max = behaviour_settings.leverage_range_for_sl(sl_pct)

    return {
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "tp3": float(tp3),
        "sl_pct": float(sl_pct),
        "lev_min": float(lev_min),
        "lev_max": float(lev_max),
    }
