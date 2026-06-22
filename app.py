import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import datetime
import requests
from supabase import create_client, Client

# ================= TEMEL AYARLAR =================
BOT_LEVERAGE = 200  # MEXC BTC/USDT futures için kullanılacak kaldıraç (cross margin)
MEXC_TAKER_FEE_PCT = 0.0002  # %0.02 - market emirleri her zaman taker sayılır
MIN_PROFIT_SAFETY_MULT = 3.0  # Kar-al mesafesi, round-trip komisyonun en az bu katı olmalı
RSI_MIDPOINT = 50  # NW bandı dokunduğunda RSI'nin hangi tarafta olması gerektiği eşiği

TF_PARAMS = {
    "1m":  {"limit": 90,  "h": 6, "rsi_period": 7,  "std_window": 15},
    "5m":  {"limit": 100, "h": 7, "rsi_period": 9,  "std_window": 18},
    "15m": {"limit": 110, "h": 8, "rsi_period": 9,  "std_window": 20},
    "1h":  {"limit": 120, "h": 8, "rsi_period": 14, "std_window": 20},
    "4h":  {"limit": 90,  "h": 7, "rsi_period": 14, "std_window": 18},
    "1d":  {"limit": 60,  "h": 6, "rsi_period": 14, "std_window": 14},
}

# DCA: volatiliteye göre dinamik zaman dilimi + büyük miktarlar (uzun vadeli ortalama düşürme)
DCA_AMOUNTS = [0.0001, 0.0004, 0.0015]   # 1:4:15 oranı, toplam 0.0020 BTC
# Scalp: her zaman sabit kısa zaman dilimi + aynı miktarlar, ayrı/bağımsız pozisyon
SCALP_AMOUNTS = [0.0001, 0.0004, 0.0015]  # toplam 0.0020 BTC
SCALP_TIMEFRAMES = ["1m", "5m", "15m"]    # Scalp her zaman bu üçünü kullanır, mod fark etmez

ATR_TP_MULT, ATR_SL_MULT = 1.0, 1.5

# MEXC Futures (Vadeli) bağlantısı. API key/secret st.secrets üzerinden okunur.
MEXC_API_KEY = st.secrets.get("MEXC_API_KEY", "")
MEXC_API_SECRET = st.secrets.get("MEXC_API_SECRET", "")
VIEWER_PASSWORD = "dca2026"
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

# Telegram ve Supabase kimlik bilgileri st.secrets üzerinden okunur.
telegram_token = st.secrets.get("TELEGRAM_TOKEN", "")
telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
supabase_url = st.secrets.get("SUPABASE_URL", "")
supabase_key = st.secrets.get("SUPABASE_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

# ================= GİRİŞ EKRANI =================
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True

    st.markdown(
        """
        <style>
        @keyframes sheepBounce {
            0%, 100% { transform: translateY(0) rotate(-4deg); }
            50% { transform: translateY(-6px) rotate(4deg); }
        }
        .sheep-emoji { display: inline-block; animation: sheepBounce 2.2s ease-in-out infinite; }
        div[data-testid="stForm"] {
            max-width: 380px;
            margin: 0 auto;
        }
        div[data-testid="stForm"] div[data-testid="InputInstructions"] {
            display: none !important;
        }
        div[data-testid="stForm"] input[type="password"] {
            padding-right: 2.6rem !important;
        }
        </style>
        <div style="display:flex; align-items:center; justify-content:center; padding:2.5rem 0 1rem; font-family: -apple-system, sans-serif;">
          <div style="width:380px; text-align:center;">
            <div style="position:relative; width:112px; height:112px; margin:0 auto 8px;">
              <svg width="112" height="112" viewBox="0 0 112 112" style="position:absolute; top:0; left:0;">
                <defs>
                  <radialGradient id="badgeGlow" cx="50%" cy="38%" r="65%">
                    <stop offset="0%" stop-color="#30386B"/>
                    <stop offset="100%" stop-color="#161B33"/>
                  </radialGradient>
                </defs>
                <circle cx="56" cy="56" r="54" fill="url(#badgeGlow)" stroke="#9A8BF0" stroke-width="1"/>
                <circle cx="56" cy="56" r="45" fill="none" stroke="#4A4F7A" stroke-width="0.6"/>
              </svg>
              <div class="sheep-emoji" style="position:absolute; top:0; left:0; width:112px; height:112px; display:flex; align-items:center; justify-content:center; font-size:46px;">🐑</div>
            </div>
            <div style="color:#9A8BF0; font-size:10px; letter-spacing:2px; margin-bottom:14px;">幸運の羊</div>
            <div style="color:#E8E9F5; font-size:28px; font-weight:600; letter-spacing:3px; margin-bottom:6px;">KYOUN</div>
            <div style="color:#6E72A0; font-size:11px; letter-spacing:2px; text-transform:uppercase; margin-bottom:8px;">şanslı koyun terminali</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    _, col_login, _ = st.columns([1, 1.4, 1])
    with col_login:
        with st.form(key="login_form"):
            user_password = st.text_input("Şifre", type="password", key="login_pass_key_global", label_visibility="collapsed", placeholder="Şifrenizi girin")
            submitted = st.form_submit_button("Giriş Yap", use_container_width=True)
            if submitted:
                if user_password == VIEWER_PASSWORD:
                    st.session_state.password_correct = True
                    st.session_state.user_role = "viewer"
                    st.rerun()
                elif ADMIN_PASSWORD and user_password == ADMIN_PASSWORD:
                    st.session_state.password_correct = True
                    st.session_state.user_role = "admin"
                    st.rerun()
                else:
                    st.error("❌ Hatalı Şifre! Erişim reddedildi.")
    return False

if not check_password():
    st.stop()

st.set_page_config(page_title="Kyoun | DCA & Scalp Hedging Terminal", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="stAppViewBlockContainer"],
    div[data-testid="stVerticalBlock"],
    [data-testid="stMain"],
    .stApp {
        opacity: 1.0 !important;
        filter: none !important;
        transition: none !important;
    }
    .element-container, .stPlotlyChart, .stMarkdown {
        opacity: 1.0 !important;
        transition: none !important;
    }
    div[data-testid="stStatusWidget"], [data-testid="stStatusWidget"] {
        display: none !important;
        visibility: hidden !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.3rem !important;
    }
    [data-testid="stMain"] h3 {
        font-size: 1.1rem !important;
        margin-top: 0.6rem !important;
        margin-bottom: 0.3rem !important;
    }
    [data-testid="stMain"] .stMarkdown p {
        font-size: 0.88rem !important;
        line-height: 1.4 !important;
    }
    section[data-testid="stSidebar"] .stRadio > div {
        gap: 0.15rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= MATEMATİKSEL FONKSİYONLAR =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high, low, close = df["Yuksek"], df["Dusuk"], df["Kapanis"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def detect_rsi_divergence(closes, rsis):
    if len(closes) < 15 or len(rsis) < 15:
        return False, False
    c, r = closes[-15:], rsis[-15:]
    lows = [i for i in range(1, len(c)-1) if c[i] < c[i-1] and c[i] < c[i+1]]
    bull = len(lows) >= 2 and c[lows[-1]] < c[lows[-2]] and r[lows[-1]] > r[lows[-2]] and r[lows[-1]] < 45
    highs = [i for i in range(1, len(c)-1) if c[i] > c[i-1] and c[i] > c[i+1]]
    bear = len(highs) >= 2 and c[highs[-1]] > c[highs[-2]] and r[highs[-1]] < r[highs[-2]] and r[highs[-1]] > 55
    return bull, bear

def nadaraya_watson_estimator(src, h=8):
    n = len(src)
    estimates = np.zeros(n)
    for i in range(n):
        past_indices = np.arange(i + 1)
        weights = np.exp(-((past_indices - i) ** 2) / (2 * h ** 2))
        estimates[i] = np.sum(src[:i+1] * weights) / np.sum(weights)
    return estimates

def calculate_nw_bands(df, std_multiplier, col_suffix, h=8, std_window=20):
    df["NW_Merkez"] = nadaraya_watson_estimator(df["Kapanis"].values, h=h)
    df["Fark"] = df["Kapanis"] - df["NW_Merkez"]
    df["Sapma_Std"] = df["Fark"].rolling(window=std_window).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

def fetch_tf_data(symbol, tf):
    """Bir zaman dilimi için OHLCV çekip NW/RSI/ATR'yi hesaplar. Tüm zaman
    dilimi bazlı işlemler bu tek fonksiyondan geçer - DCA ve Scalp aynı veriyi
    aynı şekilde hesaplar, kod tekrarı ve tutarsızlık riski ortadan kalkar."""
    p = TF_PARAMS[tf]
    raw = exchange.fetch_ohlcv(symbol, tf, limit=p["limit"])
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    df = calculate_nw_bands(df, 3.0, f"_{tf}", h=p["h"], std_window=p["std_window"])
    df["RSI"] = calculate_rsi(df["Kapanis"], period=p["rsi_period"])
    df["ATR"] = calculate_atr(df, period=14)
    return df

@st.cache_data(ttl=300)
def get_btc_funding_rate():
    try:
        fr_data = exchange.fetch_funding_rate("BTC/USDT:USDT")
        return {
            "rate": fr_data.get("fundingRate"),
            "next_rate": fr_data.get("nextFundingRate"),
            "next_time": fr_data.get("nextFundingTimestamp") or fr_data.get("fundingTimestamp"),
            "mark_price": fr_data.get("markPrice"),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:150]}"}

@st.cache_data(ttl=300)
def estimate_liquidation_pools(symbol, is_volatile=False):
    """TAHMİNİ likidasyon haritası - gerçek borsa verisi değildir. Son N saatin
    mum verisine göre, yaygın kaldıraç seviyelerinin (10x/25x/50x/100x) çakıştığı
    olası yoğunlaşma noktalarını tahmin eder. Pencere: sakin modda 3 gün, volatil
    modda 7 gün (kademe sisteminin volatil modda 1 güne kadar çıkmasıyla tutarlı)."""
    try:
        lookback_hours = 168 if is_volatile else 72
        raw = exchange.fetch_ohlcv(symbol, "1h", limit=lookback_hours)
        df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        highs, lows, volumes = df["Yuksek"].values, df["Dusuk"].values, df["Hacim"].values
        current_p = df.iloc[-1]["Kapanis"]
        round_step = 50.0 if current_p > 10000 else (1.0 if current_p > 100 else (0.1 if current_p > 1 else 0.01))
        leverage_levels = {10: 0.05, 25: 0.02, 50: 0.01, 100: 0.005}

        long_pools, short_pools = {}, {}
        for i in range(len(df)):
            for lev, pct in leverage_levels.items():
                p_long = round((lows[i] * (1 - pct)) / round_step) * round_step
                long_pools.setdefault(p_long, {"volume": 0.0, "leverages": set()})
                long_pools[p_long]["volume"] += volumes[i]
                long_pools[p_long]["leverages"].add(lev)
                p_short = round((highs[i] * (1 + pct)) / round_step) * round_step
                short_pools.setdefault(p_short, {"volume": 0.0, "leverages": set()})
                short_pools[p_short]["volume"] += volumes[i]
                short_pools[p_short]["leverages"].add(lev)

        def score(d):
            return d["volume"] * len(d["leverages"])

        sl = sorted(long_pools.items(), key=lambda x: score(x[1]), reverse=True)[:4]
        ss = sorted(short_pools.items(), key=lambda x: score(x[1]), reverse=True)[:4]
        sl.sort(key=lambda x: x[0], reverse=True)
        ss.sort(key=lambda x: x[0])
        avg_vol = df["Hacim"].mean()

        def label(d, emoji):
            n_lev, hi_vol = len(d["leverages"]), d["volume"] > avg_vol * 1.5
            if n_lev >= 3 and hi_vol:
                return f"{emoji*3} ÇOK YÜKSEK"
            elif n_lev >= 2 or hi_vol:
                return f"{emoji*2} YÜKSEK"
            return f"{emoji} ORTA"

        return (
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Çakışan Kaldıraç": "/".join(f"{l}x" for l in sorted(d["leverages"])), "Yoğunluk": label(d, "🔴")} for p, d in sl]),
            pd.DataFrame([{"Likidasyon Fiyatı": f"${p:,.2f}", "Çakışan Kaldıraç": "/".join(f"{l}x" for l in sorted(d["leverages"])), "Yoğunluk": label(d, "🟢")} for p, d in ss])
        )
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

def send_telegram_msg(message):
    if not telegram_token or not telegram_chat_id:
        return
    signed = f"🐑 *Kyoun*\n{message}"
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": telegram_chat_id, "text": signed, "parse_mode": "Markdown"})
    except Exception:
        pass

def place_futures_order(symbol, side, amount, leverage=None, is_live=False, reduce_only=False):
    """MEXC Futures emir gönderme. Kağıt modda hiçbir gerçek emir göndermez.
    Canlı modda göndermeden önce miktarın MEXC'in minimum/kontrat kuralına
    (0.0001 BTC'nin tam katı) uyup uymadığını doğrular."""
    if leverage is None:
        leverage = BOT_LEVERAGE
    if not is_live:
        return {"paper": True, "symbol": symbol, "side": side, "amount": amount, "status": "simulated"}

    MIN_ORDER_SIZE = 0.0001
    contracts = amount / MIN_ORDER_SIZE
    if amount < MIN_ORDER_SIZE or abs(contracts - round(contracts)) > 1e-6:
        return {"paper": False, "status": "error", "error": f"Geçersiz miktar: {amount} BTC, MEXC minimum {MIN_ORDER_SIZE} BTC'nin tam katı olmalı"}

    try:
        params = {"leverage": leverage, "marginMode": "cross"}
        if reduce_only:
            params["reduceOnly"] = True
        order = exchange.create_order(symbol, "market", side, amount, None, params)
        return {"paper": False, "status": "success", "order": order}
    except Exception as e:
        return {"paper": False, "status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}

# ================= GRAFİK ÇİZİM =================
import plotly.graph_objects as go

PLOTLY_CONFIG = {
    "displaylogo": False,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "hoverClosestCartesian", "hoverCompareCartesian", "toggleSpikelines"],
    "displayModeBar": True,
}

def draw_plotly_chart(df_subset, price_col, alt_band_col, ust_band_col, title, l_avg=0.0, s_avg=0.0):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[alt_band_col], name="Alt Band (Alış)",
                              line=dict(color='rgba(0, 230, 118, 0.85)', width=1.6, dash='dot')))
    fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=df_subset[ust_band_col], name="Üst Band (Satış)",
                              line=dict(color='rgba(255, 61, 87, 0.85)', width=1.6, dash='dot'),
                              fill='tonexty', fillcolor='rgba(120, 130, 255, 0.045)'))
    fig.add_trace(go.Candlestick(x=df_subset["Zaman"], open=df_subset["Acilis"], high=df_subset["Yuksek"],
                                  low=df_subset["Dusuk"], close=df_subset[price_col], name="Fiyat (OHLC)",
                                  increasing=dict(line=dict(color='#0ECB81', width=1), fillcolor='#0ECB81'),
                                  decreasing=dict(line=dict(color='#F6465D', width=1), fillcolor='#F6465D'),
                                  whiskerwidth=0.4))
    if l_avg > 0:
        fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[l_avg]*len(df_subset), name="Long Maliyet Ort.",
                                  line=dict(color='#00E676', width=1.3, dash='longdash')))
    if s_avg > 0:
        fig.add_trace(go.Scatter(x=df_subset["Zaman"], y=[s_avg]*len(df_subset), name="Short Maliyet Ort.",
                                  line=dict(color='#FF5252', width=1.3, dash='longdash')))

    last_price = df_subset[price_col].iloc[-1]
    fig.add_hline(y=last_price, line=dict(color='rgba(255,255,255,0.35)', width=1, dash='dot'),
                  annotation_text=f" {last_price:,.2f} ", annotation_position="right",
                  annotation_font=dict(color='#0B0E11', size=11, family="Arial Black"),
                  annotation_bgcolor='#F0B90B', annotation_borderpad=3, annotation_xshift=38)

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=15, color='#E8EAED', family="Arial"), x=0.01, xanchor='left', y=0.99, yanchor='top'),
        template="plotly_dark", plot_bgcolor='#0B0E11', paper_bgcolor='#0B0E11',
        font=dict(color='#B7BDC6', family="Arial"), margin=dict(l=10, r=85, t=85, b=10),
        height=420, bargap=0.25, xaxis_rangeslider_visible=False, hovermode="x unified",
        hoverlabel=dict(bgcolor='#1E2329', font_size=12, font_family="Arial", bordercolor='#2B3139'),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.0, bgcolor='rgba(0,0,0,0)', font=dict(size=11, color='#B7BDC6')),
        dragmode='pan', spikedistance=-1, hoverdistance=100
    )
    fig.update_xaxes(showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
                      showspikes=True, spikecolor='#F0B90B', spikethickness=1, spikedash='solid', spikemode='across', spikesnap='cursor',
                      tickfont=dict(color='#9098A1', size=11))
    fig.update_yaxes(showgrid=True, gridcolor='rgba(240, 185, 11, 0.06)', showline=True, linewidth=1, linecolor='#2B3139', mirror=True,
                      side='right', showspikes=True, spikecolor='#F0B90B', spikethickness=1, spikedash='solid', spikemode='across', spikesnap='cursor',
                      tickfont=dict(color='#D1D4DC', size=12), automargin=True)
    return fig

# ================= ORTAK STATE ŞEMASI =================
# DCA ve Scalp AYNI state şemasını kullanır, sadece state_key_prefix farklıdır.
# Bu, iki stratejinin kodunun birbirinden kopyalanıp tutarsız hale gelmesini önler.
selected_symbol = "BTC/USDT:USDT"
coin_title = selected_symbol.split(':')[0]
base_prefix = f"{selected_symbol}_"

def empty_position_state():
    return {
        "l_status": [False, False, False], "l_entry_prices": [0.0, 0.0, 0.0],
        "l_crypto": 0.0, "l_usd_spent": 0.0, "l_avg_price": 0.0,
        "s_status": [False, False, False], "s_entry_prices": [0.0, 0.0, 0.0],
        "s_crypto": 0.0, "s_usd_spent": 0.0, "s_avg_price": 0.0,
    }

def load_state(strategy_key):
    """strategy_key: 'dca' veya 'scalp'. Her ikisi de Supabase'de tek bir satırda,
    farklı kolon önekleriyle (dca_ / scalp_) saklanır."""
    prefix = f"{base_prefix}{strategy_key}_"
    if f"{prefix}loaded" in st.session_state:
        return prefix

    defaults = empty_position_state()
    loaded = False
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).order("id", descending=True).limit(1).execute()
            if q.data:
                d = q.data[0]
                col = lambda name: f"{strategy_key}_{name}"
                defaults["l_status"] = [d.get(col(f"l_status_{i}"), False) for i in range(3)]
                defaults["l_entry_prices"] = [d.get(col(f"l_entry_{i}"), 0.0) for i in range(3)]
                defaults["l_crypto"] = d.get(col("l_crypto"), 0.0)
                defaults["l_usd_spent"] = d.get(col("l_usd_spent"), 0.0)
                defaults["l_avg_price"] = d.get(col("l_avg_price"), 0.0)
                defaults["s_status"] = [d.get(col(f"s_status_{i}"), False) for i in range(3)]
                defaults["s_entry_prices"] = [d.get(col(f"s_entry_{i}"), 0.0) for i in range(3)]
                defaults["s_crypto"] = d.get(col("s_crypto"), 0.0)
                defaults["s_usd_spent"] = d.get(col("s_usd_spent"), 0.0)
                defaults["s_avg_price"] = d.get(col("s_avg_price"), 0.0)
                st.session_state[f"{base_prefix}balance_usd"] = d.get("balance_usd", 100.0)
                st.session_state[f"{base_prefix}log_history"] = d.get("log_history") or []
                st.session_state[f"{base_prefix}trade_history"] = d.get("trade_history") or []
                st.session_state[f"{base_prefix}manual_lock_db"] = d.get("manual_lock", False)
                st.session_state[f"{base_prefix}locked_prices"] = d.get("locked_prices")
                loaded = True
        except Exception:
            pass

    for k, v in defaults.items():
        st.session_state[f"{prefix}{k}"] = v
    if not loaded:
        st.session_state.setdefault(f"{base_prefix}balance_usd", 100.0)
        st.session_state.setdefault(f"{base_prefix}log_history", [])
        st.session_state.setdefault(f"{base_prefix}trade_history", [])
        st.session_state.setdefault(f"{base_prefix}manual_lock_db", False)
        st.session_state.setdefault(f"{base_prefix}locked_prices", None)
    st.session_state[f"{prefix}loaded"] = True
    return prefix

def save_state_to_db():
    if not supabase:
        return
    try:
        data = {"coin_symbol": selected_symbol,
                "balance_usd": st.session_state.get(f"{base_prefix}balance_usd", 100.0),
                "log_history": st.session_state.get(f"{base_prefix}log_history", []),
                "trade_history": st.session_state.get(f"{base_prefix}trade_history", []),
                "manual_lock": st.session_state.get("live_manual_lock_toggle", False),
                "locked_prices": st.session_state.get(f"{base_prefix}locked_prices")}
        for strategy_key in ("dca", "scalp"):
            prefix = f"{base_prefix}{strategy_key}_"
            col = lambda name: f"{strategy_key}_{name}"
            st_data = st.session_state
            data[col("l_crypto")] = st_data.get(f"{prefix}l_crypto", 0.0)
            data[col("l_usd_spent")] = st_data.get(f"{prefix}l_usd_spent", 0.0)
            data[col("l_avg_price")] = st_data.get(f"{prefix}l_avg_price", 0.0)
            data[col("s_crypto")] = st_data.get(f"{prefix}s_crypto", 0.0)
            data[col("s_usd_spent")] = st_data.get(f"{prefix}s_usd_spent", 0.0)
            data[col("s_avg_price")] = st_data.get(f"{prefix}s_avg_price", 0.0)
            l_status = st_data.get(f"{prefix}l_status", [False, False, False])
            s_status = st_data.get(f"{prefix}s_status", [False, False, False])
            l_entries = st_data.get(f"{prefix}l_entry_prices", [0.0, 0.0, 0.0])
            s_entries = st_data.get(f"{prefix}s_entry_prices", [0.0, 0.0, 0.0])
            for i in range(3):
                data[col(f"l_status_{i}")] = l_status[i]
                data[col(f"s_status_{i}")] = s_status[i]
                data[col(f"l_entry_{i}")] = l_entries[i]
                data[col(f"s_entry_{i}")] = s_entries[i]
        supabase.table("bot_state").upsert(data).execute()
    except Exception as e:
        st.error(f"Veritabanı kaydı başarısız: {type(e).__name__}: {str(e)[:200]}")

def record_trade(strategy_label, direction, exit_reason, entry_price, exit_price, amount, pnl_usd, pnl_pct, is_live):
    trade_record = {
        "zaman": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "strateji": strategy_label, "yon": direction, "sebep": exit_reason,
        "giris_fiyati": round(entry_price, 2), "cikis_fiyati": round(exit_price, 2),
        "miktar": round(amount, 6), "pnl_usd": round(pnl_usd, 4), "pnl_pct": round(pnl_pct, 4),
        "mod": "Canlı" if is_live else "Kağıt",
    }
    st.session_state.setdefault(f"{base_prefix}trade_history", []).append(trade_record)

# ================= ORTAK KADEMELİ POZİSYON MOTORU =================
# Hem DCA hem Scalp BU TEK fonksiyonu kullanır. Davranış farkı sadece dışarıdan
# verilen parametrelerden gelir: hangi zaman dilimleri, hangi miktarlar, hangi
# etiket. Mantığın kendisi (kademe sırası, RSI onayı, ATR bazlı kar-al/stop-loss,
# komisyon güvenliği) HER İKİ STRATEJİ İÇİN BİREBİR AYNIDIR.
def run_staged_strategy(strategy_key, strategy_label, prefix, current_price, dfs_by_tf, amounts, is_live, manual_lock=False, allow_new_entries=True):
    """
    dfs_by_tf: {tf_name: dataframe} - 3 kademe için kullanılacak, [k1_df, k2_df, k3_df] sırasıyla.
    amounts: [k1_miktar, k2_miktar, k3_miktar] BTC cinsinden.
    Döner: (nw_alt_levels, nw_ust_levels, rsi_levels, labels, active_engine_desc)
    """
    tf_names = list(dfs_by_tf.keys())
    dfk = list(dfs_by_tf.values())

    raw_alt = [df.iloc[-2][f"NW_Alt_{tf}"] for df, tf in zip(dfk, tf_names)]
    raw_ust = [df.iloc[-2][f"NW_Ust_{tf}"] for df, tf in zip(dfk, tf_names)]

    # Sıralama koruması: K1 > K2 > K3 (alt), K1 < K2 < K3 (üst) garantilenir.
    alt_base = [raw_alt[0]]
    for v in raw_alt[1:]:
        alt_base.append(min(v, alt_base[-1] * 0.997))
    ust_base = [raw_ust[0]]
    for v in raw_ust[1:]:
        ust_base.append(max(v, ust_base[-1] * 1.003))

    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    l_entries = st.session_state[f"{prefix}l_entry_prices"]
    s_entries = st.session_state[f"{prefix}s_entry_prices"]

    nw_alt = [l_entries[i] if l_status[i] else alt_base[i] for i in range(3)]
    nw_ust = [s_entries[i] if s_status[i] else ust_base[i] for i in range(3)]

    if manual_lock:
        lock_key = f"{prefix}locked_prices"
        if st.session_state.get(lock_key) is None:
            st.session_state[lock_key] = {"alt": nw_alt, "ust": nw_ust}
            save_state_to_db()
        nw_alt = st.session_state[lock_key]["alt"]
        nw_ust = st.session_state[lock_key]["ust"]
    else:
        st.session_state[f"{prefix}locked_prices"] = None

    rsi_vals = [df.iloc[-2]["RSI"] for df in dfk]
    rsi_prev_vals = [df.iloc[-3]["RSI"] for df in dfk]
    atr_k3 = dfk[2].iloc[-2]["ATR"]

    round_trip_fee_pct = 2 * MEXC_TAKER_FEE_PCT
    min_tp_distance = current_price * round_trip_fee_pct * MIN_PROFIT_SAFETY_MULT
    raw_tp_distance = ATR_TP_MULT * atr_k3
    tp_distance = max(raw_tp_distance, min_tp_distance)
    scale_factor = tp_distance / raw_tp_distance if raw_tp_distance > 0 else 1.0
    sl_distance = ATR_SL_MULT * atr_k3 * scale_factor

    # --- LONG ÇIKIŞ (sadece K3 alındıysa stop-loss aktif) ---
    if sum(l_status) > 0:
        avg = st.session_state[f"{prefix}l_avg_price"]
        amt = st.session_state[f"{prefix}l_crypto"]
        usd_spent = st.session_state[f"{prefix}l_usd_spent"]
        tp = avg + tp_distance
        sl = avg - sl_distance
        exit_reason = None
        if l_status[2] and current_price <= sl:
            exit_reason = "Stop-Loss"
        elif current_price >= tp:
            exit_reason = "Kar-Al"
        if exit_reason:
            order_result = place_futures_order(selected_symbol, "sell", amt, is_live=is_live, reduce_only=True)
            pnl_usd = (current_price - avg) * amt
            pnl_pct = ((current_price / avg) - 1) * 100 if avg > 0 else 0.0
            margin_used = usd_spent / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] += margin_used + pnl_usd
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            emoji = "🔴" if exit_reason == "Stop-Loss" else "🟢"
            msg = f"{emoji} *[{mode_tag}] {strategy_label} LONG {exit_reason} ({coin_title})*\nMaliyet Ort.: {avg:.2f}\nKapanış: {current_price:.2f}\nMiktar: {amt:.6f} BTC\nK/Z: {pnl_usd:+.4f} USDT ({pnl_pct:+.2f}%){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            record_trade(strategy_label, "LONG", exit_reason, avg, current_price, amt, pnl_usd, pnl_pct, is_live)
            st.session_state[f"{prefix}l_crypto"], st.session_state[f"{prefix}l_usd_spent"], st.session_state[f"{prefix}l_avg_price"] = 0.0, 0.0, 0.0
            st.session_state[f"{prefix}l_status"] = [False, False, False]
            st.session_state[f"{prefix}l_entry_prices"] = [0.0, 0.0, 0.0]
            save_state_to_db()
            l_status = st.session_state[f"{prefix}l_status"]

    # --- SHORT ÇIKIŞ ---
    if sum(s_status) > 0:
        avg = st.session_state[f"{prefix}s_avg_price"]
        amt = st.session_state[f"{prefix}s_crypto"]
        usd_spent = st.session_state[f"{prefix}s_usd_spent"]
        tp = avg - tp_distance
        sl = avg + sl_distance
        exit_reason = None
        if s_status[2] and current_price >= sl:
            exit_reason = "Stop-Loss"
        elif current_price <= tp:
            exit_reason = "Kar-Al"
        if exit_reason:
            order_result = place_futures_order(selected_symbol, "buy", amt, is_live=is_live, reduce_only=True)
            pnl_ratio = (avg - current_price) / avg if avg > 0 else 0.0
            pnl_usd = usd_spent * pnl_ratio
            pnl_pct = pnl_ratio * 100
            margin_used = usd_spent / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] += margin_used + pnl_usd
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            emoji = "🔴" if exit_reason == "Stop-Loss" else "🟢"
            msg = f"{emoji} *[{mode_tag}] {strategy_label} SHORT {exit_reason} ({coin_title})*\nMaliyet Ort.: {avg:.2f}\nKapanış: {current_price:.2f}\nMiktar: {amt:.6f} BTC\nK/Z: {pnl_usd:+.4f} USDT ({pnl_pct:+.2f}%){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            record_trade(strategy_label, "SHORT", exit_reason, avg, current_price, amt, pnl_usd, pnl_pct, is_live)
            st.session_state[f"{prefix}s_crypto"], st.session_state[f"{prefix}s_usd_spent"], st.session_state[f"{prefix}s_avg_price"] = 0.0, 0.0, 0.0
            st.session_state[f"{prefix}s_status"] = [False, False, False]
            st.session_state[f"{prefix}s_entry_prices"] = [0.0, 0.0, 0.0]
            save_state_to_db()
            s_status = st.session_state[f"{prefix}s_status"]

    # --- LONG GİRİŞ (sıralı kademe, RSI onaylı) ---
    for idx in range(3):
        if not allow_new_entries:
            break
        rsi_ok = rsi_vals[idx] < RSI_MIDPOINT
        can_enter = (idx == 0 or l_status[idx-1]) and not l_status[idx]
        if current_price <= nw_alt[idx] and rsi_ok and can_enter:
            val = amounts[idx]
            order_result = place_futures_order(selected_symbol, "buy", val, is_live=is_live)
            margin_used = (val * current_price) / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] -= margin_used
            st.session_state[f"{prefix}l_crypto"] += val
            st.session_state[f"{prefix}l_usd_spent"] += val * current_price
            st.session_state[f"{prefix}l_status"][idx] = True
            st.session_state[f"{prefix}l_entry_prices"][idx] = current_price
            st.session_state[f"{prefix}l_avg_price"] = st.session_state[f"{prefix}l_usd_spent"] / st.session_state[f"{prefix}l_crypto"]
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            msg = f"📈 *[{mode_tag}] {strategy_label} LONG K{idx+1} SATIN ALINDI ({coin_title})*\nFiyat: {current_price:.2f}\nMiktar: {val:.6f} BTC\nRSI: {rsi_vals[idx]:.1f} (<{RSI_MIDPOINT}){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            save_state_to_db()
            break

    # --- SHORT GİRİŞ ---
    for idx in range(3):
        if not allow_new_entries:
            break
        rsi_ok = rsi_vals[idx] > RSI_MIDPOINT
        can_enter = (idx == 0 or s_status[idx-1]) and not s_status[idx]
        if current_price >= nw_ust[idx] and rsi_ok and can_enter:
            val = amounts[idx]
            order_result = place_futures_order(selected_symbol, "sell", val, is_live=is_live)
            margin_used = (val * current_price) / BOT_LEVERAGE
            st.session_state[f"{base_prefix}balance_usd"] -= margin_used
            st.session_state[f"{prefix}s_crypto"] += val
            st.session_state[f"{prefix}s_usd_spent"] += val * current_price
            st.session_state[f"{prefix}s_status"][idx] = True
            st.session_state[f"{prefix}s_entry_prices"][idx] = current_price
            st.session_state[f"{prefix}s_avg_price"] = st.session_state[f"{prefix}s_usd_spent"] / st.session_state[f"{prefix}s_crypto"]
            mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
            note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
            msg = f"📈 *[{mode_tag}] {strategy_label} SHORT K{idx+1} AÇILDI ({coin_title})*\nFiyat: {current_price:.2f}\nMiktar: {val:.6f} BTC\nRSI: {rsi_vals[idx]:.1f} (>{RSI_MIDPOINT}){note}"
            send_telegram_msg(msg)
            st.session_state[f"{base_prefix}log_history"].append(msg)
            save_state_to_db()
            break

    return {
        "nw_alt": nw_alt, "nw_ust": nw_ust, "rsi_vals": rsi_vals, "rsi_prev_vals": rsi_prev_vals,
        "tf_names": tf_names, "tp_distance": tp_distance, "sl_distance": sl_distance, "atr_k3": atr_k3,
    }

def close_position_manual(strategy_label, prefix, direction, current_price, is_live):
    """LONG veya SHORT pozisyonu manuel olarak (kullanıcı butonu) kapatır."""
    side_field = "l" if direction == "LONG" else "s"
    avg = st.session_state[f"{prefix}{side_field}_avg_price"]
    amt = st.session_state[f"{prefix}{side_field}_crypto"]
    usd_spent = st.session_state[f"{prefix}{side_field}_usd_spent"]
    if amt <= 0:
        return
    close_side = "sell" if direction == "LONG" else "buy"
    order_result = place_futures_order(selected_symbol, close_side, amt, is_live=is_live, reduce_only=True)
    if direction == "LONG":
        pnl_usd = (current_price - avg) * amt
        pnl_pct = ((current_price / avg) - 1) * 100 if avg > 0 else 0.0
    else:
        pnl_ratio = (avg - current_price) / avg if avg > 0 else 0.0
        pnl_usd = usd_spent * pnl_ratio
        pnl_pct = pnl_ratio * 100
    margin_used = usd_spent / BOT_LEVERAGE
    st.session_state[f"{base_prefix}balance_usd"] += margin_used + pnl_usd
    mode_tag = "🔴 CANLI" if is_live else "📝 KAĞIT"
    note = "" if order_result.get("status") in ("simulated", "success") else f"\n⚠️ Emir hatası: {order_result.get('error','')}"
    msg = f"✋ *[{mode_tag}] {strategy_label} {direction} MANUEL KAPATILDI ({coin_title})*\nMaliyet Ort.: {avg:.2f}\nKapanış: {current_price:.2f}\nMiktar: {amt:.6f} BTC\nK/Z: {pnl_usd:+.4f} USDT ({pnl_pct:+.2f}%){note}"
    send_telegram_msg(msg)
    st.session_state[f"{base_prefix}log_history"].append(msg)
    record_trade(strategy_label, direction, "Manuel Kapatma", avg, current_price, amt, pnl_usd, pnl_pct, is_live)
    st.session_state[f"{prefix}{side_field}_crypto"], st.session_state[f"{prefix}{side_field}_usd_spent"], st.session_state[f"{prefix}{side_field}_avg_price"] = 0.0, 0.0, 0.0
    st.session_state[f"{prefix}{side_field}_status"] = [False, False, False]
    st.session_state[f"{prefix}{side_field}_entry_prices"] = [0.0, 0.0, 0.0]
    save_state_to_db()

# ================= STATE YÜKLEME =================
dca_prefix = load_state("dca")
scalp_prefix = load_state("scalp")
is_admin = st.session_state.get("user_role") == "admin"

# ================= SIDEBAR =================
st.sidebar.markdown("## 🐑 Kyoun")
st.sidebar.caption("BTC/USDT Futures Hedging Terminal")
role_label = "👑 Yönetici" if is_admin else "👁️ İzleyici"
st.sidebar.caption(f"Giriş: {role_label}")
if st.sidebar.button("🚪 Çıkış Yap", key="logout_button_global", use_container_width=True):
    st.session_state.password_correct = False
    st.session_state.user_role = None
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("💳 Cüzdan Durumu")
col_s1, col_s2 = st.sidebar.columns(2)
col_s1.metric("Bakiye", f"${st.session_state.get(f'{base_prefix}balance_usd', 100.0):,.2f}")
col_s2.metric("Kaldıraç", f"{BOT_LEVERAGE}x")
st.sidebar.caption(f"🔥 {coin_title} · Cross Margin")

st.sidebar.markdown("---")
btc_funding = get_btc_funding_rate()
if "error" in btc_funding:
    st.sidebar.warning(f"Fonlama oranı alınamadı: {btc_funding['error']}")
elif btc_funding.get("rate") is not None:
    rate_pct = btc_funding["rate"] * 100.0
    fr_color = "green" if rate_pct < 0 else "red"
    st.sidebar.markdown(f"💸 **Fonlama Oranı:** :{fr_color}[{rate_pct:+.4f}%]")
    if btc_funding.get("next_time"):
        try:
            next_dt = datetime.datetime.fromtimestamp(btc_funding["next_time"] / 1000, tz=datetime.timezone.utc)
            st.sidebar.caption(f"Sonraki ödeme: {next_dt.strftime('%H:%M UTC')}")
        except Exception:
            pass
else:
    st.sidebar.write("Fonlama oranı yükleniyor...")

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ İşlem Modu (MEXC Futures)")
api_keys_present = bool(MEXC_API_KEY and MEXC_API_SECRET)
if not is_admin:
    st.sidebar.info("👁️ İzleyici modundasınız. Canlı Mod sadece yönetici erişimiyle açılabilir.")
elif not api_keys_present:
    st.sidebar.warning("⚠️ MEXC API anahtarı tanımlı değil. Sadece Kağıt Mod kullanılabilir.")

trading_mode = st.sidebar.radio("Mod Seçimi", options=["📝 Kağıt Mod (Emir Gönderilmez)", "🔴 CANLI MOD (Gerçek Emir Gönderilir)"],
                                  index=0, key="trading_mode_radio", disabled=not (is_admin and api_keys_present))
live_trading_enabled = trading_mode.startswith("🔴") and api_keys_present and is_admin
if live_trading_enabled:
    st.sidebar.error("🔴 CANLI MOD AKTİF — Gerçek MEXC futures hesabınızda gerçek emir gönderilecek!")
    if not st.sidebar.checkbox("Riskleri anladım, onaylıyorum", key="live_trading_confirm_checkbox"):
        live_trading_enabled = False
        st.sidebar.info("Onay kutusu işaretlenmeden canlı emir gönderilmeyecek.")
else:
    st.sidebar.success("📝 Kağıt Mod: Sinyaller hesaplanır, gerçek emir gönderilmez.")

manual_lock = st.sidebar.toggle("🔒 Bekleyen Seviyeleri Dondur", value=st.session_state.get(f"{base_prefix}manual_lock_db", False), key="live_manual_lock_toggle", disabled=not is_admin)
if is_admin and manual_lock != st.session_state.get(f"{base_prefix}manual_lock_db", False):
    st.session_state[f"{base_prefix}manual_lock_db"] = manual_lock
    if not manual_lock:
        st.session_state[f"{base_prefix}locked_prices"] = None
    save_state_to_db()

col_b1, col_b2 = st.sidebar.columns(2)
if col_b1.button("🔔 Telegram Test", key="telegram_test_btn", use_container_width=True, disabled=not is_admin):
    send_telegram_msg("👋 *Bağlantı Testi:* Başarılı!")
    st.sidebar.success("Mesaj gönderildi!")
if col_b2.button("🔴 Tümünü Sıfırla", key="reset_all_btn", use_container_width=True, disabled=not is_admin):
    for strategy_key in ("dca", "scalp"):
        prefix = f"{base_prefix}{strategy_key}_"
        for k, v in empty_position_state().items():
            st.session_state[f"{prefix}{k}"] = v
    st.session_state[f"{base_prefix}balance_usd"] = 100.0
    st.session_state[f"{base_prefix}locked_prices"] = None
    save_state_to_db()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Strateji Modu")
dca_has_position = sum(st.session_state[f"{dca_prefix}l_status"]) > 0 or sum(st.session_state[f"{dca_prefix}s_status"]) > 0
scalp_has_position = sum(st.session_state[f"{scalp_prefix}l_status"]) > 0 or sum(st.session_state[f"{scalp_prefix}s_status"]) > 0

selected_mode_radio = st.sidebar.radio("Aktif Strateji", options=["📊 DCA (Kademeli)", "⚡ Scalp (Kademeli, Hızlı)"],
                                        index=0, key="strategy_mode_radio", label_visibility="collapsed")
selected_mode = "DCA" if selected_mode_radio.startswith("📊") else "SCALP"

if dca_has_position and selected_mode == "SCALP":
    st.sidebar.warning("📊 DCA'da açık pozisyon var. Scalp seçili görünse de yeni Scalp emri açılmaz.")
elif scalp_has_position and selected_mode == "DCA":
    st.sidebar.warning("⚡ Scalp'te açık pozisyon var. DCA seçili görünse de yeni DCA emri açılmaz.")

# ================= DCA FRAGMENT (Volatiliteye göre dinamik zaman dilimi) =================
@st.fragment(run_every="10s")
def dca_fragment():
    try:
        live_ticker = exchange.fetch_ticker(selected_symbol)
        current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0
        price_change_24h = live_ticker.get('percentage') or 0.0

        df_1m = fetch_tf_data(selected_symbol, "1m")
        df_5m = fetch_tf_data(selected_symbol, "5m")
        df_15m = fetch_tf_data(selected_symbol, "15m")
        df_1h = fetch_tf_data(selected_symbol, "1h")
        df_4h = fetch_tf_data(selected_symbol, "4h")
        df_1d = fetch_tf_data(selected_symbol, "1d")

        # 4h trend (EMA200) - ayrı, daha uzun (250 mum) bir veri çekişiyle hesaplanır.
        raw_4h_trend = exchange.fetch_ohlcv(selected_symbol, "4h", limit=250)
        df_4h_trend = pd.DataFrame(raw_4h_trend, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
        df_4h_trend["EMA_200"] = df_4h_trend["Kapanis"].ewm(span=200, adjust=False).mean()
        trend_4h = "YUKARI (BOĞA)" if df_4h_trend.iloc[-1]["Kapanis"] > df_4h_trend.iloc[-1]["EMA_200"] else "AŞAĞI (AYI)"
        warning_msg = "SHORT açarken DİKKATLİ olun!" if trend_4h == "YUKARI (BOĞA)" else "LONG açarken DİKKATLİ olun!"

        # Volatilite: fiyat std'si VE hacim onayı birlikte gerekir.
        price_std_now = df_15m["Kapanis"].rolling(20).std().iloc[-1]
        price_std_median = df_15m["Kapanis"].rolling(20).std().median()
        vol_now = df_15m["Hacim"].rolling(20).mean().iloc[-1]
        vol_median = df_15m["Hacim"].rolling(20).mean().median()
        price_is_volatile = price_std_now > price_std_median
        volume_confirms = vol_now > vol_median
        is_volatile = price_is_volatile and volume_confirms

        if is_volatile:
            market_state_label = "⚡ VOLATİL (Hacim Onaylı)"
            dfs_by_tf = {"15m": df_15m, "1h": df_1h, "1d": df_1d}
            labels = ["Kademe 1 (15m)", "Kademe 2 (1h)", "Kademe 3 (1d)"]
            engine_desc = "⚡ VOLATİL MOTOR (15m / 1h / 1d Hiyerarşisi)"
        elif price_is_volatile and not volume_confirms:
            market_state_label = "⚠️ FİYAT OYNAK AMA HACİM DÜŞÜK (Sakin Sayılır)"
            dfs_by_tf = {"1m": df_1m, "5m": df_5m, "15m": df_15m}
            labels = ["Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"]
            engine_desc = "💤 SAKİN MOTOR (1m / 5m / 15m Hiyerarşisi)"
        else:
            market_state_label = "💤 SAKİN (Yatay Salınım)"
            dfs_by_tf = {"1m": df_1m, "5m": df_5m, "15m": df_15m}
            labels = ["Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"]
            engine_desc = "💤 SAKİN MOTOR (1m / 5m / 15m Hiyerarşisi)"

        result = run_staged_strategy("dca", "DCA", dca_prefix, current_price, dfs_by_tf, DCA_AMOUNTS, live_trading_enabled, manual_lock, allow_new_entries=(selected_mode == "DCA"))

        df_long_liq, df_short_liq = estimate_liquidation_pools(selected_symbol, is_volatile)

        # --- ARAYÜZ ---
        col_left, col_right = st.columns([1.6, 1])
        with col_left:
            st.subheader("📈 DCA · Canlı Fiyat ve Nadaraya-Watson Zarf Grafikleri")
            tabs = st.tabs(["⏱️ 1m", "⏱️ 5m", "⏱️ 15m", "⏱️ 1h", "⏱️ 4h", "🌎 1d"])
            chart_dfs = {"1m": df_1m, "5m": df_5m, "15m": df_15m, "1h": df_1h, "4h": df_4h, "1d": df_1d}
            l_avg_disp = st.session_state[f"{dca_prefix}l_avg_price"]
            s_avg_disp = st.session_state[f"{dca_prefix}s_avg_price"]
            for tab, tf in zip(tabs, chart_dfs.keys()):
                with tab:
                    df_subset = chart_dfs[tf].tail(TF_PARAMS[tf]["limit"])
                    st.plotly_chart(draw_plotly_chart(df_subset, "Kapanis", f"NW_Alt_{tf}", f"NW_Ust_{tf}", f"{coin_title} - {tf} Grafik", l_avg_disp, s_avg_disp),
                                     use_container_width=True, key=f"{dca_prefix}chart_{tf}", config=PLOTLY_CONFIG)

            st.markdown("---")
            st.write("🎯 **DCA Sinyal Yönetim Kartı**")
            st.caption(f"Kar-Al: {result['tp_distance']:.2f} mesafe · Stop-Loss: {result['sl_distance']:.2f} mesafe (Kademe 3 ATR: {result['atr_k3']:.2f})")
            col_l, col_s = st.columns(2)
            with col_l:
                st.info("📈 LONG KADEMELERİ")
                l_status = st.session_state[f"{dca_prefix}l_status"]
                for i in range(3):
                    status_txt = f"✅ Alındı ({st.session_state[f'{dca_prefix}l_avg_price']:.2f})" if l_status[i] else f"⏳ Bekliyor ({result['nw_alt'][i]:.2f})"
                    st.write(f"**{labels[i]}:** {status_txt}")
                if sum(l_status) > 0:
                    st.success(f"🟢 **KAR-AL:** `{l_avg_disp + result['tp_distance']:.2f}`")
                    if l_status[2]:
                        st.error(f"🔴 **STOP-LOSS:** `{l_avg_disp - result['sl_distance']:.2f}`")
                    if st.button("✋ LONG Manuel Kapat", key="dca_close_long_btn", disabled=not is_admin, use_container_width=True):
                        close_position_manual("DCA", dca_prefix, "LONG", current_price, live_trading_enabled)
                        st.rerun(scope="fragment")
            with col_s:
                st.error("📉 SHORT KADEMELERİ")
                s_status = st.session_state[f"{dca_prefix}s_status"]
                for i in range(3):
                    status_txt = f"✅ Açıldı ({st.session_state[f'{dca_prefix}s_avg_price']:.2f})" if s_status[i] else f"⏳ Bekliyor ({result['nw_ust'][i]:.2f})"
                    st.write(f"**{labels[i]}:** {status_txt}")
                if sum(s_status) > 0:
                    st.success(f"🟢 **KAR-AL:** `{s_avg_disp - result['tp_distance']:.2f}`")
                    if s_status[2]:
                        st.error(f"🔴 **STOP-LOSS:** `{s_avg_disp + result['sl_distance']:.2f}`")
                    if st.button("✋ SHORT Manuel Kapat", key="dca_close_short_btn", disabled=not is_admin, use_container_width=True):
                        close_position_manual("DCA", dca_prefix, "SHORT", current_price, live_trading_enabled)
                        st.rerun(scope="fragment")

            st.markdown("---")
            liq_days = 7 if is_volatile else 3
            st.subheader(f"🎯 {liq_days} Günlük {coin_title.split('/')[0]} Tahmini Likidasyon Yoğunluk Haritası")
            st.caption(f"⚠️ Gerçek borsa verisi değildir. Son {liq_days*24} saatin mum verisine göre tahmindir.")
            col_liq_l, col_liq_s = st.columns(2)
            with col_liq_l:
                st.info("🔴 LONG LİKİDASYON HAVUZLARI")
                if not df_long_liq.empty:
                    st.table(df_long_liq.reset_index(drop=True))
            with col_liq_s:
                st.error("🟢 SHORT LİKİDASYON HAVUZLARI")
                if not df_short_liq.empty:
                    st.table(df_short_liq.reset_index(drop=True))

        with col_right:
            st.subheader(f"📊 Kyoun · {coin_title} DCA Terminal")
            tr_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
            st.caption(f"🕒 Son güncelleme: {tr_time.strftime('%H:%M:%S')} (TR)")
            if live_trading_enabled:
                st.error("🔴 CANLI MOD: Sinyaller gerçek emir olarak gönderiliyor!")
            else:
                st.info("📝 KAĞIT MOD: Sinyaller simüle ediliyor.")
            col_p1, col_p2 = st.columns(2)
            col_p1.metric("Anlık Fiyat", f"${current_price:,.2f}")
            col_p2.metric("24s Değişim", f"{price_change_24h:+.2f}%")
            if manual_lock:
                st.warning("🔒 SEVİYELER DONDURULDU")
            else:
                st.success("🔓 CANLI TAKİP AKTİF")
            st.markdown("---")
            st.write(f"**Piyasa Durumu:** {market_state_label}")
            st.caption(f"Aktif Motor: {engine_desc}")
            st.markdown("---")
            col_t1, col_t2 = st.columns(2)
            col_t1.metric("4h Genel Trend", trend_4h)
            if trend_4h == "YUKARI (BOĞA)":
                st.success(f"🛡️ {warning_msg}")
            else:
                st.error(f"🛡️ {warning_msg}")
            st.markdown("---")
            st.write(f"🎯 **Aktif Kademe RSI Filtreleri** (eşik: {RSI_MIDPOINT})")
            cols_rsi = st.columns(3)
            for i, col in enumerate(cols_rsi):
                with col:
                    long_ok = "✅" if result["rsi_vals"][i] < RSI_MIDPOINT else "❌"
                    short_ok = "✅" if result["rsi_vals"][i] > RSI_MIDPOINT else "❌"
                    st.write(f"**{labels[i]}**")
                    st.code(f"RSI: {result['rsi_vals'][i]:.1f}")
                    st.caption(f"L: {long_ok}  S: {short_ok}")

        st.markdown("---")
        if st.session_state[f"{base_prefix}log_history"]:
            st.write("📜 **Son Sinyaller (Log)**")
            for log in reversed(st.session_state[f"{base_prefix}log_history"][-3:]):
                st.write(log)

    except Exception as e:
        st.error(f"DCA hatası, 10s sonra tekrar denenecek: {type(e).__name__}: {str(e)[:200]}")
        try:
            has_pos = sum(st.session_state[f"{dca_prefix}l_status"]) > 0 or sum(st.session_state[f"{dca_prefix}s_status"]) > 0
            if has_pos:
                last_warn = st.session_state.get(f"{base_prefix}dca_last_warn", 0)
                if time.time() - last_warn > 300:
                    send_telegram_msg(f"⚠️ *DCA BOT HATA ALDI* ({type(e).__name__})\nAçık pozisyonunuz var, kontrol edemiyor. MEXC hesabınızı kontrol edin.")
                    st.session_state[f"{base_prefix}dca_last_warn"] = time.time()
        except Exception:
            pass
        time.sleep(5)

# ================= SCALP FRAGMENT (Her zaman sabit kısa zaman dilimi, kademeli) =================
@st.fragment(run_every="10s")
def scalp_fragment():
    try:
        live_ticker = exchange.fetch_ticker(selected_symbol)
        current_price = live_ticker.get('last') or live_ticker.get('close') or 0.0

        df_1m = fetch_tf_data(selected_symbol, "1m")
        df_5m = fetch_tf_data(selected_symbol, "5m")
        df_15m = fetch_tf_data(selected_symbol, "15m")
        dfs_by_tf = {"1m": df_1m, "5m": df_5m, "15m": df_15m}
        labels = ["Kademe 1 (1m)", "Kademe 2 (5m)", "Kademe 3 (15m)"]

        result = run_staged_strategy("scalp", "SCALP", scalp_prefix, current_price, dfs_by_tf, SCALP_AMOUNTS, live_trading_enabled, allow_new_entries=(selected_mode == "SCALP"))

        st.markdown("---")
        st.subheader("⚡ Scalp · Kademeli Hızlı Strateji")
        st.caption("Her zaman 1m/5m/15m kullanır (piyasa durumundan bağımsız). DCA ile aynı kademe mantığı, ayrı/bağımsız pozisyon.")
        if selected_mode != "SCALP" and not (sum(st.session_state[f"{scalp_prefix}l_status"]) > 0 or sum(st.session_state[f"{scalp_prefix}s_status"]) > 0):
            st.caption("Scalp Modu şu an pasif. Sidebar'dan 'Strateji Modu' bölümünden aktif edebilirsiniz.")

        col_sc1, col_sc2, col_sc3 = st.columns(3)
        col_sc1.metric("Anlık Fiyat", f"${current_price:,.2f}")
        col_sc2.metric("Kar-Al Mesafe", f"${result['tp_distance']:.2f}")
        col_sc3.metric("Stop-Loss Mesafe", f"${result['sl_distance']:.2f}")

        l_avg_disp = st.session_state[f"{scalp_prefix}l_avg_price"]
        s_avg_disp = st.session_state[f"{scalp_prefix}s_avg_price"]

        col_l, col_s = st.columns(2)
        with col_l:
            st.info("📈 SCALP LONG KADEMELERİ")
            l_status = st.session_state[f"{scalp_prefix}l_status"]
            for i in range(3):
                status_txt = f"✅ Alındı ({l_avg_disp:.2f})" if l_status[i] else f"⏳ Bekliyor ({result['nw_alt'][i]:.2f})"
                st.write(f"**{labels[i]}:** {status_txt}")
            if sum(l_status) > 0:
                st.success(f"🟢 **KAR-AL:** `{l_avg_disp + result['tp_distance']:.2f}`")
                if l_status[2]:
                    st.error(f"🔴 **STOP-LOSS:** `{l_avg_disp - result['sl_distance']:.2f}`")
                if st.button("✋ Scalp LONG Manuel Kapat", key="scalp_close_long_btn", disabled=not is_admin, use_container_width=True):
                    close_position_manual("SCALP", scalp_prefix, "LONG", current_price, live_trading_enabled)
                    st.rerun(scope="fragment")
        with col_s:
            st.error("📉 SCALP SHORT KADEMELERİ")
            s_status = st.session_state[f"{scalp_prefix}s_status"]
            for i in range(3):
                status_txt = f"✅ Açıldı ({s_avg_disp:.2f})" if s_status[i] else f"⏳ Bekliyor ({result['nw_ust'][i]:.2f})"
                st.write(f"**{labels[i]}:** {status_txt}")
            if sum(s_status) > 0:
                st.success(f"🟢 **KAR-AL:** `{s_avg_disp - result['tp_distance']:.2f}`")
                if s_status[2]:
                    st.error(f"🔴 **STOP-LOSS:** `{s_avg_disp + result['sl_distance']:.2f}`")
                if st.button("✋ Scalp SHORT Manuel Kapat", key="scalp_close_short_btn", disabled=not is_admin, use_container_width=True):
                    close_position_manual("SCALP", scalp_prefix, "SHORT", current_price, live_trading_enabled)
                    st.rerun(scope="fragment")

        st.write(f"🎯 **Scalp RSI Filtreleri** (eşik: {RSI_MIDPOINT})")
        cols_rsi = st.columns(3)
        for i, col in enumerate(cols_rsi):
            with col:
                long_ok = "✅" if result["rsi_vals"][i] < RSI_MIDPOINT else "❌"
                short_ok = "✅" if result["rsi_vals"][i] > RSI_MIDPOINT else "❌"
                st.write(f"**{labels[i]}**")
                st.code(f"RSI: {result['rsi_vals'][i]:.1f}")
                st.caption(f"L: {long_ok}  S: {short_ok}")

    except Exception as e:
        st.error(f"Scalp hatası, 10s sonra tekrar denenecek: {type(e).__name__}: {str(e)[:200]}")
        try:
            has_pos = sum(st.session_state[f"{scalp_prefix}l_status"]) > 0 or sum(st.session_state[f"{scalp_prefix}s_status"]) > 0
            if has_pos:
                last_warn = st.session_state.get(f"{base_prefix}scalp_last_warn", 0)
                if time.time() - last_warn > 300:
                    send_telegram_msg(f"⚠️ *SCALP BOT HATA ALDI* ({type(e).__name__})\nAçık pozisyonunuz var, kontrol edemiyor. MEXC hesabınızı kontrol edin.")
                    st.session_state[f"{base_prefix}scalp_last_warn"] = time.time()
        except Exception:
            pass
        time.sleep(5)

# ================= PERFORMANS PANELİ =================
@st.fragment(run_every="1s")
def countdown_fragment():
    if "scan_start_time" not in st.session_state:
        st.session_state.scan_start_time = time.time()
    elapsed = time.time() - st.session_state.scan_start_time
    remaining = max(0, 10 - int(elapsed))
    if remaining > 0:
        st.write(f"🔄 Sonraki taramaya: **{remaining}** saniye...")
    else:
        st.write("🔄 Taranıyor...")
        st.session_state.scan_start_time = time.time()

dca_fragment()
scalp_fragment()
with st.sidebar:
    countdown_fragment()

st.markdown("---")
st.header("📊 İşlem Geçmişi ve Performans")
trade_history = st.session_state.get(f"{base_prefix}trade_history", [])

if not trade_history:
    st.info("Henüz kapanmış bir işlem yok. İlk kar-al, stop-loss veya manuel kapatma burada görünecek.")
else:
    df_trades = pd.DataFrame(trade_history)
    total_trades = len(df_trades)
    winning_trades = len(df_trades[df_trades["pnl_usd"] > 0])
    losing_trades = len(df_trades[df_trades["pnl_usd"] <= 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    total_pnl_usd = df_trades["pnl_usd"].sum()
    avg_pnl_pct = df_trades["pnl_pct"].mean()
    best_trade = df_trades["pnl_usd"].max()
    worst_trade = df_trades["pnl_usd"].min()

    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    col_p1.metric("Toplam İşlem", f"{total_trades}")
    col_p2.metric("Kazanma Oranı", f"%{win_rate:.1f}", f"{winning_trades}K / {losing_trades}Z")
    col_p3.metric("Toplam K/Z", f"${total_pnl_usd:+,.4f}", f"Ort. %{avg_pnl_pct:+.3f}")
    col_p4.metric("En İyi / En Kötü", f"${best_trade:+,.4f}", f"${worst_trade:+,.4f}")

    st.markdown("##### Son İşlemler")
    df_display = df_trades.copy()
    df_display["zaman"] = pd.to_datetime(df_display["zaman"])
    df_display = df_display.sort_values("zaman", ascending=False)
    df_display["zaman"] = df_display["zaman"].dt.strftime("%d.%m %H:%M:%S")
    df_display = df_display.rename(columns={
        "zaman": "Zaman", "strateji": "Strateji", "yon": "Yön", "sebep": "Sebep",
        "giris_fiyati": "Giriş Fiyatı", "cikis_fiyati": "Çıkış Fiyatı",
        "miktar": "Miktar (BTC)", "pnl_usd": "K/Z (USDT)", "pnl_pct": "K/Z (%)", "mod": "Mod"
    })
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    csv_data = df_trades.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ İşlem Geçmişini CSV Olarak İndir", data=csv_data, file_name=f"kyoun_islem_gecmisi.csv", mime="text/csv")
