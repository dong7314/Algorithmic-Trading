import os
import pandas as pd
import streamlit as st
import plotly.express as px
import mysql.connector
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

st.set_page_config(
    page_title="LDY 비트코인 거래 내역", 
    page_icon="🪙", 
)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('MYSQL_HOST'),
        port=os.getenv('MYSQL_PORT'),
        user=os.getenv('MYSQL_USER'),
        password=os.getenv('MYSQL_PASSWORD'),
        database=os.getenv('MYSQL_DB')
    )

# 데이터 로드 
def load_data():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY timestamp DESC")
    columns = [column[0] for column in c.description]  # 컬럼명 가져오기
    rows = c.fetchall()  # 실제 데이터 가져오기
    df = pd.DataFrame(rows, columns=columns)  # 데이터프레임 생성

    return df 

# 날짜 형식 변환 함수
def format_datetime(dt):
    return pd.to_datetime(dt).strftime("%Y년 %m월 %d일 %H시 %M분 %S초")

# 메인 함수
def main():
    st.title('LDY Studio 비트코인 거래 내역 뷰어')
    st.write("")
    
    # 데이터 로드
    df = load_data()

    # 기본 통계
    st.header('📈 기본 통계')
    st.write(f"총 거래 횟수: **{len(df)}**")
    st.write(f"첫 거래 날짜: **{format_datetime(df['timestamp'].min())}**")
    st.write(f"마지막 거래 날짜: **{format_datetime(df['timestamp'].max())}**")
    st.write("")  
    st.write("")  
    
    # 가장 최근 거래 내역
    st.header('📌 가장 최근 거래 내역')
    latest_trade = df.iloc[0]  
    decision_color = "#008000" if latest_trade['decision'] == 'buy' else "#FF0000" if latest_trade['decision'] == 'sell' else "#808080"
    custom_style = f"""
    <style>
        .custom-box {{
            padding: 24px 28px;
            border-radius: 10px;
            box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
        }}
    </style>"""

    st.markdown(custom_style, unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="custom-box">
            <h3>🕒 거래 시간: {format_datetime(latest_trade['timestamp'])}</h3>
            <h4 style="color: {decision_color};">📌 거래 결정: {latest_trade['decision'].upper()}</h4>
            <p>🔍 <b>결정 이유:</b> {latest_trade['reason']}</p>
            <p>📊 <b>거래 비율:</b> {latest_trade['percentage']}%</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")  
    st.write("") 
    st.write("") 

    # 거래 내역 표시
    st.header('📜 전체 거래 내역')
    st.dataframe(df)
    st.write("")
    st.write("")

    # 거래 결정 분포 (Pie Chart)
    st.header('📊 거래 결정 분포')
    decision_counts = df['decision'].value_counts()
    fig = px.pie(values=decision_counts.values, names=decision_counts.index, title='거래 결정 비율')
    st.plotly_chart(fig)
    st.write("")

    # BTC 잔액 변화 (Line Chart)
    st.header('📉 BTC 잔액 변화')
    fig = px.line(df, x='timestamp', y='btc_balance', title='📈 BTC 잔액 변화')
    st.plotly_chart(fig)
    st.write("")

    # KRW 잔액 변화 (Line Chart)
    st.header('💰 KRW 잔액 변화')
    fig = px.line(df, x='timestamp', y='krw_balance', title='💴 KRW 잔액 변화')
    st.plotly_chart(fig)
    st.write("")

    # BTC 가격 변화 (Line Chart)
    st.header('📢 BTC 가격 변화')
    fig = px.line(df, x='timestamp', y='btc_krw_price', title='🏷️ BTC 가격 (KRW)')
    st.plotly_chart(fig)
    st.write("")

# Streamlit 실행
if __name__ == "__main__":
    main()