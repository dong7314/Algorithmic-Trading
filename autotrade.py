import os
from dotenv import load_dotenv
import pyupbit
import pandas as pd
import json
import time
import ta
from ta.utils import dropna
import google.generativeai as genai

load_dotenv()

gemini_key = os.getenv('GEMINI_KEY')
getmini_model = os.getenv('GEMINI_MODEL')
upbit_access_key = os.getenv("UPBIT_ACCESS_KEY")
upbit_secret_key = os.getenv("UPBIT_SECRET_KEY")

def add_indicators(df):
    # 볼린저 밴드
    indicator_bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_bbm'] = indicator_bb.bollinger_mavg()
    df['bb_bbh'] = indicator_bb.bollinger_hband()
    df['bb_bbl'] = indicator_bb.bollinger_lband()
    
    # RSI
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    
    # MACD
    macd = ta.trend.MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()
    
    # 이동평균선
    df['sma_20'] = ta.trend.SMAIndicator(close=df['close'], window=20).sma_indicator()
    df['ema_12'] = ta.trend.EMAIndicator(close=df['close'], window=12).ema_indicator()
    
    return df

def ai_trading():
    # Upbit 객체 생성
    upbit_access_key = os.getenv("UPBIT_ACCESS_KEY")
    upbit_secret_key = os.getenv("UPBIT_SECRET_KEY")
    upbit = pyupbit.Upbit(upbit_access_key, upbit_secret_key)

    # 1. 현재 투자 상태 조회
    all_balances = upbit.get_balances()
    filtered_balances = [balance for balance in all_balances if balance['currency'] in ['BTC', 'KRW']]
    
    # 2. 오더북(호가 데이터) 조회
    orderbook = pyupbit.get_orderbook("KRW-BTC")
    
    # 3. 차트 데이터 조회 및 보조지표 추가
    # 30일 일봉 데이터
    df_daily = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=30)
    df_daily = dropna(df_daily)
    df_daily = add_indicators(df_daily)
    
    # 24시간 시간봉 데이터
    df_hourly = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=24)
    df_hourly = dropna(df_hourly)
    df_hourly = add_indicators(df_hourly)

    # 2. AI에게 데이터 제공하고 판단 받기
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(f"models/{getmini_model}")

    system_prompt = """You are an expert in Bitcoin investing. Analyze the provided data including technical indicators and tell me whether to buy, sell, or hold at the moment. Consider the following indicators in your analysis:
    - Bollinger Bands (bb_bbm, bb_bbh, bb_bbl)
    - RSI (rsi)
    - MACD (macd, macd_signal, macd_diff)
    - Moving Averages (sma_20, ema_12)
    
    Response in json format.

    Response Example:
    {"decision": "buy", "reason": "some technical reason"}
    {"decision": "sell", "reason": "some technical reason"}
    {"decision": "hold", "reason": "some technical reason"}"""

    # 행동 강령이 포함된 프롬프트
    user_prompt = f"Current investment status: {json.dumps(filtered_balances)}\nOrderbook: {json.dumps(orderbook)}\nDaily OHLCV with indicators (30 days): {df_daily.to_json()}\nHourly OHLCV with indicators (24 hours): {df_hourly.to_json()}"
    provided_prompt = system_prompt + user_prompt

    # AI 응답 받기
    response = model.generate_content(provided_prompt)
    response_json = response.to_dict()

    # JSON 데이터 추출
    text_content = response_json["candidates"][0]["content"]["parts"][0]["text"]
    json_string = text_content.strip("```json\n").strip("```")

    # AI의 판단에 따라 실제로 자동매매 진행하기
    result = json.loads(json_string)

    print("### AI Decision: ", result["decision"].upper(), "###")
    print(f"### Reason: {result['reason']} ###")

    if result["decision"] == "buy":
        my_krw = upbit.get_balance("KRW")
        if my_krw*0.9995 > 5000:
            print("### Buy Order Executed ###")
            print(upbit.buy_market_order("KRW-BTC", my_krw * 0.9995))
        else:
            print("### Buy Order Failed: Insufficient KRW (less than 5000 KRW) ###")
    elif result["decision"] == "sell":
        my_btc = upbit.get_balance("KRW-BTC")
        current_price = pyupbit.get_orderbook(ticker="KRW-BTC")['orderbook_units'][0]["ask_price"]
        if my_btc*current_price > 5000:
            print("### Sell Order Executed ###")
            print(upbit.sell_market_order("KRW-BTC", my_btc))
        else:
            print("### Sell Order Failed: Insufficient BTC (less than 5000 KRW worth) ###")
    elif result["decision"] == "hold":
        print("### Hold Position ###")

# Main loop
while True:
    try:
        ai_trading()
        time.sleep(600)  # 10분 간격으로 실행 
    except Exception as e:
        print(f"An error occurred: {e}")
        time.sleep(60)  # 오류 발생 시 1분 후 재시도