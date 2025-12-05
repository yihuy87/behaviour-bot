# behaviour/scoring.py
# Gabungkan hasil kategori behaviour menjadi opportunity final.

from __future__ import annotations

from typing import Dict, Literal, Optional

from behaviour.behaviour_settings import behaviour_settings

Direction = Optional[Literal["long", "short"]]


def _choose_direction(cats: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    """
    Ambil semua bias kategori dan pilih arah final.
    Pakai weighting implicit dari score masing-masing kategori.
    """
    bias_long_score = 0.0
    bias_short_score = 0.0

    for name, res in cats.items():
        score = float(res.get("score", 0.0))
        bias = res.get("bias")
        if bias == "long":
            bias_long_score += score
        elif bias == "short":
            bias_short_score += score

    # kalau dua-duanya lemah → no direction
    if bias_long_score < 1.0 and bias_short_score < 1.0:
        return {
            "direction": None,
            "bias_long_score": bias_long_score,
            "bias_short_score": bias_short_score,
        }

    # cek dominasi
    # butuh selisih yang cukup, kalau enggak dianggap konflik → no trade
    if bias_long_score > bias_short_score * 1.3:
        direction: Direction = "long"
    elif bias_short_score > bias_long_score * 1.3:
        direction = "short"
    else:
        direction = None

    return {
        "direction": direction,
        "bias_long_score": bias_long_score,
        "bias_short_score": bias_short_score,
    }


def aggregate_opportunity(
    features: Dict[str, object],
    cats: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    """
    Gabung semua kategori → skor final & arah.
    Tidak mengurus SL/RR di sini, hanya behaviour murni.
    """
    # 1) tentukan arah dulu
    dir_info = _choose_direction(cats)
    direction: Direction = dir_info["direction"]
    bias_long_score = float(dir_info["bias_long_score"])
    bias_short_score = float(dir_info["bias_short_score"])

    # 2) score dasar: hanya skor kategori yang relevan + MC sebagai konteks
    score_mc = float(cats.get("mc", {}).get("score", 0.0))

    if direction == "long":
        base_score = bias_long_score + 0.5 * score_mc
    elif direction == "short":
        base_score = bias_short_score + 0.5 * score_mc
    else:
        # kalau arah tidak jelas, total score juga dianggap nol
        return {
            "score": 0.0,
            "direction": None,
            "components": cats,
            "bias_long_score": bias_long_score,
            "bias_short_score": bias_short_score,
        }

    # 3) adjust dengan chop
    chop = float(features.get("chop_score", 0.0))
    if chop >= behaviour_settings.chop_high_threshold:
        base_score *= 0.35
    elif chop >= behaviour_settings.chop_low_threshold:
        base_score *= 0.7

    # 4) adjust dengan HTF (jangan terlalu maksa lawan HTF kuat)
    htf_dom = str(features.get("htf_dom", "none"))
    htf_drift = str(features.get("htf_drift", "flat"))

    if direction == "long":
        if htf_dom == "bear" and htf_drift == "down":
            base_score *= 0.6
    elif direction == "short":
        if htf_dom == "bull" and htf_drift == "up":
            base_score *= 0.6

    score = float(max(0.0, min(base_score, 150.0)))

    return {
        "score": score,
        "direction": direction,
        "components": cats,
        "bias_long_score": bias_long_score,
        "bias_short_score": bias_short_score,
    }
