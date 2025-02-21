import os
import io
import ta
import json
import time
import base64
import logging
import pyupbit
import requests
import pandas as pd
import mysql.connector
import google.generativeai as genai

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from PIL import Image
from dotenv import load_dotenv
from ta.utils import dropna
from datetime import datetime, timedelta

load_dotenv()

gemini_key = os.getenv('GEMINI_KEY')
getmini_model = os.getenv('GEMINI_MODEL')
upbit_access_key = os.getenv("UPBIT_ACCESS_KEY")
upbit_secret_key = os.getenv("UPBIT_SECRET_KEY")
naver_client_key = os.getenv('NAVER_CLIENT_ID')
naver_client_secret = os.getenv('NAVER_CLIENT_SECRET')
serpapi_key = os.getenv("SERPAPI_API_KEY")

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('MYSQL_HOST'),
        port=os.getenv('MYSQL_PORT'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DB')
    )

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            decision VARCHAR(10),
            percentage INT,
            reason TEXT,
            btc_balance DECIMAL(18,8),
            krw_balance DECIMAL(18,8),
            btc_avg_buy_price DECIMAL(18,8),
            btc_krw_price DECIMAL(18,8),
            reflection TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

def log_trade(conn, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection=''):
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    
    sql = """INSERT INTO trades 
             (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection) 
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
             
    values = (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price, reflection)

    cursor.execute(sql, values)
    conn.commit()
    cursor.close()

def get_recent_trades(conn, days=7):
    c = conn.cursor()
    seven_days_ago = (datetime.now() - timedelta(days=days)).isoformat()
    c.execute("SELECT * FROM trades WHERE timestamp > %s ORDER BY timestamp DESC", (seven_days_ago,))
    columns = [column[0] for column in c.description]
    return pd.DataFrame.from_records(data=c.fetchall(), columns=columns)

def calculate_performance(trades_df):
    if trades_df.empty:
        return 0
    
    initial_balance = trades_df.iloc[-1]['krw_balance'] + trades_df.iloc[-1]['btc_balance'] * trades_df.iloc[-1]['btc_krw_price']
    final_balance = trades_df.iloc[0]['krw_balance'] + trades_df.iloc[0]['btc_balance'] * trades_df.iloc[0]['btc_krw_price']
    
    return (final_balance - initial_balance) / initial_balance * 100

def generate_reflection(trades_df, current_market_data):
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(f"models/{getmini_model}")
    performance = calculate_performance(trades_df)

    system_prompt = """You are an AI trading assistant tasked with analyzing recent trading performance and current market conditions to generate insights and improvements for future trading decisions."""

    user_prompt = f"""Recent trading data:
    {trades_df.to_json(orient='records')}
    
    Current market data:
    {current_market_data}
    
    Overall performance in the last 7 days: {performance:.2f}%
    
    Please analyze this data and provide:
    1. A brief reflection on the recent trading decisions
    2. Insights on what worked well and what didn't
    3. Suggestions for improvement in future trading decisions
    4. Any patterns or trends you notice in the market data
    
    Limit your response to 250 words or less.(Strictly Follow!)"""

    logger.info(f"### AI 피드백 시작 ###")
    # AI 응답 받기
    response = model.generate_content([
        {"role": "user", "parts": [{"text": system_prompt}]}, 
        {"role": "user", "parts": [{"text": user_prompt}]}, 
    ])
    response_json = response.to_dict()
    # JSON 데이터 추출
    result = response_json["candidates"][0]["content"]["parts"][0]["text"]
    logger.info(f"### AI 피드백: {result} ###")
    
    return result

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

def get_fear_and_greed_index():
    url = "https://api.alternative.me/fng/"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data['data'][0]
    else:
        print(f"공포와 탐욕 지수를 가져오는 도중 오류 발생: {response.status_code}")
        return None

def get_bitcoin_news():
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_news",
        "q": "btc",
        "api_key": serpapi_key
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Raises a HTTPError if the status is 4xx, 5xx
        data = response.json()
        
        news_results = data.get("news_results", [])
        headlines = []
        for item in news_results:
            headlines.append({
                "title": item.get("title", ""),
                "date": item.get("date", "")
            })
        
        return headlines[:5]  # 최신 5개의 뉴스 헤드라인만 반환
    except requests.RequestException as e:
        print(f"구글 뉴스를 가져오는 중 오류 발생: {e}")
        return []
    
def get_bitcoin_naver_news():
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
        print(f"네이버 뉴스를 가져오는 중 오류 발생: {news_response.status_code}")
    return news

# # 로컬용
# def setup_chrome_options():
#     chrome_options = Options()
#     chrome_options.add_argument("--start-maximized")
#     chrome_options.add_argument("--headless")  # 디버깅을 위해 헤드리스 모드 비활성화
#     chrome_options.add_argument("--disable-gpu")
#     chrome_options.add_argument("--no-sandbox")
#     chrome_options.add_argument("--disable-dev-shm-usage")
#     chrome_options.add_argument("--enable-unsafe-swiftshader")
#     chrome_options.add_argument("--window-size=1920,3000")
#     chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
#     return chrome_options

# def create_driver():
#     logger.info("ChromeDriver 설정 중...")
#     service = Service(ChromeDriverManager().install())
#     driver = webdriver.Chrome(service=service, options=setup_chrome_options())
#     return driver

# EC2 서버용
def create_driver():
    logger.info("ChromeDriver 설정 중...")
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # 헤드리스 모드 사용
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,3000")

        service = Service('/usr/bin/chromedriver')  # Specify the path to the ChromeDriver executable

        # Initialize the WebDriver with the specified options
        driver = webdriver.Chrome(service=service, options=chrome_options)

        return driver
    except Exception as e:
        logger.error(f"ChromeDriver 생성 중 오류 발생: {e}")
        raise

def scroll_into_view(driver, xpath):
    try:
        # XPath로 요소 찾기
        element = driver.find_element(By.XPATH, xpath)

        # 요소를 화면 중앙으로 스크롤
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(1)  # 스크롤 후 잠시 대기
    except Exception as e:
        logger.error(f"스크롤 중 오류 발생: {e}")

def click_element_by_xpath(driver, xpath, element_name, wait_time=5):
    try:
        # 요소가 보이도록 스크롤
        scroll_into_view(driver, xpath)

        # 요소가 클릭 가능할 때까지 대기 후 클릭
        element = WebDriverWait(driver, wait_time).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        element.click()

        logger.info(f"{element_name} 클릭 완료")
        time.sleep(2)  # 클릭 후 대기
    except TimeoutException:
        logger.error(f"{element_name} 요소를 찾는 데 시간이 초과되었습니다.")
    except ElementClickInterceptedException:
        logger.error(f"{element_name} 요소를 클릭할 수 없습니다. 다른 요소에 가려져 있을 수 있습니다.")
    except Exception as e:
        logger.error(f"{element_name} 클릭 중 오류 발생: {e}")

def perform_chart_actions(driver):
    # 시간 설정
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[1]",
        "시간 메뉴"
    )
    
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[1]/cq-menu-dropdown/cq-item[8]",
        "1시간 옵션"
    )

    # 추세 지표
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[53]",
        "MACD 옵션"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[1]",
        "ADX 옵션"
    )

    # 모멘텀 지표
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[81]",
        "RSI 옵션"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[91]",
        "스토캐스틱 모멘텀 옵션"
    )
    
    # 변동성 지표
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )
    
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[15]",
        "볼린저 밴드 옵션"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )
    
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[2]",
        "ATR 옵션"
    )

    # 거래량 지표
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )
    
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[63]",
        "OBV 옵션"
    )

    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]",
        "지표 메뉴"
    )
    
    click_element_by_xpath(
        driver,
        "/html/body/div[1]/div[2]/div[3]/span/div/div/div[1]/div/div/cq-menu[3]/cq-menu-dropdown/cq-scroll/cq-studies/cq-studies-content/cq-item[104]",
        "VWAP 옵션"
    )

def capture_and_encode_screenshot(driver):
    try:
        # 스크린샷 캡처
        png = driver.get_screenshot_as_png()
        
        # PIL Image로 변환
        img = Image.open(io.BytesIO(png))

        # 현재 시간을 파일명에 포함
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"upbit_chart_{current_time}.png"
        
        # 현재 스크립트의 경로를 가져옴
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 파일 저장 경로 설정
        file_path = os.path.join(script_dir, filename)
        
        # 이미지 파일로 저장
        img.save(file_path)
        logger.info(f"스크린샷이 저장되었습니다: {file_path}")
        
        # 이미지를 바이트로 변환
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        
        # base64로 인코딩
        base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        return base64_image, file_path
    except Exception as e:
        logger.error(f"스크린샷 캡처 및 인코딩 중 오류 발생: {e}")
        return None, None
    
def prepare_image_for_gemini(base64_image_str, image_path):
    try:
        image_bytes = base64.b64decode(base64_image_str)
        os.remove(image_path)

        return {"mime_type": "image/png", "data": image_bytes}
    except Exception as e:
        logger.error(f"이미지 처리 중 오류 발생: {e}")
        return None
    
def get_ai_response_to_json(response):
    response_json = response.to_dict()

    # JSON 데이터 추출
    try:
        text_content = response_json["candidates"][0]["content"]["parts"][0]["text"]
        json_string = text_content.strip("```json\n").strip("```")

        return json.loads(json_string)
    except Exception as e:
        print(f"AI 응답 처리 오류 발생: {e}")
        return {"decision": "hold", "percentage": 0, "reason": "AI response analysis failed - default to hold"}

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# 데이터베이스 초기화
init_db()
google_news_headlines = []

def ai_trading(current_hour):
    global google_news_headlines
    # Upbit 객체 생성
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

    # 4시간 24개 시간봉 데이터
    df_4hourly = pyupbit.get_ohlcv("KRW-BTC", interval="minute240", count=24)
    df_4hourly = dropna(df_4hourly)
    df_4hourly = add_indicators(df_4hourly)
    
    # 24시간 시간봉 데이터
    df_hourly = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=24)
    df_hourly = dropna(df_hourly)
    df_hourly = add_indicators(df_hourly)

    # 4. 공포 탐욕 지수 가져오기
    fear_greed_index = get_fear_and_greed_index()

    # 5. 뉴스 헤드라인 가져오기
    # 8시간 마다 google news 최신화
    # 매 시간 마다 naver news 최신화
    if current_hour % 8 == 0:
        google_news_headlines = get_bitcoin_news()
    naver_news_headlines = get_bitcoin_naver_news()

    # 데이터베이스 연결
    conn = get_db_connection()

    # 최근 거래 내역 가져오기
    recent_trades = get_recent_trades(conn)

    # 현재 시장 데이터 수집 (기존 코드에서 가져온 데이터 사용)
    current_market_data = {
        "fear_greed_index": fear_greed_index,
        "google_news_headlines": google_news_headlines,
        "naver_news_headlines": naver_news_headlines,
        "orderbook": orderbook,
        "daily_ohlcv": df_daily.to_dict(),
        "4_hourly_ohlcv": df_4hourly.to_dict(),
        "hourly_ohlcv": df_hourly.to_dict()
    }

    # 반성 및 개선 내용 생성
    reflection = generate_reflection(recent_trades, current_market_data)

    # Selenium으로 차트 캡처
    driver = None
    try:
        driver = create_driver()
        driver.get("https://upbit.com/full_chart?code=CRIX.UPBIT.KRW-BTC")
        logger.info("페이지 로드 완료")
        time.sleep(30)  # 페이지 로딩 대기 시간 증가
        logger.info("차트 작업 시작")
        perform_chart_actions(driver)
        logger.info("차트 작업 완료")
        chart_image, saved_file_path = capture_and_encode_screenshot(driver)
        logger.info(f"스크린샷 캡처 완료. 저장된 파일 경로: {saved_file_path}")
    except WebDriverException as e:
        logger.error(f"WebDriver 오류 발생: {e}")
        chart_image, saved_file_path = None, None
    except Exception as e:
        logger.error(f"차트 캡처 중 오류 발생: {e}")
        chart_image, saved_file_path = None, None
    finally:
        if driver:
            driver.quit()

    image_part = prepare_image_for_gemini(chart_image, saved_file_path)

    # AI에게 데이터 제공하고 판단 받기
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(f"models/{getmini_model}")

    system_prompt = f"""You are an expert in Bitcoin investing and strictly follow the trading principles of the legendary Korean Bitcoin trader 'Wonyo-ddi.' Analyze the provided chart image, which includes key technical indicators, along with market data, recent news headlines, and the Fear and Greed Index. Based on this analysis, determine whether to buy, sell, or hold at the moment while adhering to Wonyo-ddi's trading philosophy.

    ### Wonyo-ddi's Trading Principles to Follow:
    1. Strictly Chart-Based Trading
    - Ignore fundamental news and external sentiment unless it directly impacts market structure.
    - Rely primarily on price action and market structure for trade decisions.
    - Use simple indicators, mainly candlestick patterns, moving averages, and price trends.
    - Avoid excessive reliance on indicators like RSI, MACD, and Bollinger Bands, except for confirmation.

    2. Market Sentiment & Adaptive Trading
    - Gauge overall market sentiment through price action and volume.
    - Adapt trading strategy based on market conditions:
      - In bullish markets, weak bearish signals can be ignored.
      - In bearish markets, weak bullish signals should not be trusted.
    - Identify liquidity zones where large movements are likely to occur.

    3. Risk Management & Capital Allocation
    - Never invest more than 20-30% of total capital in a single trade.
    - Use low leverage (preferably under 5x, avoid high leverage).
    - Maintain a portion of capital for unexpected market movements and recovery.
    - Use stop-loss only if trade setup is invalidated, rather than mechanical stop-loss levels.

    4. Compounding & Position Management
    - Focus on high win-rate trades over high reward-to-risk setups.
    - Avoid taking large, high-risk positions that rely on one-time gains.
    - Compound gains steadily over time instead of seeking single massive wins.

    5. Practical Chart Application
    - Use daily and 4-hour charts for trend direction.
    - Use hourly charts for precision entries.
    - Avoid noise from very small timeframes (e.g., 1-minute or 5-minute charts).
    - Price action and volume analysis take precedence over lagging indicators.

    ### Decision-Making Factors:
    In your analysis, consider the following factors:  
    - **Chart analysis** (MACD, ADX, RSI, Stochastic, Bollinger Bands, ATR, OBV, VWAP)  
    - **Market data and trends**  
    - **Recent news headlines and their potential impact on Bitcoin price**  
    - **The Fear and Greed Index and its implications**  
    - **Overall market sentiment**  
    - Recent trading performance and reflection

    Ensure that you analyze the trend strength, momentum, volatility, and accumulation behavior using the given indicators.  

    ### Recent trading reflection:
    {reflection}

    ### Response Format:
    1. Decision (buy, sell, or hold)
    2. If the decision is 'buy', provide a percentage (1-100) of available KRW to use for buying. If the decision is 'sell', provide a percentage (1-100) of held BTC to sell. If the decision is 'hold', set the percentage to 0.
    3. Reason for your decision

    Ensure that the percentage is an integer between 1 and 100 for buy/sell decisions, and exactly 0 for hold decisions.
    Your percentage should reflect the strength of your conviction in the decision based on the analyzed data.

    Your response should be in JSON format as follows (Strictly Follow!):  

    {'{"decision": "buy", "percentage": {"type": "integer"}, "reason": "some technical, fundamental, and sentiment-based reason"}'}
    {'{"decision": "sell", "percentage": {"type": "integer"}, "reason": "some technical, fundamental, and sentiment-based reason"}'}
    {'{"decision": "hold", "percentage": {"type": "integer"}, "reason": "some technical, fundamental, and sentiment-based reason"}'}\n\n"""

    # 행동 강령이 포함된 프롬프트
    user_prompt = f"""### Data to provide
    Current investment status: {json.dumps(filtered_balances)}
    Orderbook: {json.dumps(orderbook)}
    Daily OHLCV with indicators (30 days): {df_daily.to_json()}
    4-Hourly OHLCV with indicators (24 counts): {df_4hourly.to_json()}
    Hourly OHLCV with indicators (24 hours): {df_hourly.to_json()}
    Recent news headlines from Google: {json.dumps(google_news_headlines)}
    Recent news headlines from Naver: {json.dumps(naver_news_headlines)}
    Fear and Greed Index: {json.dumps(fear_greed_index)}\n\n"""

    logger.info(f"### AI 매매 결정 시작 ###")
    # AI 응답 받기
    response = model.generate_content([
        {"role": "user", "parts": [{"text": system_prompt}]}, 
        {"role": "user", "parts": [{"text": user_prompt}]}, 
        {"role": "user", "parts": [image_part]} 
    ])

    # AI의 판단에 따라 실제로 자동매매 진행하기
    print(f"### Response : {response}")
    result = get_ai_response_to_json(response)

    logger.info(f"### AI 매매 결정 : {result["decision"].upper()} ###")
    logger.info(f"### 이유 : {result["reason"]} ###")
    logger.info(f"### 퍼센트 : {result["percentage"]} ###")

    order_executed = False

    if result["decision"] == "buy":
        my_krw = upbit.get_balance("KRW")
        buy_amount = my_krw * (result["percentage"] / 100) * 0.9995  # 수수료 고려
        if buy_amount > 5000:
            logger.info(f"### 실행된 매수 주문: 사용 가능한 원화의 {result["percentage"]}% ###")
            order = upbit.buy_market_order("KRW-BTC", buy_amount)
            if order:
                order_executed = True
        else:
            logger.error("### 매수 주문 실패: 원화 부족(5,000원 ​​미만) ###")
    elif result["decision"] == "sell":
        my_btc = upbit.get_balance("KRW-BTC")
        sell_amount = my_btc * (result["percentage"] / 100)
        current_price = pyupbit.get_current_price("KRW-BTC")
        if sell_amount * current_price > 5000:
            logger.info(f"### 실행된 매도 주문: 보유 BTC의 {result["percentage"]}% ###")
            order = upbit.sell_market_order("KRW-BTC", sell_amount)
            if order:
                order_executed = True
        else:
            logger.error("### 매도 주문 실패: BTC 부족(한화 5000원 미만) ###")

    # 거래 실행 여부와 관계없이 현재 잔고 조회
    time.sleep(1)  # API 호출 제한을 고려하여 잠시 대기
    balances = upbit.get_balances()
    btc_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'BTC'), 0)
    krw_balance = next((float(balance['balance']) for balance in balances if balance['currency'] == 'KRW'), 0)
    btc_avg_buy_price = next((float(balance['avg_buy_price']) for balance in balances if balance['currency'] == 'BTC'), 0)
    current_btc_price = pyupbit.get_current_price("KRW-BTC")

    # 거래 정보 로깅
    log_trade(conn, result["decision"], result["percentage"] if order_executed else 0, result["reason"], btc_balance, krw_balance, btc_avg_buy_price, current_btc_price, reflection)

    # 데이터베이스 연결 종료
    conn.close()

# Main loop
while True:
    try:
         # 현재 시간 전달
        ai_trading(datetime.now().hour)

        # 다음 정시 계산
        now = datetime.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        # 대기 시간 계산 (다음 정시 - 현재 시간)
        sleep_time = (next_hour - now).total_seconds()
        logger.info(f"현재 {sleep_time}초 뒤 {next_hour}에 자동으로 매매 기능이 동작합니다.")

        time.sleep(sleep_time)  # 정시까지 대기
    except Exception as e:
        logger.error(f"오류 발생: {e}")
        time.sleep(300)  # 오류 발생 시 5분 후 재시도