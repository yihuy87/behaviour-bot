# behaviour/analyzer.py
# Entry point analisa satu symbol (dipanggil tiap candle 5m close).

from __future__ import annotations

from typing import Dict, List, Optional

from binance.ohlc_buffer import Candle
from behaviour.behaviour_settings import behaviour_settings
from behaviour.features import compute_features
from behaviour.categories import eval_all_categories
from behaviour.scoring import aggregate_opportunity
from behaviour.levels import build_levels
from core.bot_state import state


def _tier_from_score(score: float) -> str:
    """
    Tier sederhana berdasarkan skor behaviour.
    """
    if score >= behaviour_settings.a_plus_score:
        return "A+"
    elif score >= behaviour_settings.min_score_to_send + 10:
        return "A"
    elif score >= behaviour_settings.min_score_to_send:
        return "B"
    else:
        return "NONE"


def _should_send_tier(tier: str) -> bool:
    order = {"NONE": 0, "B": 1, "A": 2, "A+": 3}
    min_tier = state.min_tier or "A"
    return order.get(tier, 0) >= order.get(min_tier, 2)


def _is_strong_bull_env(features: Dict[str, object]) -> bool:
    """
    Deteksi lingkungan bullish kuat (trend up) dari fitur behaviour:
    - HTF drift naik + dominasi bull
    - net_flow & bull_count > bear_count
    """
    htf_dom = features.get("htf_dom", "none")
    htf_drift = features.get("htf_drift", "flat")
    net_flow = float(features.get("net_flow", 0.0))
    bull_count = float(features.get("bull_count", 0.0))
    bear_count = float(features.get("bear_count", 0.0))

    strong_leg = bull_count > bear_count * 1.2 and net_flow > 0
    strong_htf = (htf_dom == "bull" and htf_drift == "up")

    return bool(strong_leg or strong_htf)


def _is_strong_bear_env(features: Dict[str, object]) -> bool:
    """
    Deteksi lingkungan bearish kuat (trend down) dari fitur behaviour.
    """
    htf_dom = features.get("htf_dom", "none")
    htf_drift = features.get("htf_drift", "flat")
    net_flow = float(features.get("net_flow", 0.0))
    bull_count = float(features.get("bull_count", 0.0))
    bear_count = float(features.get("bear_count", 0.0))

    strong_leg = bear_count > bull_count * 1.2 and net_flow < 0
    strong_htf = (htf_dom == "bear" and htf_drift == "down")

    return bool(strong_leg or strong_htf)


def _fails_anti_countertrend_filter(side: str, features: Dict[str, object]) -> bool:
    """
    Anti-countertrend behaviour-based:
    - Kalau environment bullish kuat dan sinyal mau SHORT,
      tapi tidak ada flush/rejection atas → TOLAK.
    - Kalau environment bearish kuat dan sinyal mau LONG,
      tapi tidak ada flush/rejection bawah → TOLAK.

    Tujuannya: tidak nge-short trend naik rapi seperti POLYX tadi,
    kecuali benar-benar ada extreme flush + rejection.
    """
    has_flush_down = bool(features.get("has_flush_down", False))
    has_flush_up = bool(features.get("has_flush_up", False))

    if side == "long":
        # environment turun, dan tidak ada flush bawah → jangan lawan trend
        if _is_strong_bear_env(features) and not has_flush_down:
            return True

    elif side == "short":
        # environment naik, dan tidak ada flush atas → jangan lawan trend
        if _is_strong_bull_env(features) and not has_flush_up:
            return True

    return False


def analyze_symbol_behaviour(symbol: str, candles_5m: List[Candle]) -> Optional[Dict]:
    """
    Analisa utama behaviour-based untuk satu symbol (TF 5m).
    Dipanggil sekali setiap candle 5m close.
    """
    if len(candles_5m) < behaviour_settings.min_candles:
        return None

    # 1) hitung fitur behaviour
    features = compute_features(candles_5m)
    if not features:
        return None

    # 2) evaluasi semua kategori (hemi-like, flush, drift, chop, dll)
    cats = eval_all_categories(features)

    # 3) agregasi score + arah
    opp = aggregate_opportunity(features, cats)
    score = float(opp.get("score", 0.0))
    direction = opp.get("direction")

    if not direction:
        return None

    # 4) filter score minimal (global opportunity filter)
    if score < behaviour_settings.min_score_to_send:
        return None

    side = "long" if direction == "long" else "short"

    # 5) Anti-countertrend filter (behaviour-based)
    if _fails_anti_countertrend_filter(side, features):
        # lingkungan trend kuat, tapi sinyal mau lawan arah tanpa flush → dibatalkan
        if state.debug:
            print(
                f"[{symbol}] Sinyal {side.upper()} dibatalkan oleh anti-countertrend "
                f"(htf_dom={features.get('htf_dom')}, drift={features.get('htf_drift')}, "
                f"flush_up={features.get('has_flush_up')}, flush_down={features.get('has_flush_down')})"
            )
        return None

    # 6) build level Entry/SL/TP
    levels = build_levels(side, candles_5m, features, opp)

    entry = levels["entry"]
    sl = levels["sl"]
    tp1 = levels["tp1"]
    tp2 = levels["tp2"]
    tp3 = levels["tp3"]
    sl_pct = levels["sl_pct"]
    lev_min = levels["lev_min"]
    lev_max = levels["lev_max"]

    # 7) validasi RR TP2 (harus cukup sehat)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    rr_tp2 = abs(tp2 - entry) / risk
    if rr_tp2 < behaviour_settings.min_rr_tp2:
        return None

    # (tidak ada lagi validasi max_sl_pct global;
    #  SL sudah behaviour-based di levels.py, berbasis range & noise)

    # 8) Tier & filter min_tier
    tier = _tier_from_score(score)
    if not _should_send_tier(tier):
        return None

    # 9) build teks Telegram
    direction_label = "LONG" if side == "long" else "SHORT"
    emoji = "🟢" if side == "long" else "🔴"

    sl_pct_text = f"{sl_pct:.2f}%"
    lev_text = f"{lev_min:.0f}x–{lev_max:.0f}x"

    max_age_candles = 6  # bisa dihubungkan ke behaviour_settings kalau mau
    approx_minutes = max_age_candles * 5
    valid_text = f"±{approx_minutes} menit" if approx_minutes > 0 else "singkat"

    # Risk calculator mini (fixed)
    # NOTE: di seluruh codebase kita menyimpan `sl_pct` sebagai *persen* (mis. 0.45 => 0.45%).
    # Untuk perhitungan posisi agar loss = 1% dari balance:
    #   sl_frac = sl_pct / 100.0   # convert to fraction (0.45% -> 0.0045)
    #   pos_mult = 0.01 / sl_frac  # 1% / SL_fraction
    if sl_pct > 0:
        sl_frac = sl_pct / 100.0
        # guard ekstra — kalau sl_frac sangat kecil (nyaris nol), hindari div/0 dan cap
        if sl_frac <= 0:
            pos_mult = float("inf")
        else:
            pos_mult = 0.01 / sl_frac
        example_balance = 100.0
        example_pos = pos_mult * example_balance
        risk_calc = (
            f"Risk Calc (contoh risiko 1%):\n"
            f"• SL : {sl_pct_text} → nilai posisi ≈ (1% / SL%) × balance ≈ {pos_mult:.3f}× balance\n"
            f"• Contoh balance 100 USDT → posisi ≈ {example_pos:.2f} USDT\n"
            f"(sesuaikan dengan balance & leverage kamu)"
        )
    else:
        risk_calc = "Risk Calc: SL% tidak valid (0), abaikan kalkulasi ini."

    text = (
        f"{emoji} BEHAVIOUR SIGNAL — {symbol.upper()} ({direction_label})\n"
        f"Entry : `{entry:.6f}`\n"
        f"SL    : `{sl:.6f}`\n"
        f"TP1   : `{tp1:.6f}`\n"
        f"TP2   : `{tp2:.6f}`\n"
        f"TP3   : `{tp3:.6f}`\n"
        f"Model : Behaviour-Based Market Engine\n"
        f"Rekomendasi Leverage : {lev_text} (SL {sl_pct_text})\n"
        f"Validitas Entry : {valid_text}\n"
        f"Tier : {tier} (Score {score:.0f})\n"
        f"{risk_calc}"
    )

    # 10) context HTF singkat (opsional)
    htf_ctx = {
        "htf_dom": features.get("htf_dom"),
        "htf_drift": features.get("htf_drift"),
        "htf_vol_mode": features.get("htf_vol_mode"),
        "htf_wick_bias": features.get("htf_wick_bias"),
    }

    return {
        "symbol": symbol.upper(),
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl_pct": sl_pct,
        "lev_min": lev_min,
        "lev_max": lev_max,
        "tier": tier,
        "score": score,
        "htf_context": htf_ctx,
        "categories": cats,
        "features": features,
        "message": text,
}
