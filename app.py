import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import datetime

# ================= AYARLAR =================
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015] 
MIN_STAGE_GAP_ATR_MULT = 0.5 # Kademeler arası en az 0.5 ATR mesafe olmalı

# ================= MOTOR (MESAFE KONTROLLÜ) =================
def run_advanced_engine(curr_p, dfs, s):
    # s = st.session_state.state
    atr_k3 = dfs["15m"].iloc[-1]["ATR"]
    
    # 1. Kademeler arası güvenli mesafeyi hesapla
    # (Örneğin BTC 60k ise, ATR 100 ise; kademeler arası en az 50$ olmalı)
    min_gap = atr_k3 * MIN_STAGE_GAP_ATR_MULT

    # --- ALIŞ MANTIĞI ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        # Eğer bu kademe zaten doluysa atla
        if s["l_status"][i]:
            continue
            
        # Eğer bu K2 veya K3 ise, bir önceki kademeden yeterince uzakta mıyız?
        distance_ok = True
        if i > 0 and s["l_status"][i-1]:
            last_entry = s["l_entry_prices"][i-1]
            if abs(curr_p - last_entry) < min_gap:
                distance_ok = False # Çok yakın, alma!

        # NW Bandına değdi mi?
        nw_alt = dfs[tfs[i]].iloc[-1]["NW_Alt"]
        
        if curr_p <= nw_alt and distance_ok:
            # ŞARTLAR UYGUN: Alım yap
            amt = SCALP_AMOUNTS[i]
            s["l_avg"] = ((s["l_avg"] * s["l_crypto"]) + (amt * curr_p)) / (s["l_crypto"] + amt)
            s["l_crypto"] += amt
            s["l_status"][i] = True
            s["l_entry_prices"][i] = curr_p
            return f"✅ K{i+1} Alındı @ {curr_p}"
            
    return "🔎 Sinyal taranıyor / Mesafe korunuyor"

# ================= ARAYÜZ (GÖRSEL TAKİP) =================
st.set_page_config(page_title="Kyoun Akıllı Takip", layout="wide")

if "adv_state" not in st.session_state:
    st.session_state.adv_state = {
        "l_status": [False]*3, 
        "l_entry_prices": [0.0]*3,
        "l_avg": 0.0, 
        "l_crypto": 0.0
    }

@st.fragment(run_every="10s")
def dashboard():
    # Bu kısım basitleştirilmiştir, gerçek veriler borsa bağlantısından gelir.
    st.title("🐑 Kyoun Akıllı Kademe Yönetimi")
    s = st.session_state.adv_state

    # Durum Göstergesi
    c1, c2, c3 = st.columns(3)
    for i in range(3):
        with [c1, c2, c3][i]:
            if s["l_status"][i]:
                st.success(f"K{i+1} DOLU\nFiyat: {s['l_entry_prices'][i]:,.2f}")
            else:
                st.info(f"K{i+1} BEKLİYOR\n(Güvenlik Kilidi Aktif)")

    st.divider()
    
    # BİLGİ KUTUSU
    with st.expander("ℹ️ Bot Şu An Nasıl Karar Veriyor?", expanded=True):
        st.write("""
        - **Her kademe sadece 1 kez alınır.** Pozisyon kârla kapanmadan aynı kademe tekrar açılmaz.
        - **Mesafe Kontrolü:** K2'nin alınması için sadece bandın altına düşmesi yetmez. 
          Aynı zamanda K1 alım fiyatından yeterince uzaklaşmış olması gerekir.
        - **Neden?** Çünkü piyasa yatay giderken tüm kademelerin aynı noktada dolmasını engelleyerek kasayı koruyoruz.
        """)

dashboard()
