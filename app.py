import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import requests
from supabase import create_client, Client

# ================= KİMLİK BİLGİSİ TEMİZLEME (401 HATASI ÇÖZÜMÜ) =================
def get_clean_secret(key):
    val = st.secrets.get(key, "")
    if not val: return ""
    # Tüm tırnakları, boşlukları ve gizli karakterleri temizler
    return str(val).strip().replace("'", "").replace('"', '').replace(" ", "")

MEXC_API_KEY = get_clean_secret("MEXC_API_KEY")
MEXC_API_SECRET = get_clean_secret("MEXC_API_SECRET")
SUPABASE_URL = get_clean_secret("SUPABASE_URL")
SUPABASE_KEY = get_clean_secret("SUPABASE_KEY")
TELEGRAM_TOKEN = get_clean_secret("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = get_clean_secret("TELEGRAM_CHAT_ID")
ADMIN_PASSWORD = get_clean_secret("ADMIN_PASSWORD")
VIEWER_PASSWORD = "dca2026"

# ================= TEMEL AYARLAR =================
BOT_LEVERAGE = 200  
MEXC_TAKER_FEE_PCT = 0.0002  
MIN_PROFIT_SAFETY_MULT = 3.0  
RSI_MIDPOINT = 50  

TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "rsi_period": 7,  "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "rsi_period": 9,  "std_window": 18},
    "15m": {"limit": 110, "h": 8, "rsi_period": 9,  "std_window": 20},
    "1h":  {"limit": 120, "h": 8, "rsi_period": 14, "std_window": 20},
    "4h":  {"limit": 90,  "h": 7, "rsi_period": 14, "std_window": 18},
    "1d":  {"limit": 60,  "h": 6, "rsi_period": 14, "std_window": 14},
}

DCA_AMOUNTS = [0.0001, 0.0004, 0.0015]   
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]  
SCALP_TIMEFRAMES = ["1m", "5m", "15m"]    
ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# ================= GİRİŞ EKRANI =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True

    st.markdown("""<style>div[data-testid="stForm"] {max-width:380px;margin:0 auto;}</style>""", unsafe_allow_html=True)
    _, col_login, _ = st.columns([1, 1.4, 1])
    with col_login:
        with st.form(key="login_form"):
            user_password = st.text_input("Şifre", type="password", placeholder="Şifrenizi girin")
            if st.form_submit_button("Giriş Yap", use_container_width=True):
                if user_password == VIEWER_PASSWORD:
                    st.session_state.password_correct = True
                    st.session_state.user_role = "viewer"
                    st.rerun()
                elif ADMIN_PASSWORD and user_password == ADMIN_PASSWORD:
                    st.session_state.password_correct = True
                    st.session_state.user_role = "admin"
                    st.rerun()
                else: st.error("❌ Hatalı Şifre!")
    return False

if not check_password(): st.stop()
st.set_page_config(page_title="Kyoun | DCA & Scalp Hedging Terminal", layout="wide")

# ================= MATEMATİKSEL FONKSİYONLAR =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high, low, close = df["Yuksek"], df["Dusuk"], df["Kapanis"]
    tr = pd.concat([high-low, (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def nadaraya_watson_estimator(src, h=8):
    n = len(src); estimates = np.zeros(n)
    for i in range(n):
        past = np.arange(i + 1)
        weights = np.exp(-((past - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * weights) / np.sum(weights)
    return estimates

def calculate_nw_bands(df, std_multiplier, col_suffix, h=8, std_window=20):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=h)
    df["Sapma_Std"] = (df["Kapanis"] - df["NW_Merkez"]).ewm(span=std_window, min_periods=std_window).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

def fetch_with_retry(fetch_fn):
    for attempt in range(3):
        try: return fetch_fn()
        except: time.sleep(0.5)
    return None

def fetch_tf_data(symbol, tf):
    p = TF_PARAMS[tf]
    raw = fetch_with_retry(lambda: exchange.fetch_ohlcv(symbol, tf, limit=p["limit"]))
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    df = calculate_nw_bands(df, 3.0, f"_{tf}", h=p["h"], std_window=p["std_window"])
    df["RSI"] = calculate_rsi(df["Kapanis"], period=p["rsi_period"])
    df["ATR"] = calculate_atr(df, period=14)
    return df

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🐑 *Kyoun*\n{message}", "parse_mode": "Markdown"})

def place_futures_order(symbol, side, amount, is_live=False, reduce_only=False):
    if not is_live: return {"status": "simulated"}
    params = {"leverage": BOT_LEVERAGE, "marginMode": "cross"}
    if reduce_only: params["reduceOnly"] = True
    return exchange.create_order(symbol, "market", side, amount, None, params)

# ================= STATE VE DB =================
selected_symbol = "BTC/USDT:USDT"
coin_title = selected_symbol.split(':')[0]
base_prefix = f"{selected_symbol}_"

def empty_position_state():
    return {"l_status": [False]*3, "l_entry_prices": [0.0]*3, "l_crypto": 0.0, "l_usd_spent": 0.0, "l_avg_price": 0.0,
            "s_status": [False]*3, "s_entry_prices": [0.0]*3, "s_crypto": 0.0, "s_usd_spent": 0.0, "s_avg_price": 0.0}

def load_state(sk):
    prefix = f"{base_prefix}{sk}_"
    if f"{prefix}loaded" in st.session_state: return prefix
    defaults = empty_position_state()
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).order("id", desc=True).limit(1).execute()
            if q.data:
                d = q.data[0]
                for side in ["l", "s"]:
                    defaults[f"{side}_crypto"] = d.get(f"{sk}_{side}_crypto", 0.0)
                    defaults[f"{side}_avg_price"] = d.get(f"{sk}_{side}_avg_price", 0.0)
                    defaults[f"{side}_status"] = [d.get(f"{sk}_{side}_status_{i}", False) for i in range(3)]
                st.session_state[f"{base_prefix}balance_usd"] = d.get("balance_usd", 100.0)
                st.session_state[f"{base_prefix}trade_history"] = d.get("trade_history") or []
        except Exception as e: st.session_state[f"{base_prefix}db_load_error"] = str(e)
    for k, v in defaults.items(): st.session_state[f"{prefix}{k}"] = v
    st.session_state[f"{prefix}loaded"] = True
    return prefix

def save_state_to_db():
    if not supabase: return
    try:
        data = {"coin_symbol": selected_symbol, "balance_usd": st.session_state.get(f"{base_prefix}balance_usd", 100.0),
                "trade_history": st.session_state.get(f"{base_prefix}trade_history", [])}
        for sk in ["dca", "scalp"]:
            pref = f"{base_prefix}{sk}_"
            for s in ["l", "s"]:
                data[f"{sk}_{s}_crypto"] = st.session_state.get(f"{pref}{s}_crypto", 0.0)
                data[f"{sk}_{s}_avg_price"] = st.session_state.get(f"{pref}{s}_avg_price", 0.0)
                for i in range(3): data[f"{sk}_{s}_status_{i}"] = st.session_state.get(f"{pref}{s}_status", [False]*3)[i]
        supabase.table("bot_state").upsert(data).execute()
    except Exception as e: st.sidebar.error(f"Kayıt Hatası: {e}")

# ================= MOTOR (İLK DOSYADAKİ KOMPLE MANTIK) =================
def run_staged_strategy(strategy_key, strategy_label, prefix, current_price, dfs_by_tf, amounts, is_live, manual_lock=False, allow_new_entries=True):
    tf_names = list(dfs_by_tf.keys()); dfk = list(dfs_by_tf.values())
    raw_alt = [df.iloc[-2][f"NW_Alt_{tf}"] for df, tf in zip(dfk, tf_names)]
    raw_ust = [df.iloc[-2][f"NW_Ust_{tf}"] for df, tf in zip(dfk, tf_names)]
    atr_vals = [df.iloc[-2]["ATR"] for df in dfk]
    
    MIN_STAGE_GAP_ATR_MULT = 0.5
    alt_base, alt_ready = [raw_alt[0]], [True]
    for i in range(1, 3):
        gap = alt_base[-1] - raw_alt[i]
        alt_base.append(raw_alt[i]); alt_ready.append(gap >= (MIN_STAGE_GAP_ATR_MULT * atr_vals[i]))
    
    ust_base, ust_ready = [raw_ust[0]], [True]
    for i in range(1, 3):
        gap = raw_ust[i] - ust_base[-1]
        ust_base.append(raw_ust[i]); ust_ready.append(gap >= (MIN_STAGE_GAP_ATR_MULT * atr_vals[i]))

    l_status = st.session_state[f"{prefix}l_status"]; s_status = st.session_state[f"{prefix}s_status"]
    nw_alt = [st.session_state[f"{prefix}l_entry_prices"][i] if l_status[i] else alt_base[i] for i in range(3)]
    nw_ust = [st.session_state[f"{prefix}s_entry_prices"][i] if s_status[i] else ust_base[i] for i in range(3)]

    rsi_vals = [df.iloc[-2]["RSI"] for df in dfk]; atr_k3 = dfk[2].iloc[-2]["ATR"]
    tp_distance = max(ATR_TP_MULT * atr_k3, current_price * 0.0002 * 2 * 3.0)
    sl_distance = ATR_SL_MULT * atr_k3

    # Long Çıkış
    if st.session_state[f"{prefix}l_crypto"] > 0:
        avg = st.session_state[f"{prefix}l_avg_price"]
        if current_price >= avg + tp_distance or (l_status[2] and current_price <= avg - sl_distance):
            place_futures_order(selected_symbol, "sell", st.session_state[f"{prefix}l_crypto"], is_live, True)
            send_telegram_msg(f"{strategy_label} LONG KAPANDI"); st.session_state[f"{prefix}l_crypto"] = 0.0; st.session_state[f"{prefix}l_status"] = [False]*3; save_state_to_db()

    # Short Çıkış
    if st.session_state[f"{prefix}s_crypto"] > 0:
        avg = st.session_state[f"{prefix}s_avg_price"]
        if current_price <= avg - tp_distance or (s_status[2] and current_price >= avg + sl_distance):
            place_futures_order(selected_symbol, "buy", st.session_state[f"{prefix}s_crypto"], is_live, True)
            send_telegram_msg(f"{strategy_label} SHORT KAPANDI"); st.session_state[f"{prefix}s_crypto"] = 0.0; st.session_state[f"{prefix}s_status"] = [False]*3; save_state_to_db()

    # Girişler
    if allow_new_entries:
        for i in range(3):
            if current_price <= nw_alt[i] and rsi_vals[i] < 50 and (i==0 or l_status[i-1]) and not l_status[i] and alt_ready[i]:
                place_futures_order(selected_symbol, "buy", amounts[i], is_live)
                st.session_state[f"{prefix}l_crypto"] += amounts[i]; st.session_state[f"{prefix}l_status"][i] = True
                st.session_state[f"{prefix}l_avg_price"] = current_price; save_state_to_db(); break
            if current_price >= nw_ust[i] and rsi_vals[i] > 50 and (i==0 or s_status[i-1]) and not s_status[i] and ust_ready[i]:
                place_futures_order(selected_symbol, "sell", amounts[i], is_live)
                st.session_state[f"{prefix}s_crypto"] += amounts[i]; st.session_state[f"{prefix}s_status"][i] = True
                st.session_state[f"{prefix}s_avg_price"] = current_price; save_state_to_db(); break

    return {"tp_distance": tp_distance, "sl_distance": sl_distance}

# ================= UI VE DÖNGÜ =================
dca_pref = load_state("dca"); scalp_pref = load_state("scalp")
is_admin = st.session_state.get("user_role") == "admin"
mode = st.sidebar.radio("Mod", ["📝 Kağıt Mod", "🔴 Canlı Mod"], index=0, disabled=not is_admin)
active_strat = st.sidebar.radio("Aktif Strateji", ["DCA", "Scalp"], index=0, disabled=not is_admin)

@st.fragment(run_every="10s")
def main_fragment():
    ticker = fetch_with_retry(lambda: exchange.fetch_ticker(selected_symbol))
    price = ticker['last']
    st.subheader(f"📊 {coin_title}: ${price:,.2f}")
    
    dfs = {tf: fetch_tf_data(selected_symbol, tf) for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]}
    
    # Motorları çalıştır
    run_staged_strategy("dca", "DCA", dca_pref, price, {k: dfs[k] for k in ["1m", "5m", "15m"]}, DCA_AMOUNTS, mode=="🔴 Canlı Mod", allow_new_entries=(active_strat=="DCA"))
    run_staged_strategy("scalp", "Scalp", scalp_prefix, price, {k: dfs[k] for k in ["1m", "5m", "15m"]}, SCALP_AMOUNTS, mode=="🔴 Canlı Mod", allow_new_entries=(active_strat=="Scalp"))
    
    # Bilgi Paneli
    c1, c2 = st.columns(2)
    c1.metric("DCA Pozisyon", f"{st.session_state[f'{dca_pref}l_crypto']:.4f} BTC")
    c2.metric("Scalp Pozisyon", f"{st.session_state[f'{scalp_pref}l_crypto']:.4f} BTC")
    st.session_state["dca_last_success"] = time.time()

main_fragment()
