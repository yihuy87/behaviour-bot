# behaviour/categories.py
# Evaluasi semua kategori behaviour (ELR/FAR/CEC/MC/VSDE/AWP/HBP)
# dari fitur yang sudah dihitung di features.py

from __future__ import annotations

from typing import Dict, Optional, Tuple

from behaviour.behaviour_settings import behaviour_settings

Bias = Optional[str]  # "long" / "short" / None


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


# ===============================
# 1) ELR — Exhausted Leg Reversal
# ===============================

def eval_elr(features: Dict[str, object]) -> Dict[str, object]:
    """
    Exhausted Leg Reversal:
    - Ada leg jelas (net_flow besar, bull/bear_count cukup)
    - Body_trend melemah
    - Wick mulai condong ke lawan arah
    - Harga dekat ekstrem micro range
    """
    net_flow = float(features.get("net_flow", 0.0))
    bull_count = float(features.get("bull_count", 0.0))
    bear_count = float(features.get("bear_count", 0.0))
    body_trend = float(features.get("body_trend", 0.0))
    wick_bias = str(features.get("wick_bias", "mixed"))
    pos_in_range = float(features.get("pos_in_range", 0.5))
    chop_score = float(features.get("chop_score", 0.0))

    total_candles = bull_count + bear_count

    score = 0.0
    bias: Bias = None

    # butuh leg minimal beberapa candle
    if total_candles < 6:
        return {"score": 0.0, "bias": None}

    # kekuatan leg (kasar)
    leg_strength = abs(net_flow) / max(total_candles, 1.0)

    if leg_strength <= 0:
        return {"score": 0.0, "bias": None}

    # Leg turun → kandidat long
    if net_flow < 0:
        # exhaustion: body melemah (body_trend < 0)
        if body_trend < -0.05:
            # wick_bias should mulai ke buy
            if wick_bias in ("buy", "mixed"):
                # posisi dekat bawah range
                if pos_in_range <= 0.35:
                    base = 15.0
                    # semakin dekat low semakin besar
                    extra = (0.35 - pos_in_range) * 40.0  # max ~14
                    score = base + max(0.0, extra)
                    bias = "long"

    # Leg naik → kandidat short
    elif net_flow > 0:
        if body_trend < -0.05:
            if wick_bias in ("sell", "mixed"):
                if pos_in_range >= 0.65:
                    base = 15.0
                    extra = (pos_in_range - 0.65) * 40.0
                    score = base + max(0.0, extra)
                    bias = "short"

    # penalti chop tinggi
    if score > 0 and chop_score > behaviour_settings.chop_high_threshold:
        score *= 0.4  # kuat tapi di chop → kecilin

    # clamp
    score = float(max(0.0, min(score, 25.0)))
    return {"score": score, "bias": bias}


# =========================================
# 2) FAR — Flush + Absorption Reversal
# =========================================

def eval_far(features: Dict[str, object]) -> Dict[str, object]:
    """
    Flush + Absorption Reversal:
    - has_flush_down / has_flush_up
    - kedalaman flush signifikan (flush_depth_* besar)
    - posisi dekat ekstrem
    - wick_bias mendukung (buy di bawah, sell di atas)
    """
    has_fd = bool(features.get("has_flush_down", False))
    has_fu = bool(features.get("has_flush_up", False))
    depth_down = float(features.get("flush_depth_down", 0.0))
    depth_up = float(features.get("flush_depth_up", 0.0))
    pos_in_range = float(features.get("pos_in_range", 0.5))
    wick_bias = str(features.get("wick_bias", "mixed"))
    chop_score = float(features.get("chop_score", 0.0))

    score = 0.0
    bias: Bias = None

    # kandidat long (flush down)
    if has_fd and pos_in_range <= 0.40:
        # kedalaman flush lebih dalam → score besar
        base = 18.0
        extra = depth_down * 20.0  # contoh scaling
        score = base + extra
        # wick buy bias menaikkan lagi
        if wick_bias == "buy":
            score += 4.0
        elif wick_bias == "mixed":
            score += 1.0
        bias = "long"

    # kandidat short (flush up)
    if has_fu and pos_in_range >= 0.60:
        base = 18.0
        extra = depth_up * 20.0
        s2 = base + extra
        if wick_bias == "sell":
            s2 += 4.0
        elif wick_bias == "mixed":
            s2 += 1.0

        # jika kedua sisi flush (jarang), pilih yang lebih kuat
        if s2 > score:
            score = s2
            bias = "short"

    # penalti chop
    if score > 0 and chop_score > behaviour_settings.chop_high_threshold:
        score *= 0.5

    score = float(max(0.0, min(score, 30.0)))
    return {"score": score, "bias": bias}


# ========================================================
# 3) CEC — Compression → Expansion Continuation
# ========================================================

def eval_cec(features: Dict[str, object]) -> Dict[str, object]:
    """
    Compression → Expansion Continuation:
    - range_trend turun (compression)
    - net_flow condong
    - HTF searah
    """
    net_flow = float(features.get("net_flow", 0.0))
    body_trend = float(features.get("body_trend", 0.0))
    range_trend = float(features.get("range_trend", 0.0))
    htf_dom = str(features.get("htf_dom", "none"))
    htf_drift = str(features.get("htf_drift", "flat"))
    chop_score = float(features.get("chop_score", 0.0))

    score = 0.0
    bias: Bias = None

    # butuh bias dasar
    if abs(net_flow) <= 0:
        return {"score": 0.0, "bias": None}

    # compression: range_trend < 0 (second half lebih kecil dari first half)
    if range_trend >= -0.05:
        return {"score": 0.0, "bias": None}

    # arah continuation:
    if net_flow > 0:
        # bull bias
        bias = "long"
    else:
        bias = "short"

    base = 10.0

    # HTF searah?
    if bias == "long":
        if htf_dom == "bull" or htf_drift == "up":
            base += 6.0
    else:
        if htf_dom == "bear" or htf_drift == "down":
            base += 6.0

    # body_trend yang tidak drop terlalu dalam → healthy consolidation
    if body_trend > -0.2:
        base += 2.0

    score = base

    # penalti chop
    if chop_score > behaviour_settings.chop_high_threshold:
        score *= 0.3

    score = float(max(0.0, min(score, 20.0)))
    return {"score": score, "bias": bias}


# ==========================================
# 4) MC — Momentum Collapse
# ==========================================

def eval_mc(features: Dict[str, object]) -> Dict[str, object]:
    """
    Momentum Collapse:
    - sebelumnya net_flow cukup kuat
    - body_trend turun tajam
    - wick mulai dua sisi (wick_bias mixed)
    - tidak memberi bias kuat, hanya sinyal bahwa leg lama capek
    """
    net_flow = float(features.get("net_flow", 0.0))
    body_trend = float(features.get("body_trend", 0.0))
    wick_bias = str(features.get("wick_bias", "mixed"))
    chop_score = float(features.get("chop_score", 0.0))

    score = 0.0
    bias: Bias = None

    # leg cukup kuat sebelumnya
    if abs(net_flow) <= 0:
        return {"score": 0.0, "bias": None}

    # body turun tajam
    if body_trend > -0.2:
        return {"score": 0.0, "bias": None}

    # wick mulai mixed → tanda tarik menarik
    if wick_bias != "mixed":
        return {"score": 0.0, "bias": None}

    base = 8.0

    # di chop mungkin MC sering muncul, skor kecil saja
    if chop_score > behaviour_settings.chop_high_threshold:
        base *= 0.5

    score = float(max(0.0, min(base, 12.0)))
    return {"score": score, "bias": bias}  # bias None → hanya sinyal context


# =======================================================
# 5) VSDE — Volatility Squeeze → Directional Explosion
# =======================================================

def eval_vsde(features: Dict[str, object]) -> Dict[str, object]:
    """
    Volatility Squeeze → Directional Explosion:
    - range_trend negatif (squeeze)
    - lalu sekarang (di analyzer) ada move besar (ini lebih cocok dilihat lewat RR & levels)
    Di level feature saja, kita hanya memberi sinyal bahwa squeeze sedang terjadi
    & arah bias-nya.
    """
    net_flow = float(features.get("net_flow", 0.0))
    range_trend = float(features.get("range_trend", 0.0))
    htf_drift = str(features.get("htf_drift", "flat"))
    chop_score = float(features.get("chop_score", 0.0))

    score = 0.0
    bias: Bias = None

    # squeeze: range_trend cukup negatif
    if range_trend > -0.10:
        return {"score": 0.0, "bias": None}

    # arah preferensi berdasar net_flow + HTF drift
    if net_flow > 0:
        bias = "long"
    elif net_flow < 0:
        bias = "short"
    else:
        bias = None

    base = 7.0

    # kalau HTF drift searah, naikkan sedikit
    if bias == "long" and htf_drift == "up":
        base += 3.0
    elif bias == "short" and htf_drift == "down":
        base += 3.0

    # penalti chop
    if chop_score > behaviour_settings.chop_high_threshold:
        base *= 0.4

    score = float(max(0.0, min(base, 12.0)))
    return {"score": score, "bias": bias}


# =================================
# 6) AWP — Asymmetric Wick Pressure
# =================================

def eval_awp(features: Dict[str, object]) -> Dict[str, object]:
    """
    Asymmetric Wick Pressure:
    - lower wick >> upper wick → tekanan beli
    - upper wick >> lower wick → tekanan jual
    """
    avg_up = float(features.get("avg_up_wick", 0.0))
    avg_dn = float(features.get("avg_down_wick", 0.0))
    wick_bias = str(features.get("wick_bias", "mixed"))
    chop_score = float(features.get("chop_score", 0.0))

    score = 0.0
    bias: Bias = None

    if avg_up <= 0 and avg_dn <= 0:
        return {"score": 0.0, "bias": None}

    if wick_bias == "buy":
        bias = "long"
        # makin besar ratio dn/up makin besar score
        if avg_up > 0:
            ratio = avg_dn / avg_up
            base = 6.0 + min(ratio, 3.0) * 2.0
        else:
            base = 10.0
        score = base
    elif wick_bias == "sell":
        bias = "short"
        if avg_dn > 0:
            ratio = avg_up / avg_dn
            base = 6.0 + min(ratio, 3.0) * 2.0
        else:
            base = 10.0
        score = base
    else:
        return {"score": 0.0, "bias": None}

    if chop_score > behaviour_settings.chop_high_threshold:
        score *= 0.7

    score = float(max(0.0, min(score, 15.0)))
    return {"score": score, "bias": bias}


# ===========================================
# 7) HBP — HTF Behaviour Pivot
# ===========================================

def eval_hbp(features: Dict[str, object]) -> Dict[str, object]:
    """
    HTF Behaviour Pivot (virtual):
    - dominasi HTF melemah
    - drift mulai berbalik atau flatten
    - wick_bias HTF berganti sisi
    Catatan: di sini kita cuma beri indikasi & bias, skor sedang (untuk amplifier).
    """
    htf_dom = str(features.get("htf_dom", "none"))
    htf_drift = str(features.get("htf_drift", "flat"))
    htf_wick_bias = str(features.get("htf_wick_bias", "mixed"))

    score = 0.0
    bias: Bias = None

    # Kalau HTF tidak punya dominasi jelas → tidak ada pivot yang berarti
    if htf_dom == "none":
        return {"score": 0.0, "bias": None}

    # Pivot long:
    # - sebelumnya bear (dom = bear / drift down)
    # - sekarang wick_bias mulai "buy" atau mixed
    if (htf_dom == "bear" or htf_drift == "down") and htf_wick_bias == "buy":
        bias = "long"
        score = 8.0

    # Pivot short:
    if (htf_dom == "bull" or htf_drift == "up") and htf_wick_bias == "sell":
        # kalau sebelumnya sudah set long, pilih yang lebih kuat / treat as conflict
        if bias == "long":
            # konflik pivot → jangan kasih bias tapi raise sedikit score (noise pivot)
            bias = None
            score = 4.0
        else:
            bias = "short"
            score = 8.0

    score = float(max(0.0, min(score, 10.0)))
    return {"score": score, "bias": bias}


# ===========================================
# Wrapper: evaluasi semua kategori sekaligus
# ===========================================

def eval_all_categories(features: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    """
    Return dict:
    {
      "elr": {"score": float, "bias": "long"/"short"/None},
      "far": {...},
      ...
    }
    """
    return {
        "elr": eval_elr(features),
        "far": eval_far(features),
        "cec": eval_cec(features),
        "mc": eval_mc(features),
        "vsde": eval_vsde(features),
        "awp": eval_awp(features),
        "hbp": eval_hbp(features),
    }
