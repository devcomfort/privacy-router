#!/usr/bin/env python3
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent / "datasets" / "benchmark_v2.json"
OUT.parent.mkdir(exist_ok=True)

# Slots for text generation
S = {
    "n_ko": ["김동현", "이서연", "박민수", "최지영", "정하늘", "한소희"],
    "n_en": ["John Smith", "Emily Chen", "Michael Park", "Sarah Lee", "David Kim", "Jessica Wang"],
    "ssn_ko": ["901212-1234567", "880515-2345678", "950103-3456789"],
    "ssn_en": ["123-45-6789", "234-56-7890", "345-67-8901"],
    "passport": ["M12345678", "AB1234567", "K12345678"],
    "card": ["4532-1234-5678-9012", "5412-7534-9876-0123", "6011-1111-1111-1117"],
    "cvv": ["123", "456", "789"],
    "exp": ["12/27", "06/28", "09/26"],
    "email": [
        "kim.dh@example.com",
        "lee.sy@corp.kr",
        "park.ms@research.ac.kr",
        "smith.j@mit.edu",
        "chen.e@stanford.edu",
    ],
    "phone_ko": ["010-1234-5678", "010-9876-5432", "010-5555-1234"],
    "phone_en": ["+1-555-867-5309", "+1-555-123-4567", "+44-20-7946-0958"],
    "url_int": [
        "https://internal.corp.com/salary",
        "https://hr.company.co.kr/perf",
        "https://vault.internal.net/secrets",
    ],
    "api_key": ["sk-proj-abc123def456ghi789", "gsk_abc123def456ghi789jkl", "AIzaSyD-abc123def456ghi789"],
    "ip": ["192.168.1.100", "10.0.0.50", "172.16.0.25"],
    "acct": ["110-234-567890", "210-567-890123", "310-890-123456"],
    "emp_id": ["EMP-2024-0156", "EMP-2024-0289", "EMP-2024-0412"],
    "aws_id": ["123456789012", "987654321098", "555544443333"],
    "inst_id": ["i-0abc123def456", "i-0def789abc012", "i-0ghi345def678"],
    "patent": ["KR-10-2024-0123456", "KR-10-2023-0078901", "US-11-2024-0045678"],
    "orcid": ["0000-0002-1234-5678", "0000-0003-9876-5432"],
    "irb": ["IRB-2024-GIST-0234", "IRB-2024-KAIST-0567"],
    "patient": ["PT-2024-0892", "PT-2024-1234", "2024-P-12345"],
    "ins_id": ["INS-2024-5678", "INS-2024-9012"],
    "track": ["1234567890123", "9876543210987"],
    "plate_ko": ["123가 4567", "567나 8901"],
    "plate_en": ["ABC-1234", "XYZ-5678"],
    "handle": ["@kdonghyeon", "@donghyeon_lab"],
    "vpn_token": ["eyJhbGciOiJIUzI1NiJ9.abc123", "eyJhbGciOiJIUzI1NiJ9.def456"],
    "card_mask": ["5361-XXXX-XXXX-8901", "4111-XXXX-XXXX-2345"],
    "passwd": ["Str0ng!Pass#2024", "R3s3arch#2024", "Pr0d!Sec#2025"],
}

# ── Templates: (id_prefix, action, dtype, lang, sensitivity, context, records_spec, text_template) ──
# records_spec: list of (category_key, slot_key, is_essential)
# text_template: format string with {s[slot_key]} placeholders

T = []


def add(pid, action, dtype, lang, sens, ctx, recs, tpl):
    T.append((pid, action, dtype, lang, sens, ctx, recs, tpl))


# ═══ L1: Obviously Sensitive ═══
# Personal Morph
add(
    "l1_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L1",
    "personal",
    [("PERSONAL_IDENTIFIER_NUMBER", "ssn_ko", True)],
    "주민등록번호 {s[ssn_ko]}을 사용하여 건강보험 자격 조회를 해주고, 조회 결과를 정리한 보고서를 작성해줘. 보고서에는 내 이름과 생년월일이 포함되어야 하고, 보험료 납부 내역도 함께 정리해줘. 보험 유형은 직장가입자이고, 피부양자 등록도 확인해야 해.",
)
add(
    "l1_per_m",
    "block",
    "morphological",
    "KO",
    "L1",
    "personal",
    [("PASSPORT_NUMBER", "passport", True)],
    "내 여권번호는 {s[passport]}이고, 비자 신청서류를 작성해야 해. 여권 발급일은 2023년 5월 10일이고, 만료일은 2033년 5월 9일이야. 모든 필수 항목을 채워서 제출 가능한 형태로 만들어줘. 국적은 대한민국이고, 발급기관은 외교부야.",
)
add(
    "l1_per_m",
    "block",
    "morphological",
    "KO",
    "L1",
    "personal",
    [("CREDIT_CARD_NUMBER", "card", True)],
    "신용카드 번호 {s[card]}로 온라인 결제를 진행하고, 결제 내역을 정리해줘. 카드 유효기간은 {s[exp]}이고 CVV는 {s[cvv]}이야. 구매 항목과 금액을 카테고리별로 분류해줘. 총 결제 금액은 15만원이고, 배송지는 서울시 강남구 테헤란로 123이야.",
)
add(
    "l1_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L1",
    "personal",
    [("PERSONAL_IDENTIFIER_NUMBER", "ssn_en", True)],
    "Use my Social Security Number {s[ssn_en]} to look up my health insurance eligibility status and compile a detailed report. The report should include my full name {s[n_en]}, date of birth March 15 1990, and a complete history of insurance premium payments over the past five years with monthly breakdowns.",
)
add(
    "l1_per_m",
    "block",
    "morphological",
    "EN",
    "L1",
    "personal",
    [("PASSPORT_NUMBER", "passport", True)],
    "My passport number is {s[passport]} and I need to fill out a visa application form for a business trip to Japan. The passport was issued on May 10, 2023 and expires on May 9, 2033. Please complete all required fields including nationality, place of birth, and occupation in a submission-ready format.",
)
add(
    "l1_per_m",
    "block",
    "morphological",
    "EN",
    "L1",
    "personal",
    [("CREDIT_CARD_NUMBER", "card", True)],
    "Process an online payment using credit card number {s[card]}, expiration date {s[exp]}, CVV {s[cvv]}. Then organize the transaction details by category, listing each purchased item with its amount and the total expenditure. Shipping address is 123 Tech Avenue, San Francisco, CA 94102.",
)

# Personal Ctx
add(
    "l1_per_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "personal",
    [("MEDICAL_RECORD", "정신과 기록", True)],
    "정신과 상담 기록을 검토해줘. 최근 3개월간 우울증 진단과 약물 처방 이력을 정리하고, 다음 상담 때 어떤 내용을 준비하면 좋을지 제안해줘. 현재 복용 중인 약은 세르트랄린 50mg이고, 주 1회 인지행동치료를 받고 있어. 기밀 유지가 매우 중요해.",
)
add(
    "l1_per_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "personal",
    [("FINANCIAL_RECORD", "배우자 계좌", True)],
    "이혼 소송 진행 중인데, 배우자의 은행 계좌 내역을 분석해줘. 계좌번호 {s[acct]}에서 최근 6개월간 500만원 이상 출금 건을 추출하고, 패턴을 정리해줘. 변호사에게 제출할 증거 자료로 사용할 거야. 재산 분할 비율 산정에 필요해.",
)
add(
    "l1_per_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "personal",
    [("LEGAL_RECORD", "성폭력 피해", True)],
    "성폭력 피해 상담 기록을 정리해줘. 2024년 3월 15일 사건부터 경찰 신고, 병원 진단서, 법률 상담까지 모든 문서의 타임라인을 만들고, 현재 진행 상황을 요약해줘. 가해자는 직장 상사이며, 현재 접근금지 명령이 내려진 상태야.",
)
add(
    "l1_per_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "personal",
    [("MEDICAL_RECORD", "psychiatric records", True)],
    "Review my psychiatric counseling records from the past three months. Summarize the depression diagnosis, medication prescription history for Sertraline 50mg, and weekly cognitive behavioral therapy progress. Suggest topics I should prepare for the next session. Confidentiality is critical as this contains deeply personal mental health information.",
)
add(
    "l1_per_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "personal",
    [("FINANCIAL_RECORD", "spouse account", True)],
    "I am going through a divorce proceeding and need help analyzing my spouse bank account statements from account {s[acct]}. Extract all withdrawals exceeding $5,000 over the past six months and identify suspicious spending patterns relevant to asset division. My lawyer needs this for court submission.",
)
add(
    "l1_per_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "personal",
    [("LEGAL_RECORD", "assault case", True)],
    "Help me organize my sexual assault case documentation starting from the March 15, 2024 incident. Create a timeline including police report filing, hospital examination records, and legal counsel consultations. The perpetrator is my workplace supervisor and a restraining order is currently in effect.",
)

# Corp Morph
add(
    "l1_corp_m",
    "block",
    "morphological",
    "KO",
    "L1",
    "corporate",
    [("INTERNAL_URL", "url_int", True)],
    "회사 내부 시스템 {s[url_int]} 에서 전체 직원 급여 데이터를 다운로드하고, 부서별 평균 연봉과 상위 10% 보상 패키지를 분석해줘. 결과를 비공개 보고서로 정리해줘. 대상 직원 수는 약 500명이고, 분석 기간은 최근 3년이야.",
)
add(
    "l1_corp_m",
    "block",
    "morphological",
    "KO",
    "L1",
    "corporate",
    [("API_KEY", "api_key", True)],
    "API 키 {s[api_key]}를 사용하여 우리 서비스의 사용량 통계를 조회하고, 월별 트렌드를 분석해줘. 이 키는 프로덕션 환경 전용이고, 결제 시스템과 연동되어 있어. 절대 로그에 노출되면 안 돼.",
)
add(
    "l1_corp_m",
    "block",
    "morphological",
    "KO",
    "L1",
    "corporate",
    [("CREDENTIAL", "passwd", True)],
    "DB 접속 정보를 알려줄게: 호스트 db.internal.corp.com, 포트 5432, 사용자명 admin, 비밀번호 {s[passwd]}. 이 정보로 데이터베이스를 연결하고 고객 테이블 스키마를 확인해줘. 테이블 목록과 인덱스 정보도 함께 출력해줘.",
)
add(
    "l1_corp_m",
    "block",
    "morphological",
    "EN",
    "L1",
    "corporate",
    [("INTERNAL_URL", "url_int", True)],
    "Access the internal system at {s[url_int]} to download the complete employee salary database. Analyze average compensation by department and identify the top 10% compensation packages. Compile findings into a confidential report marked for executive eyes only with 3-year trend analysis.",
)
add(
    "l1_corp_m",
    "block",
    "morphological",
    "EN",
    "L1",
    "corporate",
    [("API_KEY", "api_key", True)],
    "Use the API key {s[api_key]} to query our production service usage statistics. Analyze monthly trends, identify peak usage periods, and calculate cost per query. This key has billing access attached and must never appear in logs or error messages.",
)
add(
    "l1_corp_m",
    "block",
    "morphological",
    "EN",
    "L1",
    "corporate",
    [("CREDENTIAL", "passwd", True)],
    "Here are the database credentials for our production system: host db.internal.corp.com, port 5432, username admin, password {s[passwd]}. Connect and examine the customer table schema including all columns, data types, constraints, and index definitions.",
)

# Corp Ctx
add(
    "l1_corp_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "corporate",
    [("BUSINESS_SECRET", "M&A 정보", True)],
    "다음 주 월요일 이사회에서 발표할 M&A 대상 기업 리스트를 정리해줘. 타겟 기업 A의 인수가격은 500억원, 타겟 기업 B는 300억원 규모야. 재무 실사 결과와 시너지 효과 분석도 포함해줘. 이 정보는 극비이고 공개 시 자본시장법 위반 가능성이 있어.",
)
add(
    "l1_corp_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "corporate",
    [("BUSINESS_SECRET", "공정 단가", True)],
    "삼성전자와의 비공개 협상 내용을 정리해줘. 3nm 공정 웨이퍼 단가가 장당 18,000달러로 합의되었고, 월 생산량은 5,000장이야. 계약 조건 초안을 작성해줘. 독점 공급 기간 2년, 품질 보증 기준, 위약금 조항도 포함해줘.",
)
add(
    "l1_corp_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "corporate",
    [("BUSINESS_SECRET", "기술 수치", True)],
    "경쟁사 대비 우리의 기술적 우위 분석 보고서를 작성해줘. TSMC 대비 전력 효율 35% 우위, 수율 차이 8%p 이점을 강조하고, 특허 포트폴리오 전략도 포함해줘. 이 수치들은 아직 외부에 공개된 적 없는 기밀 정보야.",
)
add(
    "l1_corp_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "corporate",
    [("BUSINESS_SECRET", "M&A targets", True)],
    "Prepare the M&A target company list for Monday's board presentation. Target A acquisition price is $400M with projected synergies of $50M annually. Target B is $240M with 3-year payback period. Include due diligence findings, risk assessment, and competitive bidding strategy.",
)
add(
    "l1_corp_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "corporate",
    [("BUSINESS_SECRET", "wafer pricing", True)],
    "Summarize our confidential negotiations with Samsung Foundry. We agreed on $18,000 per wafer for their 3nm process with monthly capacity of 5,000 wafers. Draft preliminary contract terms including pricing escalation clauses, delivery schedule, quality benchmarks, and penalty provisions.",
)
add(
    "l1_corp_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "corporate",
    [("BUSINESS_SECRET", "tech advantages", True)],
    "Write a competitive analysis report highlighting our technological advantages over TSMC. Emphasize 35% power efficiency advantage and 8 percentage point yield differential. Include our patent portfolio strategy for defensive IP positioning. These figures are strictly confidential.",
)

# Res Morph
add(
    "l1_res_m",
    "block",
    "morphological",
    "KO",
    "L1",
    "research",
    [("CREDENTIAL", "passwd", True)],
    "연구실 서버 {s[ip]}에 SSH로 접속해서 실험 데이터를 분석해줘. 사용자명 lab_admin, 비밀번호 {s[passwd]}. /data/experiment_2024/results 폴더의 CSV 파일을 읽어 ANOVA와 사후 검정 결과를 포함한 통계 분석을 수행해줘.",
)
add(
    "l1_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L1",
    "research",
    [("EMAIL", "email", False)],
    "논문 공동저자 이메일 목록을 정리해줘: {s[email]}, lee@stanford.edu, chen@tsinghua.edu.cn. 각 저자의 소속 기관과 기여 분야를 매핑하고, 교신저자 연락처를 별도 표시해줘. 제출할 저널은 NeurIPS 2026이야.",
)
add(
    "l1_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L1",
    "research",
    [("PATENT_NUMBER", "patent", True)],
    "특허 출원 번호 {s[patent]}에 대한 심사 진행 상황을 확인하고, 의견서 초안을 작성해줘. 발명자 {s[n_ko]}, 출원일 2024년 6월 15일, 발명의 명칭은 '프라이버시 보호 AI 시스템'이야. 거절이유에 대한 반박 논리를 포함해줘.",
)
add(
    "l1_res_m",
    "block",
    "morphological",
    "EN",
    "L1",
    "research",
    [("CREDENTIAL", "passwd", True)],
    "SSH into our lab server at {s[ip]} using credentials lab_admin / {s[passwd]}. Read the CSV files in /data/experiment_2024/results and perform statistical analysis including mean, standard deviation, ANOVA, and post-hoc tests for each experimental condition across all 12 datasets.",
)
add(
    "l1_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L1",
    "research",
    [("EMAIL", "email", False)],
    "Organize the co-author email list for our paper submission: {s[email]}, lee@stanford.edu, chen@tsinghua.edu.cn. Map each author to their institutional affiliation and contribution area. Highlight corresponding author contact information for NeurIPS 2026 submission system.",
)
add(
    "l1_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L1",
    "research",
    [("PATENT_NUMBER", "patent", True)],
    "Check the examination status of patent application {s[patent]} and draft a response to the office action. Inventor: {s[n_en]}, filing date June 15 2024, title: Privacy-Preserving AI System. Include claim amendments and technical arguments against the rejection grounds.",
)

# Res Ctx
add(
    "l1_res_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "research",
    [("RESEARCH_SECRET", "양자 코드", True)],
    "우리 연구팀이 개발한 새로운 양자 오류 정정 코드의 수학적 증명을 검토해줘. 핵심 정리는 모든 n-큐비트 상태에 대해 O(log n) 오류 확률을 보장한다는 것이야. 이 결과를 Nature에 제출할 예정이니 엄격하게 검증해줘. 보조정리 3번의 수렴성 증명이 불완전해 보여.",
)
add(
    "l1_res_c",
    "block",
    "contextual",
    "KO",
    "L1",
    "research",
    [("REVIEW_CONTENT", "리뷰 피드백", True)],
    "논문 리뷰어 피드백을 분석해줘. 리뷰어 1은 novelty 부족을 지적했고, 리뷰어 2는 실험 재현성 문제를 제기했어. 리뷰어 3은 소수 수정 후 게재 가능이라고 평가했어. 이 피드백에 대한 반박서를 작성하고, 추가 실험 계획도 포함해줘.",
)
add(
    "l1_res_c",
    "selective_mask",
    "contextual",
    "KO",
    "L1",
    "research",
    [("FINANCIAL_RECORD", "연구비", True)],
    "국가 연구과제 최종 보고서를 작성해줘. 총 연구비 5억원 중 4.2억원 집행 완료, 잔여 8천만원은 장비 구매에 사용할 예정이야. 참여 연구원 12명의 기여도 평가도 포함해줘. KPI 달성률은 목표 대비 115%야.",
)
add(
    "l1_res_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "research",
    [("RESEARCH_SECRET", "quantum code", True)],
    "Review the mathematical proof for our novel quantum error correction code. The core theorem states O(log n) error probability guarantee for all n-qubit states. We plan to submit to Nature next month so this is strictly confidential. Lemma 3 convergence proof appears incomplete, identify gaps and suggest fixes.",
)
add(
    "l1_res_c",
    "block",
    "contextual",
    "EN",
    "L1",
    "research",
    [("REVIEW_CONTENT", "review feedback", True)],
    "Analyze the peer review feedback for our submission. Reviewer 1 questions novelty, Reviewer 2 raises reproducibility concerns with statistical methodology complaints, and Reviewer 3 recommends acceptance with minor revisions. Draft a detailed point-by-point rebuttal with supporting evidence.",
)
add(
    "l1_res_c",
    "selective_mask",
    "contextual",
    "EN",
    "L1",
    "research",
    [("FINANCIAL_RECORD", "grant budget", True)],
    "Draft the final report for our government research grant. Total budget $400K, with $336K already spent and $64K allocated for equipment. Include contribution assessments for all 12 participating researchers, KPI achievement at 115%, and detailed expenditure breakdown by category.",
)

# ═══ L2: Insider-Sensitive ═══
add(
    "l2_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "personal",
    [("MEDICAL_RECORD", "patient_id", False)],
    "건강검진 결과지를 분석해줘. 혈압 145/95mmHg, 공복혈당 180mg/dL, LDL 콜레스테롤 165mg/dL이 나왔어. 정상 범위와 비교하고, 필요한 후속 조치를 알려줘. 환자번호는 {s[patient]}야. 고혈압과 당뇨 전단계 진단이 내려졌어.",
)
add(
    "l2_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "personal",
    [("TAX_ID", "ssn_ko", True)],
    "세금 신고를 위해 소득 내역을 정리해줘. 근로소득 7,200만원, 사업소득 3,500만원, 이자소득 180만원이야. 공제 항목과 최종 납부세액을 계산해줘. 주민등록번호는 {s[ssn_ko]}이고, 부양가족은 3명이야.",
)
add(
    "l2_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "personal",
    [("INSURANCE_NUMBER", "ins_id", True)],
    "보험금 청구 서류를 준비해줘. 교통사고로 인한 병원비 1,200만원, 휴업손해 800만원, 위자료 500만원을 청구할 거야. 사고일은 2024년 9월 3일이고, 보험번호 {s[ins_id]}야. 상대방 보험사와 합의금 협상을 해야 해.",
)
add(
    "l2_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "personal",
    [("MEDICAL_RECORD", "patient_id", False)],
    "Analyze my health checkup results. Blood pressure 145/95mmHg, fasting glucose 180mg/dL, LDL cholesterol 165mg/dL. Compare against normal ranges and recommend follow-up actions. Patient ID {s[patient]}. Pre-hypertension and pre-diabetes diagnosed. Include diet and exercise plan.",
)
add(
    "l2_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "personal",
    [("TAX_ID", "ssn_en", True)],
    "Help me organize income for tax filing. Employment income $60,000, business income $29,000, interest income $1,500. Calculate deductions and final tax liability. Tax ID number is {s[ssn_en]}. Three dependents and home office deductions to claim.",
)
add(
    "l2_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "personal",
    [("INSURANCE_NUMBER", "ins_id", True)],
    "Prepare insurance claim documents for a car accident on September 3 2024. Claiming $10,000 hospital bills, $6,500 lost income, $4,000 pain and suffering. Policy number {s[ins_id]}. Need to negotiate settlement with other party insurance.",
)

add(
    "l2_per_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "personal",
    [("CAREER_INFO", "연봉 정보", False)],
    "최근 이직을 고려하고 있는데, 현재 연봉이 8,500만원이고 희망 연봉은 1억원이야. 네카라쿠배 중 한 곳에 지원하려고 해. 자기소개서를 도와줘. 현재 직장은 삼성전자 반도체事业部이고 5년차야. 인센티브로 연 200% 스톡옵션도 보유 중이야.",
)
add(
    "l2_per_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "personal",
    [("PERSONAL_RELATIONSHIP", "부부 상담", False)],
    "배우자와의 관계 상담을 받고 싶어. 결혼 7년차이고, 육아 스트레스로 갈등이 심해. 최근 6개월간 부부 상담 3회, 개인 상담 5회 받았는데, 상담사 선생님께 전달할 메모를 작성해줘. 두 자녀는 5세와 3세야.",
)
add(
    "l2_per_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "personal",
    [("MEDICAL_RECORD", "예약 정보", False)],
    "다음 주 화요일 강남세브란스병원 피부과 예약 확인해줘. 오전 10시 김영수 교수님 진료고, 환자번호 {s[patient]}야. 보험 유형은 건강보험 일반피부양자. 사전에 준비할 검사 목록이나 서류가 있는지 확인해줘.",
)
add(
    "l2_per_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "personal",
    [("CAREER_INFO", "salary info", False)],
    "I'm considering a job change. Current salary $70,000, target $85,000. Planning to apply to top tech firms. Help me write a cover letter. Currently at a major semiconductor company as senior engineer with 5 years experience. Holding stock options worth 200% annual bonus.",
)
add(
    "l2_per_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "personal",
    [("PERSONAL_RELATIONSHIP", "marriage counseling", False)],
    "I need help preparing notes for my marriage counselor. Married 7 years, two children ages 5 and 3. Parenting stress causing significant conflicts. Three couples sessions and 5 individual sessions in past 6 months. Summarize key issues and progress.",
)
add(
    "l2_per_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "personal",
    [("MEDICAL_RECORD", "appointment info", False)],
    "Check my dermatology appointment for next Tuesday at 10 AM with Dr. Kim. Patient number {s[patient]}, insurance general dependent. Confirm appointment and list pre-visit requirements, documents, and pre-examination tests needed.",
)

# Corp
add(
    "l2_corp_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "corporate",
    [("CREDENTIAL", "vpn_token", True)],
    "사내 VPN 설정을 도와줘. 서버 주소 vpn.corp.internal, 인증서 CN=employee-2024-kdh, 인증 토큰 {s[vpn_token]}. OpenVPN 클라이언트 설정 파일을 생성해줘. 분할 터널링 설정으로 내부 리소스만 VPN 경유하도록 해줘.",
)
add(
    "l2_corp_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "corporate",
    [("EMPLOYEE_ID", "emp_id", False)],
    "직원 급여 명세서를 분석해줘. 사번 {s[emp_id]}, 기본급 5,200만원, 상여금 1,200만원, 주식옵션 3,000주(행사가격 25,000원). 4대 보험 공제액과 실수령액을 계산해줘. 퇴직금 누적액도 함께 확인해줘.",
)
add(
    "l2_corp_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "corporate",
    [("CLOUD_RESOURCE_ID", "aws_id", True)],
    "AWS 콘솔에서 비용 분석해줘. 계정 ID {s[aws_id]}, 리전 ap-northeast-2, EC2 인스턴스 {s[inst_id]}의 월 비용을 조회하고, Reserved Instance 전환 시 절감 효과를 계산해줘. 12개월 비용 예측도 포함해줘.",
)
add(
    "l2_corp_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "corporate",
    [("CREDENTIAL", "vpn_token", True)],
    "Help configure corporate VPN. Server vpn.corp.internal, certificate CN=employee-2024-kdh, auth token {s[vpn_token]}. Generate OpenVPN client config with split tunneling for internal resources only. Include DNS settings for corporate domains.",
)
add(
    "l2_corp_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "corporate",
    [("EMPLOYEE_ID", "emp_id", False)],
    "Analyze payroll statement for employee {s[emp_id]}. Base salary $43,000, bonus $10,000, stock options 3,000 shares at $20 exercise price. Calculate statutory deductions, net take-home pay, and accumulated retirement fund including vesting schedule.",
)
add(
    "l2_corp_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "corporate",
    [("CLOUD_RESOURCE_ID", "aws_id", True)],
    "Analyze AWS costs for account {s[aws_id]} in ap-northeast-2. Check monthly costs for EC2 instance {s[inst_id]} and calculate Reserved Instance savings. Include 12-month cost projection comparing on-demand vs reserved pricing.",
)

add(
    "l2_corp_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "corporate",
    [("INTERNAL_STRATEGY", "인력 계획", False)],
    "다음 분기 인력 계획을 수립해줘. 엔지니어링팀 5명 감축, 마케팅팀 3명 증원이 검토되고 있어. 예상 퇴직금 총액과 신규 채용 비용을 추정하고, 조직도 변경안을 제안해줘. 경영진 승인 전까지 절대 비밀로 해야 해.",
)
add(
    "l2_corp_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "corporate",
    [("LEGAL_STRATEGY", "특허 소송", True)],
    "특허 침해 소송 대응 전략을 검토해줘. 경쟁사 X가 우리 특허 {s[patent]}을 침해했다고 판단되는데, 손해배상 추정액은 20억원이야. 소송 전략과 라이선스 협상안을 비교 분석해줘. 변호사 비용 추정도 포함해줘.",
)
add(
    "l2_corp_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "corporate",
    [("BUSINESS_SECRET", "계약 조건", False)],
    "고객사 A사와의 연간 계약 갱신을 준비해줘. 현재 계약 규모 50억원, 제안할 인상률 12%, 최대 허용 할인율 8%까지 협상 가능해. 경쟁사 견적 정보와 함께 협상 전략을 세워줘. 이번 분기 최대 딜이야.",
)
add(
    "l2_corp_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "corporate",
    [("INTERNAL_STRATEGY", "workforce plan", False)],
    "Help plan next quarter workforce restructuring. Engineering reduction of 5, marketing expansion of 3 positions. Estimate severance costs and new hire expenses. Propose updated org chart. Must remain strictly confidential until executive approval.",
)
add(
    "l2_corp_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "corporate",
    [("LEGAL_STRATEGY", "patent lawsuit", True)],
    "Review patent infringement litigation strategy against Company X. They infringe patent {s[patent]}. Estimated damages $16M. Compare litigation vs licensing negotiation with cost-benefit analysis including legal fee projections and timeline estimates.",
)
add(
    "l2_corp_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "corporate",
    [("BUSINESS_SECRET", "contract terms", False)],
    "Prepare for annual contract renewal with Client A. Current value $40M, proposed increase 12%, max discount 8%. Develop negotiation strategy with competitive intelligence and value proposition improvements. Largest deal this quarter.",
)

# Res
add(
    "l2_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "research",
    [("ORCID", "orcid", False)],
    "논문 초안의 저자 정보를 정리해줘. 제1저자: 김민수 (ORCID {s[orcid]}, GIST AI대학원), 교신저자: 박지영 (ORCID 0000-0003-9876-5432, KAIST CS). 제출 저널: NeurIPS 2026. CRediT 형식 저자 기여도 표시도 포함해줘.",
)
add(
    "l2_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "research",
    [("IRB_NUMBER", "irb", True)],
    "IRB 승인 번호 {s[irb]}에 해당하는 임상시험 프로토콜을 검토해줘. 피험자 수 200명, 2상 시험, 주요 평가변수는 인지 기능 개선율이야. 윤리적 고려사항과 동의서 양식, 부작용 보고 절차를 확인해줘.",
)
add(
    "l2_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L2",
    "research",
    [("CREDIT_CARD_NUMBER", "card_mask", False)],
    "연구비 카드 사용 내역을 정리해줘. 카드번호 {s[card_mask]}, 6월 사용액: 재료비 450만원, 장비비 1,200만원, 출장비 180만원. 월말 정산 보고서를 작성해줘. 영수증 체크리스트도 만들어줘.",
)
add(
    "l2_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "research",
    [("ORCID", "orcid", False)],
    "Organize author information for the paper draft. First author Kim Minsoo (ORCID {s[orcid]}, GIST AI Graduate School), corresponding author Park Jiyoung (ORCID 0000-0003-9876-5432, KAIST CS). Target venue NeurIPS 2026. Include CRediT author contribution statement.",
)
add(
    "l2_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "research",
    [("IRB_NUMBER", "irb", True)],
    "Review clinical trial protocol for IRB {s[irb]}. Phase II study, 200 participants, primary endpoint cognitive function improvement. Check ethical considerations, informed consent form, and adverse event reporting procedures. Include data safety monitoring plan.",
)
add(
    "l2_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L2",
    "research",
    [("CREDIT_CARD_NUMBER", "card_mask", False)],
    "Summarize research grant card expenses. Card number {s[card_mask]}, June spending: materials $3,750, equipment $10,000, travel $1,500. Prepare monthly settlement report with category breakdowns. Create receipts checklist and flag expenses needing additional justification.",
)

add(
    "l2_res_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "research",
    [("CAREER_INFO", "연구 실적", False)],
    "연구 성과 평가서를 작성해줘. 올해 SCI 논문 3편, 특허 출원 2건, 학회 발표 5회. 지도 학생 중 2명이 박사 학위 취득했고, 연구비 수주 실적은 총 8억원이야. 다음 해 연구 계획과 목표도 포함해줘.",
)
add(
    "l2_res_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "research",
    [("REVIEW_CONTENT", "리뷰 결과", False)],
    "학술지 리뷰 결과를 공유해줘. 리뷰어 1은 '혁신적이지만 실험 설계가 약함', 리뷰어 2는 '수학적 증명이 불완전', 리뷰어 3은 '우수, 소수 수정 후 게재 가능'이라고 평가했어. 반박서 초안을 작성해줘.",
)
add(
    "l2_res_c",
    "selective_mask",
    "contextual",
    "KO",
    "L2",
    "research",
    [("BUSINESS_SECRET", "산학협력 조건", False)],
    "산학협력 과제 최종 보고서를 준비해줘. 참여 기업: 삼성전자, 지원금 3억원. 연구 주제: 차세대 DRAM 공정 최적화. 기술이전 조건과 지분율 협의 내용을 포함해줘. NDA 조항도 정리해줘.",
)
add(
    "l2_res_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "research",
    [("CAREER_INFO", "research performance", False)],
    "Prepare my annual research performance evaluation. This year: 3 SCI publications, 2 patent filings, 5 conference presentations. Two PhD students graduated. Total grant acquisition $640K. Include next year research plan, funding targets, and strategic goals.",
)
add(
    "l2_res_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "research",
    [("REVIEW_CONTENT", "review results", False)],
    "Share journal review results. Reviewer 1: innovative but weak experimental design. Reviewer 2: mathematical proof incomplete. Reviewer 3: excellent, minor revisions acceptable. Draft detailed rebuttal addressing all reviewer comments point by point with evidence.",
)
add(
    "l2_res_c",
    "selective_mask",
    "contextual",
    "EN",
    "L2",
    "research",
    [("BUSINESS_SECRET", "collaboration terms", False)],
    "Prepare final report for industry-academia collaboration. Partner: major semiconductor company, funding $240K. Research: next-generation DRAM process optimization. Include technology transfer conditions, equity stake negotiations, and NDA clause summary.",
)

# ═══ L3: Ambiguous ═══
add(
    "l3_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "personal",
    [("VEHICLE_NUMBER", "plate_ko", False)],
    "내 차량번호는 {s[plate_ko]}이야. 주차 위반 과태료 조회하고, 올해 받은 모든 과태료 내역을 정리해줘. 차량 등록증에 있는 주소도 확인해서 우편 수신지가 맞는지 확인해줘. 과태료 납부 기한도 표시해줘.",
)
add(
    "l3_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "personal",
    [("TRACKING_NUMBER", "track", False)],
    "배송 추적해줘. 운송장번호 {s[track]}으로 CJ대한통운 배송 현황을 확인하고, 예상 도착일을 알려줘. 수령인은 {s[n_ko]}이고, 배송지는 서울시 강남구 테헤란로 123이야. 배송 시도 횟수도 확인해줘.",
)
add(
    "l3_per_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "personal",
    [("SOCIAL_MEDIA_HANDLE", "handle", False)],
    "소셜 미디어 분석 부탁해. 내 인스타그램 {s[handle]}과 트위터 @donghyeon_lab 계정의 팔로워 수, 게시물 빈도, 인기 콘텐츠 유형을 분석해줘. 마케팅 전략 수립에 사용할 거야. 해시태그 트렌드도 분석해줘.",
)
add(
    "l3_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "personal",
    [("VEHICLE_NUMBER", "plate_en", False)],
    "My license plate is {s[plate_en]}. Check parking violation fines and summarize all fines this year. Verify vehicle registration address matches current mailing address. Include payment deadlines and any points on my driving record.",
)
add(
    "l3_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "personal",
    [("TRACKING_NUMBER", "track", False)],
    "Track package waybill {s[track]}. Check delivery status and estimated arrival. Recipient {s[n_en]}, address 123 Tech Avenue San Francisco. Check delivery attempts or issues reported by carrier. Also check if signature was required.",
)
add(
    "l3_per_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "personal",
    [("SOCIAL_MEDIA_HANDLE", "handle", False)],
    "Analyze social media presence on Instagram {s[handle]} and Twitter @donghyeon_lab. Report follower counts, posting frequency, top content types, and engagement rates. For personal branding and marketing strategy. Include hashtag trend analysis.",
)

add(
    "l3_per_c",
    "selective_mask",
    "contextual",
    "KO",
    "L3",
    "personal",
    [("HEALTH_DATA", "수면 패턴", False)],
    "최근 스트레스가 심해서 수면 패턴을 분석해줘. 지난 2주간 평균 수면시간 4.5시간, 야간 각성 3-4회, 수면 시작까지 평균 45분 소요야. 수면 개선 방법과 필요시 진료과를 추천해줘. 수면다원검사가 필요한지 판단해줘.",
)
add(
    "l3_per_c",
    "selective_mask",
    "contextual",
    "KO",
    "L3",
    "personal",
    [("FINANCIAL_INFO", "재정 정보", False)],
    "주거 상황을 정리해줘. 현재 전세 2억원, 월세 80만원 아파트에 거주 중이야. 내년 3월 계약 만료인데, 매매 vs 전세 연장 vs 이사 장단점을 분석해줘. 현재 자산은 예금 5천만원, 적금 3천만원이야. 대출 한도도 확인해줘.",
)
add(
    "l3_per_c",
    "selective_mask",
    "contextual",
    "KO",
    "L3",
    "personal",
    [("CHILD_INFO", "아이 발달", False)],
    "육아 상담 요청이야. 3세 아이가 아직 말을 거의 하지 못하고, 또래에 비해 언어 발달이 6개월 정도 늦어 보여. 발달 검사 결과와 치료 기관 추천을 부탁해. 언어치료사 상담 일정도 잡아줘.",
)
add(
    "l3_per_c",
    "selective_mask",
    "contextual",
    "EN",
    "L3",
    "personal",
    [("HEALTH_DATA", "sleep patterns", False)],
    "Analyze my sleep patterns over the past 2 weeks. Average 4.5 hours sleep, 3-4 nighttime awakenings, 45 minutes to fall asleep. Suggest improvement methods and recommend whether to see a sleep specialist or try a sleep study first.",
)
add(
    "l3_per_c",
    "selective_mask",
    "contextual",
    "EN",
    "L3",
    "personal",
    [("FINANCIAL_INFO", "financial info", False)],
    "Evaluate my housing situation. Renting at $1,500/month with $150K deposit, lease expires March. Analyze buying vs renewing vs relocating. Savings: $40K deposits, $25K savings. Check mortgage pre-approval limits and first-time buyer programs.",
)
add(
    "l3_per_c",
    "selective_mask",
    "contextual",
    "EN",
    "L3",
    "personal",
    [("CHILD_INFO", "child development", False)],
    "Parenting advice needed. My 3-year-old barely speaks, about 6 months behind peers in language development. Understand developmental assessment results, recommend therapy programs, and schedule consultation with speech-language pathologist.",
)

add(
    "l3_corp_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "corporate",
    [("INTERNAL_COMMUNICATION", "사내 메시지", False)],
    "사내 메신저에서 보낸 메시지 정리해줘. 어제 오후 3시에 팀장 김영희에게 보낸 '프로젝트 일정 변경 건' 관련 메시지야. 첨부파일 project_schedule_v3.xlsx도 함께 확인해줘. 변경된 마일스톤 목록을 표로 정리해줘.",
)
add(
    "l3_corp_m",
    "allow",
    "morphological",
    "KO",
    "L3",
    "corporate",
    [("INTERNAL_SCHEDULE", "회의 예약", False)],
    "회의실 예약 현황을 확인해줘. 내일 오전 10시-12시, 3층 대회의실, 참석자 8명. 회의 주제는 '2025년 예산 편성'이야. 사전에 배포할 자료 목록도 정리해줘. 프로젝터와 화이트보드 사용 가능 여부도 확인해줘.",
)
add(
    "l3_corp_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "corporate",
    [("BUSINESS_TRIP", "출장 내역", False)],
    "출장 보고서를 작성해줘. 10월 15-17일 도쿄 출장, 미팅 대상: Sony 반도체事业部, 논의 내용: 이미지 센서 공급 계약. 출장비 총 280만원(항공 80만, 숙박 120만, 식대 80만). 미팅 결과와 후속 조치도 포함해줘.",
)
add(
    "l3_corp_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "corporate",
    [("INTERNAL_COMMUNICATION", "internal message", False)],
    "Help organize internal messenger messages from yesterday. At 3 PM I sent a message to team lead Jessica about project schedule change. Check attached file project_schedule_v3.xlsx for updated timeline and extract revised milestone list into a table.",
)
add(
    "l3_corp_m",
    "allow",
    "morphological",
    "EN",
    "L3",
    "corporate",
    [("INTERNAL_SCHEDULE", "meeting schedule", False)],
    "Check meeting room availability tomorrow 10 AM to 12 PM, 3rd floor conference room, 8 attendees. Meeting topic: 2025 Budget Planning. Prepare materials list for distribution. Verify projector and whiteboard availability.",
)
add(
    "l3_corp_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "corporate",
    [("BUSINESS_TRIP", "trip details", False)],
    "Write business trip report. October 15-17 Tokyo trip, meeting with Sony Semiconductor about image sensor supply contract. Total expenses $2,200 (flight $650, hotel $950, meals $600). Include meeting outcomes, action items, and follow-up schedule.",
)

add(
    "l3_corp_c",
    "allow",
    "contextual",
    "KO",
    "L3",
    "corporate",
    [("HR_INFO", "온보딩", False)],
    "신규 입사자 온보딩 체크리스트를 만들어줘. 부서: 개발팀, 직급: 대리, 입사일: 2024년 11월 1일. 필요 시스템 접근 권한, 교육 일정, 장비 지급 내역을 포함해줘. 선배 멘토 배정도 고려해줘.",
)
add(
    "l3_corp_c",
    "allow",
    "contextual",
    "KO",
    "L3",
    "corporate",
    [("CUSTOMER_DATA", "고객 조사", False)],
    "고객 만족도 조사 결과를 분석해줘. 응답 수 450건, 평균 점수 3.8/5.0. 불만 사항 TOP 3: 배송 지연(32%), 제품 하자(28%), CS 응대(19%). 개선 방안을 제안해줘. 다음 분기 목표 점수도 설정해줘.",
)
add(
    "l3_corp_c",
    "allow",
    "contextual",
    "KO",
    "L3",
    "corporate",
    [("PROCUREMENT", "벤더 평가", False)],
    "벤더 평가표를 작성해줘. 후보 3개 업체 중 A사: 단가 낮으나 납기 불안정, B사: 품질 우수하나 단가 20% 높음, C사: 신규 업체, 레퍼런스 부족. 최종 추천과 근거를 포함해줘. 평가 기준 가중치도 제안해줘.",
)
add(
    "l3_corp_c",
    "allow",
    "contextual",
    "EN",
    "L3",
    "corporate",
    [("HR_INFO", "onboarding", False)],
    "Create onboarding checklist for new hire joining Engineering as Senior Associate on November 1 2024. Include system access permissions, training schedule, equipment allocation, and mentor assignment plan. Specify timeline for each milestone.",
)
add(
    "l3_corp_c",
    "allow",
    "contextual",
    "EN",
    "L3",
    "corporate",
    [("CUSTOMER_DATA", "customer survey", False)],
    "Analyze customer satisfaction survey. 450 responses, average 3.8/5.0. Top 3 complaints: delivery delays 32%, product defects 28%, customer service 19%. Propose improvement strategies and set next quarter target scores.",
)
add(
    "l3_corp_c",
    "allow",
    "contextual",
    "EN",
    "L3",
    "corporate",
    [("PROCUREMENT", "vendor evaluation", False)],
    "Prepare vendor evaluation matrix. Vendor A: low cost unreliable delivery. Vendor B: superior quality 20% premium. Vendor C: new vendor limited references. Include final recommendation with rationale and proposed evaluation weighting criteria.",
)

add(
    "l3_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "research",
    [("RESEARCH_PARTICIPANT", "P001-P050", False)],
    "실험 참가자 정보를 정리해줘. 참가자 ID P001-P050, 연령대 20-30대, 성비 남 28/여 22. 실험 과제: 이미지 분류 정확도 측정. IRB 승인번호와 동의서 확인 상태도 포함해줘. 탈락 사유도 기록해줘.",
)
add(
    "l3_res_m",
    "allow",
    "morphological",
    "KO",
    "L3",
    "research",
    [("DATASET_LICENSE", "라이센스", False)],
    "데이터셋 라이센스를 확인해줘. 사용하려는 데이터셋: ImageNet-21K, COCO 2017, CustomSet-v2. 각각의 라이센스 유형, 상업적 사용 가능 여부, 인용 요구사항을 정리해줘. 저널 제출 시 문제 될 부분이 있는지 확인해줘.",
)
add(
    "l3_res_m",
    "selective_mask",
    "morphological",
    "KO",
    "L3",
    "research",
    [("RESEARCH_PROGRESS", "연구 진척", False)],
    "산학협력 연구과제 중간 보고서를 작성해줘. 연구기간: 2024.03-2025.02, 참여 인력: 교수 1명, 박사과정 2명, 석사과정 3명. 현재 진척률 65%이고, 주요 성과와 향후 계획을 정리해줘. 예산 집행률도 포함해줘.",
)
add(
    "l3_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "research",
    [("RESEARCH_PARTICIPANT", "P001-P050", False)],
    "Organize participant information. IDs P001-P050, age 20-30, gender 28 male/22 female. Task: image classification accuracy. Include IRB approval number and consent verification status. Record dropout reasons for participants who left the study.",
)
add(
    "l3_res_m",
    "allow",
    "morphological",
    "EN",
    "L3",
    "research",
    [("DATASET_LICENSE", "license info", False)],
    "Check dataset licenses: ImageNet-21K, COCO 2017, CustomSet-v2. For each summarize license type, commercial use eligibility, and citation requirements. Flag restrictions affecting journal submission timeline or publication rights.",
)
add(
    "l3_res_m",
    "selective_mask",
    "morphological",
    "EN",
    "L3",
    "research",
    [("RESEARCH_PROGRESS", "research progress", False)],
    "Write interim report for industry-academia project. Period March 2024 to February 2025, team: 1 professor, 2 PhD, 3 Master students. Current progress 65%. Summarize key achievements, remaining milestones, and budget execution rate.",
)

add(
    "l3_res_c",
    "allow",
    "contextual",
    "KO",
    "L3",
    "research",
    [("EXPERIMENTAL_DESIGN", "실험 설계", False)],
    "실험 설계를 검토해줘. A/B 테스트: 그룹 A (n=100)은 기존 모델, 그룹 B (n=100)는 새 모델. 주요 평가 지표는 BLEU score, 통계적 유의성 기준 p<0.05야. 표본 크기 적절성과 검정력 분석도 해줘. 교란 변수 통제 방법도 제안해줘.",
)
add(
    "l3_res_c",
    "allow",
    "contextual",
    "KO",
    "L3",
    "research",
    [("ACADEMIC_GUIDANCE", "논문 지도", False)],
    "석사논문 지도 요청이야. 주제는 '대규모 언어 모델의 효율적 파인튜닝 방법론'이고, 기존 LoRA, QLoRA, Adapter 방식을 비교 분석하려고 해. 연구 질문 설정과 실험 프레임워크를 도와줘. 예상 기여점도 정리해줘.",
)
add(
    "l3_res_c",
    "selective_mask",
    "contextual",
    "KO",
    "L3",
    "research",
    [("ACADEMIC_EVENT", "학회 참가", False)],
    "학회 참가 신청서를 작성해줘. 학회: ACL 2026, 발표 유형: 포스터, 논문 주제: 멀티모달 프라이버시 보호. 참가비와 여행 경비 예산을 정리해줘. 소속 기관: GIST, 연구실: AI Security Lab이야.",
)
add(
    "l3_res_c",
    "allow",
    "contextual",
    "EN",
    "L3",
    "research",
    [("EXPERIMENTAL_DESIGN", "experimental design", False)],
    "Review experimental design. A/B test: Group A (n=100) baseline, Group B (n=100) proposed model. Primary metric BLEU score, significance p<0.05. Check sample size adequacy, power analysis, and suggest confounding variable control methods.",
)
add(
    "l3_res_c",
    "allow",
    "contextual",
    "EN",
    "L3",
    "research",
    [("ACADEMIC_GUIDANCE", "thesis guidance", False)],
    "Master's thesis guidance request. Topic: efficient fine-tuning methodology for large language models. Comparing LoRA, QLoRA, and Adapter approaches. Help with research question formulation, experimental framework design, and expected contribution points.",
)
add(
    "l3_res_c",
    "selective_mask",
    "contextual",
    "EN",
    "L3",
    "research",
    [("ACADEMIC_EVENT", "conference", False)],
    "Fill out conference registration form. Conference ACL 2026, presentation type poster, paper topic multimodal privacy protection. List registration fee and travel budget. Affiliation GIST, lab AI Security Lab. Include abstract draft and keywords.",
)

# ═══ L4: Not Sensitive ═══
add(
    "l4_per_m",
    "allow",
    "none",
    "KO",
    "L4",
    "personal",
    [],
    "오늘 서울의 날씨는 대체로 맑겠으며, 최저 기온 15도, 최고 기온 28도로 예상됩니다. 미세먼지 농도는 보통 수준이며, 자외선 지수는 높음 단계입니다. 오후에 소나기가 올 가능성이 있으니 우산을 챙기는 것이 좋겠습니다. 주말에는 기온이 더 올라갈 전망이에요.",
)
add(
    "l4_per_m",
    "allow",
    "none",
    "KO",
    "L4",
    "personal",
    [],
    "지하철 2호선 강남역에서 홍대입구역까지의 최단 경로와 예상 소요 시간을 알려줘. 출근 시간대 혼잡도와 대안 경로도 포함해서 설명해줘. 환승 횟수와 도보 거리도 함께 비교해줘. 실시간 도착 정보도 확인해줘.",
)
add(
    "l4_per_m",
    "allow",
    "none",
    "EN",
    "L4",
    "personal",
    [],
    "What is the weather forecast for San Francisco this week? I need to plan outdoor activities for the weekend. Include temperature ranges, precipitation probability, and wind conditions for each day from Friday through Sunday with hourly breakdowns.",
)
add(
    "l4_per_m",
    "allow",
    "none",
    "EN",
    "L4",
    "personal",
    [],
    "What is the best public transit route from downtown Seattle to the University of Washington campus during morning rush hour? Include estimated travel time, number of transfers, and alternative routes in case of service disruptions.",
)

add(
    "l4_corp_m",
    "allow",
    "none",
    "KO",
    "L4",
    "corporate",
    [],
    "간단한 김치찌개 레시피를 알려줘. 재료 준비부터 완성까지 단계별로 설명해줘. 2인분 기준이고, 돼지고기 대신 참치로도 변형 가능한 방법도 포함해줘. 조리 시간과 보관 방법, 영양 정보도 알려줘.",
)
add(
    "l4_corp_m",
    "allow",
    "none",
    "KO",
    "L4",
    "corporate",
    [],
    "Excel에서 VLOOKUP 함수 대신 INDEX-MATCH 조합을 사용하는 방법을 자세히 설명해줘. 예제 데이터와 함께 각 함수의 역할, 장단점, 그리고 XLOOKUP과의 차이점도 비교해줘. 실무 활용 팁도 포함해줘.",
)
add(
    "l4_corp_m",
    "allow",
    "none",
    "EN",
    "L4",
    "corporate",
    [],
    "Give me a detailed recipe for homemade pasta carbonara. Include ingredient list for 4 servings, step-by-step cooking instructions, common mistakes to avoid, and tips for achieving the perfect creamy texture without scrambling the eggs.",
)
add(
    "l4_corp_m",
    "allow",
    "none",
    "EN",
    "L4",
    "corporate",
    [],
    "Explain how to create a pivot table in Excel with multiple data sources. Include step-by-step instructions, tips for organizing source data, and how to create calculated fields and custom groupings for business reporting.",
)

add(
    "l4_res_m",
    "allow",
    "none",
    "KO",
    "L4",
    "research",
    [],
    "논문의 연구 방법론 섹션을 작성하는 방법을 알려줘. 실험 설계, 변수 통제, 표본 크기 결정, 통계 분석 방법 선택 기준을 포함해서 체계적으로 설명해줘. 정량적 연구와 정성적 연구의 차이점도 비교해줘.",
)
add(
    "l4_res_m",
    "allow",
    "none",
    "KO",
    "L4",
    "research",
    [],
    "Python에서 리스트 comprehension과 generator expression의 차이점을 설명해줘. 성능 비교, 메모리 사용량, 적합한 사용 시나리오를 포함해서 설명해줘. 실제 코드 예제도 함께 보여줘.",
)
add(
    "l4_res_m",
    "allow",
    "none",
    "EN",
    "L4",
    "research",
    [],
    "Explain the differences between list comprehensions and generator expressions in Python. Include performance comparison, memory usage characteristics, and appropriate use case scenarios with practical code examples for data processing pipelines.",
)
add(
    "l4_res_m",
    "allow",
    "none",
    "EN",
    "L4",
    "research",
    [],
    "How do I write a proper research methodology section for a computer science paper? Cover experimental design, variable control, sample size determination, and criteria for selecting statistical analysis methods. Compare quantitative and qualitative approaches.",
)

# ── Padding for short texts ──
PAD_KO = [
    " 추가로 관련 배경 정보와 함께 상세한 설명을 부탁드리며, 가능한 한 구체적인 예시와 함께 정리해주세요.",
    " 이 작업과 관련된 세부 사항들도 함께 포함해주시면 감사하겠습니다. 맥락 정보가 충분히 포함되어야 합니다.",
    " 전체적인 흐름과 맥락을 고려하여 종합적으로 분석해주시고, 필요한 경우 추가 확인이 필요한 부분도 표시해주세요.",
]
PAD_EN = [
    " Additionally, please include relevant background information and provide detailed explanations with concrete examples where applicable. Context and nuance matter significantly for this request.",
    " Please ensure all relevant contextual details are included in your response. Consider edge cases and provide comprehensive coverage of the topic with supporting rationale.",
    " Take into account the full context and provide a thorough analysis. Flag any areas that require additional verification or clarification, and include supporting evidence where possible.",
]


def pad_text(text, lang, idx):
    """Extend text to ≥250 chars with context-appropriate filler."""
    pads = PAD_KO if lang == "KO" else PAD_EN
    while len(text) < 250:
        text += pads[idx % len(pads)]
        idx += 1
    return text


# ── Build final dataset ──
cases = []
seen = set()
for idx, (pid, action, dtype, lang, sens, ctx, recs_spec, tpl) in enumerate(T):
    # Resolve slot values — cycle through options per case index
    resolved_s = {}
    for key in S:
        resolved_s[key] = S[key][idx % len(S[key])]
    text = pad_text(tpl.format(s=resolved_s), lang, idx)

    # Build records from spec
    records = []
    for cat, slot_key, essential in recs_spec:
        records.append(
            {
                "category": cat,
                "span": resolved_s.get(slot_key, ""),
                "is_essential": essential,
            }
        )

    # Generate unique ID
    case_id = f"{pid}_{lang}_{idx:03d}"
    if case_id in seen:
        case_id = f"{pid}_{lang}_{idx:04d}"
    seen.add(case_id)

    is_sensitive = sens != "L4"
    cases.append(
        {
            "id": case_id,
            "text": text,
            "expected_action": action,
            "detection_type": dtype,
            "language": lang,
            "sensitivity_level": sens,
            "context": ctx,
            "is_sensitive": is_sensitive,
            "records": records,
            "text_length": len(text),
        }
    )

# Validate
short = [c for c in cases if c["text_length"] < 250]
if short:
    print(f"WARNING: {len(short)} cases under 250 chars:")
    for s in short:
        print(f"  {s['id']}: {s['text_length']} chars")

# Statistics
by_sens = Counter(c["sensitivity_level"] for c in cases)
by_ctx = Counter(c["context"] for c in cases)
by_lang = Counter(c["language"] for c in cases)
by_dtype = Counter(c["detection_type"] for c in cases)
by_action = Counter(c["expected_action"] for c in cases)

output = {
    "version": "2.0.0",
    "created": datetime.now().isoformat() if "datetime" in dir() else "2026-06-24",
    "description": "Privacy Router Benchmark v2 — 120+ bilingual cases across 4 sensitivity levels × 3 contexts × 2 types",
    "total_cases": len(cases),
    "statistics": {
        "by_sensitivity": dict(by_sens),
        "by_context": dict(by_ctx),
        "by_language": dict(by_lang),
        "by_detection_type": dict(by_dtype),
        "by_action": dict(by_action),
    },
    "cases": cases,
}

output["created"] = datetime.now().isoformat()

OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {len(cases)} cases → {OUT}")
print(f"By sensitivity: {dict(by_sens)}")
print(f"By context: {dict(by_ctx)}")
print(f"By language: {dict(by_lang)}")
print(f"By detection_type: {dict(by_dtype)}")
print(f"By action: {dict(by_action)}")
print(f"Avg text length: {sum(c['text_length'] for c in cases) / len(cases):.0f} chars")
print(f"Min text length: {min(c['text_length'] for c in cases)} chars")
print(f"Under 250 chars: {len(short)}")
