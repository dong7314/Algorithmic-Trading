import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px

st.set_page_config(
    page_title="LDY 비트코인 거래 내역", 
    page_icon="🪙", 
)

# 데이터베이스 연결 함수
def get_connection():
    return sqlite3.connect('bitcoin_trades.db')

# 데이터 로드 함수
def load_data():
    conn = get_connection()
    query = "SELECT * FROM trades"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# 날짜 형식 변환 함수
def format_datetime(dt):
    return pd.to_datetime(dt).strftime("%Y년 %m월 %d일 %H시 %M분 %S초")

# 숫자 단위 변환 함수
def format_currency(value):
    return f"{value:.0f}"

# 비트코인 소수점 포맷 함수
def format_btc(value):
    return f"{value:.8f}"

# 메인 함수
def main():
    st.title('LDY Studio 비트코인 거래 내역 뷰어')

    # 데이터 로드
    df = load_data()

    # 기본 통계
    st.header('기본 통계')
    st.write(f"총 거래 횟수: {len(df)}")
    st.write(f"첫 거래 날짜: {format_datetime(df['timestamp'].min())}")
    st.write(f"마지막 거래 날짜: {format_datetime(df['timestamp'].max())}")

    # 거래 내역 표시
    st.header('거래 내역')
    df['btc_balance'] = df['btc_balance'].apply(format_btc)
    df['krw_balance'] = df['krw_balance'].apply(format_currency)
    st.dataframe(df)

    # 거래 결정 분포
    st.header('거래 결정 분포')
    decision_counts = df['decision'].value_counts()
    fig = px.pie(values=decision_counts.values, names=decision_counts.index, title='거래 결정 비율')
    st.plotly_chart(fig)

    # BTC 잔액 변화
    st.header('BTC 잔액 변화')
    fig = px.line(df, x='timestamp', y='btc_balance', title='BTC 잔액 변화')
    st.plotly_chart(fig)

    # KRW 잔액 변화
    st.header('KRW 잔액 변화')
    fig = px.line(df, x='timestamp', y='krw_balance', title='KRW 잔액 변화')
    st.plotly_chart(fig)

    # BTC 가격 변화
    st.header('BTC 가격 변화')
    fig = px.line(df, x='timestamp', y='btc_krw_price', title='BTC 가격 (KRW)')
    st.plotly_chart(fig)

if __name__ == "__main__":
    main()
