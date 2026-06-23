import streamlit as st
from streamlit.runtime.scriptrunner import RerunException
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
from supabase import create_client, Client

# ================= AYARLAR =================
BOT_LEVERAGE = 200
MEXC_TAKER_FEE_PCT = 0.0002
TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "std_window": 18},
    "15m": {"limit": 110, "h": 8, "std_window": 20},
}
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5
SHOCK_COOLDOWN_MINUTES = 30

# API Girişleri
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

# ================= GİRİŞ EKRANI (ORİJİNAL) =================
def check_password():
    if st.session_state.get("password_correct", False): return True
    st.markdown("""
        <style>
        .sheep-emoji { display: inline-block; animation: bounce 2.2s infinite; font-size: 80px; }
        @keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
        .login-box { text-align: center; padding: 40px; background: #161B33; border-radius: 20px; border: 1px solid #9A8BF0; }
        </style>
        <div class="login-box">
            <div class="sheep-emoji">🐑</div>
            <h1 style='color:white; letter-spacing:3px;'>KYOUN</h1>
            <p style='color:#6E72A0;'>ŞANSLI KOYUN TERMİNALİ</p>
        </div>
    """, unsafe_allow_html=True)
    with st.form("login"):
        pwd = st.text_input("Giriş Şifresi", type="password")
        if st.form_submit_button("Sistemi Başlat"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.password_correct = True
                st.rerun()
            else: st.error("Hatalı Şifre!")
    return False

if not check_password(): st.stop()

st.set_page_config(page_title="Kyoun | Scalp", layout="wide")

# ================= STİL (ORİJİNAL DARK THEME) =================
st.markdown("""
    <style>
    [data-testid="stAppViewBlockContainer"] { padding-top: 1.5rem !important; background-color: #0B0E11; }
    div[data-testid="stMetric"] { background:#161B22; border:1px solid #2A2E37; border-radius:12px; padding:15px; }
    .status-bar { display: flex; align-items: center; background: #161B22; border: 1px solid #2A2E37; border-radius: 10px; padding: 10px 20px; margin-bottom: 1rem; color: #B7BDC6; }
    .pulse { width: 10px; height: 10px; background: #2ecc71; border-radius: 50%; display: inline-block; margin-right: 10px; animation: blink 1.5s infinite; }
    @keyframes blink { 0% { opacity: 0.2; } 50% { opacity: 1; } 100% { opacity: 0.2; } }
    </style>
""", unsafe_allow_html=True)

# ================= MATEMATİK & VERİ =================
def nadaraya_watson_estimator(src, h=8):
    n = len(src); estimates = np.zeros(n)
    for i in range(n):
        weights = np.exp(-((np.arange(i + 1) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * weights) / np.sum(weights)
    return estimates

def fetch_tf_data(symbol, tf):
    p = TF_PARAMS[tf]
    raw = exchange.fetch_ohlcv(symbol, tf, limit=p["limit"])
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=p["h"])
    std = (df["Kapanis"] - df["NW_Merkez"]).ewm(span=p["std_window"]).std()
    df[f"NW_Alt_{tf}"] = df["NW_Merkez"] - (3.0 * std)
    df[f"NW_Ust_{tf}"] = df["NW_Merkez"] + (3.0 * std)
    tr = pd.concat([df["Yuksek"]-df["Dusuk"], (df["Yuksek"]-df["Kapanis"].shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return df

# ================= STATE YÖNETİMİ =================
selected_symbol = "BTC/USDT:USDT"
base_prefix = f"{selected_symbol}_"
scalp_prefix = f"{base_prefix}scalp_"

def load_state():
    if f"{scalp_prefix}loaded" in st.session_state: return
    st.session_state[f"{base_prefix}balance_usd"] = 100.0
    st.session_state[f"{scalp_prefix}l_status"] = [False]*3
    st.session_state[f"{scalp_prefix}s_status"] = [False]*3
    st.session_state[f"{scalp_prefix}l_avg_price"] = 0.0
    st.session_state[f"{scalp_prefix}s_avg_price"] = 0.0
    st.session_state[f"{scalp_prefix}l_crypto"] = 0.0
    st.session_state[f"{scalp_prefix}s_crypto"] = 0.0
    st.session_state[f"{scalp_prefix}l_entry_prices"] = [0.0]*3
    st.session_state[f"{scalp_prefix}s_entry_prices"] = [0.0]*3
    st.session_state[f"{base_prefix}trade_history"] = []
    
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).execute()
            if q.data:
                d = q.data[0]
                st.session_state[f"{base_prefix}balance_usd"] = d.get("balance_usd", 100.0)
                st.session_state[f"{base_prefix}trade_history"] = d.get("trade_history", [])
                for i in range(3):
                    st.session_state[f"{scalp_prefix}l_status"][i] = d.get(f"scalp_l_status_{i}", False)
                    st.session_state[f"{scalp_prefix}s_status"][i] = d.get(f"scalp_s_status_{i}", False)
                    st.session_state[f"{scalp_prefix}l_entry_prices"][i] = d.get(f"scalp_l_entry_{i}", 0.0)
                    st.session_state[f"{scalp_prefix}s_entry_prices"][i] = d.get(f"scalp_s_entry_{i}", 0.0)
                st.session_state[f"{scalp_prefix}l_avg_price"] = d.get("scalp_l_avg_price", 0.0)
                st.session_state[f"{scalp_prefix}s_avg_price"] = d.get("scalp_s_avg_price", 0.0)
                st.session_state[f"{scalp_prefix}l_crypto"] = d.get("scalp_l_crypto", 0.0)
                st.session_state[f"{scalp_prefix}s_crypto"] = d.get("scalp_s_crypto", 0.0)
        except: pass
    st.session_state[f"{scalp_prefix}loaded"] = True

def save_state_to_db():
    if not supabase: return
    try:
        data = {
            "coin_symbol": selected_symbol,
            "balance_usd": float(st.session_state[f"{base_prefix}balance_usd"]),
            "scalp_l_crypto": float(st.session_state[f"{scalp_prefix}l_crypto"]),
            "scalp_l_avg_price": float(st.session_state[f"{scalp_prefix}l_avg_price"]),
            "scalp_s_crypto": float(st.session_state[f"{scalp_prefix}s_crypto"]),
            "scalp_s_avg_price": float(st.session_state[f"{scalp_prefix}s_avg_price"]),
            "scalp_l_margin_used": 0.0, "scalp_s_margin_used": 0.0,
            "trade_history": st.session_state[f"{base_prefix}trade_history"],
            "log_history": []
        }
        for i in range(3):
            data[f"scalp_l_status_{i}"] = bool(st.session_state[f"{scalp_prefix}l_status"][i])
            data[f"scalp_s_status_{i}"] = bool(st.session_state[f"{scalp_prefix}s_status"][i])
            data[f"scalp_l_entry_{i}"] = float(st.session_state[f"{scalp_prefix}l_entry_prices"][i])
            data[f"scalp_s_entry_{i}"] = float(st.session_state[f"{scalp_prefix}s_entry_prices"][i])
        supabase.table("bot_state").upsert(data, on_conflict="coin_symbol").execute()
    except Exception as e: st.warning(f"DB Sync Hatası: {e}")

# ================= MOTOR (BAKİYE KORUMALI) =================
def run_engine(curr_p, dfs):
    l_status = st.session_state[f"{scalp_prefix}l_status"]
    s_status = st.session_state[f"{scalp_prefix}s_status"]
    atr = dfs["15m"].iloc[-2]["ATR"]
    tp_dist = max(atr * ATR_TP_MULT, curr_p * 0.0006)
    sl_dist = atr * ATR_SL_MULT

    # --- ÇIKIŞ ---
    if any(l_status):
        avg = st.session_state[f"{scalp_prefix}l_avg_price"]
        if curr_p >= (avg + tp_dist) or (l_status[2] and curr_p <= (avg - sl_dist)):
            pnl = (curr_p - avg) * st.session_state[f"{scalp_prefix}l_crypto"]
            st.session_state[f"{base_prefix}balance_usd"] += pnl
            st.session_state[f"{scalp_prefix}l_status"] = [False]*3
            st.session_state[f"{scalp_prefix}l_crypto"], st.session_state[f"{scalp_prefix}l_avg_price"] = 0.0, 0.0
            save_state_to_db()

    if any(s_status):
        avg = st.session_state[f"{scalp_prefix}s_avg_price"]
        if curr_p <= (avg - tp_dist) or (s_status[2] and curr_p >= (avg + sl_dist)):
            pnl = (avg - curr_p) * st.session_state[f"{scalp_prefix}s_crypto"]
            st.session_state[f"{base_prefix}balance_usd"] += pnl
            st.session_state[f"{scalp_prefix}s_status"] = [False]*3
            st.session_state[f"{scalp_prefix}s_crypto"], st.session_state[f"{scalp_prefix}s_avg_price"] = 0.0, 0.0
            save_state_to_db()

    # --- GİRİŞ ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        nw_alt = dfs[tfs[i]].iloc[-2][f"NW_Alt_{tfs[i]}"]
        if curr_p <= nw_alt and not l_status[i] and (i==0 or l_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            old_amt, old_avg = st.session_state[f"{scalp_prefix}l_crypto"], st.session_state[f"{scalp_prefix}l_avg_price"]
            st.session_state[f"{scalp_prefix}l_avg_price"] = ((old_avg * old_amt) + (amt * curr_p)) / (old_amt + amt)
            st.session_state[f"{scalp_prefix}l_crypto"] += amt
            st.session_state[f"{scalp_prefix}l_status"][i] = True
            st.session_state[f"{scalp_prefix}l_entry_prices"][i] = curr_p
            save_state_to_db(); break

        nw_ust = dfs[tfs[i]].iloc[-2][f"NW_Ust_{tfs[i]}"]
        if curr_p >= nw_ust and not s_status[i] and (i==0 or s_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            old_amt, old_avg = st.session_state[f"{scalp_prefix}s_crypto"], st.session_state[f"{scalp_prefix}s_avg_price"]
            st.session_state[f"{scalp_prefix}s_avg_price"] = ((old_avg * old_amt) + (amt * curr_p)) / (old_amt + amt)
            st.session_state[f"{scalp_prefix}s_crypto"] += amt
            st.session_state[f"{scalp_prefix}s_status"][i] = True
            st.session_state[f"{scalp_prefix}s_entry_prices"][i] = curr_p
            save_state_to_db(); break
    return tp_dist, sl_dist

# ================= ANA PANEL (FRAGMENT) =================
load_state()

@st.fragment(run_every="10s")
def main_panel():
    try:
        ticker = exchange.fetch_ticker(selected_symbol)
        curr_p = ticker['last']
        dfs = {tf: fetch_tf_data(selected_symbol, tf) for tf in ["1m", "5m", "15m"]}
        tp_d, sl_d = run_engine(curr_p, dfs)
        
        # Üst Durum Çubuğu
        st.markdown(f"""
            <div class="status-bar">
                <div class="pulse"></div>
                <b>Kyoun Aktif</b> &nbsp; | &nbsp; BTC: <b>${curr_p:,.2f}</b> &nbsp; | &nbsp; 
                Saat: {datetime.datetime.now().strftime('%H:%M:%S')}
            </div>
        """, unsafe_allow_html=True)
        
        # Metrikler
        m1, m2, m3 = st.columns(3)
        m1.metric("💳 Cüzdan Bakiyesi", f"${st.session_state[f'{base_prefix}balance_usd']:,.2f}")
        
        l_active = any(st.session_state[f"{scalp_prefix}l_status"])
        s_active = any(st.session_state[f"{scalp_prefix}s_status"])
        
        # Dinamik Orta Panel: İşlem yoksa temizle, varsa göster
        if l_active or s_active:
            m2.metric("🎯 Kar-Al Hedefi", f"+${tp_d:.2f}")
            m3.metric("🛡️ Zarar-Durdur", f"-${sl_d:.2f}")
            
            with st.container(border=True):
                if l_active:
                    avg = st.session_state[f"{scalp_prefix}l_avg_price"]
                    pnl = (curr_p - avg) * st.session_state[f"{scalp_prefix}l_crypto"]
                    st.write(f"📈 **LONG POZİSYON** | Maliyet: ${avg:,.2f} | K/Z: :green[+${pnl:.4f}]")
                if s_active:
                    avg = st.session_state[f"{scalp_prefix}s_avg_price"]
                    pnl = (avg - curr_p) * st.session_state[f"{scalp_prefix}s_crypto"]
                    st.write(f"📉 **SHORT POZİSYON** | Maliyet: ${avg:,.2f} | K/Z: :red[+${pnl:.4f}]")
        else:
            m2.write("") # Boş kalsın
            m3.write("") # Boş kalsın
            st.info("⌛ **Sinyal Bekleniyor...** Nadaraya-Watson bantlarına dokunma bekleniyor.")

        # Alt Görsel (Basit Grafik)
        import plotly.graph_objects as go
        df_p = dfs["1m"].tail(40)
        fig = go.Figure(data=[go.Candlestick(x=df_p.index, open=df_p['Acilis'], high=df_p['Yuksek'], low=df_p['Dusuk'], close=df_p['Kapanis'])])
        fig.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    except Exception as e: st.error(f"Sistem Hatası: {e}")

main_panel()
