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
from datetime import datetime

load_dotenv()
# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

gemini_key = os.getenv('GEMINI_KEY')
getmini_model = os.getenv('GEMINI_MODEL')
upbit_access_key = os.getenv("UPBIT_ACCESS_KEY")
upbit_secret_key = os.getenv("UPBIT_SECRET_KEY")
serpapi_key = os.getenv("SERPAPI_API_KEY")

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
        print(f"Failed to fetch Fear and Greed Index. Status code: {response.status_code}")
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
        print(f"Error fetching news: {e}")
        return []
    

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_chrome_options():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--headless")  # 디버깅을 위해 헤드리스 모드 비활성화
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--enable-unsafe-swiftshader")
    chrome_options.add_argument("--window-size=1920,3000")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    return chrome_options

def create_driver():
    logger.info("ChromeDriver 설정 중...")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=setup_chrome_options())
    return driver

def scroll_into_view(driver, xpath):
    try:
        # XPath로 요소 찾기
        element = driver.find_element(By.XPATH, xpath)

        # 요소를 화면 중앙으로 스크롤
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(1)  # 스크롤 후 잠시 대기
    except Exception as e:
        logger.error(f"스크롤 중 오류 발생: {e}")


def click_element_by_xpath(driver, xpath, element_name, wait_time=10):
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
        
        # 이미지 리사이즈 (OpenAI API 제한에 맞춤)
        img.thumbnail((2000, 2000))
        
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
    
# Base64 문자열을 디코딩하여 Gemini API의 image upload 함수에 맞게 변환
def prepare_image_for_gemini(base64_image_str, image_path):
    try:
        image_bytes = base64.b64decode(base64_image_str)
        os.remove(image_path)

        return {"mime_type": "image/png", "data": image_bytes}
    except Exception as e:
        print(f"⚠️ 이미지 처리 중 오류 발생: {e}")
        return None
    
def ai_trading():
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
    
    # 24시간 시간봉 데이터
    df_hourly = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=24)
    df_hourly = dropna(df_hourly)
    df_hourly = add_indicators(df_hourly)

    # 4. 공포 탐욕 지수 가져오기
    fear_greed_index = get_fear_and_greed_index()

    # 5. 뉴스 헤드라인 가져오기
    # news_headlines = get_bitcoin_news()
    news_headlines = []

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

    system_prompt = """You are an expert in Bitcoin investing. Analyze the provided chart image, which includes key technical indicators, along with market data, recent news headlines, and the Fear and Greed Index. Based on this analysis, determine whether to buy, sell, or hold at the moment.

    In your analysis, consider the following factors:  
    - **Chart analysis** (MACD, ADX, RSI, Stochastic, Bollinger Bands, ATR, OBV, VWAP)  
    - **Market data and trends**  
    - **Recent news headlines and their potential impact on Bitcoin price**  
    - **The Fear and Greed Index and its implications**  
    - **Overall market sentiment**  

    Ensure that you analyze the trend strength, momentum, volatility, and accumulation behavior using the given indicators.  

    ### Response Format  
    Your response should be in JSON format as follows:  

    {"decision": "buy", "reason": "some technical, fundamental, and sentiment-based reason"}  
    {"decision": "sell", "reason": "some technical, fundamental, and sentiment-based reason"}  
    {"decision": "hold", "reason": "some technical, fundamental, and sentiment-based reason"}\n\n"""

    # 행동 강령이 포함된 프롬프트
    user_prompt = f"""Current investment status: {json.dumps(filtered_balances)}
    Orderbook: {json.dumps(orderbook)}
    Daily OHLCV with indicators (30 days): {df_daily.to_json()}
    Hourly OHLCV with indicators (24 hours): {df_hourly.to_json()}
    Recent news headlines from Google: {json.dumps(news_headlines)}
    Fear and Greed Index: {json.dumps(fear_greed_index)}\n\n"""

    # AI 응답 받기
    response = model.generate_content([
        {"role": "user", "parts": [{"text": system_prompt}]}, 
        {"role": "user", "parts": [{"text": user_prompt}]}, 
        {"role": "user", "parts": [image_part]} 
    ])
    response_json = response.to_dict()

    # JSON 데이터 추출
    text_content = response_json["candidates"][0]["content"]["parts"][0]["text"]
    json_string = text_content.strip("```json\n").strip("```")

    # AI의 판단에 따라 실제로 자동매매 진행하기
    result = json.loads(json_string)
    print(result)
    print("### AI Decision: ", result["decision"].upper(), "###")
    print(f"### Reason: {result['reason']} ###")

    # if result["decision"] == "buy":
    #     my_krw = upbit.get_balance("KRW")
    #     if my_krw*0.9995 > 5000:
    #         print("### Buy Order Executed ###")
    #         print(upbit.buy_market_order("KRW-BTC", my_krw * 0.9995))
    #     else:
    #         print("### Buy Order Failed: Insufficient KRW (less than 5000 KRW) ###")
    # elif result["decision"] == "sell":
    #     my_btc = upbit.get_balance("KRW-BTC")
    #     current_price = pyupbit.get_orderbook(ticker="KRW-BTC")['orderbook_units'][0]["ask_price"]
    #     if my_btc*current_price > 5000:
    #         print("### Sell Order Executed ###")
    #         print(upbit.sell_market_order("KRW-BTC", my_btc))
    #     else:
    #         print("### Sell Order Failed: Insufficient BTC (less than 5000 KRW worth) ###")
    # elif result["decision"] == "hold":
    #     print("### Hold Position ###")

# Main loop
# ai_trading()
while True:
    try:
        ai_trading()
        time.sleep(600)  # 10분 간격으로 실행 
    except Exception as e:
        print(f"An error occurred: {e}")
        time.sleep(60)  # 오류 발생 시 1분 후 재시도