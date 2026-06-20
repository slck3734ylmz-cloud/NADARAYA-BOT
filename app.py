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

# Telegram Bilgileriniz Entegre Durumdadır
telegram_token = "8736096328:AAH2_3BAIhbOxy9yo7v-L47h9KK3xCbALXE"
telegram_chat_id = "665969213"

# Durum Değişkenleri (Streamlit session_state ile saklanır)
if 'balance_usd' not in st.session_state:
    st.session_state.balance_usd = 100.0
    st.session_state.initial_balance = 100.0
    
    # LONG Pozisyon Durumları
    st.session_state.l_status = [False, False, False]
    st.session_state.l_crypto = 0.0
    st.session_state.l_usd_spent = 0.0
    st.session_state.l_avg_price = 0.0
    
    # SHORT Pozisyon Durumları
    st.session_state.s_status = [False, False, False]
    st.session_state.s_crypto = 0.0
    st.session_state.s_usd_spent = 0.0
    st.session_state.s_avg_price = 0.0
    
    st.session_state.log_history = []

layer_sizes = [0.0001, 0.0002, 0.0012]
target_profit_ratio = 0.01
stop_loss_ratio = 0.02

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except:
        pass

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

exchange = ccxt.kraken()

# Canlı Taramayı Başlat
while True:
    try:
        # 1. Trend Hesaplama (4H)
        raw_4h = exchange.fetch_ohlcv('BTC/USD', "4h", limit=210)
        df_4h = pd.DataFrame(raw_4h, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h["EMA_200"] = df_4h["Kapanis"].rolling(200).mean()
        
        latest_4h_close = df_4h.iloc[-1]["Kapanis"]
        latest_4h_ema = df_4h.iloc[-1]["EMA_200"]
        trend_4h = "YUKARI (BOĞA)" if latest_4h_close > latest_4h_ema else "AŞAĞI (AYI)"
        warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

        # 2. Canlı 15m/30m/2h Verilerini Al
        raw_candles = exchange.fetch_ohlcv('BTC/USD', "15m", limit=100)
        df = pd.DataFrame(raw_candles, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
        df = calculate_nw_bands(df, 2.0, "_15m")

        df_30m = df.resample("30min", on="Zaman").last().ffill().reset_index()
        df_30m = calculate_nw_bands(df_30m, 2.0, "_30m")
        df = pd.merge_asof(df.sort_values("Zaman"), df_30m[["Zaman", "NW_Ust_30m", "NW_Alt_30m"]].sort_values("Zaman"), on="Zaman", direction="backward")

        df_2h = df.resample("2h", on="Zaman").last().ffill().reset_index()
        df_2h = calculate_nw_bands(df_2h, 1.8, "_2h")
        df = pd.merge_asof(df.sort_values("Zaman"), df_2h[["Zaman", "NW_Ust_2h", "NW_Alt_2h"]].sort_values("Zaman"), on="Zaman", direction="backward")

        latest_row = df.iloc[-1]
        current_price = latest_row["Kapanis"]
        nw_alt_15m = latest_row["NW_Alt_15m"]
        nw_alt_30m = latest_row["NW_Alt_30m"]
        nw_alt_2h = latest_row["NW_Alt_2h"]
        nw_ust_15m = latest_row["NW_Ust_15m"]
        nw_ust_30m = latest_row["NW_Ust_30m"]
        nw_ust_2h = latest_row["NW_Ust_2h"]

        # =================== LONG POZİSYON ÇIKIŞLARI ===================
        if sum(st.session_state.l_status) > 0:
            l_stop = st.session_state.l_avg_price * (1 - stop_loss_ratio)
            l_tp = st.session_state.l_avg_price * (1 + target_profit_ratio)

            # Stop-Loss yalnızca 3. Kademe alındıysa aktifleşir
            if st.session_state.l_status[2] and current_price <= l_stop:
                st.session_state.balance_usd += st.session_state.l_crypto * current_price
                msg = f"🔴 *LONG ORTAK STOP-LOSS TETİKLENDİ*\nSatış: {current_price:.2f} USD"
                send_telegram_msg(msg)
                st.session_state.log_history.append(msg)
                st.session_state.l_crypto = 0.0
                st.session_state.l_usd_spent = 0.0
                st.session_state.l_avg_price = 0.0
                st.session_state.l_status = [False, False, False]

            elif current_price >= l_tp:
                st.session_state.balance_usd += st.session_state.l_crypto * current_price
                msg = f"🟢 *LONG ORTAK KAR-AL TETİKLENDİ*\nSatış: {current_price:.2f} USD"
                send_telegram_msg(msg)
                st.session_state.log_history.append(msg)
                st.session_state.l_crypto = 0.0
                st.session_state.l_usd_spent = 0.0
                st.session_state.l_avg_price = 0.0
                st.session_state.l_status = [False, False, False]

        # =================== SHORT POZİSYON ÇIKIŞLARI ===================
        if sum(st.session_state.s_status) > 0:
            s_stop = st.session_state.s_avg_price * (1 + stop_loss_ratio)
            s_tp = st.session_state.s_avg_price * (1 - target_profit_ratio)

            # Stop-Loss yalnızca 3. Kademe alındıysa aktifleşir
            if st.session_state.s_status[2] and current_price >= s_stop:
                pnl = (st.session_state.s_avg_price - current_price) / st.session_state.s_avg_price
                st.session_state.balance_usd += st.session_state.s_usd_spent * (1 + pnl)
                msg = f"🔴 *SHORT ORTAK STOP-LOSS TETİKLENDİ*\nKapanış: {current_price:.2f} USD"
                send_telegram_msg(msg)
                st.session_state.log_history.append(msg)
                st.session_state.s_crypto = 0.0
                st.session_state.s_usd_spent = 0.0
                st.session_state.s_avg_price = 0.0
                st.session_state.s_status = [False, False, False]

            elif current_price <= s_tp:
                pnl = (st.session_state.s_avg_price - current_price) / st.session_state.s_avg_price
                st.session_state.balance_usd += st.session_state.s_usd_spent * (1 + pnl)
                msg = f"🟢 *SHORT ORTAK KAR-AL TETİKLENDİ*\nKapanış: {current_price:.2f} USD"
                send_telegram_msg(msg)
                st.session_state.log_history.append(msg)
                st.session_state.s_crypto = 0.0
                st.session_state.s_usd_spent = 0.0
                st.session_state.s_avg_price = 0.0
                st.session_state.s_status = [False, False, False]

        # =================== GİRİŞ SİNYALLERİ ===================
        # LONG Girişler
        if current_price <= nw_alt_15m and not st.session_state.l_status[0]:
            buy_amt = layer_sizes[0]
            st.session_state.balance_usd -= buy_amt * current_price
            st.session_state.l_crypto += buy_amt
            st.session_state.l_usd_spent += buy_amt * current_price
            st.session_state.l_status[0] = True
            st.session_state.l_avg_price = st.session_state.l_usd_spent / st.session_state.l_crypto
            msg = f"📈 *LONG K1 SATIN ALINDI*\nFiyat: {current_price:.2f} USD"
            send_telegram_msg(msg)
            st.session_state.log_history.append(msg)

        if current_price <= nw_alt_30m and not st.session_state.l_status[1]:
            buy_amt = layer_sizes[1]
            st.session_state.balance_usd -= buy_amt * current_price
            st.session_state.l_crypto += buy_amt
            st.session_state.l_usd_spent += buy_amt * current_price
            st.session_state.l_status[1] = True
            st.session_state.l_avg_price = st.session_state.l_usd_spent / st.session_state.l_crypto
            msg = f"📈 *LONG K2 SATIN ALINDI*\nFiyat: {current_price:.2f} USD"
            send_telegram_msg(msg)
            st.session_state.log_history.append(msg)

        if current_price <= nw_alt_2h and not st.session_state.l_status[2]:
            buy_amt = layer_sizes[2]
            st.session_state.balance_usd -= buy_amt * current_price
            st.session_state.l_crypto += buy_amt
            st.session_state.l_usd_spent += buy_amt * current_price
            st.session_state.l_status[2] = True
            st.session_state.l_avg_price = st.session_state.l_usd_spent / st.session_state.l_crypto
            msg = f"📈 *LONG K3 SATIN ALINDI (SON KADEME)*\nFiyat: {current_price:.2f} USD"
            send_telegram_msg(msg)
            st.session_state.log_history.append(msg)

        # SHORT Girişler
        if current_price >= nw_ust_15m and not st.session_state.s_status[0]:
            sell_amt = layer_sizes[0]
            st.session_state.balance_usd -= sell_amt * current_price
            st.session_state.s_crypto += sell_amt
            st.session_state.s_usd_spent += sell_amt * current_price
            st.session_state.s_status[0] = True
            st.session_state.s_avg_price = st.session_state.s_usd_spent / st.session_state.s_crypto
            msg = f"📉 *SHORT K1 AÇILDI*\nFiyat: {current_price:.2f} USD"
            send_telegram_msg(msg)
            st.session_state.log_history.append(msg)

        if current_price >= nw_ust_30m and not st.session_state.s_status[1]:
            sell_amt = layer_sizes[1]
            st.session_state.balance_usd -= sell_amt * current_price
            st.session_state.s_crypto += sell_amt
            st.session_state.s_usd_spent += sell_amt * current_price
            st.session_state.s_status[1] = True
            st.session_state.s_avg_price = st.session_state.s_usd_spent / st.session_state.s_crypto
            msg = f"📉 *SHORT K2 AÇILDI*\nFiyat: {current_price:.2f} USD"
            send_telegram_msg(msg)
            st.session_state.log_history.append(msg)

        if current_price >= nw_ust_2h and not st.session_state.s_status[2]:
            sell_amt = layer_sizes[2]
            st.session_state.balance_usd -= sell_amt * current_price
            st.session_state.s_crypto += sell_amt
            st.session_state.s_usd_spent += sell_amt * current_price
            st.session_state.s_status[2] = True
            st.session_state.s_avg_price = st.session_state.s_usd_spent / st.session_state.s_crypto
            msg = f"📉 *SHORT K3 AÇILDI (SON KADEME)*\nFiyat: {current_price:.2f} USD"
            send_telegram_msg(msg)
            st.session_state.log_history.append(msg)

        # =================== EKRAN GÜNCELLEMELERİ (WEB UI) ===================
        with title_placeholder.container():
            st.title("📊 Nadaraya-Watson Çift Yönlü DCA Canlı Takip Paneli")
            st.write(f"Kraken Canlı Fiyatı: **{current_price:.2f} USD**")

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
                k1_status = f"✅ Alındı ({st.session_state.l_avg_price:.2f} USD)" if st.session_state.l_status[0] else f"⏳ Bekliyor ({nw_alt_15m:.2f})"
                k2_status = f"✅ Alındı" if st.session_state.l_status[1] else f"⏳ Bekliyor ({nw_alt_30m:.2f})"
                k3_status = f"✅ Alındı" if st.session_state.l_status[2] else f"⏳ Bekliyor ({nw_alt_2h:.2f})"
                
                st.write(f"**Kademe 1 (15m):** {k1_status}")
                st.write(f"**Kademe 2 (30m):** {k2_status}")
                st.write(f"**Kademe 3 (2h):** {k3_status}")
                
                if sum(st.session_state.l_status) > 0:
                    l_tp = st.session_state.l_avg_price * 1.01
                    l_sl = st.session_state.l_avg_price * 0.98 if st.session_state.l_status[2] else "PASİF (3. Kademeden Sonra)"
                    st.write(f"**Ortalama Giriş Fiyatı:** {st.session_state.l_avg_price:.2f} USD")
                    st.write(f"🟢 **Kar-Al Hedefi (%1):** {l_tp:.2f} USD")
                    st.write(f"🔴 **Stop-Loss (%2):** {f'{l_sl:.2f} USD' if isinstance(l_sl, float) else l_sl}")
                else:
                    st.write("*Aktif Long pozisyon bulunmuyor.*")

            # --- SHORT GRID KARTI ---
            with col_s:
                st.error("📉 SHORT (Ayı) KADEMELERİ")
                s_k1_status = f"✅ Açıldı ({st.session_state.s_avg_price:.2f} USD)" if st.session_state.s_status[0] else f"⏳ Bekliyor ({nw_ust_15m:.2f})"
                s_k2_status = f"✅ Açıldı" if st.session_state.s_status[1] else f"⏳ Bekliyor ({nw_ust_30m:.2f})"
                s_k3_status = f"✅ Açıldı" if st.session_state.s_status[2] else f"⏳ Bekliyor ({nw_ust_2h:.2f})"
                
                st.write(f"**Kademe 1 (15m):** {s_k1_status}")
                st.write(f"**Kademe 2 (30m):** {s_k2_status}")
                st.write(f"**Kademe 3 (2h):** {s_k3_status}")
                
                if sum(st.session_state.s_status) > 0:
                    s_tp = st.session_state.s_avg_price * 0.99
                    s_sl = st.session_state.s_avg_price * 1.02 if st.session_state.s_status[2] else "PASİF (3. Kademeden Sonra)"
                    st.write(f"**Ortalama Giriş Fiyatı:** {st.session_state.s_avg_price:.2f} USD")
                    st.write(f"🟢 **Kar-Al Hedefi (%1):** {s_tp:.2f} USD")
                    st.write(f"🔴 **Stop-Loss (%2):** {f'{s_sl:.2f} USD' if isinstance(s_sl, float) else s_sl}")
                else:
                    st.write("*Aktif Short pozisyon bulunmuyor.*")

        # Web Sayfası Grafiğini Güncelleme
        with chart_placeholder.container():
            df_subset = df.tail(50)
            
            fig, ax = plt.subplots(figsize=(15, 5))
            ax.plot(df_subset["Zaman"], df_subset["Kapanis"], label="Anlık Fiyat", color="royalblue", linewidth=2)
            ax.plot(df_subset["Zaman"], df_subset["NW_Alt_15m"], label="Long Al (Alt Band)", color="limegreen", linestyle="--")
            ax.plot(df_subset["Zaman"], df_subset["NW_Ust_15m"], label="Short Aç (Üst Band)", color="crimson", linestyle="--")
            
            if sum(st.session_state.l_status) > 0:
                ax.axhline(y=st.session_state.l_avg_price, color="green", linestyle="-", alpha=0.7)
            if sum(st.session_state.s_status) > 0:
                ax.axhline(y=st.session_state.s_avg_price, color="red", linestyle="-", alpha=0.7)
                
            ax.legend(loc="upper left")
            ax.grid(True, alpha=0.1)
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            st.pyplot(fig)
            plt.close(fig)

        # İşlem Loglarını Güncelleme
        with log_placeholder.container():
            if st.session_state.log_history:
                st.subheader("📜 Son Sinyaller (Log)")
                for log in reversed(st.session_state.log_history[-5:]):
                    st.write(log)

    except Exception as e:
        st.sidebar.error(f"Hata oluştu, 5s sonra denenecek: {e}")
        
    time.sleep(30)
