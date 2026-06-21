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

# ================= ENTEGRE EDİLMİŞ TELEGRAM AYARLARINIZ =================
telegram_token = "8736096328:AAH2_3BAIhbOxy9yo7v-L47h9KK3xCbALXE"
telegram_chat_id = "665969213"
# =========================================================================

# GATE.IO FUTURES BAĞLANTISI (Vadeli Modu Aktif)
exchange = ccxt.gate({
    'options': {
        'defaultType': 'swap',
    }
})

# ================= GATE.IO FUTURES EN YÜKSEK HACİMLİ 50 PERPETUAL TARAYICI =================
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
            return [
                {'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"},
                {'symbol': "ETH/USDT:USDT", 'display': "ETH/USDT ($3,500.00 | +0.00%)"}
            ]
            
        usd_tickers.sort(key=lambda x: x['volume'], reverse=True)
        top_50_data = []
        for item in usd_tickers[:50]:
            clean_sym = item['symbol'].split(":")[0]
            display_name = f"{clean_sym} (${item['price']:,.2f} | {item['change']:+.2f}%)"
            top_50_data.append({
                'symbol': item['symbol'],
                'display': display_name
            })
        return top_50_data
    except Exception as e:
        return [
            {'symbol': "BTC/USDT:USDT", 'display': "BTC/USDT ($64,222.00 | +0.00%)"},
            {'symbol': "ETH/USDT:USDT", 'display': "ETH/USDT ($3,500.00 | +0.00%)"}
        ]

# En yüksek hacimli 50 vadeli coini çekiyoruz
top_50_data = get_top_50_volume_coins()
display_options = [item['display'] for item in top_50_data]

# Streamlit Yan Panel (Sidebar) Tasarımı
st.sidebar.title("💳 Cüzdan Durumu")
st.sidebar.write("Başlangıç Bakiyesi: 100.00 USD")

# COİN SEÇİM KUTUSU
selected_display = st.sidebar.selectbox("🔥 Vadeli Coin Seçin (Hacim Sıralı 50)", display_options)
selected_symbol = [item['symbol'] for item in top_50_data if item['display'] == selected_display][0]

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
stop_loss_ratio = 0.01  # Kural: %1.0 Stop-Loss (Son alımın %1 aşağısı)

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except:
        pass

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

# Ekran Güncelleme Alanları (Placeholders)
title_placeholder = st.empty()
trend_placeholder = st.empty()
dca_cards_placeholder = st.empty()
chart_placeholder = st.empty()
log_placeholder = st.empty()

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

        # 2. Canlı 5m/1h/4h Verilerini Al (5m master veri limitini 1000 yapıyoruz ki 4h'lik 20 sapma hesaplanabilsin)
        raw_candles = exchange.fetch_ohlcv(selected_symbol, "5m", limit=1000)
        df = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
        
        # Kademe 1: 5m Grafik (Birebir 3.0 Std)
        df = calculate_nw_bands(df, 3.0, "_5m")

        # Kademe 2: 1h Grafik (Birebir 3.0 Std) (Resample '60min' ile)
        df_1h = df.resample("60min", on="Zaman").last().ffill().reset_index()
        df_1h = calculate_nw_bands(df_1h, 3.0, "_1h")
        df = pd.merge_asof(df.sort_values("Zaman"), df_1h[["Zaman", "NW_Ust_1h", "NW_Alt_1h"]].sort_values("Zaman"), on="Zaman", direction="backward")

        # Kademe 3: 4h Grafik (Birebir 3.0 Std) (Resample '240min' ile)
        df_4h_res = df.resample("240min", on="Zaman").last().ffill().reset_index()
        df_4h_res = calculate_nw_bands(df_4h_res, 3.0, "_4h")
        df = pd.merge_asof(df.sort_values("Zaman"), df_4h_res[["Zaman", "NW_Ust_4h", "NW_Alt_4h"]].sort_values("Zaman"), on="Zaman", direction="backward")

        latest_row = df.iloc[-1]
        current_price = latest_row["Kapanis"]
        nw_alt_5m = latest_row["NW_Alt_5m"]
        nw_alt_1h = latest_row["NW_Alt_1h"]
        nw_alt_4h = latest_row["NW_Alt_4h"]
        nw_ust_5m = latest_row["NW_Ust_5m"]
        nw_ust_1h = latest_row["NW_Ust_1h"]
        nw_ust_4h = latest_row["NW_Ust_4h"]

        # =================== LONG POZİSYON ÇIKIŞLARI ===================
        if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
            l_tp = st.session_state[f"{state_prefix}l_avg_price"] * (1 + target_profit_ratio)
            
            # Kural: Stop-loss sadece 3. kademe alındıysa aktifleşir ve son alım fiyatının (NW_Alt_4h) %1 aşağısıdır
            if st.session_state[f"{state_prefix}l_status"][2]:
                l_stop = nw_alt_4h * (1 - stop_loss_ratio)
                if current_price <= l_stop:
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                    msg = f"🔴 *LONG ORTAK STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f} (Son Alımın %1 Altı)"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}l_crypto"] = 0.0
                    st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
                    st.session_state[f"{state_prefix}l_avg_price"] = 0.0
                    st.session_state[f"{state_prefix}l_status"] = [False, False, False]
                    
            if current_price >= l_tp and sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}l_crypto"] * current_price
                msg = f"🟢 *LONG ORTAK KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nSatış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}l_crypto"] = 0.0
                st.session_state[f"{state_prefix}l_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}l_avg_price"] = 0.0
                st.session_state[f"{state_prefix}l_status"] = [False, False, False]

        # =================== SHORT POZİSYON ÇIKIŞLARI ===================
        if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
            s_tp = st.session_state[f"{state_prefix}s_avg_price"] * (1 - target_profit_ratio)

            # Kural: Stop-loss sadece 3. kademe alındıysa aktifleşir ve son alım fiyatının (NW_Ust_4h) %1 yukarısıdır
            if st.session_state[f"{state_prefix}s_status"][2]:
                s_stop = nw_ust_4h * (1 + stop_loss_ratio)
                if current_price >= s_stop:
                    pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                    st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                    msg = f"🔴 *SHORT ORTAK STOP-LOSS TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f} (Son Alımın %1 Üstü)"
                    send_telegram_msg(msg)
                    st.session_state[f"{state_prefix}log_history"].append(msg)
                    st.session_state[f"{state_prefix}s_crypto"] = 0.0
                    st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
                    st.session_state[f"{state_prefix}s_avg_price"] = 0.0
                    st.session_state[f"{state_prefix}s_status"] = [False, False, False]

            if current_price <= s_tp and sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                pnl = (st.session_state[f"{state_prefix}s_avg_price"] - current_price) / st.session_state[f"{state_prefix}s_avg_price"]
                st.session_state[f"{state_prefix}balance_usd"] += st.session_state[f"{state_prefix}s_usd_spent"] * (1 + pnl)
                msg = f"🟢 *SHORT ORTAK KAR-AL TETİKLENDİ ({selected_symbol.split(':')[0]})*\nKapanış: {current_price:.2f}"
                send_telegram_msg(msg)
                st.session_state[f"{state_prefix}log_history"].append(msg)
                st.session_state[f"{state_prefix}s_crypto"] = 0.0
                st.session_state[f"{state_prefix}s_usd_spent"] = 0.0
                st.session_state[f"{state_prefix}s_avg_price"] = 0.0
                st.session_state[f"{state_prefix}s_status"] = [False, False, False]

        # =================== LONG GİRİŞLERİ ===================
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

        # =================== SHORT GİRİŞLERİ ===================
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

        # =================== EKRAN GÜNCELLEMELERİ (WEB UI) ===================
        with title_placeholder.container():
            st.title(f"📊 {selected_symbol.split(':')[0]} Vadeli DCA Canlı Takip Paneli")
            st.write(f"Gate.io Futures Canlı Fiyatı: **{current_price:.2f} USDT**")

        with trend_placeholder.container():
            col_t1, col_t2 = st.columns(2)
            col_t1.metric(label="4 Saatlik Genel Trend Yönü", value=trend_4h)
            if trend_4h == "YUKARI (BOĞA)":
                col_t2.success(f"🛡️ Emniyet Uyarısı: {warning_msg}")
            else:
                col_t2.error(f"🛡️ Emniyet Uyarısı: {warning_msg}")

        # Dinamik Kademe ve Hedef Kartı (DCA Sinyal Kartı)
        with dca_cards_placeholder.container():
            st.subheader("🎯 Canlı Sinyal Takip ve DCA Yönetim Kartı")
            
            col_l, col_s = st.columns(2)
            
            # --- LONG GRID KARTI ---
            with col_l:
                st.info("📈 LONG (Boğa) KADEMELERİ")
                k1_status = f"✅ Alındı ({st.session_state[f'{state_prefix}l_avg_price']:.2f} USDT)" if st.session_state[f"{state_prefix}l_status"][0] else f"⏳ Bekliyor ({nw_alt_5m:.2f} | {layer_sizes[0]:.4f} {selected_symbol.split('/')[0]})"
                k2_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][1] else f"⏳ Bekliyor ({nw_alt_1h:.2f} | {layer_sizes[1]:.4f} {selected_symbol.split('/')[0]})"
                k3_status = f"✅ Alındı" if st.session_state[f"{state_prefix}l_status"][2] else f"⏳ Bekliyor ({nw_alt_4h:.2f} | {layer_sizes[2]:.4f} {selected_symbol.split('/')[0]})"
                
                st.write(f"**Kademe 1 (5m):** {k1_status}")
                st.write(f"**Kademe 2 (1h):** {k2_status}")
                st.write(f"**Kademe 3 (4h):** {k3_status}")
                
                if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                    l_tp = st.session_state[f"{state_prefix}l_avg_price"] * 1.01
                    l_sl = nw_alt_4h * 0.99 if st.session_state[f"{state_prefix}l_status"][2] else "PASİF (3. Kademeden Sonra)"
                    st.write(f"**Ortalama Giriş Fiyatı:** {st.session_state[f'{state_prefix}l_avg_price']:.2f} USDT")
                    st.write(f"🟢 **Kar-Al Hedefi (%1):** {l_tp:.2f} USDT")
                    st.write(f"🔴 **Stop-Loss (%2):** {f'{l_sl:.2f} USDT' if isinstance(l_sl, float) else l_sl}")
                else:
                    st.write("*Aktif Long pozisyon bulunmuyor.*")

            # --- SHORT GRID KARTI ---
            with col_s:
                st.error("📉 SHORT (Ayı) KADEMELERİ")
                s_k1_status = f"✅ Açıldı ({st.session_state[f'{state_prefix}s_avg_price']:.2f} USDT)" if st.session_state[f"{state_prefix}s_status"][0] else f"⏳ Bekliyor ({nw_ust_5m:.2f} | {layer_sizes[0]:.4f} {selected_symbol.split('/')[0]})"
                s_k2_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][1] else f"⏳ Bekliyor ({nw_ust_1h:.2f} | {layer_sizes[1]:.4f} {selected_symbol.split('/')[0]})"
                s_k3_status = f"✅ Açıldı" if st.session_state[f"{state_prefix}s_status"][2] else f"⏳ Bekliyor ({nw_ust_4h:.2f} | {layer_sizes[2]:.4f} {selected_symbol.split('/')[0]})"
                
                st.write(f"**Kademe 1 (5m):** {s_k1_status}")
                st.write(f"**Kademe 2 (1h):** {s_k2_status}")
                st.write(f"**Kademe 3 (4h):** {s_k3_status}")
                
                if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                    s_tp = st.session_state[f"{state_prefix}s_avg_price"] * 0.99
                    s_sl = nw_ust_4h * 1.02 if st.session_state[f"{state_prefix}s_status"][2] else "PASİF (3. Kademeden Sonra)"
                    st.write(f"**Ortalama Giriş Fiyatı:** {st.session_state[f'{state_prefix}s_avg_price']:.2f} USDT")
                    st.write(f"🟢 **Kar-Al Hedefi (%1):** {s_tp:.2f} USDT")
                    st.write(f"🔴 **Stop-Loss (%2):** {f'{s_sl:.2f} USDT' if isinstance(s_sl, float) else s_sl}")
                else:
                    st.write("*Aktif Short pozisyon bulunmuyor.*")

        # Web Sayfası Grafiğini Güncelleme
        with chart_placeholder.container():
            df_subset = df.tail(50)
            
            fig, ax = plt.subplots(figsize=(15, 5))
            ax.plot(df_subset["Zaman"], df_subset["Kapanis"], label="Anlık Fiyat", color="royalblue", linewidth=2)
            ax.plot(df_subset["Zaman"], df_subset["NW_Alt_5m"], label="Long Al (Alt Band)", color="limegreen", linestyle="--")
            ax.plot(df_subset["Zaman"], df_subset["NW_Ust_5m"], label="Short Aç (Üst Band)", color="crimson", linestyle="--")
            
            if sum(st.session_state[f"{state_prefix}l_status"]) > 0:
                ax.axhline(y=st.session_state[f"{state_prefix}l_avg_price"], color="green", linestyle="-", alpha=0.7)
            if sum(st.session_state[f"{state_prefix}s_status"]) > 0:
                ax.axhline(y=st.session_state[f"{state_prefix}s_avg_price"], color="red", linestyle="-", alpha=0.7)
                
            ax.legend(loc="upper left")
            ax.grid(True, alpha=0.1)
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            st.pyplot(fig)
            plt.close(fig)

        # İşlem Loglarını Güncelleme
        with log_placeholder.container():
            if st.session_state[f"{state_prefix}log_history"]:
                st.subheader("📜 Son Sinyaller (Log)")
                for log in reversed(st.session_state[f"{state_prefix}log_history"][-5:]):
                    st.write(log)

    except Exception as e:
        st.sidebar.error(f"Hata oluştu, 5s sonra denenecek: {e}")
        
    time.sleep(10) # 10 Saniyelik Ultra Hızlı Kontrol Döngüsü
