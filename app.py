import streamlit as st
from streamlit.runtime.scriptrunner import RerunException
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import requests
from supabase import create_client, Client

# ================= TEMEL AYARLAR =================
BOT_LEVERAGE = 200
MEXC_TAKER_FEE_PCT = 0.0002
MIN_PROFIT_SAFETY_MULT = 3.0

TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "std_window": 18},
    "15m": {"limit": 110, "h": 8, "std_window": 20},
}

SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

SHOCK_WINDOWS = {
    "1dk":  {"bars_back": 1, "threshold_pct": 1.5},
    "5dk":  {"bars_back": 5, "threshold_pct": 2.5},
    "15dk": {"bars_back": 1, "threshold_pct": 4.0},
}
SHOCK_COOLDOWN_MINUTES = 30

MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

telegram_token = st.secrets.get("TELEGRAM_TOKEN", "")
telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

# ================= GİRİŞ EKRANI =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True
    
    st.markdown("""
        <style>
        .sheep-emoji { display: inline-block; animation: bounce 2.2s infinite; }
        @keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
        </style>
        <div style="text-align:center; padding:2rem;">
            <h1 class="sheep-emoji">🐑</h1>
            <h2>KYOUN TERMINAL</h2>
        </div>
    """, unsafe_allow_html=True)

    with st.form("login"):
        pwd = st.text_input("Şifre", type="password")
        if st.form_submit_button("Giriş"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.password_correct = True
                st.rerun()
            else: st.error("Hatalı!")
    return False

if not check_password(): st.stop()

st.set_page_config(page_title="Kyoun | Scalp", layout="wide")

# ================= YARDIMCI FONKSİYONLAR =================
def calculate_atr(df, period=14):
    high, low, close = df["Yuksek"], df["Dusuk"], df["Kapanis"]
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def nadaraya_watson_estimator(src, h=8):
    n = len(src)
    estimates = np.zeros(n)
    for i in range(n):
        weights = np.exp(-((np.arange(i + 1) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * weights) / np.sum(weights)
    return estimates

def fetch_tf_data(symbol, tf):
    p = TF_PARAMS[tf]
    raw = exchange.fetch_ohlcv(symbol, tf, limit=p["limit"])
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=p["h"])
    std = (df["Kapanis"] - df["NW_Merkez"]).ewm(span=p["std_window"]).std()
    df[f"NW_Ust_{tf}"] = df["NW_Merkez"] + (3.0 * std)
    df[f"NW_Alt_{tf}"] = df["NW_Merkez"] - (3.0 * std)
    df["ATR"] = calculate_atr(df)
    return df

def adjust_balance_atomic(delta):
    """Bakiyeyi sadece kar/zarar durumunda günceller."""
    if delta == 0: return
    if supabase:
        try:
            resp = supabase.rpc("adjust_balance", {"p_coin_symbol": "BTC/USDT:USDT", "p_delta": delta}).execute()
            if resp.data: st.session_state[f"BTC/USDT:USDT_balance_usd"] = resp.data
        except: pass
    else:
        st.session_state[f"BTC/USDT:USDT_balance_usd"] += delta

# ================= STATE YÖNETİMİ =================
selected_symbol = "BTC/USDT:USDT"
base_prefix = f"{selected_symbol}_"

def load_state():
    prefix = f"{base_prefix}scalp_"
    if f"{prefix}loaded" in st.session_state: return prefix
    
    st.session_state[f"{base_prefix}balance_usd"] = 100.0
    st.session_state[f"{prefix}l_status"] = [False]*3
    st.session_state[f"{prefix}s_status"] = [False]*3
    st.session_state[f"{prefix}l_avg_price"] = 0.0
    st.session_state[f"{prefix}s_avg_price"] = 0.0
    st.session_state[f"{prefix}l_crypto"] = 0.0
    st.session_state[f"{prefix}s_crypto"] = 0.0
    st.session_state[f"{prefix}l_entry_prices"] = [0.0]*3
    st.session_state[f"{prefix}s_entry_prices"] = [0.0]*3
    
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).execute()
            if q.data:
                d = q.data[0]
                st.session_state[f"{base_prefix}balance_usd"] = d.get("balance_usd", 100.0)
                for i in range(3):
                    st.session_state[f"{prefix}l_status"][i] = d.get(f"scalp_l_status_{i}", False)
                    st.session_state[f"{prefix}s_status"][i] = d.get(f"scalp_s_status_{i}", False)
                    st.session_state[f"{prefix}l_entry_prices"][i] = d.get(f"scalp_l_entry_{i}", 0.0)
                    st.session_state[f"{prefix}s_entry_prices"][i] = d.get(f"scalp_s_entry_{i}", 0.0)
                st.session_state[f"{prefix}l_avg_price"] = d.get("scalp_l_avg_price", 0.0)
                st.session_state[f"{prefix}s_avg_price"] = d.get("scalp_s_avg_price", 0.0)
                st.session_state[f"{prefix}l_crypto"] = d.get("scalp_l_crypto", 0.0)
                st.session_state[f"{prefix}s_crypto"] = d.get("scalp_s_crypto", 0.0)
        except: pass
    st.session_state[f"{prefix}loaded"] = True
    return prefix

def save_state():
    if not supabase: return
    prefix = f"{base_prefix}scalp_"
    data = {
        "coin_symbol": selected_symbol,
        "balance_usd": st.session_state[f"{base_prefix}balance_usd"],
        "scalp_l_avg_price": st.session_state[f"{prefix}l_avg_price"],
        "scalp_s_avg_price": st.session_state[f"{prefix}s_avg_price"],
        "scalp_l_crypto": st.session_state[f"{prefix}l_crypto"],
        "scalp_s_crypto": st.session_state[f"{prefix}s_crypto"],
    }
    for i in range(3):
        data[f"scalp_l_status_{i}"] = st.session_state[f"{prefix}l_status"][i]
        data[f"scalp_s_status_{i}"] = st.session_state[f"{prefix}s_status"][i]
        data[f"scalp_l_entry_{i}"] = st.session_state[f"{prefix}l_entry_prices"][i]
        data[f"scalp_s_entry_{i}"] = st.session_state[f"{prefix}s_entry_prices"][i]
    supabase.table("bot_state").upsert(data, on_conflict="coin_symbol").execute()

# ================= STRATEJİ MOTORU =================
def run_scalp_logic(current_price, dfs, is_live):
    prefix = f"{base_prefix}scalp_"
    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    
    # ATR ve Mesafe Hesapları
    atr_k3 = dfs["15m"].iloc[-2]["ATR"]
    tp_dist = max(atr_k3 * ATR_TP_MULT, current_price * 0.001)
    sl_dist = atr_k3 * ATR_SL_MULT

    # --- ÇIKIŞ KONTROLÜ ---
    # LONG Çıkış
    if any(l_status):
        avg = st.session_state[f"{prefix}l_avg_price"]
        amt = st.session_state[f"{prefix}l_crypto"]
        if current_price >= (avg + tp_dist) or (l_status[2] and current_price <= (avg - sl_dist)):
            pnl = (current_price - avg) * amt
            adjust_balance_atomic(pnl)
            st.session_state[f"{prefix}l_status"] = [False]*3
            st.session_state[f"{prefix}l_crypto"] = 0.0
            st.session_state[f"{prefix}l_avg_price"] = 0.0
            save_state()

    # SHORT Çıkış
    if any(s_status):
        avg = st.session_state[f"{prefix}s_avg_price"]
        amt = st.session_state[f"{prefix}s_crypto"]
        if current_price <= (avg - tp_dist) or (s_status[2] and current_price >= (avg + sl_dist)):
            pnl = (avg - current_price) * amt
            adjust_balance_atomic(pnl)
            st.session_state[f"{prefix}s_status"] = [False]*3
            st.session_state[f"{prefix}s_crypto"] = 0.0
            st.session_state[f"{prefix}s_avg_price"] = 0.0
            save_state()

    # --- GİRİŞ KONTROLÜ ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        # Long Giriş
        nw_alt = dfs[tfs[i]].iloc[-2][f"NW_Alt_{tfs[i]}"]
        if current_price <= nw_alt and not l_status[i] and (i==0 or l_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            prev_total = st.session_state[f"{prefix}l_avg_price"] * st.session_state[f"{prefix}l_crypto"]
            st.session_state[f"{prefix}l_crypto"] += amt
            st.session_state[f"{prefix}l_avg_price"] = (prev_total + amt*current_price) / st.session_state[f"{prefix}l_crypto"]
            st.session_state[f"{prefix}l_status"][i] = True
            st.session_state[f"{prefix}l_entry_prices"][i] = current_price
            save_state()
            break
        
        # Short Giriş
        nw_ust = dfs[tfs[i]].iloc[-2][f"NW_Ust_{tfs[i]}"]
        if current_price >= nw_ust and not s_status[i] and (i==0 or s_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            prev_total = st.session_state[f"{prefix}s_avg_price"] * st.session_state[f"{prefix}s_crypto"]
            st.session_state[f"{prefix}s_crypto"] += amt
            st.session_state[f"{prefix}s_avg_price"] = (prev_total + amt*current_price) / st.session_state[f"{prefix}s_crypto"]
            st.session_state[f"{prefix}s_status"][i] = True
            st.session_state[f"{prefix}s_entry_prices"][i] = current_price
            save_state()
            break

    return tp_dist, sl_dist

# ================= UI & FRAGMENT =================
scalp_prefix = load_state()

@st.fragment(run_every="10s")
def main_loop():
    ticker = exchange.fetch_ticker(selected_symbol)
    curr_p = ticker['last']
    
    dfs = {tf: fetch_tf_data(selected_symbol, tf) for tf in ["1m", "5m", "15m"]}
    tp_d, sl_d = run_scalp_logic(curr_p, dfs, False)
    
    # Header
    bal = st.session_state[f"{base_prefix}balance_usd"]
    c1, c2, c3 = st.columns(3)
    c1.metric("💳 Bakiye", f"${bal:,.2f}")
    c2.metric("BTC Fiyat", f"${curr_p:,.2f}")
    
    # Pozisyon Varsa TP/SL Göster
    l_active = any(st.session_state[f"{scalp_prefix}l_status"])
    s_active = any(st.session_state[f"{scalp_prefix}s_status"])
    
    if l_active or s_active:
        c3.info(f"🎯 Hedef: ${tp_d:.2f} | 🛡️ Stop: ${sl_d:.2f}")
    else:
        c3.write("⌛ Sinyal Bekleniyor...")

    # Pozisyon Detayları
    if l_active:
        with st.expander("📈 Açık LONG Pozisyon", expanded=True):
            avg = st.session_state[f"{scalp_prefix}l_avg_price"]
            pnl = (curr_p - avg) * st.session_state[f"{scalp_prefix}l_crypto"]
            st.write(f"Maliyet: {avg:,.2f} | K/Z: {pnl:+.4f} USDT")
    
    if s_active:
        with st.expander("📉 Açık SHORT Pozisyon", expanded=True):
            avg = st.session_state[f"{scalp_prefix}s_avg_price"]
            pnl = (avg - curr_p) * st.session_state[f"{scalp_prefix}s_crypto"]
            st.write(f"Maliyet: {avg:,.2f} | K/Z: {pnl:+.4f} USDT")

    # Grafik (Sadece 1m)
    import plotly.graph_objects as go
    df_plot = dfs["1m"].tail(50)
    fig = go.Figure(data=[go.Candlestick(x=df_plot['Zaman'], open=df_plot['Acilis'], high=df_plot['Yuksek'], low=df_plot['Dusuk'], close=df_plot['Kapanis'])])
    fig.update_layout(height=400, template="plotly_dark", margin=dict(l=0,r=0,t=0,b=0))
    st.plotly_chart(fig, use_container_width=True)

main_loop()
