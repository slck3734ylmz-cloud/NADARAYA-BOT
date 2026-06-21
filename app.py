import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Streamlit sayfa yapılandırması
st.set_page_config(page_title="DCA Live Hedging Dashboard", layout="wide")
plt.style.use('dark_background')

# ================= ENTEGRE EDİLMİŞ TELEGRAM AYARLARINIZ =================
telegram_token = "8736096328:AAH2_3BAIhbOxy9yo7v-L47h9KK3xCbALXE"
telegram_chat_id = "@kyounkripto"
# =========================================================================

# GATE.IO FUTURES BAĞLANTISI (Vadeli Modu Aktif)
exchange = ccxt.gate({'options': {'defaultType': 'swap'}})

# ================= GÖMÜLÜ CANLI FİYAT VE YÜZDELİKLİ TARAYICI =================
@st.cache_data(ttl=300)
def get_top_50_volume_coins():
    try:
        tickers = exchange.fetch_tickers()
        usd_tickers = []
        for symbol, ticker in tickers.items():
            if symbol.endswith(':USDT'):
                quote_vol = ticker.get('quoteVolume')
                if quote_vol is None:
                    base_vol = ticker.get('baseVolume') or 0.0
                    last_price = ticker.get('last') or ticker.get('close') or 0.0
                    quote_vol = base_vol * last_price
                
                if quote_vol is not None and quote_vol > 0:
                    usd_tickers.append({
                        'symbol': symbol, 
                        'volume': quote_vol, 
                        'price': ticker.get('last') or ticker.get('close') or 0.0, 
                        'change': ticker.get('percentage') or 0.0
                    })
        if len(usd_tickers) == 0:
            return [{'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"}]
            
        usd_tickers.sort(key=lambda x: x['volume'], reverse=True)
        top_50_data = []
        for item in usd_tickers[:50]:
            clean_sym = item['symbol'].split(":")[0]
            display_name = f"{clean_sym} (${item['price']:,.2f} | {item['change']:+.2f}%)"
            top_50_data.append({'symbol': item['symbol'], 'display': display_name})
        return top_50_data
    except Exception as e:
        return [{'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"}]

# ================= EN EKSTREM FONLAMA ORANLARI TARAYICISI =================
@st.cache_data(ttl=300)
def get_extreme_funding_rates():
    try:
        tickers = exchange.fetch_tickers()
        funding_rates = []
        for symbol, ticker in tickers.items():
            if symbol.endswith(':USDT'):
                raw_info = ticker.get('info', {})
                funding_val = raw_info.get('funding_rate')
                if funding_val is not None:
                    funding_rates.append({'symbol': symbol.split(':')[0], 'rate': float(funding_val) * 100.0})
        if len(funding_rates) == 0:
            return []
        funding_rates.sort(key=lambda x: abs(x['rate']), reverse=True)
        return funding_rates[:5]
    except:
        return []

# Canlı Fiyatlı ve Yüzdelikli 50 coini çekiyoruz
top_50_data = get_top_50_volume_coins()
display_options = [item['display'] for item in top_50_data]

# Streamlit Yan Panel (Sidebar) Tasarımı
st.sidebar.title("💳 Cüzdan Durumu")
st.sidebar.write("Başlangıç Bakiyesi: 100.00 USD")

# COİN SEÇİM KUTUSU
selected_display = st.sidebar.selectbox("🔥 Vadeli Coin Seçin (Hacim Sıralı 50)", display_options)
selected_symbol = [item['symbol'] for item in top_50_data if item['display'] == selected_display][0]

# ================= SOL PANEL (SIDEBAR) FONLAMA ORANLARI YAZDIRMA =================
st.sidebar.markdown("---")
st.sidebar.subheader("💸 En Ekstrem Fonlama Oranları (Top 5)")
extreme_rates = get_extreme_funding_rates()
if extreme_rates:
    for item in extreme_rates:
        rate_str = f"{item['rate']:+.4f}%"
        if item['rate'] < 0:
            st.sidebar.markdown(f"**{item['symbol']}**: :green[{rate_str}]")
        else:
            st.sidebar.markdown(f"**{item['symbol']}**: :red[{rate_str}]")
else:
    st.sidebar.write("Fonlama oranları yükleniyor...")
st.sidebar.markdown("---")

# GERİ SAYIM SAYACI ALANI
st.sidebar.write("🔄 Sonraki Tarama İlerlemesi:")
countdown_placeholder = st.sidebar.progress(0)

# Seçilen coinin durum değişkenleri (Her coin için bağımsız session_state saklanır)
state_prefix = f"{selected_symbol}_"
if f"{state_prefix}balance_usd" not in st.session_state:
    st.session_state[f"{state_prefix}balance_usd"] = 100.0
    st.session_state[f"{state_prefix}initial_balance"] = 100.0
    st.session_state[f"{state_prefix}l_status"] = [False, False, False]
    st.session_state[f"{state_prefix}l_crypto"] = 0.0
    st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
    st.session_state[f"{state_prefix}l_avg_price"] = 0.0
    st.session_state[f"{state_prefix}s_status"] = [False, False, False]
    st.session_state[f"{state_prefix}s_crypto"] = 0.0
    st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
    st.session_state[f"{state_prefix}s_avg_price"] = 0.0
    st.session_state[f"{state_prefix}log_history"] = []

# Seçilen coinin fiyatına göre kademe adetlerini dinamik ölçeklendiriyoruz
try:
    ticker_info = exchange.fetch_ticker(selected_symbol)
    coin_price = ticker_info.get('last') or ticker_info.get('close') or 63000.0
    scale_factor = 63000.0 / coin_price
    layer_sizes = [0.0001 * scale_factor, 0.0002 * scale_factor, 0.0012 * scale_factor]
except:
    layer_sizes = [0.0001, 0.0002, 0.0012]

target_profit_ratio = 0.01
stop_loss_ratio = 0.02

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload)
    except: pass

# TELEGRAM BAĞLANTI TESTİ BUTONU
if st.sidebar.button("🔔 Telegram Bağlantısını Test Et"):
    send_telegram_msg(f"👋 *Bağlantı Testi:* Web siteniz üzerinden gönderilen test mesajı başarılı!")
    st.sidebar.success("Test mesajı gönderildi!")

def nadaraya_watson_estimator(src, h=8):
    n = len(src)
    estimates = np.zeros(n)
    for i in range(n):
        weights = np.exp(-((np.arange(n) - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src * weights) / np.sum(weights)
    return estimates

def calculate_nw_bands(df, std_multiplier, col_suffix):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=8)
    df["Fark"] = df["Kapanis"] - df["NW_Merkez"]
    df["Sapma_Std"] = df["Fark"].rolling(window=20).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

# ================= DİNAMİK GRAPH ÇİZİM FONKSİYONU (DRY PRENSİBİ - 100 SATIR KISALTILDI) =================
def draw_one_chart(df_sub, alt_col, ust_col, label):
    fig, ax = plt.subplots(figsize=(15, 4.5), facecolor='#0e1117')
    ax.set_facecolor('#0e1117')
    ax.plot(df_sub["Zaman"], df_sub["Kapanis"], label=f"Anlık Fiyat", color="royalblue", linewidth=2.5)
    ax.plot(df_sub["Zaman"], df_sub[alt_col], label=f"Alt Band ({label})", color="limegreen", linestyle="--")
    ax.plot(df_sub["Zaman"], df_sub[ust_col], label=f"Üst Band ({label})", color="crimson", linestyle="--")
    
    # Pozisyon çizgileri
    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
        ax.axhline(y=st.session_state[f"{state_prefix}l_avg_price"], color="green", linestyle="-", alpha=0.6, label="Long Ort.")
    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
        ax.axhline(y=st.session_state[f"{state_prefix}s_avg_price"], color="red", linestyle="-", alpha=0.6, label="Short Ort.")
        
    ax.legend(loc="upper left")
    ax.grid(True, color='white', alpha=0.03)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if label != "1d" else "%d/%m"))
    st.pyplot(fig)
    plt.close(fig)
# =====================================================================================================

main_container = st.empty()

# Canlı Taramayı Başlat
while True:
    try:
        # 1. Seçilen Vadeli Coin İçin Trend Hesaplama (4H)
        raw_4h = exchange.fetch_ohlcv(selected_symbol, "4h", limit=210)
        df_4h = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h["EMA_200"] = df_4h["Kapanis"].ewm(span=200, adjust=False).mean()
        
        latest_4h_close = df_4h.iloc[-1]["Kapanis"]
        latest_4h_ema = df_4h.iloc[-1]["EMA_200"]
        trend_4h = "YUKARI (BOĞA)" if latest_4h_close > latest_4h_ema else "AŞAĞI (AYI)"
        warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

        # 2. Canlı 5m/1h/4h Verilerini Al (Limit 1000)
        raw_candles = exchange.fetch_ohlcv(selected_symbol, "5m", limit=1000)
        df = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
        
        df = calculate_nw_bands(df, 3.0, "_5m")
        delta = df["Kapanis"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df["RSI_14"] = 100 - (100 / (1 + rs))

        df_1h = df.resample("60min", on="Zaman").last().ffill().reset_index()
        df_1h = calculate_nw_bands(df_1h, 3.0, "_1h")
        diff_1h = df_1h["Kapanis"].diff()
        up_1h = diff_1h.clip(lower=0)
        down_1h = -diff_1h.clip(upper=0)
        ma_up_1h = up_1h.rolling(14).mean()
        ma_down_1h = down_1h.rolling(14).mean()
        rs_1h = ma_up_1h / ma_down_1h
        df_1h["RSI_14"] = 100 - (100 / (1 + rs_1h))
        df = pd.merge_asof(df.sort_values("Zaman"), df_1h[["Zaman", "NW_Ust_1h", "NW_Alt_1h", "RSI_14"]].sort_values("Zaman"), on="Zaman", direction="backward", suffixes=('', '_1h'))

        df_4h_res = df.resample("240min", on="Zaman").last().ffill().reset_index()
        df_4h_res = calculate_nw_bands(df_4h_res, 3.0, "_4h")
        df = pd.merge_asof(df.sort_values("Zaman"), df_4h_res[["Zaman", "NW_Ust_4h", "NW_Alt_4h"]].sort_values("Zaman"), on="Zaman", direction="backward")

        raw_candles_1d = exchange.fetch_ohlcv(selected_symbol, "1d", limit=100)
        df_1d = pd.DataFrame(raw_candles_1d, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_1d["Zaman"] = pd.to_datetime(df_1d["Zaman"], unit="ms")
        df_1d = calculate_nw_bands(df_1d, 3.0, "_1d")

        latest_row = df.iloc[-1]
        current_price = latest_row["Kapanis"]
        nw_alt_5m = latest_row["NW_Alt_5m"]
        nw_alt_1h = latest_row["NW_Alt_1h"]
        nw_alt_4h = latest_row["NW_Alt_4h"]
        nw_ust_5m = latest_row["NW_Ust_5m"]
        nw_ust_1h = latest_row["NW_Ust_1h"]
        nw_ust_4h = latest_row["NW_Ust_4h"]
        
        rsi_5m = latest_row["RSI_14"]
        rsi_1h = latest_row["RSI_14_1h"] if "RSI_14_1h" in latest_row else 50.0
        bull_div_5m, bear_div_5m = detect_rsi_divergence(df["Kapanis"].values, df["RSI_14"].values)

        # =================== LONG ÇIKIŞLARI ===================
        if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
            l_tp = st.session_state[f"{state_prefix}l_avg_price"] * (1 + target_profit_ratio)
            if st.session_state[f"{state_prefix}l_status"][2]:
                l_stop = nw_alt_4h * (1 - stop_loss_ratio)
                if current_price <= l_stop:
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                    msg = f"🔴 *LONG STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"], st.session_state[f"{state_prefix}l_status"] = 0.0, 0.0, 0.0, [False, False, False]
                    
            if current_price >= l_tp and sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                msg = f"🟢 *LONG KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"], st.session_state[f"{state_prefix}l_usd_spent"], st.session_state[f"{state_prefix}l_avg_price"], st.session_state[f"{state_prefix}l_status"] = 0.0, 0.0, 0.0, [False, False, False]

        # =================== SHORT ÇIKIŞLARI ===================
        if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
            s_tp = st.session_state[f"{state_prefix}s_avg_price"] * (1 - target_profit_ratio)
            if st.session_state[f"{state_prefix}s_status"][2]:
                s_stop = nw_ust_4h * (1 + stop_loss_ratio)
                if current_price >= s_stop:
                    pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                    msg = f"🔴 *SHORT STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"], st.session_state[f"{state_prefix}s_status"] = 0.0, 0.0, 0.0, [False, False, False]

            if current_price <= s_tp and sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                msg = f"🟢 *SHORT KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"], st.session_state[f"{state_prefix}s_usd_spent"], st.session_state[f"{state_prefix}s_avg_price"], st.session_state[f"{state_prefix}s_status"] = 0.0, 0.0, 0.0, [False, False, False]

        # =================== GİRİŞLER ===================
        if current_price <= nw_alt_5m and not st.session_state[f"{state_prefix}l_status"][0]:
            buy_amt = layer_sizes[0]
            st.session_state[f"{state_prefix}balance_usd"] -= buy_amt * current_price
            st.session_state[f"{state_prefix}l_crypto"] += buy_amt
            st.session_state[f"{state_prefix}l_usd_spent"] += buy_amt * current_price
            st.session_state[f"{state_prefix}l_status"][0] = True
            st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
            msg = f"📈 *LONG K1 SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)

        if current_price <= nw_alt_1h and not st.session_state[f"{state_prefix}l_status"][1]:
            buy_amt = layer_sizes[1]
            st.session_state[f"{state_prefix}balance_usd"] -= buy_amt * current_price
            st.session_state[f"{state_prefix}l_crypto"] += buy_amt
            st.session_state[f"{state_prefix}l_usd_spent"] += buy_amt * current_price
            st.session_state[f"{state_prefix}l_status"][1] = True
            st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
            msg = f"📈 *LONG K2 SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)

        if current_price <= nw_alt_4h and not st.session_state[f"{state_prefix}l_status"][2]:
            buy_amt = layer_sizes[2]
            st.session_state[f"{state_prefix}balance_usd"] -= buy_amt * current_price
            st.session_state[f"{state_prefix}l_crypto"] += buy_amt
            st.session_state[f"{state_prefix}l_usd_spent"] += buy_amt * current_price
            st.session_state[f"{state_prefix}l_status"][2] = True
            st.session_state[f"{state_prefix}l_avg_price"] = st.session_state[f"{state_prefix}l_usd_spent"] / st.session_state[f"{state_prefix}l_crypto"]
            msg = f"📈 *LONG K3 SATIN ALINDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)

        # SHORT Girişler
        if current_price >= nw_ust_5m and not st.session_state[f"{state_prefix}s_status"][0]:
            sell_amt = layer_sizes[0]
            st.session_state[f"{state_prefix}balance_usd"] -= sell_amt * current_price
            st.session_state[f"{state_prefix}s_crypto"] += sell_amt
            st.session_state[f"{state_prefix}s_usd_spent"] += sell_amt * current_price
            st.session_state[f"{state_prefix}s_status"][0] = True
            st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
            msg = f"📉 *SHORT K1 AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)

        if current_price >= nw_ust_1h and not st.session_state[f"{state_prefix}s_status"][1]:
            sell_amt = layer_sizes[1]
            st.session_state[f"{state_prefix}balance_usd"] -= sell_amt * current_price
            st.session_state[f"{state_prefix}s_crypto"] += sell_amt
            st.session_state[f"{state_prefix}s_usd_spent"] += sell_amt * current_price
            st.session_state[f"{state_prefix}s_status"][1] = True
            st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
            msg = f"📉 *SHORT K2 AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)

        if current_price >= nw_ust_4h and not st.session_state[f"{state_prefix}s_status"][2]:
            sell_amt = layer_sizes[2]
            st.session_state[f"{state_prefix}balance_usd"] -= sell_amt * current_price
            st.session_state[f"{state_prefix}s_crypto"] += sell_amt
            st.session_state[f"{state_prefix}s_usd_spent"] += sell_amt * current_price
            st.session_state[f"{state_prefix}s_status"][2] = True
            st.session_state[f"{state_prefix}s_avg_price"] = st.session_state[f"{state_prefix}s_usd_spent"] / st.session_state[f"{state_prefix}s_crypto"]
            msg = f"📉 *SHORT K3 AÇILDI ({selected_symbol.split(':')[0]})*\nFiyat: {current_price:.2f}"
            send_telegram_msg(msg)
            st.session_state[f"{state_prefix}log_history"].append(msg)

        # =================== EKRAN GÜNCELLEMELERİ (WEB UI - PRO GRID TASARIM) ===================
        with main_container.container():
            col_left, col_right = st.columns([1.6, 1])
            
            # --- SOL SÜTUN (3 SEKME Lİ GRAFİKLER) ---
            with col_left:
                st.subheader("📈 Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
                tab_5m, tab_1h, tab_4h, tab_1d = st.tabs(["⏱️ 5 Dakikalık Grafik", "⏱️ 1 Saatlik Grafik", "⏱️ 4 Saatlik Grafik", "🌎 1 Günlük Grafik"])
                
                with tab_5m: draw_one_chart(df.tail(100), "NW_Alt_5m", "NW_Ust_5m", "5m")
                with tab_1h: draw_one_chart(df.tail(100), "NW_Alt_1h", "NW_Ust_1h", "1h")
                with tab_4h: draw_one_chart(df.tail(100), "NW_Alt_4h", "NW_Ust_4h", "4h")
                with tab_1d: draw_one_chart(df_1d.tail(30), "NW_Alt_1d", "NW_Ust_1d", "1d")

            # --- SAĞ SÜTUN (KONTROL MASASI VE GÖSTERGELER) ---
            with col_right:
                st.subheader(f"📊 {selected_symbol.split(':')[0]} Canlı Terminal")
                st.write(f"Anlık Vadeli Fiyat: **{current_price:.2f} USDT**")
                
                # Trend Kartı
                st.markdown("---")
                col_t1, col_t2 = st.columns([1, 1.2])
                col_t1.metric(label="4h Genel Trend", value=trend_4h)
                if trend_4h == "YUKARI (BOĞA)": col_t2.success(f"🛡️ Emniyet: {warning_msg}")
                else: col_t2.error(f"🛡️ Emniyet: {warning_msg}")
                
                # RSI & Iraksama Kartı
                st.markdown("---")
                st.write("⚡ **RSI & Momentum Süzgeci**")
                rsi_5m_state = f"{rsi_5m:.1f} (AŞIRI SATIM 🟢)" if rsi_5m < 30 else (f"{rsi_5m:.1f} (AŞIRI ALIM 🔴)" if rsi_5m > 70 else f"{rsi_5m:.1f} (NÖTR ⚪)")
                div_5m_state = "📈 BOĞA IRAKSAMASI!" if bull_div_5m else ("📉 AYI IRAKSAMASI!" if bear_div_5m else "Yok")
                st.metric(label="5m Anlık RSI Gücü", value=rsi_5m_state, delta=div_5m_state, delta_color="normal" if "VAR" in div_5m_state else "off")
                st.write(f"**1h RSI Değeri:** {rsi_1h:.1f} (NÖTR ⚪)")
                
                # DCA Sinyal Takip ve Yönetim Kartı
                st.markdown("---")
                st.write("🎯 **Canlı Sinyal Takip ve DCA Yönetim Kartı**")
                col_l, col_s = st.columns(2)
                
                with col_l:
                    st.info("📈 LONG KADEMELERİ")
                    k1_status = f"✅ Alındı ({st.session_state[f'{state_prefix}l_avg_price']:.2f} USDT)" if st.session_state[f"{state_prefix}l_status"][0] else f"⏳ Bekliyor ({nw_alt_5m:.2f} | {layer_sizes[0]:.4f} BTC)"
                    k2_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][1] else f"⏳ Bekliyor ({nw_alt_1h:.2f} | {layer_sizes[1]:.4f} BTC)"
                    k3_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][2] else f"⏳ Bekliyor ({nw_alt_4h:.2f} | {layer_sizes[2]:.4f} {selected_symbol.split('/')[0]})"
                    st.write(f"**K1 (5m):** {k1_status}")
                    st.write(f"**K2 (1h):** {k2_status}")
                    st.write(f"**K3 (4h):** {k3_status}")
                    if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                        l_tp = st.session_state[f"{state_prefix}l_avg_price"] * 1.01
                        l_sl = nw_alt_4h * 0.99 if st.session_state[f"{state_prefix}l_status"][2] else "PASİF (3. Kademeden Sonra)"
                        st.write(f"**Ort. Giriş:** {st.session_state[f'{state_prefix}l_avg_price']:.2f}")
                        st.write(f"🟢 **Kar-Al (%1):** {l_tp:.2f}")
                        st.write(f"🔴 **Stop (%2):** {f'{l_sl:.2f}' if isinstance(l_sl, float) else l_sl}")

                with col_s:
                    st.error("📉 SHORT KADEMELERİ")
                    s_k1_status = f"✅ Açıldı ({st.session_state[f'{state_prefix}s_avg_price']:.2f} USDT)" if st.session_state[f"{state_prefix}s_status"][0] else f"⏳ Bekliyor ({nw_ust_5m:.2f} | {layer_sizes[0]:.4f} BTC)"
                    s_k2_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][1] else f"⏳ Bekliyor ({nw_ust_1h:.2f} | {layer_sizes[1]:.4f} BTC)"
                    s_k3_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][2] else f"⏳ Bekliyor ({nw_ust_4h:.2f} | {layer_sizes[2]:.4f} {selected_symbol.split('/')[0]})"
                    st.write(f"**K1 (5m):** {s_k1_status}")
                    st.write(f"**K2 (1h):** {s_k2_status}")
                    st.write(f"**K3 (4h):** {s_k3_status}")
                    if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                        s_tp = st.session_state[f"{state_prefix}s_avg_price"] * 0.99
                        s_sl = nw_ust_4h * 1.02 if st.session_state[f"{state_prefix}s_status"][2] else "PASİF (3. Kademeden Sonra)"
                        st.write(f"**Ort. Giriş:** {st.session_state[f'{state_prefix}s_avg_price']:.2f}")
                        st.write(f"🟢 **Kar-Al (%1):** {s_tp:.2f}")
                        st.write(f"🔴 **Stop (%2):** {f'{s_sl:.2f}' if isinstance(s_sl, float) else s_sl}")
                
                # Son Sinyaller
                st.markdown("---")
                if st.session_state[f"{state_prefix}log_history"]:
                    st.write("📜 **Son Sinyaller (Log)**")
                    for log in reversed(st.session_state[f"{state_prefix}log_history"][-3:]):
                        st.write(log)

    except Exception as e:
        st.sidebar.error(f"Hata oluştu, 5s sonra denenecek: {e}")
        
    # ================= ANLIK GERİ SAYIM SAYACI (ULTRA HIZLI SIDEBAR) =================
    for remaining in range(10, 0, -1):
        countdown_placeholder.write(f"🔄 Sonraki taramaya: **{remaining}** saniye...")
        time.sleep(1)
    countdown_placeholder.write("🔄 Taranıyor...")
