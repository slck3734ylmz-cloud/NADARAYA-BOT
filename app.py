import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import datetime
from supabase import create_client, Client

# ================= KESİN AYARLAR =================
BOT_LEVERAGE = 200
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

exchange = ccxt.mexc({'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

# ================= GÜVENLİK =================
if "password_correct" not in st.session_state: st.session_state.password_correct = False
if not st.session_state.password_correct:
    pwd = st.text_input("Kyoun Şifre", type="password")
    if st.button("Sistemi Aç"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.password_correct = True
            st.rerun()
    st.stop()

st.set_page_config(page_title="Kyoun | Fix", layout="wide")

# ================= MATEMATİK =================
def fetch_clean_data(symbol, tf):
    raw = exchange.fetch_ohlcv(symbol, tf, limit=50)
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    # ATR Hesapla
    tr = pd.concat([df["Yuksek"]-df["Dusuk"], (df["Yuksek"]-df["Kapanis"].shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    # NW Bantları
    src = df["Kapanis"].values; n = len(src); h = 8; estimates = np.zeros(n)
    for i in range(n):
        w = np.exp(-((np.arange(i + 1) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * w) / np.sum(w)
    df["NW_Merkez"] = estimates
    std = (df["Kapanis"] - df["NW_Merkez"]).rolling(20).std()
    df["NW_Alt"] = df["NW_Merkez"] - (3.0 * std)
    df["NW_Ust"] = df["NW_Merkez"] + (3.0 * std)
    return df

# ================= STATE VE TAMİR (KRİTİK) =================
selected_symbol = "BTC/USDT:USDT"
prefix = f"{selected_symbol}_scalp_"

def force_repair_state():
    """Bakiye 100'den farklıysa veya hayalet pozisyon varsa temizle."""
    st.session_state[f"{selected_symbol}_balance_usd"] = 100.0
    st.session_state[f"{prefix}l_status"] = [False]*3
    st.session_state[f"{prefix}s_status"] = [False]*3
    st.session_state[f"{prefix}l_crypto"] = 0.0
    st.session_state[f"{prefix}s_crypto"] = 0.0
    st.session_state[f"{prefix}l_avg_price"] = 0.0
    st.session_state[f"{prefix}s_avg_price"] = 0.0
    st.session_state[f"{prefix}l_entry_prices"] = [0.0]*3
    st.session_state[f"{prefix}s_entry_prices"] = [0.0]*3
    
    if supabase:
        try:
            data = {
                "coin_symbol": selected_symbol, "balance_usd": 100.0,
                "scalp_l_crypto": 0.0, "scalp_l_avg_price": 0.0,
                "scalp_s_crypto": 0.0, "scalp_s_avg_price": 0.0,
                "scalp_l_margin_used": 0.0, "scalp_s_margin_used": 0.0,
                "trade_history": [], "log_history": []
            }
            for i in range(3):
                data[f"scalp_l_status_{i}"] = False; data[f"scalp_s_status_{i}"] = False
                data[f"scalp_l_entry_{i}"] = 0.0; data[f"scalp_s_entry_{i}"] = 0.0
            supabase.table("bot_state").upsert(data, on_conflict="coin_symbol").execute()
        except: pass

# İlk çalıştırmada state'i yükle
if f"{prefix}loaded" not in st.session_state:
    force_repair_state()
    st.session_state[f"{prefix}loaded"] = True

# ================= MOTOR =================
def run_engine(curr_p, dfs):
    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    atr = dfs["1m"].iloc[-1]["ATR"]
    # Gerçekçi Mesafeler (BTC için)
    tp_dist = max(atr * 2.0, curr_p * 0.001) # Minimum %0.1
    sl_dist = tp_dist * 1.5

    # --- ÇIKIŞ ---
    if any(l_status):
        avg = st.session_state[f"{prefix}l_avg_price"]
        if curr_p >= (avg + tp_dist) or (l_status[2] and curr_p <= (avg - sl_dist)):
            pnl = (curr_p - avg) * st.session_state[f"{prefix}l_crypto"]
            st.session_state[f"{selected_symbol}_balance_usd"] += pnl
            force_repair_state(); st.rerun()

    if any(s_status):
        avg = st.session_state[f"{prefix}s_avg_price"]
        if curr_p <= (avg - tp_dist) or (s_status[2] and curr_p >= (avg + sl_dist)):
            pnl = (avg - curr_p) * st.session_state[f"{prefix}s_crypto"]
            st.session_state[f"{selected_symbol}_balance_usd"] += pnl
            force_repair_state(); st.rerun()

    # --- GİRİŞ ---
    # Sadece 1m üzerinden basit giriş (test amaçlı)
    nw_alt = dfs["1m"].iloc[-1]["NW_Alt"]
    nw_ust = dfs["1m"].iloc[-1]["NW_Ust"]
    
    if curr_p <= nw_alt and not any(l_status):
        st.session_state[f"{prefix}l_avg_price"] = curr_p
        st.session_state[f"{prefix}l_crypto"] = SCALP_AMOUNTS[0]
        st.session_state[f"{prefix}l_status"][0] = True
    elif curr_p >= nw_ust and not any(s_status):
        st.session_state[f"{prefix}s_avg_price"] = curr_p
        st.session_state[f"{prefix}s_crypto"] = SCALP_AMOUNTS[0]
        st.session_state[f"{prefix}s_status"][0] = True
        
    return tp_dist, sl_dist

# ================= ARAYÜZ =================
@st.fragment(run_every="10s")
def render():
    try:
        ticker = exchange.fetch_ticker(selected_symbol)
        curr_p = ticker['last']
        df_1m = fetch_clean_data(selected_symbol, "1m")
        tp_d, sl_d = run_engine(curr_p, {"1m": df_1m})
        
        # Üst Bilgi
        st.markdown(f"""
            <div style="background:#161B22; border:1px solid #2A2E37; padding:10px; border-radius:10px; color:#B7BDC6;">
                🟢 <b>Kyoun Sistem:</b> Online | BTC: <b>${curr_p:,.2f}</b> | 
                Saat: {datetime.datetime.now().strftime('%H:%M:%S')}
            </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        
        # Metrikler
        c1, c2, c3 = st.columns(3)
        c1.metric("💳 Cüzdan Bakiyesi", f"${st.session_state[f'{selected_symbol}_balance_usd']:,.2f}")
        
        l_pos = st.session_state[f"{prefix}l_crypto"] > 0
        s_pos = st.session_state[f"{prefix}s_crypto"] > 0
        
        if l_pos or s_pos:
            c2.metric("🎯 Kar Hedefi", f"+${tp_d:,.2f}")
            c3.metric("🛡️ Zarar Durdur", f"-${sl_d:,.2f}")
            
            if l_pos:
                avg = st.session_state[f"{prefix}l_avg_price"]
                pnl = (curr_p - avg) * st.session_state[f"{prefix}l_crypto"]
                st.success(f"📈 **LONG AÇIK** | Maliyet: ${avg:,.2f} | PnL: **${pnl:+.4f}**")
            if s_pos:
                avg = st.session_state[f"{prefix}s_avg_price"]
                pnl = (avg - curr_p) * st.session_state[f"{prefix}s_crypto"]
                st.error(f"📉 **SHORT AÇIK** | Maliyet: ${avg:,.2f} | PnL: **${pnl:+.4f}**")
        else:
            c2.write("")
            c3.write("")
            st.info("⌛ **Sinyal Bekleniyor...** Her şey temizlendi ve sistem stabilize edildi.")

        if st.button("🔴 SİSTEMİ VE BAKİYEYİ SIFIRLA (100$)"):
            force_repair_state()
            st.rerun()

    except Exception as e: st.error(f"Hata: {e}")

render()
