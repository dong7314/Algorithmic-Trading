import os
import json
import pyupbit
import requests
import google.generativeai as genai

from dotenv import load_dotenv

load_dotenv()

# key 세팅
gemini_key = os.getenv('GEMINI_KEY')
getmini_model = os.getenv('GEMINI_MODEL')
upbit_access_key = os.getenv("UPBIT_ACCESS_KEY")
upbit_secret_key = os.getenv("UPBIT_SECRET_KEY")
naver_client_key = os.getenv('NAVER_CLIENT_ID')
naver_client_secret = os.getenv('NAVER_CLIENT_SECRET')

def ai_trading():
    # 1. 업비트 차트 데이터 가져오기 (30일 일봉) 및 네이버 뉴스 가져오기
    df = pyupbit.get_ohlcv("KRW-BTC", count=30, interval="day")
    df_minutes = pyupbit.get_ohlcv("KRW-BTC", count=30, interval="minute10")

    naver_request_url = 'https://openapi.naver.com/v1/search/news.json?query=비트코인&display=50&start=1&sort=date'
    headers = {
        "Accept": "application/json",
        "X-Naver-Client-Id": naver_client_key,
        "X-Naver-Client-Secret": naver_client_secret
    }

    news_response = requests.get(naver_request_url, headers=headers)
    news = []
    if news_response.status_code == 200:
        news = news_response.json()["items"]
    else:
        print(f"Error: {news_response.status_code}")

    # 2. AI에게 데이터 제공하고 판단 받기
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(f"models/{getmini_model}")

    # 행동 강령이 포함된 프롬프트
    user_prompt = f"""
    You are an expert in Bitcoin investing. Analyze the provided chart data (both daily and 10-minute intervals) along with relevant news data to determine whether to buy, sell, or hold at the moment. Ensure your response is in JSON format.

    ### Response Example:
    {{"decision": "buy", "reason": "some technical reason"}}
    {{"decision": "sell", "reason": "some technical reason"}}
    {{"decision": "hold", "reason": "some technical reason"}}

    ### Provided Data:
    #### 1. Bitcoin Daily Chart Data (Last 30 Days)
    {df.to_json()}

    #### 2. Bitcoin 10-Minute Interval Chart Data (Last 30 Entries)
    {df_minutes.to_json()}

    #### 3. Relevant News Data
    {news}

    ### Instructions:
    - Analyze both daily and 10-minute interval data to identify trends.
    - Consider **only objective** news data that may influence Bitcoin's price. Do not include subjective opinions, rumors, or speculative information. Focus on factual reports that could have a direct impact on Bitcoin's market.
    - Make an informed decision based on both technical analysis and news.
    """


    # AI 응답 받기
    response = model.generate_content(user_prompt)
    response_json = response.to_dict()

    # JSON 데이터 추출
    text_content = response_json["candidates"][0]["content"]["parts"][0]["text"]
    json_string = text_content.strip("```json\n").strip("```")
    ai_response_json = json.loads(json_string)

    # 3. AI의 판단에 따라 실제로 자동매매 진행하기
    upbit = pyupbit.Upbit(upbit_access_key, upbit_secret_key)
    if ai_response_json["decision"] == "buy":
        # 매수
        my_krw = upbit.get_balance("KRW")
        if my_krw*0.9995 > 5000:
            print("### Buy Order Executed ###")
            print(upbit.buy_market_order("KRW-BTC", my_krw * 0.9995))
        else:
            print("### Buy Order Failed: Insufficient KRW (less than 5000 KRW) ###")
    elif ai_response_json["decision"] == "sell":
        # 매도
        my_btc =upbit.get_balance("KRW-BTC")
        current_price = pyupbit.get_orderbook(ticker="KRW-BTC")['orderbook_units'][0]["ask_price"]
        if my_btc*current_price > 5000:
                print("### Sell Order Executed ###")
                print(upbit.sell_market_order("KRW-BTC", my_btc))
        else:
            print("### Sell Order Failed: Insufficient BTC (less than 5000 KRW worth) ###")
    elif ai_response_json["decision"] == "hold":
        # 유지
        print("### Hold Position ###")


while True:
    import time
    time.sleep(60*60)
    ai_trading()