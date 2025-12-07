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


def _compute_noise_floor(
    candles_5m: List[Candle],
    features: Dict[str, object],
) -> Tuple[float, float]:
    """
    Hitung:
    - noise_floor_abs: lantai minimal risk (Entry–SL) berbasis wick & range lokal
    - avg_range_local: rata-rata range lokal (untuk batas risk maksimum)

    Tujuannya:
    - cegah SL terlalu dekat dengan noise wajar (terutama pair wicky)
    - tapi tetap murni dari kelakuan harga (bukan % statis).
    """
    n = len(candles_5m)
    if n == 0:
        return 0.0, 0.0

    lookback = behaviour_settings.noise_lookback
    start = max(0, n - lookback)
    segment = candles_5m[start:]
    if not segment:
        return 0.0, 0.0

    ranges: List[float] = []
    upper_wicks: List[float] = []
    lower_wicks: List[float] = []

    for c in segment:
        high = c["high"]
        low = c["low"]
        open_ = c["open"]
        close = c["close"]

        r = high - low
        if r <= 0:
            continue
        ranges.append(r)
        upper_wicks.append(high - max(open_, close))
        lower_wicks.append(min(open_, close) - low)

    if not ranges:
        return 0.0, 0.0

    avg_range_local = sum(ranges) / len(ranges)

    def _avg(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    avg_upper = _avg(upper_wicks)
    avg_lower = _avg(lower_wicks)
    avg_wick = 0.5 * (avg_upper + avg_lower)

    # fallback: kalau avg_range_local aneh, pakai fitur global
    if avg_range_local <= 0:
        try:
            avg_range_feat = float(features.get("avg_range", 0.0))
        except Exception:
            avg_range_feat = 0.0
        if avg_range_feat > 0:
            avg_range_local = avg_range_feat

    # lantai noise = max(dari wick, dari range)
    wick_floor = (
        behaviour_settings.noise_wick_factor * avg_wick if avg_wick > 0 else 0.0
    )
    range_floor = (
        behaviour_settings.noise_range_factor * avg_range_local
        if avg_range_local > 0
        else 0.0
    )

    floor = max(wick_floor, range_floor)

    if floor <= 0:
        return 0.0, float(avg_range_local)

    return float(floor), float(avg_range_local)


def build_levels(
    side: Side,
    candles_5m: List[Candle],
    features: Dict[str, object],
    opp: Dict[str, object],
) -> Dict[str, float]:
    """
    Bangun Entry / SL / TP berdasarkan behaviour:
    - Entry pakai struktur candle terakhir (anti-FOMO)
    - SL di luar low/high candle + buffer struktur
    - SL minimal sejauh 'noise floor' (berbasis wick & range lokal)
    - SL maksimal dikontrol oleh max_risk_factor * avg_range_local (behaviour-based)
    - TP dinamis dari RR + skor peluang
    """
    last = candles_5m[-1]
    open_ = last["open"]
    close = last["close"]
    high = last["high"]
    low = last["low"]

    rng = max(high - low, 1e-9)
    last_price = close
    avg_range_feat = float(features.get("avg_range", rng))

    # ===================== ENTRY =====================
    if side == "long":
        # entry dekat bagian bawah candle (sedikit di atas low)
        raw_entry = low + 0.25 * rng
        entry = min(raw_entry, last_price)  # jangan di atas harga sekarang
        # buffer struktur: kombinasi range candle & avg_range
        base_buffer = 0.15 * rng + 0.10 * avg_range_feat
        sl_raw = low - base_buffer
    else:
        # short: entry dekat bagian atas candle (sedikit di bawah high)
        raw_entry = high - 0.25 * rng
        entry = max(raw_entry, last_price)  # jangan di bawah harga sekarang
        base_buffer = 0.15 * rng + 0.10 * avg_range_feat
        sl_raw = high + base_buffer

    if entry == 0:
        # fallback ekstrem (jarang terjadi)
        entry = last_price

    # ===================== NOISE FLOOR & VOLATILITY =====================
    noise_floor_abs, avg_range_local = _compute_noise_floor(candles_5m, features)
    if avg_range_local <= 0:
        avg_range_local = avg_range_feat

    # Risk awal (sebelum adjust)
    risk = abs(entry - sl_raw)

    # 1) Jika risk lebih kecil dari noise floor → SL dijauhkan
    if noise_floor_abs > 0.0 and risk < noise_floor_abs:
        if side == "long":
            sl_raw = entry - noise_floor_abs
        else:
            sl_raw = entry + noise_floor_abs
        risk = abs(entry - sl_raw)

    # 2) Jika risk terlalu besar vs volatilitas lokal → tarik SL mendekat
    if avg_range_local > 0 and risk > behaviour_settings.max_risk_factor * avg_range_local:
        max_risk_allowed = behaviour_settings.max_risk_factor * avg_range_local
        if side == "long":
            sl_raw = entry - max_risk_allowed
        else:
            sl_raw = entry + max_risk_allowed
        risk = abs(entry - sl_raw)

    # ===================== FINAL SL & SL% =====================
    sl = sl_raw

    if risk <= 0:
        # fallback kecil kalau ada kasus ekstrem
        risk = abs(entry) * 0.003
        if side == "long":
            sl = entry - risk
        else:
            sl = entry + risk

    sl_pct = (risk / entry) * 100.0 if entry != 0 else 0.0

    # ===================== RR & TP (DINAMIS) =====================
    rr1, rr2, rr3 = _dynamic_rr_factors(float(opp.get("score", 0.0)))

    if side == "long":
        tp1 = entry + rr1 * risk
        tp2 = entry + rr2 * risk
        tp3 = entry + rr3 * risk
    else:
        tp1 = entry - rr1 * risk
        tp2 = entry - rr2 * risk
        tp3 = entry - rr3 * risk

    # ===================== LEVERAGE (HANYA OUTPUT) =====================
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
