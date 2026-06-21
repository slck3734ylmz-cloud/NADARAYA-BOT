import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go
from supabase import create_client, Client

# ================= GÜVENLİK GİRİŞİ =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True
    st.markdown("<h2 style='text-align: center; color: white; margin-top: 50px;'>🔒 DCA Terminal Güvenlik Girişi</h2>", unsafe_allow_html=True)
    col_login, _ = st.columns([1, 1.5])
    with col_login:
        user_password = st.text_input("Lütfen şahsi siber güvenlik şifrenizi girin:", type="password", key="login_pass_key_global")
        if st.button("Giriş Yap", key="login_btn_key_global"):
            if user_password == "dca2026": 
                st.session_state.password_correct = True
                st.rerun()
            else: st.error("❌ Hatalı Şifre! Erişim reddedildi.")
    return False

if not check_password(): st.stop()

st.set_page_config(page_title="DCA Live Hedging Terminal", layout="wide")

# Flicker-Free CSS
st.markdown("<style>div[data-testid='stAppViewBlockContainer']{opacity:1.0!important;transition:none!important;}div[data-testid='stStatusWidget']{display:none!important;visibility:hidden!important;}</style>", unsafe_allow_html=True)

# API ve Database Bağlantıları
telegram_token = "8736096328:AAH2_3BAIhbOxy9yo7v-L47h9KK3xCbALXE"
telegram_chat_id = "@kyounkripto"
supabase_url = "https://ahnwbxfghccotwnlhzgl.supabase.co"
supabase_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFobndieGZnaGNjb3R3bmxoemdsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIwMTI3NzcsImV4cCI6MjA5NzU4ODc3N30.9cR5NBti19ddH7UivdcikYFoCRwk42mIkOkElYqT2Oc"
supabase: Client = create_client(supabase_url, supabase_key)
exchange = ccxt.gate({'options': {'defaultType': 'swap'}})

# ================= MATEMATİKSEL METRİKLER =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    return 100 - (100 / (1 + (gain / (loss + 1e-9))))

def detect_rsi_divergence(closes, rsis):
    if len(closes) < 15 or len(rsis) < 15: return False, False
    c, r = closes[-15:], rsis[-15:]
    lows = [i for i in range(1, len(c)-1) if c[i] < c[i-1] and c[i] < c[i+1]]
    bull = len(lows) >= 2 and c[lows[-1]] < c[lows[-2]] and r[lows[-1]] > r[lows[-2]] and r[lows[-1]] < 45
    highs = [i for i in range(1, len(c)-1) if c[i] > c[i-1] and c[i] > c[i+1]]
    bear = len(highs) >= 2 and c[highs[-1]] > c[highs[-2]] and r[highs[-1]] < r[highs[-2]] and r[highs[-1]] > 55
    return bull, bear

@st.cache_data(ttl=300)
def get_top_50_volume_coins():
    try:
        tickers = exchange.fetch_tickers()
        usd = []
        for sym, t in tickers.items():
            if sym.endswith(':USDT'):
                v = t.get('quoteVolume') or (t.get('baseVolume', 0.0) * (t.get('last') or t.get('close') or 0.0))
                if v > 0: usd.append({'symbol': sym, 'volume': v, 'price': t.get('last') or t.get('close') or 0.0, 'change': t.get('percentage') or 0.0})
        usd.sort(key=lambda x: x['volume'], reverse=True)
        return [{'symbol': x['symbol'], 'display': f"{x['symbol'].split(':')[0]} (${x['price']:,.2f} | {x['change']:+.2f}%)"} for x in usd[:50]]
    except: return [{'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"}]

@st.cache_data(ttl=300)
def get_market_movers_and_funding():
    try:
        tickers = exchange.fetch_tickers()
        movers, funding = [], []
        for sym, t in tickers.items():
            if sym.endswith(':USDT'):
                p, c = t.get('last') or t.get('close') or 0.0, t.get('percentage') or 0.0
                fr = float(t.get('info', {}).get('funding_rate', 0.0)) * 100.0
                clean = sym.split(":")[0]
                if p > 0:
                    movers.append({'Coin': clean, 'Fiyat (USDT)': p, 'Değişim (%)': c, 'Fonlama Oranı': fr})
                    funding.append({'symbol': clean, 'rate': fr})
        funding.sort(key=lambda x: abs(x['rate']), reverse=True)
        df_m = pd.DataFrame(movers)
        df_g = df_m.sort_values(by='Değişim (%)', ascending=False).head(5).copy()
        df_l = df_m.sort_values(by='Değişim (%)', ascending=True).head(5).copy()
        for df in [df_g, df_l]:
            df['Değişim (%)'] = df['Değişim (%)'].apply(lambda x: f"{x:+.2f}%")
            df['Fonlama Oranı'] = df['Fonlama Oranı'].apply(lambda x: f"{x:+.4f}%")
            df['Fiyat (USDT)'] = df['Fiyat (USDT)'].apply(lambda x: f"${x:,.2f}")
        return funding[:5], df_g, df_l
    except: return [], pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=300)
def estimate_liquidation_pools(symbol):
    try:
        raw = exchange.fetch_ohlcv(symbol, "1h", limit=72)
        df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        cur = df.iloc[-1]["Kapanis"]
        step = 50.0 if cur > 10000 else (1.0 if cur > 100 else (0.1 if cur > 1 else 0.01))
        long_l, short_l = {}, {}
        for i, row in df.iterrows():
            for m in [0.99, 0.98, 0.96]:
                p = round((row["Dusuk"] * m) / step) * step
                long_l[p] = long_l.get(p, 0.0) + row["Hacim"]
            for m in [1.01, 1.02, 1.04]:
                p = round((row["Yuksek"] * m) / step) * step
                short_l[p] = short_l.get(p, 0.0) + row["Hacim"]
        sl, ss = sorted(long_l.items(), key=lambda x: x[1], reverse=True)[:3], sorted(short_l.items(), key=lambda x: x[1], reverse=True)[:3]
        sl.sort(key=lambda x: x[0], reverse=True)
        ss.sort(key=lambda x: x[0], reverse=False)
        return (
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Yoğunluk Derecesi": "🔴🔴🔴 YÜKSEK" if v > df["Hacim"].mean()*1.5 else "🔴🔴 ORTA"} for p, v in sl]),
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Yoğunluk Derecesi": "🟢🟢🟢 YÜKSEK" if v > df["Hacim"].mean()*1.5 else "🟢🟢 ORTA"} for p, v in ss])
        )
    except: return pd.DataFrame(), pd.DataFrame()

# Non-Repainting NW Filtresi ve Grafik Çizimi
def nadaraya_watson_estimator(src, h=8):
    n = len(src)
    estimates = np.zeros(n)
    for i in range(n):
        past_indices = np.arange(i + 1)
        weights = np.exp(-((past_indices - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * weights) / np.sum(weights)
    return estimates

def calculate_nw_bands(df, std_multiplier, col_suffix):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=8)
    df["Fark"] = df["Kapanis"] - df["NW_Merkez"]
    df["Sapma_Std"] = df["Fark"].rolling(window=20).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

def draw_plotly_chart(df_subset, price_col, alt_band_col, ust_band_col, title, l_avg=0.0, s_avg=0.0):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[price_col], name="Anlık Fiyat", line=dict(color='royalblue', width=2)))
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[ust_band_col], name="Üst Band (Satış)", line=dict(color='crimson', width=1.5, dash='dash')))
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[alt_band_col], name="Alt Band (Alış)", line=dict(color='limegreen', width=1.5, dash='dash')))
    if l_avg > 0: fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[l_avg]*len(df_subset), name="Long Maliyet Ort.", line=dict(color='green', width=1.5)))
    if s_avg > 0: fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[s_avg]*len(df_subset), name="Short Maliyet Ort.", line=dict(color='red', width=1.5)))
    fig.update_layout(title=title, template="plotly_dark", xaxis_title="Zaman", yaxis_title="Fiyat", margin=dict(l=20, r=20, t=40, b=20), height=400, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig

# ================= GLOBAL VERİLER VE YAN PANEL =================
extreme_rates, df_gainers, df_losers = get_market_movers_and_funding()
top_50_data = get_top_50_volume_coins()

selected_display = st.sidebar.selectbox("🔥 Vadeli Coin Seçin", [x['display'] for x in top_50_data], key="sidebar_coin_selectbox_global")
selected_symbol = [x['symbol'] for x in top_50_data if x['display'] == selected_display][0]
coin_title = selected_symbol.split(':')[0]
state_prefix = f"{selected_symbol}_"

try:
    db = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).execute()
    if db.data:
        data = db.data[0]
        for k in ["balance_usd", "l_crypto", "l_usd_spent", "l_avg_price", "s_crypto", "s_usd_spent", "s_avg_price", "log_history"]:
            st.session_state[f"{state_prefix}{k}"] = data[k] if k != "log_history" else (data[k] or [])
        st.session_state[f"{state_prefix}l_status"] = [data["l_status_0"], data["l_status_1"], data["l_status_2"]]
        st.session_state[f"{state_prefix}s_status"] = [data["s_status_0"], data["s_status_1"], data["s_status_2"]]
except: pass

if f"{state_prefix}balance_usd" not in st.session_state:
    st.session_state[f"{state_prefix}balance_usd"] = 100.0
    st.session_state[f"{state_prefix}l_status"] = [False, False, False]
    st.session_state[f"{state_prefix}l_crypto"] = 0.0
    st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
    st.session_state[f"{state_prefix}l_avg_price"] = 0.0
    st.session_state[f"{state_prefix}s_status"] = [False, False, False]
    st.session_state[f"{state_prefix}s_crypto"] = 0.0
    st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
    st.session_state[f"{state_prefix}s_avg_price"] = 0.0
    st.session_state[f"{state_prefix}log_history"] = []
if f"{state_prefix}locked_prices" not in st.session_state: st.session_state[f"{state_prefix}locked_prices"] = None

def save_state_to_db():
    try:
        data = {
            "coin_symbol": selected_symbol, "balance_usd": st.session_state[f"{state_prefix}balance_usd"],
            "l_status_0": st.session_state[f"{state_prefix}l_status"][0], "l_status_1": st.session_state[f"{state_prefix}l_status"][1], "l_status_2": st.session_state[f"{state_prefix}l_status"][2],
            "l_crypto": st.session_state[f"{state_prefix}l_crypto"], "l_usd_spent": st.session_state[f"{state_prefix}l_usd_spent"], "l_avg_price": st.session_state[f"{state_prefix}l_avg_price"],
            "s_status_0": st.session_state[f"{state_prefix}s_status"][0], "s_status_1": st.session_state[f"{state_prefix}s_status"][1], "s_status_2": st.session_state[f"{state_prefix}s_status"][2],
            "s_crypto": st.session_state[f"{state_prefix}s_crypto"], "s_usd_spent": st.session_state[f"{state_prefix}s_usd_spent"], "s_avg_price": st.session_state[f"{state_prefix}s_avg_price"],
            "log_history": st.session_state[f"{state_prefix}log_history"]
        }
        supabase.table("bot_state").upsert(data).execute()
    except Exception as e: st.sidebar.error(f"Veritabanı hatası: {e}")

try:
    ticker_info = exchange.fetch_ticker(selected_symbol)
    coin_price = ticker_info.get('last') or ticker_info.get('close') or 63000.0
    scale = 63000.0 / coin_price
    layer_sizes = [0.0001 * scale, 0.0002 * scale, 0.0012 * scale]
except: layer_sizes = [0.0001, 0.0002, 0.0012]

target_profit, stop_loss = 0.01, 0.02
def send_telegram_msg(message):
    try: requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage", json={"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"})
    except: pass

# ================= MODLARIN ÇALIŞTIRILMASI =================
if app_mode == "📊 Geriye Dönük Test (Backtest)":
    st.title("📊 Geriye Dönük Test (Backtest) Masası")
    col_bt1, col_bt2, col_bt3 = st.columns(3)
    bt_tf = col_bt1.selectbox("Test Zaman Dilimi", ["5m", "15m", "1h", "4h"], index=2, key="backtest_tf_unique")
    bt_limit = col_bt2.number_input("Test Edilecek Mum Sayısı", min_value=100, max_value=3000, value=1000, step=100, key="backtest_limit_unique")
    bt_std = col_bt3.number_input("Std Sapma Çarpanı", min_value=1.5, max_value=4.0, value=3.0, step=0.1, key="backtest_std_input")
    bt_tp = st.slider("Hedef Kar-Al (%)", min_value=0.2, max_value=5.0, value=1.0, step=0.1, key="bt_tp_slider") / 100.0
    bt_sl = st.slider("Stop-Loss (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.1, key="bt_sl_slider") / 100.0
    
    if st.button("▶️ Geriye Dönük Testi Çalıştır", key="backtest_run_button"):
        with st.spinner("Veriler analiz ediliyor..."):
            try:
                bt_raw = exchange.fetch_ohlcv(selected_symbol, bt_tf, limit=int(bt_limit))
                df_bt = pd.DataFrame(bt_raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
                df_bt["Zaman"] = pd.to_datetime(df_bt["Zaman"], unit="ms")
                df_bt = calculate_nw_bands(df_bt, bt_std * 0.7, "_K1")
                df_bt = calculate_nw_bands(df_bt, bt_std * 0.85, "_K2")
                df_bt = calculate_nw_bands(df_bt, bt_std, "_K3")
                
                initial, balance = 1000.0, 1000.0
                l_status, l_crypto, l_usd, l_avg = [False, False, False], 0.0, 0.0, 0.0
                equity, logs = [], []
                
                for i, row in df_bt.iterrows():
                    close, t_time = row["Kapanis"], row["Zaman"]
                    if sum(l_status) > 0:
                        l_tp_target = l_avg * (1 + bt_tp)
                        if l_status[2] and close <= (df_bt.at[i, "NW_Alt_K3"] * (1 - bt_sl)):
                            balance += l_crypto * close
                            logs.append({"Tür": "LONG STOP-LOSS", "Kapanış Zamanı": t_time, "Giriş Fiyatı": l_avg, "Kapanış Fiyatı": close, "Kar/Zarar ($)": (l_crypto * close) - l_usd, "Kalan Bakiye": balance})
                            l_crypto, l_usd, l_avg, l_status = 0.0, 0.0, 0.0, [False, False, False]
                        elif close >= l_tp_target:
                            balance += l_crypto * close
                            logs.append({"Tür": "LONG KAR-AL", "Kapanış Zamanı": t_time, "Giriş Fiyatı": l_avg, "Kapanış Fiyatı": close, "Kar/Zarar ($)": (l_crypto * close) - l_usd, "Kalan Bakiye": balance})
                            l_crypto, l_usd, l_avg, l_status = 0.0, 0.0, 0.0, [False, False, False]
                            
                    for idx, th, val in zip([0, 1, 2], ["_K1", "_K2", "_K3"], [0.05, 0.10, 0.25]):
                        if close <= row[f"NW_Alt{th}"] and (idx == 0 or l_status[idx-1]) and not l_status[idx]:
                            buy_usd = initial * val
                            if balance >= buy_usd:
                                balance -= buy_usd
                                l_crypto += buy_usd / close
                                l_usd += buy_usd
                                l_status[idx] = True
                                l_avg = l_usd / l_crypto
                    equity.append(balance + (l_crypto * close))
                    
                df_eq, df_tr = pd.DataFrame({"Zaman": df_bt["Zaman"], "Bakiye": equity}), pd.DataFrame(logs)
                if not df_tr.empty:
                    st.metric("Win Rate", f"%{(len(df_tr[df_tr['Kar/Zarar ($)'] > 0]) / len(df_tr)) * 100.0:.1f}")
                    fig_bt = go.Figure()
                    fig_bt.add_trace(go.Scatter(x=df_eq["Zaman"], y=df_eq["Bakiye"], name="Bakiye", line=dict(color="gold", width=2.5)))
                    fig_bt.update_layout(title="Equity Curve", template="plotly_dark", height=400)
                    st.plotly_chart(fig_bt, use_container_width=True, key="backtest_chart_p")
                    st.dataframe(df_tr)
                else: st.warning("İşlem gerçekleşmedi.")
            except Exception as e: st.error(f"Hata: {e}")

elif app_mode == "🖥️ Canlı DCA Terminal":
    manual_lock = st.sidebar.toggle("🔒 Bekleyen Seviyeleri Dondur", value=False, key="live_manual_lock_toggle")
    
    if st.sidebar.button("🔴 Tüm Kademeleri Manuel Sıfırla", key="live_reset_all_positions_button"):
        for k in ["l_crypto", "l_usd_spent", "l_avg_price", "s_crypto", "s_usd_spent", "s_avg_price", "locked_prices"]:
            st.session_state[f"{state_prefix}{k}"] = 0.0 if k != "locked_prices" else None
        st.session_state[f"{state_prefix}l_status"] = [False, False, False]
        st.session_state[f"{state_prefix}s_status"] = [False, False, False]
        st.session_state[f"{state_prefix}balance_usd"] = 100.0
        save_state_to_db()
        st.rerun()

    st.sidebar.write("🔄 Sonraki Tarama İlerlemesi:")
    countdown_placeholder = st.sidebar.empty()
    main_container = st.empty()

    while True:
        try:
            live_ticker = exchange.fetch_ticker(selected_symbol)
            current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
            price_change_24h = live_ticker.get('percentage') or 0.0

            raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=210)
            df_4h_master = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_4h_master["EMA_200"] = df_4h_master["Kapanis"].ewm(span=200, adjust=False).mean()
            trend_4h = "YUKARI (BOĞA)" if df_4h_master.iloc[-1]["Kapanis"] > df_4h_master.iloc[-1]["EMA_200"] else "AŞAĞI (AYI)"
            warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

            raw_vol = exchange.fetch_ohlcv(selected_symbol, "15m", limit=120)
            df_vol = pd.DataFrame(raw_vol, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            is_volatile = df_vol["Kapanis"].rolling(20).std().iloc[-1] > df_vol["Kapanis"].rolling(20).std().median()
            market_state_label = "⚡ VOLATİL (Trend / Sert Hareket)" if is_volatile else "💤 SAKİN (Yatay Salınım)"

            raw_candles = exchange.fetch_ohlcv(selected_symbol, "1m", limit=1000)
            df_1m = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_1m["Zaman"] = pd.to_datetime(df_1m["Zaman"], unit="ms")
            df_1m = calculate_nw_bands(df_1m, 3.0, "_1m")
            df_1m["RSI"] = calculate_rsi(df_1m["Kapanis"])

            dfs = {}
            for tf, name in zip(["5min", "15min", "60min", "240min"], ["_5m", "_15m", "_1h", "_4h"]):
                df_res = df_1m.resample(tf, on='Zaman').agg({'Acilis':'first', 'Yuksek':'max', 'Dusuk':'min', 'Kapanis':'last', 'Hacim':'sum'}).reset_index()
                df_res = calculate_nw_bands(df_res, 3.0, name)
                df_res["RSI"] = calculate_rsi(df_res["Kapanis"])
                dfs[name] = df_res

            df_5m, df_15m, df_1h, df_4h = dfs["_5m"], dfs["_15m"], dfs["_1h"], dfs["_4h"]

            raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=100)
            df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
            df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
            df_1d = calculate_nw_bands(df_1d, 3.0, "_1d")
            df_1d["RSI"] = calculate_rsi(df_1d["Kapanis"])

            df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol)

            if not is_volatile:
                dyn_alt_5m, dyn_alt_1h, dyn_alt_4h = df_1m.iloc[-1]["NW_Alt_1m"], df_5m.iloc[-1]["NW_Alt_5m"], df_15m.iloc[-1]["NW_Alt_15m"]
                dyn_ust_5m, dyn_ust_1h, dyn_ust_4h = df_1m.iloc[-1]["NW_Ust_1m"], df_5m.iloc[-1]["NW_Ust_5m"], df_15m.iloc[-1]["NW_Ust_15m"]
                l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
                s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"
                active_engine_name = "⏱️ SİSTEM A: ULTRA HIZLI SCALP (1m/5m/15m)"
            else:
                dyn_alt_5m, dyn_alt_1h, dyn_alt_4h = df_5m.iloc[-1]["NW_Alt_5m"], df_1h.iloc[-1]["NW_Alt_1h"], df_4h.iloc[-1]["NW_Alt_4h"]
                dyn_ust_5m, dyn_ust_1h, dyn_ust_4h = df_5m.iloc[-1]["NW_Ust_5m"], df_1h.iloc[-1]["NW_Ust_1h"], df_4h.iloc[-1]["NW_Ust_4h"]
                l1_lbl, l2_lbl, l3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
                s1_lbl, s2_lbl, s3_lbl = "Kademe 1 (5m)", "Kademe 2 (1h)", "Kademe 3 (4h)"
                active_engine_name = "🌎 SİSTEM B: MAKRO TREND (5m/1h/4h)"

            if manual_lock:
                if st.session_state[f"{state_prefix}locked_prices"] is None:
                    st.session_state[f"{state_prefix}locked_prices"] = {"nw_alt_5m": dyn_alt_5m, "nw_alt_1h": dyn_alt_1h, "nw_alt_4h": dyn_alt_4h, "nw_ust_5m": dyn_ust_5m, "nw_ust_1h": dyn_ust_1h, "nw_ust_4h": dyn_ust_4h}
                nw_alt_5m, nw_alt_1h, nw_alt_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_alt_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_alt_4h"]
                nw_ust_5m, nw_ust_1h, nw_ust_4h = st.session_state[f"{state_prefix}locked_prices"]["nw_ust_5m"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_1h"], st.session_state[f"{state_prefix}locked_prices"]["nw_ust_4h"]
            else:
                st.session_state[f"{state_prefix}locked_prices"] = None
                nw_alt_5m, nw_alt_1h, nw_alt_4h = dyn_alt_5m, dyn_alt_1h, dyn_alt_4h
                nw_ust_5m, nw_ust_1h, nw_ust_4h = dyn_ust_5m, dyn_ust_1h, dyn_ust_4h

            rsi_1m_val, rsi_5m_val, rsi_15m_val, rsi_1h_val, rsi_4h_val, rsi_1d_val = df_1m.iloc[-1]["RSI"], df_5m.iloc[-1]["RSI"], df_15m.iloc[-1]["RSI"], df_1h.iloc[-1]["RSI"], df_4h.iloc[-1]["RSI"], df_1d.iloc[-1]["RSI"]

            # LONG ÇIKIŞLARI
            if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                l_tp = st.session_state[f"{state_prefix}l_avg_price"] * (1 + target_profit_ratio)
                if st.session_state[f"{state_prefix}l_status"][2] and current_price <= (nw_alt_4h * (1 - stop_loss_ratio)):
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                    msg = f"🔴 *LONG STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"], st.session_state[f"{state_prefix}l_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()
                elif current_price >= l_tp:
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                    msg = f"🟢 *LONG KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"], st.session_state[f"{state_prefix}l_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()

            # SHORT ÇIKIŞLARI
            if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                s_stop = st.session_state[f"{state_prefix}s_avg_price"] * (1 + stop_loss_ratio)
                s_tp = st.session_state[f"{state_prefix}s_avg_price"] * (1 - target_profit_ratio)
                if st.session_state[f"{state_prefix}s_status"][2] and current_price >= s_stop:
                    pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                    msg = f"🔴 *SHORT STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"], st.session_state[f"{state_prefix}s_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()
                elif current_price <= s_tp:
                    pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                    msg = f"🟢 *SHORT KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"], st.session_state[f"{state_prefix}s_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    save_state_to_db()

            # LONG GİRİŞLERİ
            for idx, th, val in zip([0, 1, 2], [nw_alt_5m, nw_alt_1h, nw_alt_4h], layer_sizes):
                if current_price <= th and (idx == 0 or st.session_state[f"{state_prefix}l_status"][idx-1]) and not st.session_state[f"{state_prefix}l_status"][idx]:
                    st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                    st.session_state[f"{state_prefix}l_crypto"] += val
                    st.session_state[f"{state_prefix}l_usd_spent"] += val * current_price
                    st.session_state[f"{state_prefix}l_status"][idx] = True
                    st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
                    msg = f"📈 *LONG K{idx+1} SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    save_state_to_db()

            # SHORT GİRİŞLERİ
            for idx, th, val in zip([0, 1, 2], [nw_ust_5m, nw_ust_1h, nw_ust_4h], layer_sizes):
                if current_price >= th and (idx == 0 or st.session_state[f"{state_prefix}s_status"][idx-1]) and not st.session_state[f"{state_prefix}s_status"][idx]:
                    st.session_state[f"{state_prefix}balance_usd"] -= val * current_price
                    st.session_state[f"{state_prefix}s_crypto"] += val
                    st.session_state[f"{state_prefix}s_usd_spent"] += val * current_price
                    st.session_state[f"{state_prefix}s_status"][idx] = True
                    st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
                    msg = f"📈 *SHORT K{idx+1} AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    save_state_to_db()

            # ARAYÜZÜ DOĞRUDAN ÇİZİYORUZ
            with main_container.container():
                col_left, col_right = st.columns([1.6, 1])
                
                with col_left:
                    st.subheader("📈 Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
                    tab_1m, tab_5m, tab_15m, tab_1h, tab_4h, tab_1d = st.tabs(["⏱️ 1m", "⏱️ 5m", "⏱️ 15m", "⏱️ 1h", "⏱️ 4h", "🌎 1d"])
                    
                    with tab_1m:
                        df_subset = df_1m.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1m", "NW_Ust_1m", f"{coin_title} - 1m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True)
                    with tab_5m:
                        df_subset = df_5m.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_5m", "NW_Ust_5m", f"{coin_title} - 5m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True)
                    with tab_15m:
                        df_subset = df_15m.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_15m", "NW_Ust_15m", f"{coin_title} - 15m Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True)
                    with tab_1h:
                        df_subset = df_1h.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1h", "NW_Ust_1h", f"{coin_title} - 1h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True)
                    with tab_4h:
                        df_subset = df_4h.tail(100)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_4h", "NW_Ust_4h", f"{coin_title} - 4h Grafik", st.session_state[f'{state_prefix}l_avg_price'], st.session_state[f'{state_prefix}s_avg_price']), use_container_width=True)
                    with tab_1d:
                        df_subset = df_1d.tail(30)
                        st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", "NW_Alt_1d", "NW_Ust_1d", f"{coin_title} - 1d Grafik"), use_container_width=True)

                st.markdown("---")
                st.subheader(f"🎯 3 Günlük {selected_symbol.split('/')[0]} Tahmini Likidasyon Yoğunluk Haritası")
                col_liq_l, col_liq_s = st.columns(2)
                with col_liq_l:
                    st.info("🔴 LONG LİKİDASYON HAVUZLARI")
                    if not df_long_liq.empty: st.table(df_long_liq.reset_index(drop=True))
                with col_liq_s:
                    st.error("🟢 SHORT LİKİDASYON HAVUZLARI")
                    if not df_short_liq.empty: st.table(df_short_liq.reset_index(drop=True))

            with col_right:
                st.subheader(f"📊 {coin_title} Canlı Terminal")
                col_live_p, col_live_c = st.columns(2)
                col_live_p.metric(label="Anlık Fiyat (USDT)", value=f"${current_price:,.2f}")
                col_live_c.metric(label="24 Saatlik Değişim", value=f"{price_change_24h:+.2f}%")

                if manual_lock:
                    st.warning("🔒 SEVİYELER DONDURULDU: Kademeler el ile kilitlendi.")
                else:
                    st.success("🔓 CANLI TAKİP AKTİF: Seviyeler anlık güncelleniyor.")

                st.write(f"Mevcut Durum: **{market_state_label}**")
                st.write(f"Aktif Motor  : **{active_engine_name}**")
                
                st.markdown("---")
                col_t1, col_t2 = st.columns([1, 1.2])
                col_t1.metric(label="4h Genel Trend", value=trend_4h)
                if trend_4h == "YUKARI (BOĞA)": st.success(f"🛡️ Emniyet: {warning_msg}")
                else: st.error(f"🛡️ Emniyet: {warning_msg}")
                
                st.markdown("---")
                st.write("⚡ **RSI & Momentum Süzgeci (Tüm Zaman Dilimleri)**")
                col_rsi_a, col_rsi_b, col_rsi_c = st.columns(3)
                with col_rsi_a:
                    st.write("**1m (Skalp)**"); st.code(f"{rsi_1m_val:.1f}")
                    st.write("**1h (Orta)**"); st.code(f"{rsi_1h_val:.1f}")
                with col_rsi_b:
                    st.write("**5m (Hızlı)**"); st.code(f"{rsi_5m_val:.1f}")
                    st.write("**4h (Makro)**"); st.code(f"{rsi_4h_val:.1f}")
                with col_rsi_c:
                    st.write("**15m (Normal)**"); st.code(f"{rsi_15m_val:.1f}")
                    st.write("**1d (Ana Trend)**"); st.code(f"{rsi_1d_val:.1f}")
                
                st.markdown("---")
                st.write("🎯 **Canlı Sinyal DCA Yönetim Kartı**")
                col_l, col_s = st.columns(2)
                
                with col_l:
                    st.info("📈 LONG KADEMELERİ")
                    k1_status = f"✅ Alındı ({st.session_state[f'{state_prefix}l_avg_price']:.2f})" if st.session_state[f"{state_prefix}l_status"][0] else f"⏳ Bekliyor ({nw_alt_5m:.2f})"
                    k2_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][1] else f"⏳ Bekliyor ({nw_alt_1h:.2f})"
                    k3_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][2] else f"⏳ Bekliyor ({nw_alt_4h:.2f})"
                    st.write(f"**{l1_lbl}:** {k1_status}"); st.write(f"**{l2_lbl}:** {k2_status}"); st.write(f"**{l3_lbl}:** {k3_status}")
                    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                        st.success(f"🟢 **KAR-AL (%1):** `{st.session_state[f'{state_prefix}l_avg_price'] * 1.01:.2f}`")

                with col_s:
                    st.error("📉 SHORT KADEMELERİ")
                    s_k1_status = f"✅ Açıldı ({st.session_state[f'{state_prefix}s_avg_price']:.2f})" if st.session_state[f"{state_prefix}s_status"][0] else f"⏳ Bekliyor ({nw_ust_5m:.2f})"
                    s_k2_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][1] else f"⏳ Bekliyor ({nw_ust_1h:.2f})"
                    s_k3_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][2] else f"⏳ Bekliyor ({nw_ust_4h:.2f})"
                    st.write(f"**{s1_lbl}:** {s_k1_status}"); st.write(f"**{s2_lbl}:** {s_k2_status}"); st.write(f"**{s3_lbl}:** {s_k3_status}")
                    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                        st.success(f"🟢 **KAR-AL (%1):** `{st.session_state[f'{state_prefix}s_avg_price'] * 0.99:.2f}`")

            # Günlük Piyasa Liderleri (Yığılmayı önlemek için main_container içerisine alındı)
            st.markdown("---")
            st.subheader("🌎 Günlük Piyasa Liderleri (Top 5 Yükselen & Düşen)")
            col_g, col_lo = st.columns(2)
            with col_g:
                st.success("📈 EN ÇOK YÜKSELENLER")
                if not df_gainers.empty: st.table(df_gainers.reset_index(drop=True))
            with col_lo:
                st.error("📉 EN ÇOK DÜŞENLER")
                if not df_losers.empty: st.table(df_losers.reset_index(drop=True))

            st.markdown("---")
            if st.session_state[f"{state_prefix}log_history"]:
                st.write("📜 **Son Sinyaller (Log)**")
                for log in reversed(st.session_state[f"{state_prefix}log_history"][-3:]): st.write(log)

            # SIFIRLAMA BUTONU
            st.markdown("---")
            if st.button("🔴 Tüm Kademeleri Manuel Sıfırla", key="reset_all_positions_button"):
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]
                st.session_state[f"{state_prefix}l_crypto"] = 0.0
                st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}l_avg_price"] = 0.0
                st.session_state[f"{state_prefix}s_crypto"] = 0.0
                st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}s_avg_price"] = 0.0
                st.session_state[f"{state_prefix}balance_usd"] = 100.0
                st.session_state[f"{state_prefix}locked_prices"] = None
                save_state_to_db()
                st.rerun()

        except Exception as e:
            st.sidebar.error(f"Hata oluştu, 5s sonra denenecek: {e}")
            time.sleep(5)  # Hata durumunda CPU yorulmasını önlemek için bekleme eklendi
            
        # ================= GERİ SAYIM SAYACI =================
        for remaining in range(10, 0, -1):
            countdown_placeholder.write(f"🔄 Sonraki taramaya: **{remaining}** saniye...")
            time.sleep(1)
        countdown_placeholder.write("🔄 Taranıyor...")
