import streamlit as st
from streamlit.runtime.scriptrunner import RerunException
import ccxt
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= AYARLAR (KURAL SETİ) =================
BOT_LEVERAGE = 200
MEXC_TAKER_FEE_PCT = 0.0002 # %0.02
MIN_PROFIT_MULT = 3.0       # Komisyonun en az 3 katı kâr hedefle
MIN_STAGE_GAP_MULT = 0.5    # Kademeler arası en az 0.5 ATR mesafe olmalı
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015] # K1, K2, K3 Miktarları

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
selected_symbol = "BTC/USDT:USDT"

# ================= STİL VE GİRİŞ =================
st.set_page_config(page_title="Kyoun Professional Cockpit", layout="wide")

if "password_correct" not in st.session_state: st.session_state.password_correct = False
if not st.session_state.password_correct:
    st.title("🐑 Kyoun Terminal")
    pwd = st.text_input("Şifre", type="password")
    if st.button("Giriş"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.password_correct = True
            st.rerun()
    st.stop()

st.markdown("""
    <style>
    .stApp { background-color: #0B0E11; color: #B7BDC6; }
    div[data-testid="stMetric"] { background:#161B22; border:1px solid #2A2E37; border-radius:10px; padding:15px; }
    .status-card { background:#1c2128; border:1px solid #444c56; padding:15px; border-radius:10px; }
    </style>
""", unsafe_allow_html=True)

# ================= MATEMATİKSEL ANALİZ =================
def get_analysis(symbol, tf):
    raw = exchange.fetch_ohlcv(symbol, tf, limit=100)
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    # NW Bantları
    src = df["Kapanis"].values; h = 8; estimates = np.zeros(len(src))
    for i in range(len(src)):
        w = np.exp(-((np.arange(i + 1) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * w) / np.sum(w)
    df["NW_Merkez"] = estimates
    std = (df["Kapanis"] - df["NW_Merkez"]).rolling(20).std()
    df["NW_Alt"] = df["NW_Merkez"] - (3.0 * std)
    df["NW_Ust"] = df["NW_Merkez"] + (3.0 * std)
    # ATR
    tr = pd.concat([df["Yuksek"]-df["Dusuk"], (df["Yuksek"]-df["Kapanis"].shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return df

# ================= HAFIZA (STATE) YÖNETİMİ =================
prefix = f"{selected_symbol}_scalp_v5_"

def init_state():
    if f"{prefix}loaded" in st.session_state: return
    st.session_state[f"{selected_symbol}_balance"] = 100.0
    st.session_state[f"{prefix}history"] = []
    st.session_state[f"{prefix}l_status"] = [False]*3
    st.session_state[f"{prefix}l_entries"] = [0.0]*3
    st.session_state[f"{prefix}l_crypto"] = 0.0
    st.session_state[f"{prefix}l_avg"] = 0.0
    st.session_state[f"{prefix}logs"] = ["Sistem hazır."]
    
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).execute()
            if q.data:
                d = q.data[0]
                st.session_state[f"{selected_symbol}_balance"] = d.get("balance_usd", 100.0)
                st.session_state[f"{prefix}history"] = d.get("trade_history", [])
        except: pass
    st.session_state[f"{prefix}loaded"] = True

def add_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    st.session_state[f"{prefix}logs"].insert(0, f"[{ts}] {msg}")

# ================= MOTOR (LOGIC) =================
def run_engine(curr_p, dfs, is_live):
    s = st.session_state
    pre = prefix
    atr = dfs["15m"].iloc[-1]["ATR"]
    
    # Komisyon maliyeti (Giriş+Çıkış)
    fee_cost_pct = MEXC_TAKER_FEE_PCT * 2
    # Kar-Al Mesafesi: ATR veya Komisyonun 3 katı (hangisi büyükse)
    tp_dist = max(atr * 1.2, curr_p * fee_cost_pct * MIN_PROFIT_MULT)
    sl_dist = tp_dist * 1.5

    # --- ÇIKIŞ ---
    if any(s[f"{pre}l_status"]):
        tp_price = s[f"{pre}l_avg"] + tp_dist
        sl_price = s[f"{pre}l_avg"] - sl_dist
        
        if curr_p >= tp_price or (s[f"{pre}l_status"][2] and curr_p <= sl_price):
            pnl = (curr_p - s[f"{pre}l_avg"]) * s[f"{pre}l_crypto"]
            st.session_state[f"{selected_symbol}_balance"] += pnl
            res = "KAR ✅" if curr_p > s[f"{pre}l_avg"] else "STOP ❌"
            s[f"{pre}history"].append({"Tarih": datetime.datetime.now().strftime("%H:%M"), "PnL": round(pnl, 4), "Sonuç": res})
            add_log(f"İşlem Kapandı: {res} | Net: ${pnl:.4f}")
            s[f"{pre}l_status"] = [False]*3; s[f"{pre}l_crypto"] = 0.0; s[f"{pre}l_avg"] = 0.0
            # DB Güncellemesi yapılabilir

    # --- GİRİŞ (Mesafe Kontrollü) ---
    tfs = ["1m", "5m", "15m"]
    min_gap = atr * MIN_STAGE_GAP_MULT
    
    for i in range(3):
        nw_alt = dfs[tfs[i]].iloc[-1]["NW_Alt"]
        
        # Kademe şartı
        if curr_p <= nw_alt and not s[f"{pre}l_status"][i] and (i==0 or s[f"{pre}l_status"][i-1]):
            # Mesafe şartı (K2 ve K3 için)
            distance_ok = True
            if i > 0:
                last_entry = s[f"{pre}l_entries"][i-1]
                if abs(curr_p - last_entry) < min_gap: distance_ok = False
            
            if distance_ok:
                amt = SCALP_AMOUNTS[i]
                old_total = s[f"{pre}l_avg"] * s[f"{pre}l_crypto"]
                s[f"{pre}l_crypto"] += amt
                s[f"{pre}l_avg"] = (old_total + (amt * curr_p)) / s[f"{pre}l_crypto"]
                s[f"{pre}l_status"][i] = True
                s[f"{pre}l_entries"][i] = curr_p
                add_log(f"K{i+1} Alındı ({tfs[i]}) @ {curr_p}")
                break
    return tp_dist, sl_dist

# ================= ARAYÜZ (COCKPIT) =================
init_state()

with st.sidebar:
    st.header("🐑 Kyoun Ayarlar")
    is_live = st.toggle("🔴 CANLI MODU AÇ", value=False)
    if st.button("Sıfırla (100$)"):
        st.session_state[f"{selected_symbol}_balance"] = 100.0
        st.session_state[f"{prefix}history"] = []
        st.rerun()

@st.fragment(run_every="10s")
def cockpit():
    ticker = exchange.fetch_ticker(selected_symbol)
    curr_p = ticker['last']
    dfs = {tf: get_analysis(selected_symbol, tf) for tf in ["1m", "5m", "15m"]}
    tp_d, sl_d = run_engine(curr_p, dfs, is_live)
    s = st.session_state
    pre = prefix

    # 1. METRİKLER
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💳 Bakiye", f"${s[f'{selected_symbol}_balance']:,.2f}")
    hist = s[f"{pre}history"]
    total_pnl = sum(i['PnL'] for i in hist)
    c2.metric("📈 Toplam K/Z", f"${total_pnl:+.4f}")
    wins = len([i for i in hist if i['Sonuç'] == "KAR ✅"])
    wr = (wins / len(hist) * 100) if hist else 0
    c3.metric("🏆 Başarı Oranı", f"%{wr:.1f}")
    c4.metric("📊 İşlem Sayısı", len(hist))

    st.divider()

    # 2. KADEME VE HEDEF TAKİBİ
    col_l, col_r = st.columns([1.2, 1])
    with col_l:
        st.markdown("### 🪜 Kademe Durumu")
        k_cols = st.columns(3)
        for i in range(3):
            status = "✅" if s[f"{pre}l_status"][i] else "⏳"
            k_cols[i].markdown(f"""
                <div class="status-card">
                    <small>Kademe {i+1}</small><br><b>{status}</b><br>
                    <small>{s[f"{pre}l_entries"][i] if s[f"{pre}l_status"][i] else '-'}</small>
                </div>
            """, unsafe_allow_html=True)
        
        # Grafik
        df_p = dfs["1m"].tail(50)
        fig = go.Figure(data=[go.Candlestick(x=df_p['Zaman'], open=df_p['Acilis'], high=df_p['Yuksek'], low=df_p['Dusuk'], close=df_p['Kapanis'])])
        fig.add_trace(go.Scatter(x=df_p['Zaman'], y=df_p['NW_Alt'], line=dict(color='green', width=1), name="Destek"))
        fig.update_layout(template="plotly_dark", height=320, margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown("### 🚀 Hedef Bilgisi")
        if any(s[f"{pre}l_status"]):
            tp_p = s[f"{pre}l_avg"] + tp_d
            with st.container(border=True):
                st.write(f"📉 **Ortalama:** ${s[f'{pre}l_avg']:,.2f}")
                st.write(f"💰 **Satış Hedefi:** :green[${tp_p:,.2f}]")
                dist = ((tp_p / curr_p) - 1) * 100
                st.info(f"Hedefe kalan: %{dist:.2f}")
        else:
            st.write("Sinyal taranıyor...")

        st.markdown("**🧠 Sistem Günlüğü**")
        logs_html = f"<div style='height:150px; overflow-y:auto; background:#1c2128; padding:10px; font-family:monospace; font-size:12px; color:#adbac7; border:1px solid #444c56;'>{'<br>'.join(s[f'{pre}logs'])}</div>"
        st.markdown(logs_html, unsafe_allow_html=True)

    # 3. GEÇMİŞ
    st.markdown("### 📜 İşlem Geçmişi")
    if hist:
        st.dataframe(pd.DataFrame(hist).sort_index(ascending=False).head(10), use_container_width=True, hide_index=True)

cockpit()
