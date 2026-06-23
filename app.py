import streamlit as st
from streamlit.runtime.scriptrunner import RerunException
import ccxt
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= 1. TEMEL AYARLAR =================
BOT_LEVERAGE = 200
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]
TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "std_window": 18},
    "15m": {"limit": 110, "h": 8, "std_window": 20},
}

MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

exchange = ccxt.mexc({'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
symbol = "BTC/USDT:USDT"
prefix = f"{symbol}_scalp_"

# ================= 2. KRİTİK: HAFIZA BAŞLATMA (HATA ÇÖZÜMÜ) =================
# Scriptin en başında, hiçbir şey yapmadan önce hafızayı kontrol et
if f"{prefix}l_avg" not in st.session_state:
    st.session_state[f"{symbol}_balance"] = 100.0
    st.session_state[f"{prefix}history"] = []
    st.session_state[f"{prefix}logs"] = ["Sistem Başlatıldı..."]
    st.session_state[f"{prefix}l_status"] = [False, False, False]
    st.session_state[f"{prefix}l_crypto"] = 0.0
    st.session_state[f"{prefix}l_avg"] = 0.0
    
    # Supabase'den eski verileri çekip hafızaya yaz
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", symbol).execute()
            if q.data:
                d = q.data[0]
                st.session_state[f"{symbol}_balance"] = d.get("balance_usd", 100.0)
                st.session_state[f"{prefix}history"] = d.get("trade_history", [])
                st.session_state[f"{prefix}l_crypto"] = d.get("scalp_l_crypto", 0.0)
                st.session_state[f"{prefix}l_avg"] = d.get("scalp_l_avg_price", 0.0)
                for i in range(3):
                    st.session_state[f"{prefix}l_status"][i] = d.get(f"scalp_l_status_{i}", False)
        except: pass

# ================= 3. YARDIMCI FONKSİYONLAR =================
def fetch_tf_data(tf):
    p = TF_PARAMS[tf]
    raw = exchange.fetch_ohlcv(symbol, tf, limit=p["limit"])
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    # Nadaraya Watson
    src = df["Kapanis"].values; n = len(src); h = 8; estimates = np.zeros(n)
    for i in range(n):
        w = np.exp(-((np.arange(i + 1) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * w) / np.sum(w)
    df["NW_Merkez"] = estimates
    std = (df["Kapanis"] - df["NW_Merkez"]).rolling(p["std_window"]).std()
    df["NW_Alt"] = df["NW_Merkez"] - (3.0 * std)
    df["NW_Ust"] = df["NW_Merkez"] + (3.0 * std)
    # ATR
    tr = pd.concat([df["Yuksek"]-df["Dusuk"], (df["Yuksek"]-df["Kapanis"].shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return df

def save_db():
    if not supabase: return
    try:
        data = {
            "coin_symbol": symbol,
            "balance_usd": float(st.session_state[f"{symbol}_balance"]),
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
    if len(st.session_state[f"{prefix}logs"]) > 20: st.session_state[f"{prefix}logs"].pop()

# ================= 4. MOTOR (MANTIK) =================
def run_scalp(curr_p, dfs):
    l_status = st.session_state[f"{prefix}l_status"]
    l_crypto = st.session_state[f"{prefix}l_crypto"]
    l_avg = st.session_state[f"{prefix}l_avg"]
    
    atr = dfs["15m"].iloc[-1]["ATR"]
    tp_dist = max(atr * 1.0, curr_p * 0.0008)
    sl_dist = tp_dist * 1.5

    # --- ÇIKIŞ ---
    if any(l_status):
        if curr_p >= (l_avg + tp_dist) or (l_status[2] and curr_p <= (l_avg - sl_dist)):
            pnl = (curr_p - l_avg) * l_crypto
            st.session_state[f"{symbol}_balance"] += pnl
            res = "TP ✅" if curr_p > l_avg else "SL ❌"
            st.session_state[f"{prefix}history"].append({"Zaman": datetime.datetime.now().strftime("%H:%M"), "PnL": round(pnl, 4), "Sonuç": res})
            add_log(f"İŞLEM KAPANDI: {res} | Kar: ${pnl:.4f}")
            st.session_state[f"{prefix}l_status"] = [False]*3
            st.session_state[f"{prefix}l_crypto"], st.session_state[f"{prefix}l_avg"] = 0.0, 0.0
            save_db()

    # --- GİRİŞ ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        nw_alt = dfs[tfs[i]].iloc[-1]["NW_Alt"]
        if curr_p <= nw_alt and not l_status[i] and (i==0 or l_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            st.session_state[f"{prefix}l_avg"] = ((l_avg * l_crypto) + (amt * curr_p)) / (l_crypto + amt)
            st.session_state[f"{prefix}l_crypto"] += amt
            st.session_state[f"{prefix}l_status"][i] = True
            add_log(f"LONG Kademe {i+1} Girildi @ {curr_p}")
            save_db(); break
            
    return tp_dist, sl_dist

# ================= 5. ARAYÜZ (GÖRÜNÜM) =================
st.set_page_config(page_title="Kyoun Professional", layout="wide")

# Sidebar
with st.sidebar:
    st.header("🐑 Kyoun Cockpit")
    if st.button("🔴 Tüm Verileri Sıfırla (100$)"):
        st.session_state[f"{symbol}_balance"] = 100.0
        st.session_state[f"{prefix}history"] = []
        st.session_state[f"{prefix}l_status"] = [False]*3
        st.session_state[f"{prefix}l_crypto"] = 0.0
        st.session_state[f"{prefix}l_avg"] = 0.0
        save_db(); st.rerun()

# Ana Sayfa Fragment
@st.fragment(run_every="10s")
def cockpit():
    try:
        ticker = exchange.fetch_ticker(symbol)
        curr_p = ticker['last']
        dfs = {tf: fetch_tf_data(tf) for tf in ["1m", "5m", "15m"]}
        tp_d, sl_d = run_scalp(curr_p, dfs)

        # 1. Metrikler
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💳 Bakiye", f"${st.session_state[f'{symbol}_balance']:,.2f}")
        
        hist = st.session_state[f"{prefix}history"]
        pnl = sum(i['PnL'] for i in hist)
        wins = len([i for i in hist if "✅" in i['Sonuç']])
        wr = (wins / len(hist) * 100) if hist else 0
        
        c2.metric("📈 Net Kar/Zarar", f"${pnl:+.4f}")
        c3.metric("🏆 Başarı Oranı", f"%{wr:.1f}")
        c4.metric("📊 İşlemler", len(hist))

        st.divider()

        # 2. Orta Panel
        col_l, col_r = st.columns([2, 1])
        with col_l:
            df_plot = dfs["1m"].tail(50)
            fig = go.Figure(data=[go.Candlestick(x=df_plot['Zaman'], open=df_plot['Acilis'], high=df_plot['Yuksek'], low=df_plot['Dusuk'], close=df_plot['Kapanis'])])
            fig.add_trace(go.Scatter(x=df_plot['Zaman'], y=df_plot['NW_Ust'], line=dict(color='red', width=1), name="Direnç"))
            fig.add_trace(go.Scatter(x=df_plot['Zaman'], y=df_plot['NW_Alt'], line=dict(color='green', width=1), name="Destek"))
            fig.update_layout(template="plotly_dark", height=380, margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
        with col_r:
            st.markdown("**🧠 Sistem Günlüğü**")
            log_box = f"<div style='height:200px; overflow-y:auto; background:#1c2128; padding:10px; font-family:monospace; font-size:12px; color:#adbac7; border:1px solid #444c56;'>{'<br>'.join(st.session_state[f'{prefix}logs'])}</div>"
            st.markdown(log_box, unsafe_allow_html=True)
            
            if any(st.session_state[f"{prefix}l_status"]):
                with st.container(border=True):
                    avg = st.session_state[f"{prefix}l_avg"]
                    st.success(f"🚀 POZİSYONDA: LONG @ {avg:,.2f}")
                    st.caption(f"Hedef: +${tp_d:.2f} | Stop: -${sl_d:.2f}")
            else:
                st.info("🔎 Sinyal taranıyor...")

        # 3. Geçmiş
        st.markdown("### 📜 İşlem Geçmişi")
        if hist:
            st.dataframe(pd.DataFrame(hist).sort_index(ascending=False), use_container_width=True, hide_index=True)

    except Exception as e: st.error(f"Hata: {e}")

cockpit()
