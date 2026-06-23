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
# .strip() eklenerek olası boşluk/karakter hataları temizlendi.
supabase_url = st.secrets.get("SUPABASE_URL", "").strip()
supabase_key = st.secrets.get("SUPABASE_KEY", "").strip()
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
    df["Sapma_Std"] = df["Fark"].ewm(span=std_window, min_periods=std_window).std()
    df[f"NW_Ust{col_suffix}"] = df["NW_Merkez"] + (std_multiplier * df["Sapma_Std"])
    df[f"NW_Alt{col_suffix}"] = df["NW_Merkez"] - (std_multiplier * df["Sapma_Std"])
    return df

def fetch_with_retry(fetch_fn, max_retries=2, base_delay=0.5):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fetch_fn()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(base_delay * (attempt + 1))
    raise last_error

def fetch_tf_data(symbol, tf):
    p = TF_PARAMS[tf]
    raw = fetch_with_retry(lambda: exchange.fetch_ohlcv(symbol, tf, limit=p["limit"]))
    df = pd.DataFrame(raw, columns=["Zaman", "Acilis", "Yuksek", "Dusuk", "Kapanis", "Hacim"])
    df["Zaman"] = pd.to_datetime(df["Zaman"], unit="ms")
    df = calculate_nw_bands(df, 3.0, f"_{tf}", h=p["h"], std_window=p["std_window"])
    df["RSI"] = calculate_rsi(df["Kapanis"], period=p["rsi_period"])
    df["ATR"] = calculate_atr(df, period=14)
    return df

@st.cache_data(ttl=300)
def get_btc_funding_rate():
    try:
        fr_data = fetch_with_retry(lambda: exchange.fetch_funding_rate("BTC/USDT:USDT"))
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
    try:
        lookback_hours = 168 if is_volatile else 72
        raw = fetch_with_retry(lambda: exchange.fetch_ohlcv(symbol, "1h", limit=lookback_hours))
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
    return fig

# ================= ORTAK STATE ŞEMASI =================
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
    prefix = f"{base_prefix}{strategy_key}_"
    if f"{prefix}loaded" in st.session_state:
        return prefix

    defaults = empty_position_state()
    loaded = False
    db_error = None
    if supabase:
        try:
            q = supabase.table("bot_state").select("*").eq("coin_symbol", selected_symbol).order("id", desc=True).limit(1).execute()
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
                st.session_state[f"{prefix}locked_prices"] = d.get(col("locked_prices"))
                loaded = True
        except Exception as e:
            db_error = f"{type(e).__name__}: {str(e)[:200]}"

    for k, v in defaults.items():
        st.session_state[f"{prefix}{k}"] = v
    if not loaded:
        st.session_state.setdefault(f"{base_prefix}balance_usd", 100.0)
        st.session_state.setdefault(f"{base_prefix}log_history", [])
        st.session_state.setdefault(f"{base_prefix}trade_history", [])
        st.session_state.setdefault(f"{base_prefix}manual_lock_db", False)
        if db_error:
            st.session_state[f"{base_prefix}db_load_error"] = db_error
    st.session_state.setdefault(f"{prefix}locked_prices", None)
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
                "manual_lock": st.session_state.get("live_manual_lock_toggle", False)}
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
            data[col("locked_prices")] = st_data.get(f"{prefix}locked_prices")
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

def run_staged_strategy(strategy_key, strategy_label, prefix, current_price, dfs_by_tf, amounts, is_live, manual_lock=False, allow_new_entries=True):
    tf_names = list(dfs_by_tf.keys())
    dfk = list(dfs_by_tf.values())
    raw_alt = [df.iloc[-2][f"NW_Alt_{tf}"] for df, tf in zip(dfk, tf_names)]
    raw_ust = [df.iloc[-2][f"NW_Ust_{tf}"] for df, tf in zip(dfk, tf_names)]
    atr_vals = [df.iloc[-2]["ATR"] for df in dfk]
    MIN_STAGE_GAP_ATR_MULT = 0.5
    alt_base = [raw_alt[0]]
    alt_ready = [True]
    min_gaps_alt = [0.0]
    for i in range(1, 3):
        min_gap = MIN_STAGE_GAP_ATR_MULT * atr_vals[i]
        gap = alt_base[-1] - raw_alt[i]
        alt_base.append(raw_alt[i])
        alt_ready.append(gap >= min_gap)
        min_gaps_alt.append(min_gap)
    ust_base = [raw_ust[0]]
    ust_ready = [True]
    min_gaps_ust = [0.0]
    for i in range(1, 3):
        min_gap = MIN_STAGE_GAP_ATR_MULT * atr_vals[i]
        gap = raw_ust[i] - ust_base[-1]
        ust_base.append(raw_ust[i])
        ust_ready.append(gap >= min_gap)
        min_gaps_ust.append(min_gap)
    l_status = st.session_state[f"{prefix}l_status"]
    s_status = st.session_state[f"{prefix}s_status"]
    l_entries = st.session_state[f"{prefix}l_entry_prices"]
    s_entries = st.session_state[f"{prefix}s_entry_prices"]
    nw_alt = [l_entries[i] if l_status[i] else alt_base[i] for i in range(3)]
    nw_ust = [s_entries[i] if s_status[i] else raw_ust[i] for i in range(3)]
    if manual_lock:
        lock_key = f"{prefix}locked_prices"
        if st.session_state.get(lock_key) is None:
            st.session_state[lock_key] = {"alt": nw_alt, "ust": nw_ust, "alt_ready": alt_ready, "ust_ready": ust_ready}
            save_state_to_db()
        locked = st.session_state[lock_key]
        nw_alt = locked["alt"]; nw_ust = locked["ust"]; alt_ready = locked.get("alt_ready", alt_ready); ust_ready = locked.get("ust_ready", ust_ready)
    else: st.session_state[f"{prefix}locked_prices"] = None
    rsi_vals = [df.iloc[-2]["RSI"] for df in dfk]
    atr_k3 = dfk[2].iloc[-2]["ATR"]
    round_trip_fee_pct = 2 * MEXC_TAKER_FEE_PCT
    min_tp_distance = current_price * round_trip_fee_pct * MIN_PROFIT_SAFETY_MULT
    raw_tp_distance = ATR_TP_MULT * atr_k3
    tp_distance = max(raw_tp_distance, min_tp_distance)
    sl_distance = ATR_SL_MULT * atr_k3 * (tp_distance / raw_tp_distance if raw_tp_distance > 0 else 1.0)

    if sum(l_status) > 0:
        avg = st.session_state[f"{prefix}l_avg_price"]; amt = st.session_state[f"{prefix}l_crypto"]; usd_spent = st.session_state[f"{prefix}l_usd_spent"]
        tp = avg + tp_distance; sl = avg - sl_distance; exit_reason = None
        if l_status[2] and current_price <= sl: exit_reason = "Stop-Loss"
        elif current_price >= tp: exit_reason = "Kar-Al"
        if exit_reason:
            order_result = place_futures_order(selected_symbol, "sell", amt, is_live=is_live, reduce_only=True)
            pnl_usd = (current_price - avg) * amt; pnl_pct = ((current_price / avg) - 1) * 100
            st.session_state[f"{base_prefix}balance_usd"] += (usd_spent / BOT_LEVERAGE) + pnl_usd
            msg = f"{'🔴' if exit_reason=='Stop-Loss' else '🟢'} *[{'CANLI' if is_live else 'KAĞIT'}] {strategy_label} LONG {exit_reason}*\nOrt: {avg:.2f} Kapat: {current_price:.2f} K/Z: {pnl_usd:+.4f}"
            send_telegram_msg(msg); st.session_state[f"{base_prefix}log_history"].append(msg)
            record_trade(strategy_label, "LONG", exit_reason, avg, current_price, amt, pnl_usd, pnl_pct, is_live)
            st.session_state[f"{prefix}l_crypto"], st.session_state[f"{prefix}l_usd_spent"], st.session_state[f"{prefix}l_avg_price"] = 0.0, 0.0, 0.0
            st.session_state[f"{prefix}l_status"] = [False, False, False]; st.session_state[f"{prefix}l_entry_prices"] = [0.0, 0.0, 0.0]; save_state_to_db()

    if sum(s_status) > 0:
        avg = st.session_state[f"{prefix}s_avg_price"]; amt = st.session_state[f"{prefix}s_crypto"]; usd_spent = st.session_state[f"{prefix}s_usd_spent"]
        tp = avg - tp_distance; sl = avg + sl_distance; exit_reason = None
        if s_status[2] and current_price >= sl: exit_reason = "Stop-Loss"
        elif current_price <= tp: exit_reason = "Kar-Al"
        if exit_reason:
            order_result = place_futures_order(selected_symbol, "buy", amt, is_live=is_live, reduce_only=True)
            pnl_usd = usd_spent * ((avg - current_price) / avg); pnl_pct = ((avg - current_price) / avg) * 100
            st.session_state[f"{base_prefix}balance_usd"] += (usd_spent / BOT_LEVERAGE) + pnl_usd
            msg = f"{'🔴' if exit_reason=='Stop-Loss' else '🟢'} *[{'CANLI' if is_live else 'KAĞIT'}] {strategy_label} SHORT {exit_reason}*\nOrt: {avg:.2f} Kapat: {current_price:.2f} K/Z: {pnl_usd:+.4f}"
            send_telegram_msg(msg); st.session_state[f"{base_prefix}log_history"].append(msg)
            record_trade(strategy_label, "SHORT", exit_reason, avg, current_price, amt, pnl_usd, pnl_pct, is_live)
            st.session_state[f"{prefix}s_crypto"], st.session_state[f"{prefix}s_usd_spent"], st.session_state[f"{prefix}s_avg_price"] = 0.0, 0.0, 0.0
            st.session_state[f"{prefix}s_status"] = [False, False, False]; st.session_state[f"{prefix}s_entry_prices"] = [0.0, 0.0, 0.0]; save_state_to_db()

    for idx in range(3):
        if not allow_new_entries: break
        if current_price <= nw_alt[idx] and rsi_vals[idx] < RSI_MIDPOINT and (idx == 0 or l_status[idx-1]) and not l_status[idx] and alt_ready[idx]:
            val = amounts[idx]; order_result = place_futures_order(selected_symbol, "buy", val, is_live=is_live)
            st.session_state[f"{base_prefix}balance_usd"] -= (val * current_price) / BOT_LEVERAGE
            st.session_state[f"{prefix}l_crypto"] += val; st.session_state[f"{prefix}l_usd_spent"] += val * current_price; st.session_state[f"{prefix}l_status"][idx] = True; st.session_state[f"{prefix}l_entry_prices"][idx] = current_price
            st.session_state[f"{prefix}l_avg_price"] = st.session_state[f"{prefix}l_usd_spent"] / st.session_state[f"{prefix}l_crypto"]
            msg = f"📈 *[{'CANLI' if is_live else 'KAĞIT'}] {strategy_label} LONG K{idx+1} SATIN ALINDI*"
            send_telegram_msg(msg); st.session_state[f"{base_prefix}log_history"].append(msg); save_state_to_db(); break

    for idx in range(3):
        if not allow_new_entries: break
        if current_price >= nw_ust[idx] and rsi_vals[idx] > RSI_MIDPOINT and (idx == 0 or s_status[idx-1]) and not s_status[idx] and ust_ready[idx]:
            val = amounts[idx]; order_result = place_futures_order(selected_symbol, "sell", val, is_live=is_live)
            st.session_state[f"{base_prefix}balance_usd"] -= (val * current_price) / BOT_LEVERAGE
            st.session_state[f"{prefix}s_crypto"] += val; st.session_state[f"{prefix}s_usd_spent"] += val * current_price; st.session_state[f"{prefix}s_status"][idx] = True; st.session_state[f"{prefix}s_entry_prices"][idx] = current_price
            st.session_state[f"{prefix}s_avg_price"] = st.session_state[f"{prefix}s_usd_spent"] / st.session_state[f"{prefix}s_crypto"]
            msg = f"📉 *[{'CANLI' if is_live else 'KAĞIT'}] {strategy_label} SHORT K{idx+1} AÇILDI*"
            send_telegram_msg(msg); st.session_state[f"{base_prefix}log_history"].append(msg); save_state_to_db(); break

    return {"nw_alt": nw_alt, "nw_ust": nw_ust, "rsi_vals": rsi_vals, "tf_names": tf_names, "tp_distance": tp_distance, "sl_distance": sl_distance, "alt_ready": alt_ready, "ust_ready": ust_ready, "min_gaps_alt": min_gaps_alt, "min_gaps_ust": min_gaps_ust}

def close_position_manual(strategy_label, prefix, direction, current_price, is_live):
    side_field = "l" if direction == "LONG" else "s"; amt = st.session_state[f"{prefix}{side_field}_crypto"]
    if amt <= 0: return
    order_result = place_futures_order(selected_symbol, "sell" if direction == "LONG" else "buy", amt, is_live=is_live, reduce_only=True)
    avg = st.session_state[f"{prefix}{side_field}_avg_price"]; usd_spent = st.session_state[f"{prefix}{side_field}_usd_spent"]
    pnl_usd = (current_price - avg) * amt if direction == "LONG" else usd_spent * ((avg - current_price) / avg)
    st.session_state[f"{base_prefix}balance_usd"] += (usd_spent / BOT_LEVERAGE) + pnl_usd
    msg = f"✋ *[{'CANLI' if is_live else 'KAĞIT'}] {strategy_label} {direction} MANUEL KAPATILDI*"
    send_telegram_msg(msg); st.session_state[f"{base_prefix}log_history"].append(msg)
    record_trade(strategy_label, direction, "Manuel Kapatma", avg, current_price, amt, pnl_usd, (pnl_usd/usd_spent)*100, is_live)
    st.session_state[f"{prefix}{side_field}_crypto"], st.session_state[f"{prefix}{side_field}_usd_spent"], st.session_state[f"{prefix}{side_field}_avg_price"] = 0.0, 0.0, 0.0
    st.session_state[f"{prefix}{side_field}_status"] = [False, False, False]; st.session_state[f"{prefix}{side_field}_entry_prices"] = [0.0, 0.0, 0.0]; save_state_to_db()

# ================= KADEMELİ PANEL VE FRAGMENTLAR =================
dca_prefix = load_state("dca"); scalp_prefix = load_state("scalp"); is_admin = st.session_state.get("user_role") == "admin"
st.sidebar.markdown("## 🐑 Kyoun")
if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True): st.session_state.password_correct = False; st.session_state.user_role = None; st.rerun()
if st.session_state.get(f"{base_prefix}db_load_error"): st.sidebar.error(f"⚠️ Veri hatası: {st.session_state[f'{base_prefix}db_load_error']}")
trading_mode = st.sidebar.radio("Mod", options=["📝 Kağıt Mod", "🔴 Canlı Mod"], index=0, disabled=not is_admin)
live_trading_enabled = trading_mode.startswith("🔴") and is_admin
selected_mode_radio = st.sidebar.radio("Strateji", options=["📊 DCA", "⚡ Scalp"], index=0, disabled=not is_admin)
selected_mode = "DCA" if "DCA" in selected_mode_radio else "SCALP"
manual_lock = st.sidebar.toggle("🔒 Seviyeleri Dondur", value=st.session_state.get(f"{base_prefix}manual_lock_db", False), disabled=not is_admin)
if is_admin: st.session_state[f"{base_prefix}manual_lock_db"] = manual_lock; save_state_to_db()

@st.fragment(run_every="1s")
def status_bar_fragment():
    now_tr = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
    dca_age = f"{int(time.time() - st.session_state.get('dca_last_success', 0))}s" if st.session_state.get('dca_last_success') else "..."
    scalp_age = f"{int(time.time() - st.session_state.get('scalp_last_success', 0))}s" if st.session_state.get('scalp_last_success') else "..."
    st.markdown(f'<div class="live-status-bar"><div><span class="live-pulse"></span><b>Aktif</b> · {now_tr.strftime("%H:%M:%S")} · {"🔴 CANLI" if live_trading_enabled else "📝 KAĞIT"}</div><div>📊 DCA: {dca_age} &nbsp; ⚡ Scalp: {scalp_age}</div></div>', unsafe_allow_html=True)
    bal = st.session_state.get(f"{base_prefix}balance_usd", 100.0); hist = st.session_state.get(f"{base_prefix}trade_history", [])
    pnl = sum(t["pnl_usd"] for t in hist) if hist else 0.0
    t1, t2, t3 = st.columns(3); t1.metric("💳 Bakiye", f"${bal:,.2f}"); t2.metric("📈 K/Z", f"${pnl:+,.4f}"); t3.metric("🎯 Mod", selected_mode)

status_bar_fragment(); st.divider()

def render_strategy_panel(label, prefix, current_price, result, chart_dfs, tf_keys, l_labels, key_ns):
    col_chart, col_side = st.columns([1.7, 1])
    with col_chart:
        tabs = st.tabs([f"⏱️ {tf}" for tf in tf_keys])
        for tab, tf in zip(tabs, tf_keys):
            with tab: st.plotly_chart(draw_plotly_chart(chart_dfs[tf].tail(TF_PARAMS[tf]["limit"]), "Kapanis", f"NW_Alt_{tf}", f"NW_Ust_{tf}", f"{coin_title} - {tf}", st.session_state[f"{prefix}l_avg_price"], st.session_state[f"{prefix}s_avg_price"]), use_container_width=True, key=f"{key_ns}_{tf}", config=PLOTLY_CONFIG)
    with col_side:
        st.markdown(f"##### 💼 {label}")
        for side, d_label in [("l", "LONG"), ("s", "SHORT")]:
            if st.session_state[f"{prefix}{side}_crypto"] > 0:
                with st.container(border=True):
                    avg = st.session_state[f"{prefix}{side}_avg_price"]; amt = st.session_state[f"{prefix}{side}_crypto"]
                    pnl = (current_price - avg) * amt if side == "l" else st.session_state[f"{prefix}{side}_usd_spent"] * ((avg - current_price) / avg)
                    st.write(f"**{d_label}** · Ort: {avg:,.2f}"); st.metric("K/Z", f"${pnl:+,.4f}")
                    if st.button(f"✋ Kapat", key=f"cl_{key_ns}_{side}", use_container_width=True): close_position_manual(label, prefix, d_label, current_price, live_trading_enabled); st.rerun()

@st.fragment(run_every="10s")
def dca_fragment():
    try:
        live = fetch_with_retry(lambda: exchange.fetch_ticker(selected_symbol))
        price = live.get('last'); df15 = fetch_tf_data(selected_symbol, "15m"); is_vol = df15["Kapanis"].rolling(20).std().iloc[-1] > df15["Kapanis"].rolling(20).std().median()
        tfs = ["15m", "1h", "1d"] if is_vol else ["1m", "5m", "15m"]
        dfs = {tf: (fetch_tf_data(selected_symbol, tf) if tf not in ["15m"] else df15) for tf in tfs}
        res = run_staged_strategy("dca", "DCA", dca_prefix, price, dfs, DCA_AMOUNTS, live_trading_enabled, manual_lock, selected_mode=="DCA")
        render_strategy_panel("DCA", dca_prefix, price, res, dfs, tfs, [f"K{i+1}" for i in range(3)], "dca")
        st.session_state["dca_last_success"] = time.time()
    except Exception as e: st.error(f"DCA Hatası: {str(e)[:100]}")

@st.fragment(run_every="10s")
def scalp_fragment():
    try:
        live = fetch_with_retry(lambda: exchange.fetch_ticker(selected_symbol))
        price = live.get('last'); tfs = ["1m", "5m", "15m"]
        dfs = {tf: fetch_tf_data(selected_symbol, tf) for tf in tfs}
        res = run_staged_strategy("scalp", "SCALP", scalp_prefix, price, dfs, SCALP_AMOUNTS, live_trading_enabled, manual_lock, selected_mode=="SCALP")
        render_strategy_panel("SCALP", scalp_prefix, price, res, dfs, tfs, [f"K{i+1}" for i in range(3)], "scalp")
        st.session_state["scalp_last_success"] = time.time()
    except Exception as e: st.error(f"Scalp Hatası: {str(e)[:100]}")

tab_dca, tab_scalp, tab_hist = st.tabs(["📊 DCA", "⚡ Scalp", "📜 Geçmiş"])
with tab_dca: dca_fragment()
with tab_scalp: scalp_fragment()
with tab_hist: st.dataframe(pd.DataFrame(st.session_state.get(f"{base_prefix}trade_history", [])).sort_values("zaman", ascending=False) if st.session_state.get(f"{base_prefix}trade_history") else pd.DataFrame(), use_container_width=True)
