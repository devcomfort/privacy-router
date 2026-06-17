"""Multi-turn test conversations: Samsung Semiconductor senior researcher persona.

Tests the Privacy Router's ability to detect business secrets and competitive
information across conversational context. Each conversation simulates a real
researcher consulting an AI about technical problems while inadvertently
(or deliberately) disclosing sensitive internal data.

Policy actions (from agents/router/router.py):
  - allow:             not sensitive → forward to external LLM as-is
  - mask_and_send:     sensitive but maskable → replace spans, then send
  - route_to_local:    sensitive & essential → cannot mask, route to local model
  - block:             high risk → refuse entirely
  - prompt_user:       ask the user to confirm before proceeding
"""

from __future__ import annotations

RESEARCHER_CONVERSATIONS: list[dict] = [
    # ── 1. Yield data discussed across multiple turns ──────────────────────
    {
        "id": "researcher_yield_progression",
        "persona": "Samsung Semiconductor senior researcher",
        "description": (
            "Researcher discusses internal 2nm GAA yield data across turns, "
            "starting with generic questions and escalating to specific "
            "confidential numbers. Tests whether the router detects the "
            "escalation and applies increasingly strict policy actions."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "안녕하세요. 저는 삼성반도체에서 2nm GAA 공정을 개발 중인 "
                    "연구원입니다. GAA(Gate-All-Around) 트랜지스터 구조에서 "
                    "Nanosheet width variability가 수율에 미치는 영향에 대해 "
                    "일반적인 설명을 해줄 수 있나요?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "GAA 트랜지스터에서 Nanosheet width variability는 "
                    "드레인 전류(Id)와 문턱전압(Vth) 변동에 직접 영향을 미칩니다. "
                    "Width가 불균일하면 채널 전류 밀도가 달라져 수율이 떨어질 수 있습니다. "
                    "일반적으로 ±1nm 이내의 variablity를 목표로 공정을 제어합니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "우리 팀은 현재 HVM 기준으로 2nm GAA 수율이 62% 정도 나와요. "
                    "경쟁사 TSMC의 N2는 70% 이상이라고 들었는데, 이 차이를 "
                    "좁히기 위한 전략을 제안해주세요."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "수율 개선을 위해서는 Nanosheet 형성 단계의 etch uniformity "
                    "개선과 spacer 공정의 정밀도 향상이 중요합니다. 구체적인 "
                    "내부 데이터를 기반으로 분석하려면 더 많은 정보가 필요합니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "추가로 말씀드리면, 우리의 Gate oxide thickness는 "
                    "1.2nm에서 ±0.15nm 범위로 관리되고 있고, "
                    "Inner spacer의 void 비율이 현재 3.8%입니다. "
                    "이 수치들을 기반으로 수율 개선 우선순위를 분석해주세요."
                ),
            },
        ],
        "expected_sensitive_turns": [2, 4],
        "expected_actions": [
            "allow",
            "allow",
            "mask_and_send",
            "allow",
            "mask_and_send",
        ],
        "tags": ["competitive", "multi_turn", "business", "yield", "escalation"],
        "sensitive_spans": [
            {
                "turn_index": 2,
                "spans": [
                    {"text": "62%", "category": "YIELD_RATE_INTERNAL"},
                    {"text": "TSMC", "category": "COMPETITOR_NAME"},
                    {"text": "N2", "category": "COMPETITOR_PROCESS_NODE"},
                ],
            },
            {
                "turn_index": 4,
                "spans": [
                    {"text": "1.2nm", "category": "PROCESS_PARAMETER_INTERNAL"},
                    {"text": "±0.15nm", "category": "PROCESS_TOLERANCE_INTERNAL"},
                    {"text": "3.8%", "category": "DEFECT_RATE_INTERNAL"},
                ],
            },
        ],
    },

    # ── 2. Competitor (TSMC) strategy with internal comparisons ────────────
    {
        "id": "researcher_competitor_comparison",
        "persona": "Samsung Semiconductor senior researcher",
        "description": (
            "Researcher discusses Samsung's internal strategic decisions "
            "in direct comparison with TSMC's publicly known roadmap. "
            "Includes confidential investment decisions and partnership details."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "TSMC가 2nm에서 backside power delivery network(BSPDN)를 "
                    "도입한다는 뉴스를 봤습니다. BSPDN의 기술적 장점에 대해 "
                    "설명해주세요."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "BSPDN은 전원 배선을 웨이퍼 뒷면으로 이동시켜 프론트사이드의 "
                    "신호 배선만 남기는 기술입니다. IR drop을 줄이고 트랜지스터 "
                    "밀도를 높이는 장점이 있습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "우리도 BSPDN을 도입할지 내부에서 논의 중인데, "
                    "경영진에서 2nm 1차 양산에는 BSPDN을 제외하고 "
                    "2.5nm부터 적용하기로 결정했습니다. "
                    "대신 2nm에는 SADP 방식의 미세 배선에 집중하기로 했어요."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "내부 전략 결정이시군요. 기술적 관점에서 SADP 방식은 "
                    "BSPDN 대비 복잡도가 낮지만 트랜지스터 밀도에서 "
                    "열위일 수 있습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "TSMC와 비교하면, 우리는 대만 TSMC의 N2 대비 "
                    "가격 경쟁력을 확보하기 위해 파운드리 단가를 "
                    "wafer당 $17,500으로 책정했습니다. "
                    "TSMC는 $19,000 이상이라고 알고 있어요. "
                    "이 가격 전략이 유효할까요?"
                ),
            },
            {
                "role": "user",
                "content": (
                    "그리고 인텔과의 기술 제휴도 검토 중인데, "
                    "인텔의 RibbonFET 특허 크로스라이선스를 통해 "
                    "GAA 구조의 특허 리스크를 줄이는 방안을 "
                    "법무팀과 논의하고 있습니다."
                ),
            },
        ],
        "expected_sensitive_turns": [2, 4, 5],
        "expected_actions": [
            "allow",
            "allow",
            "mask_and_send",
            "allow",
            "mask_and_send",
            "route_to_local",
        ],
        "tags": ["competitive", "multi_turn", "business", "strategy", "pricing"],
        "sensitive_spans": [
            {
                "turn_index": 2,
                "spans": [
                    {
                        "text": "2nm 1차 양산에는 BSPDN을 제외",
                        "category": "PROCESS_ROADMAP_DECISION",
                    },
                    {"text": "2.5nm부터 적용", "category": "TECHNOLOGY_TIMELINE"},
                    {"text": "SADP", "category": "INTERNAL_PROCESS_CHOICE"},
                ],
            },
            {
                "turn_index": 4,
                "spans": [
                    {"text": "$17,500", "category": "PRICING_STRATEGY_INTERNAL"},
                    {"text": "$19,000", "category": "COMPETITOR_PRICING_INTEL"},
                ],
            },
            {
                "turn_index": 5,
                "spans": [
                    {"text": "인텔", "category": "PARTNERSHIP_NEGOTIATION"},
                    {
                        "text": "RibbonFET 특허 크로스라이선스",
                        "category": "IP_LICENSING_STRATEGY",
                    },
                ],
            },
        ],
    },

    # ── 3. Budget figures accumulate across turns ──────────────────────────
    {
        "id": "researcher_budget_accumulation",
        "persona": "Samsung Semiconductor senior researcher",
        "description": (
            "Researcher starts with a general question about R&D efficiency, "
            "then incrementally reveals confidential budget allocations, "
            "headcount, and investment figures across multiple turns. "
            "Tests whether the router catches accumulating financial data."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "반도체 R&D 효율성을 높이기 위한 방법론에 대해 "
                    "알려주세요. 스크럽(Scrub) 프로세스나 "
                    "기술 게이트 리뷰 같은 것들이요."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "R&D 효율성을 위해 Stage-Gate 모델을 활용합니다. "
                    "각 단계에서 기술 성숙도(TRL)를 평가하고, "
                    "게이트 리뷰를 통해 리소스 배분을 조정합니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "우리 팀의 2nm GAA 프로젝트 예산이 올해 "
                    "총 4,500억원인데, EUV 노광 장비 구매에 1,800억원, "
                    "공정 개발 인건비에 1,200억원이 배정되어 있습니다."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "대규모 투자이시네요. 예산 배분에서 가장 큰 비중을 "
                    "차지하는 EUV 장비 비용을 줄이기 위한 전략을 "
                    "고려해볼 수 있습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "여기에 더해서 ASML과의 EUV 장비 구매 계약에서 "
                    "장비 1대당 가격이 약 3,800억원이고, "
                    "우리는 올해 2대를 주문했습니다. "
                    "총 투자비가 7,600억원이 되는 셈이에요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "내년에는 투자를 더 확대해서 R&D 예산을 "
                    "6,200억원으로 증액할 계획입니다. "
                    "대신 인력을 현재 320명에서 450명으로 늘리고, "
                    "EUV 장비를 추가 3대 더 구매할 예정입니다. "
                    "이 규모의 투자가 적절한지 분석해주세요."
                ),
            },
        ],
        "expected_sensitive_turns": [2, 4, 5],
        "expected_actions": [
            "allow",
            "allow",
            "mask_and_send",
            "allow",
            "mask_and_send",
            "block",
        ],
        "tags": ["competitive", "multi_turn", "business", "budget", "financial"],
        "sensitive_spans": [
            {
                "turn_index": 2,
                "spans": [
                    {"text": "4,500억원", "category": "R_AND_D_BUDGET_TOTAL"},
                    {"text": "1,800억원", "category": "CAPITAL_EXPENDITURE"},
                    {"text": "1,200억원", "category": "LABOR_COST_ALLOCATION"},
                ],
            },
            {
                "turn_index": 4,
                "spans": [
                    {"text": "3,800억원", "category": "EQUIPMENT_UNIT_PRICE"},
                    {"text": "7,600억원", "category": "TOTAL_EQUIPMENT_INVESTMENT"},
                ],
            },
            {
                "turn_index": 5,
                "spans": [
                    {"text": "6,200억원", "category": "FUTURE_BUDGET_PLAN"},
                    {"text": "320명", "category": "HEADCOUNT_CURRENT"},
                    {"text": "450명", "category": "HEADCOUNT_PLANNED"},
                    {"text": "3대", "category": "EQUIPMENT_PURCHASE_PLAN"},
                ],
            },
        ],
    },

    # ── 4. Mixed public technical + internal decisions ─────────────────────
    {
        "id": "researcher_mixed_sensitivity",
        "persona": "Samsung Semiconductor senior researcher",
        "description": (
            "Alternates between public-domain technical questions (safe) and "
            "internal strategic decisions (sensitive). Tests whether the "
            "router correctly allows safe turns while catching sensitive ones, "
            "and whether it can detect information that becomes sensitive "
            "only in context of prior turns."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "High-NA EUV lithography의 해상도와 depth of focus에 "
                    "대해 설명해주세요. 기존 EUV(NA 0.33) 대비 "
                    "High-NA(NA 0.55)의 장단점이 궁금합니다."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "High-NA EUV는 NA 0.55를 통해 ~8nm 해상도를 달성합니다. "
                    "기존 EUV(NA 0.33) 대비 해상도가 향상되지만 "
                    "depth of focus가 줄어들어 overlay 정밀도 확보가 중요합니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "감사합니다. 그런데 사실 우리는 High-NA EUV를 "
                    "2nm 양산에 투입하지 않기로 내부 방침을 정했습니다. "
                    "대신 기존 EUV의 multi-patterning으로 대응하고, "
                    "High-NA는 차세대 1.4nm 공정 전용으로 배정하기로 했어요."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "내부 전략 결정이시군요. 기술적으로 multi-patterning은 "
                    "cost와 throughput에서 불리할 수 있습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "공정 미세화에서 FinFET vs GAA의 단락 특성(short channel "
                    "effect) 비교에 대해 설명해주세요. DIBL, Vth roll-off "
                    "관점에서요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "아, 그리고 한 가지 더. 우리 2nm GAA의 게이트 길이 "
                    "목표가 12nm인데, 이 수치는 아직 외부에 공개되지 않은 "
                    "사항입니다. 이 정보를 외부 LLM에 보내지 마세요."
                ),
            },
        ],
        "expected_sensitive_turns": [2, 5],
        "expected_actions": [
            "allow",
            "allow",
            "mask_and_send",
            "allow",
            "allow",
            "route_to_local",
        ],
        "tags": [
            "competitive",
            "multi_turn",
            "mixed",
            "context_sensitive",
            "confidentiality_marker",
        ],
        "sensitive_spans": [
            {
                "turn_index": 2,
                "spans": [
                    {
                        "text": "High-NA EUV를 2nm 양산에 투입하지 않기로",
                        "category": "EQUIPMENT_STRATEGY_DECISION",
                    },
                    {
                        "text": "1.4nm 공정 전용으로 배정",
                        "category": "TECHNOLOGY_ROADMAP",
                    },
                ],
            },
            {
                "turn_index": 5,
                "spans": [
                    {
                        "text": "게이트 길이 목표가 12nm",
                        "category": "PROCESS_TARGET_PARAMETER",
                    },
                ],
            },
        ],
    },

    # ── 5. Patent application before filing ────────────────────────────────
    {
        "id": "researcher_patent_prefiling",
        "persona": "Samsung Semiconductor senior researcher",
        "description": (
            "Researcher discusses a patent application for a novel GAA "
            "contact structure before it is filed. Includes the invention's "
            "core concept, potential claims, and competitive advantage. "
            "Tests detection of pre-filing patent content as a high-risk "
            "business secret requiring blocking or local routing."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "반도체 특허 출원 절차에 대해 알려주세요. "
                    "특히 미국 특허(USPTO)와 한국 특허(KIPRIS) "
                    "동시 출원 시 주의사항이 궁금합니다."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "미국과 한국 동시 출원 시 Paris Convention을 활용하면 "
                    "우선권 기간(12개월) 내에 추가 출원이 가능합니다. "
                    "USPTO는 first-to-file, KIPRIS는 등록주의를 따릅니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "실은 저희 팀에서 GAA 구조의 새로운 콘택트 형성 "
                    "방법에 대한 특허를 준비 중인데, 특허 명세서 "
                    "작성을 도와주세요."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "특허 명세서 작성을 도와드리겠습니다. "
                    "발명의 구체적인 구성과 효과를 알려주세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "발명의 핵심은 Nanosheet 채널 사이의 inner spacer "
                    "형성 시, 기존 CVD 방식 대신 ALD(Atomic Layer Deposition)를 "
                    "사용하되, precursor로 TMA(trimethylaluminum)와 "
                    "H₂O를 교차 주입하는 방식입니다. "
                    "이를 통해 void 비율을 0.5% 이하로 줄일 수 있습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "청구항 1은 'ALD 기반 inner spacer 형성 방법'이고, "
                    "청구항 2는 'TMA/H₂O 교차 주입을 포함하는 "
                    "GAA 트랜지스터 제조 방법'입니다. "
                    "이 발명으로 TSMC 대비 inner spacer 품질에서 "
                    "경쟁 우위를 확보할 수 있을 것으로 기대합니다. "
                    "이 내용은 절대 외부로 유출되면 안 됩니다."
                ),
            },
        ],
        "expected_sensitive_turns": [2, 4, 5],
        "expected_actions": [
            "allow",
            "allow",
            "route_to_local",
            "allow",
            "block",
            "block",
        ],
        "tags": [
            "competitive",
            "multi_turn",
            "business",
            "patent",
            "pre_filing",
            "high_risk",
        ],
        "sensitive_spans": [
            {
                "turn_index": 2,
                "spans": [
                    {
                        "text": "GAA 구조의 새로운 콘택트 형성 방법",
                        "category": "PATENT_INVENTION_CONCEPT",
                    },
                ],
            },
            {
                "turn_index": 4,
                "spans": [
                    {"text": "ALD", "category": "PATENT_PROCESS_METHOD"},
                    {
                        "text": "TMA(trimethylaluminum)",
                        "category": "PATENT_MATERIAL_CHOICE",
                    },
                    {"text": "H₂O", "category": "PATENT_MATERIAL_CHOICE"},
                    {
                        "text": "0.5% 이하",
                        "category": "PATENT_PERFORMANCE_TARGET",
                    },
                ],
            },
            {
                "turn_index": 5,
                "spans": [
                    {
                        "text": "ALD 기반 inner spacer 형성 방법",
                        "category": "PATENT_CLAIM_TEXT",
                    },
                    {
                        "text": "TMA/H₂O 교차 주입을 포함하는 GAA 트랜지스터 제조 방법",
                        "category": "PATENT_CLAIM_TEXT",
                    },
                    {"text": "TSMC", "category": "COMPETITOR_NAME"},
                ],
            },
        ],
    },
]
