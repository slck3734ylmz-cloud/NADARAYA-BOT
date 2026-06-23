import streamlit as st
from streamlit.runtime.scriptrunner import RerunException
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= TEMEL AYARLAR =================
BOT_LEVERAGE = 200
MEXC_TAKER_FEE_PCT = 0.0002
TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "std_window": 18},
    "15m": {"limit": 110, "h": 8, "std_window": 20},
}
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015] # Toplam 0.0020 BTC
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

# API & DB BAĞLANTILARI
MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET,
    'enableRateLimit': True, 'options': {'defaultType': 'swap'}
})

# ================= GÜVENLİK VE STİL =================
if "password_correct" not in st.session_state: st.session_state.password_correct = False
if not st.session_state.password_correct:
    st.title("🐑 Kyoun Terminal Login")
    pwd = st.text_input("Şifre", type="password")
    if st.button("Giriş Yap"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.password_correct = True
            st.rerun()
    st.stop()

st.set_page_config(page_title="Kyoun | Professional Scalp", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0B0E11; color: #B7BDC6; }
    div[data-testid="stMetric"] { background:#161B22; border:1px solid #2A2E37; border-radius:10px; padding:15px; }
    .log-box { background: #1c2128; border: 1px solid #444c56; padding: 10px; border-radius: 5px; height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; }
    </style>
""", unsafe_allow_html=True)

# ================= MATEMATİKSEL FONKSİYONLAR =================
def nadaraya_watson_estimator(src, h=8):
    n = len(src); estimates = np.zeros(n)
    for i in range(n):
        w = np.exp(-((np.arange(i + 1) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * w) / np.sum(w)
    return estimates

def fetch_tf_data(symbol, tf):
    p = TF_PARAMS[tf]
    raw = exchange.fetch_ohlcv(symbol, tf, limit=p["limit"])
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=p["h"])
    std = (df["Kapanis"] - df["NW_Merkez"]).rolling(p["std_window"]).std()
    df["NW_Alt"] = df["NW_Merkez"] - (3.0 * std)
    df["NW_Ust"] = df["NW_Merkez"] + (3.0 * std)
    tr = pd.concat([df["Yuksek"]-df["Dusuk"], (df["Yuksek"]-df["Kapanis"].shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return df

# ================= STATE VE DB YÖNETİMİ =================
selected_symbol = "BTC/USDT:USDT"
prefix = f"{selected_symbol}_scalp_"

def load_state():
    if f"{prefix}loaded" in st.session_state: return
    # Varsayılan değerler
    st.session_state[f"{selected_symbol}_balance"] = 100.0
    st.session_state[f"{prefix}history"] = []
    st.session_state[f"{prefix}logs"] = ["Sistem başlatıldı..."]
    st.session_state[f"{prefix}l_status"] = [False]*3
    st.session_state[f"{prefix}l_crypto"] = 0.0
    st.session_state[f"{prefix}l_avg"] = 0.0
    
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).execute()
            if q.data:
                d = q.data[0]
                st.session_state[f"{selected_symbol}_balance"] = d.get("balance_usd", 100.0)
                st.session_state[f"{prefix}history"] = d.get("trade_history", [])
                st.session_state[f"{prefix}l_crypto"] = d.get("scalp_l_crypto", 0.0)
                st.session_state[f"{prefix}l_avg"] = d.get("scalp_l_avg_price", 0.0)
                for i in range(3): st.session_state[f"{prefix}l_status"][i] = d.get(f"scalp_l_status_{i}", False)
        except: pass
    st.session_state[f"{prefix}loaded"] = True

def save_state():
    if not supabase: return
    try:
        data = {
            "coin_symbol": selected_symbol,
            "balance_usd": float(st.session_state[f"{selected_symbol}_balance"]),
            "trade_history": st.session_state[f"{prefix}history"],
            "scalp_l_crypto": float(st.session_state[f"{prefix}l_crypto"]),
            "scalp_l_avg_price": float(st.session_state[f"{prefix}l_avg"]),
            "scalp_l_margin_used": 0.0, "scalp_s_margin_used": 0.0, "log_history": []
        }
        for i in range(3): data[f"scalp_l_status_{i}"] = bool(st.session_state[f"{prefix}l_status"][i])
        supabase.table("bot_state").upsert(data, on_conflict="coin_symbol").execute()
    except: pass

def add_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    st.session_state[f"{prefix}logs"].insert(0, f"[{ts}] {msg}")
    if len(st.session_state[f"{prefix}logs"]) > 30: st.session_state[f"{prefix}logs"].pop()

# ================= MOTOR (LOGIC) =================
def run_scalp(curr_p, dfs):
    l_status = st.session_state[f"{prefix}l_status"]
    l_crypto = st.session_state[f"{prefix}l_crypto"]
    l_avg = st.session_state[f"{prefix}l_avg"]
    
    atr = dfs["15m"].iloc[-1]["ATR"]
    tp_dist = max(atr * ATR_TP_MULT, curr_p * 0.0008)
    sl_dist = tp_dist * 1.5

    # --- ÇIKIŞ ---
    if any(l_status):
        if curr_p >= (l_avg + tp_dist) or (l_status[2] and curr_p <= (l_avg - sl_dist)):
            pnl = (curr_p - l_avg) * l_crypto
            st.session_state[f"{selected_symbol}_balance"] += pnl
            reason = "TP ✅" if curr_p > l_avg else "SL ❌"
            st.session_state[f"{prefix}history"].append({
                "Zaman": datetime.datetime.now().strftime("%d/%m %H:%M"),
                "Tip": "LONG", "Sonuç": reason, "PnL": round(pnl, 4), "Fiyat": curr_p
            })
            add_log(f"LONG Pozisyon Kapatıldı: {reason} | Kar: ${pnl:.4f}")
            st.session_state[f"{prefix}l_status"] = [False]*3
            st.session_state[f"{prefix}l_crypto"] = 0.0
            st.session_state[f"{prefix}l_avg"] = 0.0
            save_state()

    # --- GİRİŞ (3 Kademe) ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        nw_alt = dfs[tfs[i]].iloc[-1]["NW_Alt"]
        if curr_p <= nw_alt and not l_status[i] and (i==0 or l_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            st.session_state[f"{prefix}l_avg"] = ((l_avg * l_crypto) + (amt * curr_p)) / (l_crypto + amt)
            st.session_state[f"{prefix}l_crypto"] += amt
            st.session_state[f"{prefix}l_status"][i] = True
            add_log(f"LONG Kademe {i+1} Açıldı @ {curr_p}")
            save_state(); break
            
    return tp_dist, sl_dist

# ================= ARAYÜZ (COCKPIT) =================
load_state()

# SIDEBAR
with st.sidebar:
    st.title("🐑 Kyoun Terminal")
    st.info(f"Mod: Canlı (Simulation)")
    if st.button("🔴 Verileri Sıfırla"):
        st.session_state[f"{selected_symbol}_balance"] = 100.0
        st.session_state[f"{prefix}history"] = []
        save_state(); st.rerun()
    st.divider()
    st.caption("v2024.12 - Pro Edition")

# ANA PANEL
@st.fragment(run_every="10s")
def cockpit():
    try:
        ticker = exchange.fetch_ticker(selected_symbol)
        curr_p = ticker['last']
        dfs = {tf: fetch_tf_data(selected_symbol, tf) for tf in ["1m", "5m", "15m"]}
        tp_d, sl_d = run_scalp(curr_p, dfs)
        
        # 1. METRİKLER
        hist = st.session_state[f"{prefix}history"]
        total_pnl = sum(t['PnL'] for t in hist)
        wins = len([t for t in hist if "✅" in t['Sonuç']])
        wr = (wins / len(hist) * 100) if hist else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💳 Bakiye", f"${st.session_state[f'{selected_symbol}_balance']:,.2f}")
        c2.metric("📈 Net K/Z", f"${total_pnl:+.4f}")
        c3.metric("🏆 Win Rate", f"%{wr:.1f}")
        c4.metric("📊 İşlemler", len(hist))
        
        st.divider()
        
        # 2. GRAFİK VE LOGLAR
        col_left, col_right = st.columns([2, 1])
        with col_left:
            # Basit Candlestick Grafiği
            df_plot = dfs["1m"].tail(50)
            fig = go.Figure(data=[go.Candlestick(x=df_plot['Zaman'], open=df_plot['Acilis'], high=df_plot['Yuksek'], low=df_plot['Dusuk'], close=df_plot['Kapanis'])])
            fig.add_trace(go.Scatter(x=df_plot['Zaman'], y=df_plot['NW_Ust'], line=dict(color='#ff4b4b', width=1), name="Direnç"))
            fig.add_trace(go.Scatter(x=df_plot['Zaman'], y=df_plot['NW_Alt'], line=dict(color='#00ff41', width=1), name="Destek"))
            fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
        with col_right:
            st.markdown("🔍 **Canlı Sistem Günlüğü**")
            logs_html = f"<div class='log-box'>{'<br>'.join(st.session_state[f'{prefix}logs'])}</div>"
            st.markdown(logs_html, unsafe_allow_html=True)
            
            # Aktif Pozisyon Bilgisi
            if any(st.session_state[f"{prefix}l_status"]):
                with st.container(border=True):
                    avg = st.session_state[f"{prefix}l_avg"]
                    curr_pnl = (curr_p - avg) * st.session_state[f"{prefix}l_crypto"]
                    st.success(f"📈 LONG AKTİF")
                    st.write(f"Maliyet: ${avg:,.2f} | K/Z: ${curr_pnl:+.4f}")
                    st.caption(f"Hedef: +${tp_d:.2f} | Stop: -${sl_d:.2f}")
            else:
                st.info("⌛ Sinyal bekleniyor... Fiyat bant dışına çıkmalı.")

        # 3. GEÇMİŞ TABLOSU
        st.markdown("### 📜 Son İşlemler")
        if hist:
            st.dataframe(pd.DataFrame(hist).sort_index(ascending=False), use_container_width=True, hide_index=True)
        else:
            st.caption("Henüz tamamlanmış işlem yok.")

    except Exception as e: st.error(f"Döngü Hatası: {e}")

cockpit()
