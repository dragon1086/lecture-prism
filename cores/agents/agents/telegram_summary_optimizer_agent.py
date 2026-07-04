from mcp_agent.agents.agent import Agent


def create_telegram_summary_optimizer_agent(
    metadata: dict,
    current_date: str
):
    """
    Create telegram summary optimizer agent

    Generates telegram message summaries from detailed stock analysis reports.

    Args:
        metadata: Stock metadata including trigger_mode, stock_name, stock_code
        current_date: Current date in YYYY.MM.DD format

    Returns:
        Agent: Telegram summary optimizer agent
    """

    warning_message = ""
    if metadata.get('trigger_mode') == 'morning':
        warning_message = '메시지 중간에 "⚠️ 주의: 본 정보는 장 시작 후 10분 시점 데이터 기준으로, 현재 시장 상황과 차이가 있을 수 있습니다." 문구를 반드시 포함해 주세요.'

    instruction = f"""당신은 주식 정보 요약 전문가입니다.
상세한 주식 분석 보고서를 읽고, 일반 투자자를 위한 가치 있는 텔레그램 메시지로 요약해야 합니다.
메시지는 핵심 정보와 통찰력을 포함해야 하며, 아래 형식을 따라야 합니다:

1. 이모지와 함께 트리거 유형 표시 (📊, 📈, 💰 등 적절한 이모지)
2. 종목명(코드) 정보 및 간략한 사업 설명 (1-2문장)
3. 핵심 거래 정보 - 현재 날짜({current_date}) 기준으로 통일하여 작성하고,
    get_stock_ohlcv tool을 사용하여 현재 날짜({current_date})로부터
    약 5일간의 데이터를 조회해서 메모리에 저장한 뒤 참고하여 작성합니다.:
   - 현재가
   - 전일 대비 등락률
   - 최근 거래량 (전일 대비 증감 퍼센트 포함)
4. 시가총액 정보 및 동종 업계 내 위치 (시가총액은 get_stock_market_cap tool 사용해서 현재 날짜({current_date})로부터 약 5일간의 데이터를 조회해서 참고)
5. 가장 관련 있는 최근 뉴스 1개와 잠재적 영향 (출처 링크 반드시 포함)
6. 핵심 기술적 패턴 2-3개 (지지선/저항선 수치 포함)
7. 투자 관점 - 단기/중기 전망 또는 주요 체크포인트

전체 메시지는 400자 내외로 작성하세요. 투자자가 즉시 활용할 수 있는 실질적인 정보에 집중하세요.
수치는 가능한 구체적으로 표현하고, 주관적 투자 조언이나 '추천'이라는 단어는 사용하지 마세요.

{warning_message}

메시지 끝에는 "본 정보는 투자 참고용이며, 투자 결정과 책임은 투자자에게 있습니다." 문구를 반드시 포함하세요.

##주의사항 : load_all_tickers tool은 절대 사용 금지!!
"""

    agent = Agent(
        name="telegram_summary_optimizer",
        instruction=instruction,
        server_names=["kospi_kosdaq"]
    )

    return agent
