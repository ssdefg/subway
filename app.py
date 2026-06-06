# -*- coding: utf-8 -*-
"""
빠른 이동 속도는 부유한 자들의 특권인가?
광교 → 강남 통근 비용 분석 대시보드 (Streamlit + SQLite + Plotly)
"""

import os
import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

# ----------------------------------------------------------------------
# 0. 기본 설정
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="빠른 이동 속도는 부유한 자들의 특권인가?",
    page_icon="🚇",
    layout="wide",
)

# app.py 가 있는 폴더를 기준 경로로 사용 (어디서 실행하든 경로가 깨지지 않도록)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "commute.db")

# CSV 파일명 → SQLite 테이블명 매핑
CSV_TABLE_MAP = {
    "gangnam_rent.csv": "gangnam_rent",
    "yeongtong_rent.csv": "yeongtong_rent",
    "shinbundang_fare.csv": "shinbundang_fare",
    "standard_fare.csv": "standard_fare",
    "time_budget.csv": "time_budget",
}

# 한글 폰트 깨짐 방지: Plotly 차트에 한글 지원 폰트를 기본값으로 지정
KOR_FONT = "Malgun Gothic, AppleGothic, NanumGothic, Nanum Gothic, Noto Sans KR, sans-serif"
pio.templates["kor"] = go.layout.Template(layout=dict(font=dict(family=KOR_FONT, size=14)))
pio.templates.default = "plotly_white+kor"


# ----------------------------------------------------------------------
# 1. 가드레일: 데이터 파일 존재 여부 확인
# ----------------------------------------------------------------------
def check_files():
    """필요한 CSV 가 모두 있는지 확인. 없으면 어떤 파일이 어디에 없는지 출력하고 중단."""
    missing = [
        fname for fname in CSV_TABLE_MAP
        if not os.path.exists(os.path.join(BASE_DIR, fname))
    ]
    if missing:
        st.error("❌ 실행에 필요한 데이터 파일을 찾을 수 없습니다.")
        st.write("아래 파일들을 **app.py 와 같은 폴더**에 넣어주세요:")
        for fname in missing:
            st.code(os.path.join(BASE_DIR, fname), language="bash")
        st.info("현재 app.py 폴더: " + BASE_DIR)
        st.stop()  # 여기서 실행 중단


# ----------------------------------------------------------------------
# 2. 데이터 적재: 인코딩 혼재(cp949 / utf-8-sig)에 견고하게 대응
# ----------------------------------------------------------------------
def read_csv_robust(path):
    """여러 인코딩을 순차적으로 시도하여 CSV 를 안전하게 읽는다."""
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    # 모든 인코딩 실패 시: 깨진 문자를 대체해서라도 읽어 실행이 멈추지 않게 함
    return pd.read_csv(path, encoding="cp949", encoding_errors="replace")


@st.cache_resource(show_spinner="데이터베이스를 준비하는 중...")
def get_connection():
    """CSV 를 SQLite(commute.db)로 적재하고 연결 객체를 반환. (캐시되어 1회만 실행)"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    for fname, table in CSV_TABLE_MAP.items():
        df = read_csv_robust(os.path.join(BASE_DIR, fname))
        # 헤더 앞뒤 공백 제거 (CSV 헤더에 숨은 공백이 있으면 SQL 컬럼명과 어긋남)
        df.columns = [str(c).strip() for c in df.columns]
        df.to_sql(table, conn, if_exists="replace", index=False)
    return conn


@st.cache_data(show_spinner=False)
def run_query(sql):
    """SQL 을 실행해 DataFrame 으로 반환. (동일 쿼리는 캐시 재사용)"""
    conn = get_connection()
    return pd.read_sql_query(sql, conn)


# ----------------------------------------------------------------------
# 3. SQL 쿼리 (요구사항: 원문 그대로 삽입)
# ----------------------------------------------------------------------
Q_JEONSE = """
SELECT '강남구' as 지역, COUNT(*) as 거래건수, 
       ROUND(AVG("보증금(만원)"), 1) as "평균 전세금 (만원)",
       ROUND(AVG("보증금(만원)") / 10000.0, 1) as "평균 전세금 (억원)"
FROM gangnam_rent
WHERE "전월세구분" = '전세' AND "전용면적(㎡)" <= 60

UNION ALL

SELECT '수원시 영통구' as 지역, COUNT(*) as 거래건수, 
       ROUND(AVG("보증금(만원)"), 1) as "평균 전세금 (만원)",
       ROUND(AVG("보증금(만원)") / 10000.0, 1) as "평균 전세금 (억원)"
FROM yeongtong_rent
WHERE "전월세구분" = '전세' AND "전용면적(㎡)" <= 60;
"""

Q_WOLSE = """
SELECT '강남구' as 지역, COUNT(*) as 거래건수, 
       ROUND(AVG("보증금(만원)"), 1) as "평균 월세보증금 (만원)",
       ROUND(AVG("월세금(만원)"), 1) as "평균 월세 (만원)"
FROM gangnam_rent
WHERE "전월세구분" = '월세' AND "전용면적(㎡)" <= 60

UNION ALL

SELECT '수원시 영통구' as 지역, COUNT(*) as 거래건수, 
       ROUND(AVG("보증금(만원)"), 1) as "평균 월세보증금 (만원)",
       ROUND(AVG("월세금(만원)"), 1) as "평균 월세 (만원)"
FROM yeongtong_rent
WHERE "전월세구분" = '월세' AND "전용면적(㎡)" <= 60;
"""

Q_FARE = """
SELECT s."하차역 (광교역 승차 기준)" as 목적지_역, 
       s."신분당선 실제 요금 (원)" as 신분당선_요금, 
       st."수도권 표준요금 (원)" as 표준_요금,
       (s."신분당선 실제 요금 (원)" - st."수도권 표준요금 (원)") as "편도 운임 격차 (원)",
       s."월간 교통비 (원_20일 기준)" as 신분당선_월교통비,
       st."월간 교통비 (원_20일 기준)" as 표준_월교통비,
       (s."월간 교통비 (원_20일 기준)" - st."월간 교통비 (원_20일 기준)") as "월 누적 추가부담액 (원)"
FROM shinbundang_fare s
JOIN standard_fare st ON s."하차역 (광교역 승차 기준)" = st."하차역 (광교역 승차 기준)"
WHERE s."하차역 (광교역 승차 기준)" IN ('판교', '강남', '신사')
ORDER BY s."신분당선 실제 요금 (원)" ASC;
"""

Q_FATIGUE_SAT = """
SELECT "피곤함정도코드" as 피로도_수준, -- (예: 1에 가까울수록 매우 피곤함 등 조사 설계 기준 따름)
       COUNT(*) as 응답자수,
       ROUND(AVG("(주행동시간량_921) 출근" + "(주행동시간량_922) 퇴근"), 1) as "일평균 왕복통근시간 (분)", 
       ROUND(AVG("삶만족도코드"), 2) as "평균 삶의 만족도"
FROM time_budget
GROUP BY "피곤함정도코드"
ORDER BY "피곤함정도코드" ASC;
"""

Q_INCOME_ALL = """
SELECT "가구총소득구간코드" as 소득_구간,
       COUNT(*) as 응답자수,
       ROUND(AVG("(주행동시간량_921) 출근" + "(주행동시간량_922) 퇴근"), 1) as "일평균 왕복통근시간 (분)",
       ROUND(AVG("피곤함정도코드"), 2) as "평균 피로도"
FROM time_budget
WHERE "가구총소득구간코드" IS NOT NULL
GROUP BY "가구총소득구간코드"
ORDER BY "가구총소득구간코드" ASC;
"""

Q_INCOME_GG = """
SELECT "가구총소득구간코드" as 소득_구간,
       COUNT(*) as 응답자수,
       ROUND(AVG("(주행동시간량_921) 출근" + "(주행동시간량_922) 퇴근"), 1) as "일평균 왕복통근시간 (분)",
       ROUND(AVG("피곤함정도코드"), 2) as "평균 피로도"
FROM time_budget
WHERE "행정구역시도코드" = 31 
  AND ("(주행동시간량_921) 출근" + "(주행동시간량_922) 퇴근") > 0
GROUP BY "가구총소득구간코드"
ORDER BY "가구총소득구간코드" ASC;
"""

Q_FINAL = """
SELECT 
    ROUND(g_rent.avg_rent - y_rent.avg_rent, 0) as "① 월 주거비 절감액 (원)",
    
    (s."월간 교통비 (원_20일 기준)" - st."월간 교통비 (원_20일 기준)") as "② 신분당선 추가운임 (원)",
    
  
    ROUND((94.5 / 60.0) * 10320 * 20, 0) as "③ 통근 시간량 기회비용 (원)",
    
   
    ROUND(
        (g_rent.avg_rent - y_rent.avg_rent) - 
        (s."월간 교통비 (원_20일 기준)" - st."월간 교통비 (원_20일 기준)") - 
        ((94.5 / 60.0) * 10320 * 20), 0
    ) as "④ 최종 실질 이득 (원)"

FROM 
    (SELECT AVG("월세금(만원)") * 10000 as avg_rent FROM gangnam_rent WHERE "전월세구분" = '월세' AND "전용면적(㎡)" <= 60) g_rent,
    
    (SELECT AVG("월세금(만원)") * 10000 as avg_rent FROM yeongtong_rent WHERE "전월세구분" = '월세' AND "전용면적(㎡)" <= 60) y_rent,
    
    shinbundang_fare s
JOIN standard_fare st ON s."하차역 (광교역 승차 기준)" = st."하차역 (광교역 승차 기준)"
WHERE s."하차역 (광교역 승차 기준)" = '강남';
"""


# ----------------------------------------------------------------------
# 4. 섹션별 렌더링 함수
# ----------------------------------------------------------------------
def section_intro():
    st.title("🚇 빠른 이동 속도는 부유한 자들의 특권인가?")
    st.subheader("광교(수원 영통) → 강남 통근의 숨은 비용 해부")
    st.markdown(
        "강남에 살면 비싸지만 출근이 빠르다. 수원 영통에 살면 집값은 싸지만 매일 신분당선 "
        "프리미엄 요금과 긴 통근 시간을 감수해야 한다. "
        "이 대시보드는 **주거비 · 교통비 · 시간 기회비용**을 한 화면에서 비교해 "
        "'시간을 사는 일'이 결국 누구의 특권인지 따져본다."
    )
    st.info("핵심 질문: 거리를 돈으로, 돈을 시간으로 바꾸는 거래에서 — 멀리 사는 사람은 정말 이득을 보는가?")
    c1, c2, c3 = st.columns(3)
    c1.metric("분석 지역", "강남구 vs 영통구")
    c2.metric("분석 노선", "신분당선 (광교 기점)")
    c3.metric("시간가치 기준", "최저시급 10,320원")
    st.caption("좌측 사이드바에서 6개 섹션을 이동하세요.")


def section_jeonse():
    st.header("① 전세 보증금 격차")
    df = run_query(Q_JEONSE)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 고정 메시지 → 고정 막대 차트 + metric
    fig = px.bar(
        df, x="지역", y="평균 전세금 (만원)", color="지역",
        text="평균 전세금 (만원)", title="전용 60㎡ 이하 평균 전세 보증금",
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    try:
        g = df.loc[df["지역"] == "강남구", "평균 전세금 (만원)"].iloc[0]
        y = df.loc[df["지역"] == "수원시 영통구", "평균 전세금 (만원)"].iloc[0]
        gap = g - y
        st.metric("강남 - 영통 전세금 격차", f"{gap:,.0f} 만원",
                  delta=f"강남이 {g / y:.1f}배" if y else None)
    except (IndexError, ZeroDivisionError):
        st.warning("격차 계산에 필요한 데이터가 부족합니다.")


def section_wolse():
    st.header("② 월세 부담 & 가처분 소득 잠식")
    df = run_query(Q_WOLSE)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 보증금 / 월세를 나란히 비교하는 고정 차트
    melt = df.melt(
        id_vars="지역",
        value_vars=["평균 월세보증금 (만원)", "평균 월세 (만원)"],
        var_name="항목", value_name="금액(만원)",
    )
    fig = px.bar(
        melt, x="항목", y="금액(만원)", color="지역", barmode="group",
        text="금액(만원)", title="전용 60㎡ 이하 평균 월세 조건 비교",
    )
    fig.update_traces(texttemplate="%{text:,.1f}", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    try:
        g = df.loc[df["지역"] == "강남구", "평균 월세 (만원)"].iloc[0]
        y = df.loc[df["지역"] == "수원시 영통구", "평균 월세 (만원)"].iloc[0]
        st.metric("월세(임대료) 격차", f"{g - y:,.1f} 만원/월",
                  help="강남 월세 - 영통 월세. 양수일수록 영통 거주 시 매달 절약되는 금액.")
    except IndexError:
        st.warning("월세 격차 계산에 필요한 데이터가 부족합니다.")
    st.info("월세는 가처분 소득에서 매달 빠져나가는 고정 비용이다. 보증금 부담까지 더하면 "
            "'싼 동네'의 의미가 단순 임대료 비교만으로는 드러나지 않는다.")


def section_fare():
    st.header("③ 신분당선 운임 격차 & 소득 잠식")
    df = run_query(Q_FARE)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 편도 요금 비교 (고정 차트)
    melt = df.melt(
        id_vars="목적지_역",
        value_vars=["신분당선_요금", "표준_요금"],
        var_name="요금유형", value_name="편도요금(원)",
    )
    fig = px.bar(
        melt, x="목적지_역", y="편도요금(원)", color="요금유형", barmode="group",
        text="편도요금(원)", title="광교 기점 편도 요금: 신분당선 실제 vs 수도권 표준",
    )
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    # 인사이트 탐색 → 동적 슬라이더: 통근 일수에 따른 월 추가부담액 재계산
    st.subheader("월 통근일수에 따른 추가 운임 부담 (탐색)")
    days = st.slider("한 달 통근일수", min_value=10, max_value=26, value=20, step=1)
    explore = df[["목적지_역", "편도 운임 격차 (원)"]].copy()
    # 왕복 2회 × 일수 기준으로 환산
    explore["월 추가부담액(원)"] = explore["편도 운임 격차 (원)"] * 2 * days
    fig2 = px.bar(
        explore, x="목적지_역", y="월 추가부담액(원)", color="목적지_역",
        text="월 추가부담액(원)",
        title=f"신분당선 프리미엄으로 인한 월 추가 교통비 ({days}일 · 왕복 기준)",
    )
    fig2.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("※ 슬라이더는 편도 운임 격차에 왕복(×2)과 통근일수를 곱해 즉석 추산한 값입니다.")


def section_time_fatigue():
    st.header("④ 통근 시간 · 피로도 · 삶의 만족도")

    # (A) 피로도 수준별 통근시간 / 만족도 — 고정 메시지
    st.subheader("피로도 수준별 통근시간과 삶의 만족도")
    df1 = run_query(Q_FATIGUE_SAT)
    st.dataframe(df1, use_container_width=True, hide_index=True)
    fig1 = px.line(
        df1, x="피로도_수준", y=["일평균 왕복통근시간 (분)", "평균 삶의 만족도"],
        markers=True, title="피로도 수준에 따른 통근시간 · 만족도 추이",
    )
    st.plotly_chart(fig1, use_container_width=True)
    st.info("피곤함정도코드의 방향성(1에 가까울수록 매우 피곤함 등)은 원 조사 설계 기준을 따른다. "
            "통근시간이 길수록 피로 응답과 만족도가 어떻게 움직이는지 확인하라.")

    st.divider()

    # (B) 소득구간별 분석 — 인사이트 탐색 → 동적 토글(전체 vs 경기도 근로자)
    st.subheader("소득 구간별 통근시간 & 피로도")
    only_gg = st.toggle("경기도 거주 실제 근로자만 보기 (행정구역시도코드 = 31)", value=False)
    df2 = run_query(Q_INCOME_GG if only_gg else Q_INCOME_ALL)
    st.dataframe(df2, use_container_width=True, hide_index=True)
    fig2 = px.bar(
        df2, x="소득_구간", y="일평균 왕복통근시간 (분)",
        color="평균 피로도", color_continuous_scale="Reds",
        title=("경기도 근로자: " if only_gg else "전체: ")
              + "소득 구간별 통근시간 (색=평균 피로도)",
    )
    st.plotly_chart(fig2, use_container_width=True)


def section_time_poverty():
    st.header("⑤ 시간빈곤 & 최종 실질 이득")
    df = run_query(Q_FINAL)
    st.dataframe(df, use_container_width=True, hide_index=True)

    row = df.iloc[0]
    save = float(row["① 월 주거비 절감액 (원)"])
    fare = float(row["② 신분당선 추가운임 (원)"])
    time_cost = float(row["③ 통근 시간량 기회비용 (원)"])
    net = float(row["④ 최종 실질 이득 (원)"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("① 주거비 절감", f"{save:,.0f} 원")
    c2.metric("② 추가 운임", f"-{fare:,.0f} 원")
    c3.metric("③ 시간 기회비용", f"-{time_cost:,.0f} 원")
    c4.metric("④ 최종 실질 이득", f"{net:,.0f} 원", delta="이득" if net > 0 else "손해")

    # 고정 메시지 → 워터폴 차트
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["relative", "relative", "relative", "total"],
        x=["주거비 절감(+)", "추가 운임(-)", "시간 기회비용(-)", "최종 실질이득"],
        y=[save, -fare, -time_cost, net],
        text=[f"{save:,.0f}", f"-{fare:,.0f}", f"-{time_cost:,.0f}", f"{net:,.0f}"],
        textposition="outside",
        connector={"line": {"color": "rgb(120,120,120)"}},
    ))
    fig.update_layout(title="멀리 사는 선택의 실질 손익 분해 (월 기준, 원)")
    st.plotly_chart(fig, use_container_width=True)

    if net > 0:
        st.success(f"계산상 멀리 거주하는 쪽이 월 {net:,.0f}원 이득. 단, 시간 가치를 최저시급으로만 환산한 보수적 추정이다.")
    else:
        st.error(f"시간 기회비용까지 더하면 월 {-net:,.0f}원 손해. '싼 집'이 실제로는 비싼 거래일 수 있다.")

    # 인사이트 탐색 → 동적 슬라이더: 시간 가치 가정을 바꿔 재계산
    st.subheader("가정 바꿔보기: 내 시간은 얼마짜리인가?")
    col_a, col_b, col_c = st.columns(3)
    wage = col_a.slider("시급 (원)", 9000, 50000, 10320, step=500)
    minutes = col_b.slider("일 왕복 통근시간 (분)", 30, 180, 95, step=5)
    workdays = col_c.slider("월 통근일수", 10, 26, 20, step=1)

    new_time_cost = (minutes / 60.0) * wage * workdays
    new_net = save - fare - new_time_cost
    st.metric("재계산된 ③ 시간 기회비용", f"{new_time_cost:,.0f} 원")
    st.metric("재계산된 ④ 최종 실질 이득", f"{new_net:,.0f} 원",
              delta="이득" if new_net > 0 else "손해")
    st.caption("시급을 높일수록(=시간의 가치가 큰 고소득자일수록) 멀리 사는 거래의 이득은 빠르게 사라진다. "
               "이것이 '속도는 부유한 자의 특권'이라는 명제의 정량적 근거다.")


# ----------------------------------------------------------------------
# 5. 사이드바 네비게이션 & 라우팅
# ----------------------------------------------------------------------
SECTIONS = {
    "문제의식": section_intro,
    "전세 보증금 격차": section_jeonse,
    "월세 부담 분석": section_wolse,
    "신분당선 운임 격차": section_fare,
    "통근시간 · 피로도": section_time_fatigue,
    "시간빈곤 (최종 손익)": section_time_poverty,
}


def main():
    check_files()          # 1. 파일 가드레일
    get_connection()       # 2. DB 적재 (캐시되어 최초 1회만)

    st.sidebar.title("📊 섹션 이동")
    choice = st.sidebar.radio("이동할 섹션을 선택하세요", list(SECTIONS.keys()))
    st.sidebar.divider()
    st.sidebar.caption("데이터: 실거래가(전월세) · 신분당선/표준 운임 · 생활시간조사")

    SECTIONS[choice]()     # 선택된 섹션 렌더링


if __name__ == "__main__":
    main()
