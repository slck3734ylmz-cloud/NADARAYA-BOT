import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
from supabase import create_client, Client

# ================= AYARLAR =================
BOT_LEVERAGE = 200
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

TF_PARAMS = {
    "1m":  {"limit": 60, "h": 6, "std_window": 15},
    "5m":  {"limit": 60, "h": 7, "std_window": 18},
    "15m": {"limit": 60, "h": 8, "std_window": 20},
}

# API Bilgileri
MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

# ================= GÜVENLİK =================
if "password_correct" not in st.session_state:
    st.session_state.password_correct = False

if not st.session_state.password_correct:
    pwd = st.text_input("Şifre", type="password")
    if st.button("Giriş"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.password_correct = True
            st.rerun()
        else: st.error("Hatalı!")
    st.stop()

st.set_page_config(page_title="Kyoun Scalp", layout="wide")

# ================= ARAÇLAR =================
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
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=p["h"])
    std = (df["Kapanis"] - df["NW_Merkez"]).ewm(span=p["std_window"]).std()
    df[f"NW_Alt_{tf}"] = df["NW_Merkez"] - (3.0 * std)
    df[f"NW_Ust_{tf}"] = df["NW_Merkez"] + (3.0 * std)
    # ATR
    tr = pd.concat([df["Yuksek"]-df["Dusuk"], (df["Yuksek"]-df["Kapanis"].shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return df

# ================= VERİTABANI & BAKİYE =================
selected_symbol = "BTC/USDT:USDT"
prefix = f"{selected_symbol}_scalp_"

def save_to_db():
    if not supabase: return
    try:
        data = {
            "coin_symbol": selected_symbol,
            "balance_usd": float(st.session_state.get(f"{selected_symbol}_balance_usd", 100.0)),
            "scalp_l_crypto": float(st.session_state.get(f"{prefix}l_crypto", 0.0)),
            "scalp_l_avg_price": float(st.session_state.get(f"{prefix}l_avg_price", 0.0)),
            "scalp_s_crypto": float(st.session_state.get(f"{prefix}s_crypto", 0.0)),
            "scalp_s_avg_price": float(st.session_state.get(f"{prefix}s_avg_price", 0.0)),
            "scalp_l_margin_used": 0.0,
            "scalp_s_margin_used": 0.0,
            "log_history": [],
            "trade_history": []
        }
        for i in range(3):
            data[f"scalp_l_status_{i}"] = bool(st.session_state[f"{prefix}l_status"][i])
            data[f"scalp_s_status_{i}"] = bool(st.session_state[f"{prefix}s_status"][i])
            data[f"scalp_l_entry_{i}"] = float(st.session_state[f"{prefix}l_entry_prices"][i])
            data[f"scalp_s_entry_{i}"] = float(st.session_state[f"{prefix}s_entry_prices"][i])
        supabase.table("bot_state").upsert(data, on_conflict="coin_symbol").execute()
    except: pass

def init_state():
    if f"{prefix}loaded" in st.session_state: return
    st.session_state[f"{selected_symbol}_balance_usd"] = 100.0
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
                st.session_state[f"{selected_symbol}_balance_usd"] = d.get("balance_usd", 100.0)
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

# ================= MOTOR =================
def run_logic(curr_p, dfs):
    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    atr = dfs["15m"].iloc[-2]["ATR"]
    tp_dist = max(atr * ATR_TP_MULT, curr_p * 0.0006)
    sl_dist = atr * ATR_SL_MULT

    # --- ÇIKIŞ ---
    if any(l_status):
        avg = st.session_state[f"{prefix}l_avg_price"]
        if curr_p >= (avg + tp_dist) or (l_status[2] and curr_p <= (avg - sl_dist)):
            pnl = (curr_p - avg) * st.session_state[f"{prefix}l_crypto"]
            st.session_state[f"{selected_symbol}_balance_usd"] += pnl
            st.session_state[f"{prefix}l_status"] = [False]*3
            st.session_state[f"{prefix}l_crypto"], st.session_state[f"{prefix}l_avg_price"] = 0.0, 0.0
            save_to_db()
    
    if any(s_status):
        avg = st.session_state[f"{prefix}s_avg_price"]
        if curr_p <= (avg - tp_dist) or (s_status[2] and curr_p >= (avg + sl_dist)):
            pnl = (avg - curr_p) * st.session_state[f"{prefix}s_crypto"]
            st.session_state[f"{selected_symbol}_balance_usd"] += pnl
            st.session_state[f"{prefix}s_status"] = [False]*3
            st.session_state[f"{prefix}s_crypto"], st.session_state[f"{prefix}s_avg_price"] = 0.0, 0.0
            save_to_db()

    # --- GİRİŞ ---
    tfs = ["1m", "5m", "15m"]
    for i in range(3):
        # Long
        nw_alt = dfs[tfs[i]].iloc[-2][f"NW_Alt_{tfs[i]}"]
        if curr_p <= nw_alt and not l_status[i] and (i==0 or l_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            old_amt, old_avg = st.session_state[f"{prefix}l_crypto"], st.session_state[f"{prefix}l_avg_price"]
            st.session_state[f"{prefix}l_avg_price"] = ((old_avg * old_amt) + (amt * curr_p)) / (old_amt + amt)
            st.session_state[f"{prefix}l_crypto"] += amt
            st.session_state[f"{prefix}l_status"][i] = True
            st.session_state[f"{prefix}l_entry_prices"][i] = curr_p
            save_to_db()
            break
        # Short
        nw_ust = dfs[tfs[i]].iloc[-2][f"NW_Ust_{tfs[i]}"]
        if curr_p >= nw_ust and not s_status[i] and (i==0 or s_status[i-1]):
            amt = SCALP_AMOUNTS[i]
            old_amt, old_avg = st.session_state[f"{prefix}s_crypto"], st.session_state[f"{prefix}s_avg_price"]
            st.session_state[f"{prefix}s_avg_price"] = ((old_avg * old_amt) + (amt * curr_p)) / (old_amt + amt)
            st.session_state[f"{prefix}s_crypto"] += amt
            st.session_state[f"{prefix}s_status"][i] = True
            st.session_state[f"{prefix}s_entry_prices"][i] = curr_p
            save_to_db()
            break
    return tp_dist, sl_dist

# ================= UI =================
init_state()

@st.fragment(run_every="10s")
def main():
    try:
        ticker = exchange.fetch_ticker(selected_symbol)
        curr_p = ticker['last']
        dfs = {tf: fetch_tf_data(selected_symbol, tf) for tf in ["1m", "5m", "15m"]}
        tp_d, sl_d = run_logic(curr_p, dfs)
        
        bal = st.session_state[f"{selected_symbol}_balance_usd"]
        l_active = any(st.session_state[f"{prefix}l_status"])
        s_active = any(st.session_state[f"{prefix}s_status"])
        
        # Üst Panel
        c1, c2, c3 = st.columns(3)
        c1.metric("💳 Bakiye", f"${bal:,.2f}")
        c2.metric("BTC Fiyat", f"${curr_p:,.2f}")
        
        # Pozisyon yoksa c3 boş kalsın veya sadece sistem aktif desin
        if l_active or s_active:
            c3.success(f"🎯 Kar-Al Mesafesi: ${tp_d:.2f}")
            if l_active:
                avg = st.session_state[f"{prefix}l_avg_price"]
                pnl = (curr_p - avg) * st.session_state[f"{prefix}l_crypto"]
                st.info(f"📈 LONG AÇIK | Maliyet: {avg:,.2f} | K/Z: ${pnl:+.4f}")
            if s_active:
                avg = st.session_state[f"{prefix}s_avg_price"]
                pnl = (avg - curr_p) * st.session_state[f"{prefix}s_crypto"]
                st.warning(f"📉 SHORT AÇIK | Maliyet: {avg:,.2f} | K/Z: ${pnl:+.4f}")
        else:
            c3.write("🟢 Sistem Aktif / Sinyal Bekleniyor")

    except Exception as e:
        st.error(f"Hata: {str(e)}")

main()
