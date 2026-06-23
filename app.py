import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= AYARLAR =================
BOT_LEVERAGE = 200
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015] # K1, K2, K3 Miktarları
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

# API & DB (Secrets'tan çekilir)
MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

exchange = ccxt.mexc({'apiKey': MEXC_API_KEY, 'secret': MEXC_API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
selected_symbol = "BTC/USDT:USDT"
prefix = f"{selected_symbol}_scalp_"

# ================= YARDIMCI FONKSİYONLAR =================
def fetch_data(symbol, tf):
    raw = exchange.fetch_ohlcv(symbol, tf, limit=80)
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

# ================= STATE YÖNETİMİ =================
if "state_v4" not in st.session_state:
    st.session_state.state_v4 = {
        "balance": 100.0,
        "history": [],
        "l_status": [False, False, False], # K1, K2, K3
        "l_avg": 0.0,
        "l_crypto": 0.0,
        "logs": ["🤖 Bot başlatıldı, sinyal taranıyor..."]
    }

def add_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    st.session_state.state_v4["logs"].insert(0, f"[{ts}] {msg}")

# ================= MOTOR =================
def run_scalp(curr_p, dfs):
    s = st.session_state.state_v4
    atr = dfs["15m"].iloc[-1]["ATR"]
    tp_dist = max(atr * ATR_TP_MULT, curr_p * 0.0008)
    sl_dist = tp_dist * 1.5

    # --- SATIŞ KONTROLÜ (EXIT) ---
    if any(s["l_status"]):
        tp_price = s["l_avg"] + tp_dist
        sl_price = s["l_avg"] - sl_dist
        
        # Kar-Al (TP)
        if curr_p >= tp_price:
            pnl = (curr_p - s["l_avg"]) * s["l_crypto"]
            s["balance"] += pnl
            s["history"].append({"Tarih": datetime.datetime.now().strftime("%H:%M"), "Kar/Zarar": round(pnl, 4)})
            add_log(f"💰 SATILDI (Kar-Al)! Kar: ${pnl:.4f}")
            s["l_status"] = [False]*3; s["l_avg"] = 0.0; s["l_crypto"] = 0.0
            
        # Zarar-Durdur (SL) - Sadece K3 varsa aktif
        elif s["l_status"][2] and curr_p <= sl_price:
            pnl = (curr_p - s["l_avg"]) * s["l_crypto"]
            s["balance"] += pnl
            add_log(f"🛑 STOP-LOSS! Zarar: ${pnl:.4f}")
            s["l_status"] = [False]*3; s["l_avg"] = 0.0; s["l_crypto"] = 0.0

    # --- ALIŞ KONTROLÜ (ENTRY) ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        nw_alt = dfs[tfs[i]].iloc[-1]["NW_Alt"]
        # Kademe şartı: bir önceki kademe alınmış olmalı ve mevcut kademe boş olmalı
        if curr_p <= nw_alt and not s["l_status"][i] and (i == 0 or s["l_status"][i-1]):
            amt = SCALP_AMOUNTS[i]
            s["l_avg"] = ((s["l_avg"] * s["l_crypto"]) + (amt * curr_p)) / (s["l_crypto"] + amt)
            s["l_crypto"] += amt
            s["l_status"][i] = True
            add_log(f"🪜 KADEME {i+1} ALINDI ({tfs[i]}) @ {curr_p}")
            break
            
    return tp_dist, sl_dist

# ================= ARAYÜZ =================
st.set_page_config(page_title="Kyoun Professional Dashboard", layout="wide")

@st.fragment(run_every="10s")
def cockpit():
    ticker = exchange.fetch_ticker(selected_symbol)
    curr_p = ticker['last']
    dfs = {tf: fetch_data(selected_symbol, tf) for tf in ["1m", "5m", "15m"]}
    tp_d, sl_d = run_scalp(curr_p, dfs)
    s = st.session_state.state_v4

    # --- ÜST ÖZET ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💳 Bakiye", f"${s['balance']:,.2f}")
    c2.metric("BTC Fiyat", f"${curr_p:,.2f}")
    total_pnl = sum(i['Kar/Zarar'] for i in s['history'])
    c3.metric("📈 Net Kar/Zarar", f"${total_pnl:+.4f}")
    c4.metric("📊 Kapanan İşlem", len(s['history']))

    st.divider()

    # --- KADEME VE DURUM PANELİ ---
    col1, col2 = st.columns([1.5, 1])
    
    with col1:
        st.subheader("🪜 Kademe Takip Sistemi")
        k_cols = st.columns(3)
        for i in range(3):
            label = ["K1 (Hızlı)", "K2 (Orta)", "K3 (Derin)"][i]
            status = "✅ DOLU" if s["l_status"][i] else "⏳ BEKLİYOR"
            color = "green" if s["l_status"][i] else "gray"
            k_cols[i].markdown(f"""
                <div style="background:#161B22; padding:15px; border-radius:10px; border-left: 5px solid {color}; text-align:center;">
                    <small>{label}</small><br><b>{status}</b>
                </div>
            """, unsafe_allow_html=True)
            
        st.write("")
        # --- GRAFİK ---
        df_p = dfs["1m"].tail(50)
        fig = go.Figure(data=[go.Candlestick(x=df_p['Zaman'], open=df_p['Acilis'], high=df_p['Yuksek'], low=df_p['Dusuk'], close=df_p['Kapanis'])])
        fig.add_trace(go.Scatter(x=df_p['Zaman'], y=df_p['NW_Alt'], line=dict(color='green', width=1), name="Destek"))
        fig.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("🚀 Hedef Defteri")
        if any(s["l_status"]):
            tp_price = s["l_avg"] + tp_d
            sl_price = s["l_avg"] - sl_d
            with st.container(border=True):
                st.write(f"📉 **Maliyet Ort.:** ${s['l_avg']:,.2f}")
                st.write(f"💰 **Satış Hedefi (Kar-Al):** :green[${tp_price:,.2f}]")
                if s["l_status"][2]:
                    st.write(f"🛑 **Stop-Loss:** :red[${sl_price:,.2f}]")
                else:
                    st.caption("Stop-loss 3. kademeden sonra aktif olur.")
                
                # Kar-Al'a ne kadar kaldı?
                dist_pct = ((tp_price / curr_p) - 1) * 100
                st.progress(max(0.0, min(1.0, 1 - (dist_pct/0.5))), text=f"Hedefe %{dist_pct:.2f} kaldı")
        else:
            st.info("İşlemde değil. Yeşil bantlara değmesi bekleniyor.")

        st.markdown("**🧠 Sistem Günlüğü**")
        st.markdown(f"<div style='height:150px; overflow-y:auto; background:#1c2128; padding:10px; font-family:monospace; font-size:12px; border:1px solid #444c56;'>{'<br>'.join(s['logs'])}</div>", unsafe_allow_html=True)

cockpit()
