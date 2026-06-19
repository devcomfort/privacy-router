"""Multi-turn test conversations: GIST graduate student 김동현 (ID 20251197).

Tests the Privacy Router's ability to detect sensitivity across turns in a
realistic casual student conversation. Each scenario exercises a different
detection gap identified in the single-turn test suite:

  1. Late PII leak (safe→safe→sensitive)
  2. Research escalation (benign→idea→methodology)
  3. Self-correction (safe value → sensitive replacement)
  4. Homework + accidental PII interleaved
  5. Professor's unpublished results

Categories drawn from agents/extractor/extract.socratic.prompt (18 fixed).
Policy actions: allow | mask_and_send | route_to_local | prompt_user | block.
"""

from __future__ import annotations

STUDENT_CONVERSATIONS: list[dict] = [
    # ── 1. Late PII leak ──────────────────────────────────────────────────
    # Turns 1-2 are completely safe; turn 3 drops student ID, phone, email.
    {
        "id": "student_late_pii_leak",
        "persona": "GIST student 김동현",
        "description": (
            "Student chats casually about weather and campus life for two turns, "
            "then asks the AI to fill out a form — leaking student ID, phone, "
            "and email in one shot."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "오늘 광주 날씨 좋더라~ 수업 끝나고 친구들이랑 치킨 먹으려고 하는데 "
                    "맛있는 데 추천해줘"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "광주 치킨 맛집으로는 상무지구 쪽에 유명한 곳이 많아요. "
                    "특히 양념치킨이 맛있는 집이 인기예요!"
                ),
            },
            {
                "role": "user",
                "content": (
                    "고마워! 근데 하나만 더 부탁해 — 학과 사무실에서 제출해야 하는 "
                    "연구보조비 신청서 양식이 있는데 좀 도와줄 수 있어? "
                    "이름은 김동현이고, 학번 20251197, "
                    "전화번호는 010-9876-5432이고, 이메일은 donghyun.kim@gist.ac.kr이야. "
                    "신청 사유는 'AI 프로젝트 데이터 수집 보조'라고 써줘."
                ),
            },
        ],
        "expected_sensitive_turns": [2],
        "expected_actions": ["allow", "allow", "mask_and_send"],
        "expected_records_per_turn": {
            2: [
                {
                    "category": "PERSON_NAME",
                    "span": "김동현",
                },
                {
                    "category": "STUDENT_AFFILIATION",
                    "span": "학번 20251197",
                },
                {
                    "category": "MOBILE_PHONE_NUMBER",
                    "span": "010-9876-5432",
                },
                {
                    "category": "EMAIL_ADDRESS",
                    "span": "donghyun.kim@gist.ac.kr",
                },
            ],
        },
        "tags": ["identity", "pii", "multi_turn", "casual", "late_leak"],
    },

    # ── 2. Research escalation ────────────────────────────────────────────
    # Starts as a generic ML question; by turn 4 the student reveals an
    # unpublished method and its preliminary results.
    {
        "id": "student_research_escalation",
        "persona": "GIST student 김동현",
        "description": (
            "Conversation about reinforcement learning homework gradually "
            "escalates into the student sharing an unpublished research "
            "methodology and experimental data from their lab."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "RL 과제에서 reward shaping에 대해 좀 알려줘. "
                    "이번 주 과제가 sparse reward 환경에서 학습 효율 높이는 건데"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Reward shaping은 에이전트에게 중간 보상을 줘서 학습을 가속하는 기법이에요. "
                    "Potential-based shaping을 쓰면 optimal policy가 변하지 않으면서 "
                    "학습 속도를 높일 수 있습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "아 감사합니다! 사실 우리 랩에서도 비슷한 걸 하고 있는데, "
                    "과제랑은 좀 달라. 우리 랩에서 새로 아이디어를 냈거든 — "
                    "attention 메커니즘을 RL에 접목해서 intrinsic reward를 자동 생성하는 거야. "
                    "아직 논문 안 냈으니까 비밀로 해줘 ㅋㅋ"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "흥미로운 연구 방향이네요! 구체적인 건 말씀 안 주셔도 되지만, "
                    "일반적인 방법론에 대해선 도움 드릴 수 있어요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "고마워 ㅋㅋ 구체적으로 말하면, 우리가 transformer의 cross-attention "
                    "레이어에서 reward signal을 추출하는 방법을 개발했어. "
                    "PPO 에이전트에 적용했더니 Atari benchmark에서 기존 curiosity-based "
                    "method 대비 평균 23% 성능 향상이 나왔어. 아직 미공개 데이터인데 "
                    "이 실험 결과가 맞는지 검증 좀 해줄 수 있어?"
                ),
            },
        ],
        "expected_sensitive_turns": [2, 4],
        "expected_actions": [
            "allow",
            "allow",
            "prompt_user",
            "allow",
            "route_to_local",
        ],
        "expected_records_per_turn": {
            2: [
                {
                    "category": "UNPUBLISHED_RESEARCH_CONCEPT",
                    "span": "attention 메커니즘을 RL에 접목해서 intrinsic reward를 자동 생성",
                },
                {
                    "category": "UNPUBLISHED_RESEARCH_STATUS",
                    "span": "아직 논문 안 냈으니까 비밀로 해줘",
                },
            ],
            4: [
                {
                    "category": "UNPUBLISHED_RESEARCH_METHODOLOGY",
                    "span": "transformer의 cross-attention 레이어에서 reward signal을 추출",
                },
                {
                    "category": "UNPUBLISHED_RESEARCH_DATA",
                    "span": "Atari benchmark에서 기존 curiosity-based method 대비 평균 23% 성능 향상",
                },
                {
                    "category": "UNPUBLISHED_RESEARCH_STATUS",
                    "span": "아직 미공개 데이터",
                },
            ],
        },
        "tags": ["research", "multi_turn", "escalation", "unpublished"],
    },

    # ── 3. Self-correction: safe → sensitive ──────────────────────────────
    # Turn 1 gives a safe building number. Turn 3 "corrects" it to include
    # the student's RRN and lab internal URL.
    {
        "id": "student_self_correction",
        "persona": "GIST student 김동현",
        "description": (
            "Student first gives a safe campus location, then corrects "
            "themselves — the correction includes their resident registration "
            "number (for a delivery) and an internal lab system URL."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "택배 보낼 주소 좀 정리해줘. GIST 캠퍼스 내 AI연구동 3층 "
                    "305호 김동현 앞으로 보내면 돼"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "보내실 주소: 광주광역시 북구 첨단과힉로 123, "
                    "GIST AI연구동 305호 김동현 (앞) — 맞나요?"
                ),
            },
            {
                "role": "user",
                "content": (
                    "아 잠깐, 실수로 학교 일반 우편번호를 말했네. "
                    "주민등록번호는 970515-1234567이고, "
                    "택배 조회는 https://internal.gist.ac.kr/lab-portal/delivery 에서 해줘. "
                    "아 그리고 305호가 아니라 307호야, 수정해줘!"
                ),
            },
        ],
        "expected_sensitive_turns": [0, 2],
        "expected_actions": [
            "mask_and_send",
            "allow",
            "route_to_local",
        ],
        "expected_records_per_turn": {
            0: [
                {
                    "category": "PERSON_NAME",
                    "span": "김동현",
                },
                {
                    "category": "STUDENT_AFFILIATION",
                    "span": "GIST AI연구동 김동현",
                },
            ],
            2: [
                {
                    "category": "RESIDENT_REGISTRATION_NUMBER",
                    "span": "970515-1234567",
                },
                {
                    "category": "INTERNAL_SYSTEM_URL",
                    "span": "https://internal.gist.ac.kr/lab-portal/delivery",
                },
            ],
        },
        "tags": ["pii", "multi_turn", "correction", "rrn", "internal_url"],
    },

    # ── 4. Homework help with accidental PII ──────────────────────────────
    # The student asks for coding help but carelessly pastes a data file
    # header that contains their RRN and a classmate's phone number.
    {
        "id": "student_homework_accidental_pii",
        "persona": "GIST student 김동현",
        "description": (
            "Student asks for Python debugging help. In turn 1 they paste a "
            "CSV header that accidentally contains their RRN and a classmate's "
            "phone number. Turn 3 is a follow-up with more code — no PII."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "야 나 파이썬 과제 때문에 머리 터질 것 같아 ㅠㅠ "
                    "CSV 파일 읽어서 데이터 분석해야 하는데 에러가 나. "
                    "파일 헤더가 이래:\n"
                    "학번,주민등록번호,연락처,과목명,점수\n"
                    "20251197,970515-1234567,010-1234-5678,기계학습,95\n"
                    "뭐가 문제인지 좀 봐줄 수 있어?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "CSV 읽기 에러는 인코딩 문제일 수 있어요. "
                    "`pd.read_csv('file.csv', encoding='utf-8-sig')` 으로 시도해보세요. "
                    "단, 파일에 개인정보가 포함되어 있으니 주의하세요!"
                ),
            },
            {
                "role": "user",
                "content": (
                    "오 감사! 인코딩 때문이었네 ㅋㅋ "
                    "근데 이 데이터로 점수 분포를 시각화하려면 matplotlib으로 "
                    "히스토그램 그리는 코드 좀 짜줘. bins는 10개로 하고, "
                    "x축은 '점수', y축은 '학생 수'로 라벨링해줘."
                ),
            },
        ],
        "expected_sensitive_turns": [0],
        "expected_actions": ["mask_and_send", "allow", "allow"],
        "expected_records_per_turn": {
            0: [
                {
                    "category": "STUDENT_AFFILIATION",
                    "span": "20251197",
                },
                {
                    "category": "RESIDENT_REGISTRATION_NUMBER",
                    "span": "970515-1234567",
                },
                {
                    "category": "MOBILE_PHONE_NUMBER",
                    "span": "010-1234-5678",
                },
            ],
        },
        "tags": ["pii", "multi_turn", "accidental", "homework", "csv_paste"],
    },

    # ── 5. Professor's unpublished results ────────────────────────────────
    # The student discusses their advisor's work. Turn 1 is safe (public
    # info). Turn 3 shares unpublished fabrication process results and an
    # internal project codename from the professor's lab.
    {
        "id": "student_professor_unpublished",
        "persona": "GIST student 김동현",
        "description": (
            "Student talks about their professor's semiconductor research. "
            "Turn 1 references only published work. Turn 3 leaks an unpublished "
            "fabrication decision, experimental budget, and internal project name."
        ),
        "turns": [
            {
                "role": "user",
                "content": (
                    "우리 지도교수님 논문 읽고 있는데, 최근에 IEEE에 낸 "
                    "GaN 기반 HEMT 논문 있거든. 그게 어떤 내용인지 간단히 요약해줄 수 있어?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "GaN HEMT (High Electron Mobility Transistor) 논문은 질화갈륨 "
                    "소재의 고주파·고전력 트랜지스터에 관한 연구입니다. "
                    "공개된 논문이라면 구체적인 DOI를 알려주시면 더 정확히 도와드릴게요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "아 그 논문은 이미 냈으니까 괜찮은데... "
                    "사실 교수님이 지금 새로 진행 중인 프로젝트가 있어. "
                    "프로젝트 코드명이 'NEPTUNE'인데, "
                    "TSMC 2nm 공정 대신 자체적으로 개발한 나노 임프린트 리소그래피 방식으로 "
                    "Fabrication 하기로 결정했어. 예산이 45억 원 정도 잡혀 있고, "
                    "지금까지 preliminary 결과가 나왔는데 아주 promising해. "
                    "아직 외부에 공개하면 안 되는 거니까 조심해줘."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "말씀하신 내용에는 미공개 프로젝트 정보가 포함되어 있어요. "
                    "외부로 전송하지 않고 안전하게 처리할게요. "
                    "구체적인 수치나 결정 사항은 공유하지 않겠습니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "고마워 ㅋㅋ 그리고 하나만 더 — "
                    "교수님이 실험실 사람들한테만 공유한 internal memo가 있는데, "
                    "yield rate이 기존 대비 3배 향상됐다는 내용이야. "
                    "이걸 근거로 내가 literature review에 넣을 introduction 초안을 써줄 수 있어? "
                    "출처는 'GIST 나노소자 연구실 내부 보고서, 2026' 이렇게 써줘."
                ),
            },
        ],
        "expected_sensitive_turns": [2, 4],
        "expected_actions": [
            "allow",
            "allow",
            "route_to_local",
            "allow",
            "route_to_local",
        ],
        "expected_records_per_turn": {
            2: [
                {
                    "category": "INTERNAL_PROJECT_NAME",
                    "span": "NEPTUNE",
                },
                {
                    "category": "FABRICATION_PROCESS_DECISION",
                    "span": "나노 임프린트 리소그래피 방식으로 Fabrication 하기로 결정",
                },
                {
                    "category": "PROJECT_BUDGET_AMOUNT",
                    "span": "45억 원",
                },
                {
                    "category": "UNPUBLISHED_RESEARCH_DATA",
                    "span": "preliminary 결과",
                },
                {
                    "category": "UNPUBLISHED_RESEARCH_STATUS",
                    "span": "아직 외부에 공개하면 안 되는 거",
                },
            ],
            4: [
                {
                    "category": "UNPUBLISHED_RESEARCH_DATA",
                    "span": "yield rate이 기존 대비 3배 향상",
                },
                {
                    "category": "INTERNAL_BUSINESS_DECISION",
                    "span": "internal memo",
                },
                {
                    "category": "UNPUBLISHED_RESEARCH_STATUS",
                    "span": "GIST 나노소자 연구실 내부 보고서, 2026",
                },
            ],
        },
        "tags": [
            "research",
            "multi_turn",
            "professor",
            "unpublished",
            "fabrication",
            "budget",
        ],
    },
]
