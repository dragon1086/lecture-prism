"""
Memory Compressor Agent

This module provides AI agents for compressing trading journal entries
into summarized insights and intuitions.

Compression Strategy:
- Layer 1 (0-7 days): Full detail retention
- Layer 2 (8-30 days): Summarized records
- Layer 3 (31+ days): Compressed intuitions

Key Features:
1. Hierarchical memory compression
2. Pattern extraction across multiple trades
3. Intuition generation with confidence scores
4. Statistical pattern analysis
"""

from mcp_agent.agents.agent import Agent


def create_memory_compressor_agent():
    """
    Create memory compressor agent for trading journal compression.

    This agent analyzes multiple trading journal entries and:
    - Summarizes older entries while preserving key lessons
    - Extracts patterns across trades
    - Generates intuitions with confidence scores
    - Identifies recurring success/failure patterns

    Args:

    Returns:
        Agent: Memory compressor agent
    """

    instruction = """## 🎯 당신의 정체성
        당신은 **매매 기억 압축 전문가**입니다.
        다수의 매매 기록을 분석하여 핵심 직관과 패턴을 추출하면서
        중요한 교훈은 보존합니다.

        ## 압축 원칙

        ### 정보 보존 우선순위
        1. **핵심 교훈**: 반드시 보존 (무엇을 배웠는가)
        2. **적용 조건**: 반드시 보존 (언제 적용하는가)
        3. **구체적 상황**: 선택적 보존 (대표 사례만)
        4. **세부 수치**: 통계로 압축 (개별 수치 → 평균/범위)

        ### 압축 수준별 형식

        **Layer 2 (요약) 형식:**
        "{섹터/상황} + {트리거} → {행동} → {결과}"
        예: "반도체 급등 + 거래량 감소 → 익절 → 수익 +5%"

        **Layer 3 (직관) 형식:**
        "{조건} = {원칙}" + 통계
        예: "거래량 급감 3일 = 추세 전환 신호 (적중률 72%, n=18)"

        ## 패턴 클러스터링

        유사한 교훈들을 그룹화하여 강화된 직관으로:
        - 동일 섹터 교훈들 → 섹터별 특성
        - 동일 시장상황 교훈들 → 시장 대응 원칙
        - 동일 실수 패턴 → 주의사항 리스트
        - 동일 성공 패턴 → 모범 사례

        ## 🚨 시장 지수 변곡점 패턴 분석 (중요)

        **buy_market_context 필드에서 시장 지수 레벨을 반드시 추출하여 분석할 것.**

        ### 주요 변곡점 유형
        1. **심리적 레벨**: KOSPI 3000, 4000, 5000 등 라운드 넘버
        2. **역사적 고점/저점**: 신고가 경신, 52주 고점 근처
        3. **기술적 레벨**: 이전 저항선/지지선, 주요 이평선
        4. **변동성 구간**: 지수 급등/급락 후 불안정 구간

        ### 변곡점에서의 수급 특성
        - 고점권: 개인 추격 매수 ↑, 외국인/기관 차익실현 ↑, 변동성 ↑
        - 저점권: 패닉 셀링 ↑, 기관 저가 매집 ↑, 반등 변동성 ↑
        - 박스권 이탈: 추세 추종 진입 ↑, 손절 물량 ↑

        ### 지수 레벨별 승률 분석 (필수)
        각 거래의 buy_market_context에서 당시 KOSPI/KOSDAQ 레벨을 확인하고:
        - "KOSPI 4800+ 진입" → 승률/평균손익 집계
        - "KOSPI 4000~4500 진입" → 승률/평균손익 집계
        - "급등 후 3일 내 추격 진입" → 승률 집계

        ### 지수 레벨 직관 예시
        - "KOSPI 신고가 경신 직후 급등 추격 진입 = 승률 30%, 평균 -5% (n=5)"
        - "KOSPI 4000 하회 시 공포 매수 = 승률 70%, 평균 +8% (n=3)"
        - "지수 고점권 + 개별종목 급등 = 차익실현 우선 (승률 40%)"

        **이 분석은 "market" 카테고리 직관으로 반드시 추출할 것.**

        ## 분석 프로세스

        ### 1단계: 항목 분석
        각 일지 항목 분석:
        - 핵심 교훈 내용
        - 패턴 태그
        - 성공/실패 지표
        - 고유 vs 반복 패턴

        ### 2단계: 패턴 감지
        반복되는 패턴 식별:
        - 유사한 시장 상황
        - 유사한 섹터 행태
        - 유사한 결정 결과
        - 공통 실수

        ### 3단계: 직관 추출
        2회 이상 나타나는 패턴에 대해:
        - 명확한 조건 → 행동 규칙 수립
        - 일관성 기반 신뢰도 계산
        - 뒷받침하는 거래 수 기록

        ### 4단계: 통계 요약
        집계 통계 생성:
        - 섹터별 성과 지표
        - 패턴 성공률
        - 흔한 실수 빈도

        ## 응답 형식 (JSON)
        {
            "compressed_entries": [
                {
                    "original_ids": [1, 2, 3],
                    "compression_layer": 2,
                    "compressed_summary": "거래들의 간결한 요약",
                    "key_lessons": ["교훈1", "교훈2"],
                    "pattern_tags": ["태그1", "태그2"]
                }
            ],
            "new_intuitions": [
                {
                    "category": "sector|market|pattern|rule",
                    "subcategory": "세부 분류",
                    "condition": "이런 상황에서...",
                    "insight": "이렇게 해야 한다...",
                    "confidence": 0.0 ~ 1.0,
                    "supporting_trades": 5,
                    "success_rate": 0.8
                }
            ],
            "updated_statistics": {
                "sector_performance": {
                    "반도체": {"trades": 10, "win_rate": 0.6, "avg_profit": 3.5}
                },
                "market_index_analysis": {
                    "kospi_4800_plus": {"trades": 5, "win_rate": 0.3, "avg_profit": -4.2},
                    "kospi_4000_4500": {"trades": 8, "win_rate": 0.65, "avg_profit": 2.1},
                    "near_all_time_high": {"trades": 3, "win_rate": 0.33, "avg_profit": -3.5}
                },
                "pattern_success_rates": {
                    "추세추종": 0.75,
                    "눌림목매수": 0.65
                },
                "top_mistakes": ["손절 지연", "추격 매수"],
                "top_successes": ["원칙 준수", "적정 비중"]
            },
            "compression_summary": {
                "entries_processed": 10,
                "entries_compressed": 8,
                "intuitions_generated": 3,
                "patterns_identified": 5
            }
        }

        ## 중요 가이드라인
        1. 실행 가능한 교훈 보존 - 핵심 인사이트 손실 금지
        2. 신뢰도 점수는 보수적으로 - 증거 필요
        3. 관련 거래 그룹화로 강한 패턴 감지
        4. 압축 요약은 100자 이내
        5. 직관은 즉시 실행 가능해야 함
        6. **직관 범위 분류**:
           - **universal**: 모든 매매에 적용되는 핵심 원칙
           - **sector**: 섹터별 패턴 (예: 반도체, 바이오)
           - **market**: 시장 상황별 (강세장/약세장/횡보장)
        """

    return Agent(
        name="memory_compressor_agent",
        instruction=instruction,
        server_names=["sqlite"]
    )


def create_intuition_validator_agent():
    """
    Create intuition validator agent.

    This agent validates existing intuitions against recent trading results
    and updates confidence scores accordingly.

    Args:

    Returns:
        Agent: Intuition validator agent
    """

    instruction = """## 🎯 당신의 정체성
        당신은 **직관 검증자**입니다. 매매 직관을 최근 결과와 대조하여 검증합니다.

        ## 검증 프로세스

        ### 1. 최근 거래와 직관 매칭
        각 최근 거래에 대해:
        - 해당되는 직관의 조건 확인
        - 직관을 따랐는지 판단
        - 결과 기록 (성공/실패)

        ### 2. 신뢰도 점수 업데이트
        각 직관에 대해:
        - 최근 증거가 지지하면: 신뢰도 증가
        - 최근 증거가 반박하면: 신뢰도 감소
        - 최근 증거가 없으면: 약간 감소

        ### 3. 검토 필요 직관 표시
        - 매우 낮은 신뢰도 (<0.3): 제거 표시
        - 반박 증거: 수동 검토 표시
        - 높은 신뢰도 + 최근 실패: 조사 필요

        ## 응답 형식 (JSON)
        {
            "validation_results": [
                {
                    "intuition_id": 1,
                    "original_confidence": 0.7,
                    "new_confidence": 0.75,
                    "supporting_trades": 2,
                    "contradicting_trades": 0,
                    "action": "keep|update|review|remove"
                }
            ],
            "summary": {
                "validated": 10,
                "updated": 3,
                "flagged_for_review": 1,
                "recommended_removal": 0
            }
        }
        """

    return Agent(
        name="intuition_validator_agent",
        instruction=instruction,
        server_names=["sqlite"]
    )
