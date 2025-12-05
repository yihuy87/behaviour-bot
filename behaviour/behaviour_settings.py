# behaviour/behaviour_settings.py
from dataclasses import dataclass


@dataclass
class BehaviourSettings:
    # --- Window & data requirements ---
    min_candles: int = 40            # minimal candle 5m untuk mulai analisa
    feature_window: int = 40         # berapa candle terakhir untuk fitur utama
    htf_window: int = 12             # ~1 jam (12 x 5m) untuk HTF virtual
    flush_lookback: int = 20         # lookback untuk deteksi flush / extreme

    # --- Flush / extreme behaviour ---
    # seberapa dalam flush dibanding range rata-rata supaya dianggap meaningful
    flush_min_depth_ratio: float = 0.35   # 35% dari avg_range

    # --- Chop detection ---
    # body kecil = body < small_body_factor * avg_body
    small_body_factor: float = 0.45
    # wick "cukup besar" relatif terhadap range candle
    big_wick_ratio: float = 0.35

    # bobot komponen untuk chop_score (0–100)
    chop_weight_color_flip: float = 0.4
    chop_weight_small_body: float = 0.3
    chop_weight_two_sided_wick: float = 0.3

    # batas nilai chop yang dianggap racun
    chop_high_threshold: float = 65.0     # di atas ini cenderung NO-TRADE
    chop_low_threshold: float = 35.0      # di bawah ini dianggap sehat

    # --- HTF virtual drift ---
    # toleransi supaya "flat" tidak terlalu sensitif
    htf_drift_tolerance_pct: float = 0.15  # 0.15% dari harga

    # --- Global scoring / filtering ---
    min_score_to_send: float = 70.0       # minimal opportunity_score kirim sinyal
    a_plus_score: float = 85.0            # batas A+ (opsional dipakai tier)
    max_sl_pct: float = 1.0               # batas atas SL% supaya sinyal masih masuk akal
    min_sl_pct: float = 0.10              # batas bawah SL% (jangan absurd terlalu kecil)

    # --- RR minimal (global) ---
    min_rr_tp2: float = 1.6               # minimal RR untuk TP2

    # --- Leverage rekomendasi (berdasarkan SL%) ---
    # (mirip gaya IMB/SMC tapi behaviour-based)
    def leverage_range_for_sl(self, sl_pct: float) -> tuple[float, float]:
        if sl_pct <= 0:
            return 5.0, 10.0
        if sl_pct <= 0.25:
            return 20.0, 30.0
        if sl_pct <= 0.40:
            return 15.0, 25.0
        if sl_pct <= 0.70:
            return 8.0, 15.0
        if sl_pct <= 1.20:
            return 5.0, 8.0
        return 3.0, 5.0


behaviour_settings = BehaviourSettings()
