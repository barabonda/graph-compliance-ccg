# 위반 패턴 카탈로그 (violation_catalog)

소스: 금융광고규제 가이드라인(금융위·금감원 2021.6.8) · 은행 광고심의 기준 및 세칙(은행연합회 2022.8.25 제정, 2023.1.26 개정)

정본 데이터는 `eval/violation_taxonomy_v0_2.json`. 이 문서는 패턴별 **원문 인용**과
정답 라벨을 사람이 읽기 위한 렌더링이다. 변이 지시문은 아래 원문 인용에서만 도출한다
(우리 검출 코드 역산 금지).

- 총 패턴: **46개** (예금/대출 생성 대상 37 · 생성 제외[보험/투자] 9)
- 유형별: 이자율수익률 8, 산정방법 2, 부수혜택 2, 대출 3, 금지행위 10, 의무표시누락 9, 준수사항 4, 보험 7, 하드케이스 1

## 이자율수익률 (8)

### `RATE_RELATIVE_SUPERIORITY_UNFOUNDED`

- **적용 상품군**: deposit  |  **category**: `rate_or_yield_mislead`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➊이자율·수익률에 관한 표시·광고중 부당사례
- **원문 인용**: “타 상품보다 상대적으로 높은 수익률을 제공 할 수 없음에도 제공하는 것처럼 표시”
- **변이 지시문(원문 도출)**: Claim a higher rate/return than the ProductFact evidence supports, implying the product beats comparable products when it does not.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 실제 적용 이자율, 우대조건, 산출기준

### `LOAN_ATYPICAL_PREFERENTIAL_RATE`

- **적용 상품군**: loan  |  **category**: `rate_or_yield_mislead`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➊이자율·수익률에 관한 표시·광고중 부당사례
- **원문 인용**: “대출시 일반적으로 적용하지 않는 우대금리를 적용”
- **변이 지시문(원문 도출)**: Advertise a preferential loan rate that is not generally applicable as if it were the standard offered rate.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 우대금리 적용조건, 대출금리 범위 및 산출기준

### `RATE_OVERSTATED_OR_STALE`

- **적용 상품군**: deposit  |  **category**: `rate_or_yield_mislead`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➊이자율·수익률에 관한 표시·광고중 부당사례
- **원문 인용**: “실제보다 이자율(수익률)을 높게 기재하거나 최근 하락하였음에도 이전 수익률을 안내”
- **변이 지시문(원문 도출)**: State a rate higher than the ProductFact evidence, or present a previously higher rate as if it were current.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 현재 적용 이자율, 적용 기준일

### `RATE_BEST_AMONG_ALL_FIRMS`

- **적용 상품군**: deposit/loan  |  **category**: `rate_or_yield_mislead`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➊이자율·수익률에 관한 표시·광고중 부당사례
- **원문 인용**: “금융상품의 이자율(수익률)이 타 금융사 포함 모든 상품보다 유리한 것 처럼 표시”
- **변이 지시문(원문 도출)**: Imply the rate is more favorable than every other product across all financial institutions, without objective basis.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 비교 근거 및 출처, 실제 적용 이자율

### `RATE_PRETAX_POSTTAX_OMITTED`

- **적용 상품군**: deposit  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➊이자율·수익률에 관한 표시·광고중 부당사례
- **원문 인용**: “수익률(이자율)표기시 ' 세전' ' 세후' 구분 누락”
- **변이 지시문(원문 도출)**: Advertise a rate/yield figure while removing the 세전/세후 (pre-tax/post-tax) distinction.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 세전·세후 구분, 이자율 산출기준

### `RATE_VARIABILITY_OMITTED`

- **적용 상품군**: deposit/loan  |  **category**: `rate_or_yield_mislead`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (일반원칙) 부당한 표시·광고 예시 / ➊이자율·수익률 부당사례 — ➍금융상품의 거래조건이 변동될 수 있음에도 변동가능성에 대한 표기를 누락하는 경우 / 실적배당신탁상품 수익률의 변동가능성을 누락
- **원문 인용**: “금융상품의 거래조건이 변동될 수 있음에도 변동가능성에 대한 표기를 누락하는 경우”
- **변이 지시문(원문 도출)**: Present a variable rate/return as if fixed, omitting the disclosure that the rate can change.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 금리 변동 가능성, 변동금리 산출기준

### `YIELD_DIVIDEND_FALSE_RISING`

- **적용 상품군**: investment  |  **category**: `rate_or_yield_mislead`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➊이자율·수익률에 관한 표시·광고중 부당사례
- **원문 인용**: “근거 없이 자사 신탁상품 배당률이 사실과 다르게 상승하고 있다고 표시”
- **변이 지시문(원문 도출)**: Claim a trust/investment product's dividend rate is rising without objective basis (investment-only pattern; excluded from deposit/loan generation).
- **gold articles**: 금소법 제22조
- **required_disclosures**: 배당률 산출근거, 수익률 변동 가능성

### `INVEST_PAST_PERFORMANCE_NO_WARNING`

- **적용 상품군**: investment  |  **category**: `past_performance_or_future_return`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 / 금소법 제21조·제22조 (투자성 상품 — 예금/대출 생성 제외) — 금소법 제21조·제22조
- **원문 인용**: “과거 성과가 미래 수익을 보장하지 않는다는 사항 등 위험 표시 (투자성 상품 광고 원칙)”
- **변이 지시문(원문 도출)**: Use past performance as if it indicates future return and omit the future-performance warning.
- **gold articles**: 금소법 제21조, 금소법 제22조
- **required_disclosures**: 과거 성과는 미래 수익을 보장하지 않음, 원금손실 가능성

## 산정방법 (2)

### `COMPOUND_SIMPLE_UNDIFFERENTIATED`

- **적용 상품군**: deposit  |  **category**: `calc_method_mislead`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➌이자·수익 산정방법에 관한 표시·광고중 부당사례
- **원문 인용**: “일⋅월복리 등 구분하여 표기하지 않고 단순히 ' 복리식 ' 으로 표시”
- **변이 지시문(원문 도출)**: Label the interest as generic '복리식' without specifying daily/monthly compounding basis.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 이자 산정방법(일·월복리 구분), 이자율 산출기준

### `ALWAYS_COMPOUND_REGARDLESS_EARLY_TERMINATION`

- **적용 상품군**: deposit  |  **category**: `calc_method_mislead`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➌이자·수익 산정방법에 관한 표시·광고중 부당사례
- **원문 인용**: “중도해지 구분없이 항상 복리로 지급하는 것처럼 표시”
- **변이 지시문(원문 도출)**: Imply compound interest always applies, ignoring that early termination changes the payout.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 중도해지 이율, 이자 지급제한 사유

## 부수혜택 (2)

### `TAX_BENEFIT_LIMIT_OMITTED`

- **적용 상품군**: deposit  |  **category**: `side_benefit_condition_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➎부수적 혜택에 관한 표시·광고중 부당 사례
- **원문 인용**: “세금우대혜택시 제한 사항(세대당 1통장)을 알리지 않은 경우”
- **변이 지시문(원문 도출)**: Advertise a tax-preferential benefit while omitting its eligibility limit (e.g., one account per household).
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제18조
- **required_disclosures**: 세금우대 자격 및 한도(세대당 1통장 등)

### `SPECIAL_RATE_GIFT_MONEY_IMPLIED`

- **적용 상품군**: deposit  |  **category**: `side_benefit_condition_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➎부수적 혜택에 관한 표시·광고중 부당 사례
- **원문 인용**: “특별금리 저축상품에 경품성격의 금전을 지급하는 것처럼 표시”
- **변이 지시문(원문 도출)**: Imply a special-rate savings product pays out gift-like cash on top of interest.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제18조
- **required_disclosures**: 경품·혜택 지급 조건 및 기간

## 대출 (3)

### `LOAN_ELIGIBILITY_LIMITS_OMITTED`

- **적용 상품군**: loan  |  **category**: `required_disclosure_missing`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➍대출상품에 대한 표시·광고중 부당 사례
- **원문 인용**: “대출가능 대상이나 자격 , 담보제공 등 제한조 건을 표기하지 않는 경우”
- **변이 지시문(원문 도출)**: Advertise loan availability while omitting eligible target, qualification, and collateral/limit conditions.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 대출 대상 및 자격요건, 담보·심사 조건

### `LOAN_PARTIAL_SALE_AS_ALL`

- **적용 상품군**: loan  |  **category**: `misleading_scope`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➍대출상품에 대한 표시·광고중 부당 사례
- **원문 인용**: “일부계정(신탁)에 대한 ' 대출세일' 을 모든 대출에 적용하는 것처럼 표시”
- **변이 지시문(원문 도출)**: Present a rate discount that applies only to a limited loan category as if it applies to all loans.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 할인 적용 대상 대출의 범위

### `LOAN_EASY_APPROVAL_MISLEADING`

- **적용 상품군**: loan  |  **category**: `misleading_approval_claim`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 ➍대출상품 부당사례 (제한조건 미표기) / 은행 광고심의 기준 제17조제4호 — ➍대출상품에 대한 표시·광고중 부당 사례 / 제17조제4호
- **원문 인용**: “대출가능 대상이나 자격 , 담보제공 등 제한조 건을 표기하지 않는 경우 / 거래 상대방 등에 따라 거래조건이 달리 적용될 수 있음에도 누구에게나 적용되는 것으로 오해를 유발”
- **변이 지시문(원문 도출)**: Suggest that loan approval is easy or guaranteed without screening.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 심사 조건, 대출금리 범위, 상환 조건

## 금지행위 (10)

### `LOAN_DAILY_INTEREST_MINIMIZE`

- **적용 상품군**: loan  |  **category**: `prohibited_expression`  |  **risk**: high  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제3호
- **원문 인용**: “대출이자를 일 단위로 표시하는 등 금융소비자의 경제적 부담이 작아 보이도록 하거나 계약체결에 따른 이익을 크게 인지하도록 하는 행위”
- **변이 지시문(원문 도출)**: Express loan interest in per-day terms to make the cost look small.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 연 이자율 및 총 이자 부담, 대출금리 범위 및 산출기준

### `UNIVERSAL_SCOPE_MISLEADING`

- **적용 상품군**: deposit/loan  |  **category**: `misleading_scope`  |  **risk**: high  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) / 금융광고규제 가이드라인 참고3 판단사례2 — 제17조제4호
- **원문 인용**: “거래 상대방 등에 따라 거래조건이 달리 적용될 수 있음에도 확정적인 것으로 표시하거나 누구에게나 적용되는 것으로 오해를 유발하는 표현을 하는 행위”
- **변이 지시문(원문 도출)**: Make a consumer-dependent rate or eligibility condition sound universally available to everyone with no conditions.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조, 금융소비자 보호에 관한 감독규정 제19조
- **required_disclosures**: 우대조건, 가입대상, 가입기간

### `SUPERLATIVE_NO_BASIS`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제5호
- **원문 인용**: “객관적 근거가 있는 사실이나 공인된 자료 없이 최고, 최상, 최저, 최초, 최대, 1위, 제일, 유일 등의 최상급 표현을 사용하는 행위”
- **변이 지시문(원문 도출)**: Use a superlative expression (최고/최상/최저/최초/최대/1위/제일/유일) without objective or authorized basis.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 최상급 표현의 객관적 근거·출처

### `COMPARATIVE_SUPERIORITY_NO_BASIS`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제2호
- **원문 인용**: “이자율의 범위 및 산정방법, 이자의 지급 및 부과 시기, 부수적 혜택 및 비용과 관련하여 구체적인 근거와 내용을 제시하지 아니하면서 다른 금융상품보다 비교우위에 있음을 나타내는 행위”
- **변이 지시문(원문 도출)**: Claim comparative superiority over other products without providing concrete basis and content.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 비교 근거 및 구체적 내용

### `FALSE_EXAGGERATED_DECEPTIVE`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: high  |  **routing**: reject
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제7호
- **원문 인용**: “사실과 다르게 표시 광고하는 거짓 광고 행위나 사실을 지나치게 부풀리는 과장 광고행위, 사실을 은폐하거나 축소하는 등 기만적인 광고에 해당하는 행위”
- **변이 지시문(원문 도출)**: Overstate the product benefit beyond the ProductFact evidence (false/exaggerated/deceptive claim).
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조, 표시·광고의 공정화에 관한 법률 제3조
- **required_disclosures**: 실제 상품 조건, 위험 및 제한 사항

### `UNFAIR_COMPARATIVE_AD`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제8호가목
- **원문 인용**: “비교대상 및 기준을 분명하게 밝히지 않거나, 객관적 근거 및 공인된 자료 없이, 자사에 유리하도록 비교기준을 설정하여 자사가 우월해 보이도록 표현하는 행위”
- **변이 지시문(원문 도출)**: Compare against unnamed competitors with a self-serving basis and no objective source.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조, 표시·광고의 공정화에 관한 법률 제3조
- **required_disclosures**: 비교대상 및 기준, 객관적 근거·출처

### `PARTIAL_AS_WHOLE_COMPARISON`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제8호나목
- **원문 인용**: “일부에 대하여 비교하면서 마치 전체에 대한 비교인 것처럼 주장하거나 상호 관련이 없는 사항을 비교하여 우월성을 표시하는 행위”
- **변이 지시문(원문 도출)**: Compare only one aspect but present it as if it were an overall superiority.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조, 표시·광고의 공정화에 관한 법률 제3조
- **required_disclosures**: 비교 범위의 한정, 비교 근거

### `DISPARAGING_AD`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제8호다목
- **원문 인용**: “비록 사실이라 하더라도 비교 대상을 중상·비방하는 행위”
- **변이 지시문(원문 도출)**: Disparage or slander a competitor product/institution.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조, 표시·광고의 공정화에 관한 법률 제3조
- **required_disclosures**: 비방 표현 삭제

### `SELLER_IDENTITY_OBSCURED`

- **적용 상품군**: deposit/loan  |  **category**: `prohibited_expression`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제17조(금지사항) — 제17조제6호
- **원문 인용**: “해당 광고매체 또는 금융상품판매대리·중개업자의 상호를 부각시키는 등 금융소비자가 금융상품직접판매업자를 올바르게 인지하는 것을 방해하는 행위”
- **변이 지시문(원문 도출)**: Foreground a platform/agent brand so the actual direct-selling bank is hard to recognize.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제17조
- **required_disclosures**: 금융상품직접판매업자(은행) 명칭 명확 표시

### `GUARANTEE_RETURN_DEFINITIVE`

- **적용 상품군**: deposit/loan  |  **category**: `guarantee_or_return_misleading`  |  **risk**: high  |  **routing**: reject
- **출처**: 은행 광고심의 기준 제17조(금지사항) / 금융광고규제 가이드라인 참고2 (일반원칙) — 제17조제1호 / ➊확정되지 않은 사항을 확정적으로 표현하는 경우
- **원문 인용**: “이자율의 범위 및 산정방법, 이자의 지급 및 부과 시기, 부수적 혜택 및 비용 등과 관련하여 불확실한 사항에 대해 단정적 판단을 제공하거나 확정적으로 표시하여 금융소비자가 오인하게 하는 행위”
- **변이 지시문(원문 도출)**: Inject wording that implies guaranteed return or definitive/certain benefit beyond the documented product condition.
- **gold articles**: 금소법 제21조, 금소법 제22조, 은행 광고심의 기준 제17조, 금융소비자 보호에 관한 법률 시행령 제20조
- **required_disclosures**: 조건, 위험, 상품설명서·약관 확인

## 의무표시누락 (9)

### `DEPOSIT_RATE_CONDITION_MISSING`

- **적용 상품군**: deposit  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) / 금소법 제22조 — 제16조제1항제5호나목(예금성 상품 이자율의 범위 및 산출기준)
- **원문 인용**: “예금성 상품의 경우 거래조건으로 ... 나. 이자율의 범위 및 산출기준”
- **변이 지시문(원문 도출)**: Advertise the highest preferential rate without placing eligibility, term, or preferential-condition disclosure at the same hierarchy.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 우대조건, 가입기간, 금리 산출기준

### `DEP_DISC_PROTECTION_MISSING`

- **적용 상품군**: deposit  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제5호라목(예금자보호법 등에 따른 부보내용)
- **원문 인용**: “예금성 상품의 경우 거래조건으로 ... 라. 예금자보호법 등에 따른 부보내용”
- **변이 지시문(원문 도출)**: Advertise a deposit product while removing the depositor-protection (예금자보호) disclosure.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 예금자보호 여부 및 한도

### `DEP_DISC_MATURITY_EXAMPLE_NO_WARNING`

- **적용 상품군**: deposit  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제5호마목(만기지급금 예시 시 미래수익 비보장 표시)
- **원문 인용**: “만기지급금 등을 예시하여 광고하는 경우에는 해당 예시된 지급금 등이 미래의 수익을 보장하는 것이 아니라는 사항”
- **변이 지시문(원문 도출)**: Show an illustrative maturity payout as if it were a guaranteed future return, omitting the non-guarantee notice.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 예시 지급금은 미래 수익을 보장하지 않음

### `LOAN_DISC_RATE_RANGE_BASIS_MISSING`

- **적용 상품군**: loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) / 금융광고규제 가이드라인 참고3 판단사례1 — 제16조제1항제6호나목(대출성 이자율의 범위 및 산출기준, 연체이자율 포함)
- **원문 인용**: “대출성 상품의 경우 거래조건으로 ... 나. 이자율의 범위 및 산출기준(연체이자율을 포함)”
- **변이 지시문(원문 도출)**: Advertise a low loan rate without disclosing the rate range, calculation basis, or 연체이자율.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 대출금리 범위 및 산출기준, 연체이자율

### `LOAN_DISC_ELIGIBILITY_MISSING`

- **적용 상품군**: loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제6호가목(금융소비자의 자격요건)
- **원문 인용**: “대출성 상품의 경우 거래조건으로 ... 가. 금융소비자의 자격요건(갖춰야 할 신용수준 등)”
- **변이 지시문(원문 도출)**: Advertise loan approval without disclosing the borrower qualification (credit level etc.).
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 대출 자격요건(신용수준 등)

### `LOAN_DISC_REPAYMENT_PREPAYMENT_MISSING`

- **적용 상품군**: loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제6호라목·마목(원리금 상환방법·중도상환 조건)
- **원문 인용**: “대출성 상품의 경우 거래조건으로 ... 라. 원리금의 상환방법 마. 중도상환 조건”
- **변이 지시문(원문 도출)**: Advertise the loan while omitting repayment method and prepayment conditions.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 원리금 상환방법, 중도상환 조건(수수료 포함)

### `LOAN_DISC_FEES_MISSING`

- **적용 상품군**: loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제6호바목(수수료 등 부대비용)
- **원문 인용**: “대출성 상품의 경우 거래조건으로 ... 바. 수수료 등 부대비용”
- **변이 지시문(원문 도출)**: Advertise the loan as cost-free while omitting fees and incidental costs.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 수수료 등 부대비용

### `DISC_PRODUCT_DOC_CHECK_MISSING`

- **적용 상품군**: deposit/loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제3호(상품설명서·약관 확인 권유 문구)
- **원문 인용**: “계약 체결 전 상품설명서 및 약관 확인을 권유하는 문구”
- **변이 지시문(원문 도출)**: Remove the '계약 체결 전 상품설명서 및 약관을 확인' recommendation and push immediate sign-up instead.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 계약 전 상품설명서·약관 확인 권유

### `DISC_EXPLANATION_RIGHT_MISSING`

- **적용 상품군**: deposit/loan  |  **category**: `required_disclosure_missing`  |  **risk**: low  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제16조(의무 표시사항) — 제16조제1항제7호(금융상품에 대한 설명을 받을 권리)
- **원문 인용**: “금융상품에 대한 설명을 받을 권리”
- **변이 지시문(원문 도출)**: Omit any mention of the consumer's right to receive an explanation and imply no explanation is needed.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제16조
- **required_disclosures**: 금융상품 설명을 받을 권리

## 준수사항 (4)

### `EVENT_CONDITIONS_OMITTED`

- **적용 상품군**: deposit/loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제18조(기타 준수사항) — 제18조제3호
- **원문 인용**: “이벤트·특판·프로모션 및 연계·제휴서비스 등 부수되는 서비스를 광고하는 경우 대상, 자격요건, 기간 및 내용 등을 함께 안내”
- **변이 지시문(원문 도출)**: Advertise an event/특판/promotion benefit while omitting its target, eligibility, period, and details.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제18조
- **required_disclosures**: 이벤트 대상·자격요건·기간·내용

### `BENEFIT_WITHOUT_DISADVANTAGE`

- **적용 상품군**: deposit/loan  |  **category**: `required_disclosure_missing`  |  **risk**: medium  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제18조(기타 준수사항) — 제18조제4호
- **원문 인용**: “금융소비자가 받을 수 있는 혜택을 알리는 경우 해당 금융상품등으로 인한 불이익도 균형 있게 전달”
- **변이 지시문(원문 도출)**: State only the benefits while removing any balanced disclosure of the corresponding disadvantages/risks.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제18조
- **required_disclosures**: 상품 이용에 따른 불이익·위험

### `AWARD_CERT_DETAIL_MISSING`

- **적용 상품군**: deposit/loan  |  **category**: `required_disclosure_missing`  |  **risk**: low  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제18조(기타 준수사항) — 제18조제1호
- **원문 인용**: “타 기관 등으로부터 수상, 선정, 인증, 특허 등을 받은 내용을 표기하는 경우 그 시기 및 내용 등 표시”
- **변이 지시문(원문 도출)**: Cite an award/selection/certification without stating its time and specific content.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제18조
- **required_disclosures**: 수상·인증의 시기 및 내용

### `STATISTIC_SOURCE_MISSING`

- **적용 상품군**: deposit/loan  |  **category**: `required_disclosure_missing`  |  **risk**: low  |  **routing**: revise
- **출처**: 은행 광고심의 기준 제18조(기타 준수사항) — 제18조제2호
- **원문 인용**: “통계수치나 도표 등을 표시하는 경우 해당 자료의 출처 및 기준일자 명시”
- **변이 지시문(원문 도출)**: Present a statistic/figure without citing its source and reference date.
- **gold articles**: 금소법 제22조, 은행 광고심의 기준 제18조
- **required_disclosures**: 통계수치의 출처 및 기준일자

## 보험 (7)

### `INS_PREMIUM_BASIS_MISSING`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➋보험상품에 관한 표시·광고중 부당 사례
- **원문 인용**: “보험료산출기준을 적절하게 표기하지 않는 경우”
- **변이 지시문(원문 도출)**: Insurance-only pattern: advertise premium without proper 보험료 산출기준. Not generated (no insurance product graph).
- **gold articles**: 금소법 제22조
- **required_disclosures**: 보험료 산출기준

### `INS_MAIN_CONTRACT_AS_RIDER`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➋보험상품에 관한 표시·광고중 부당 사례
- **원문 인용**: “주계약보험료만으로 특약보장내용까지 혜택을 받는 것처럼 표시”
- **변이 지시문(원문 도출)**: Insurance-only pattern: imply rider coverage is included in the main-contract premium. Not generated.
- **gold articles**: 금소법 제22조
- **required_disclosures**: 특약 가입 필요 여부 및 별도 보험료

### `INS_COVERAGE_LIMITS_HIDDEN`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➋보험상품에 관한 표시·광고중 부당 사례
- **원문 인용**: “보장내용에 관한 사항을 사실과 다르게 밝히거나 제한사항을 밝히지 않는 경우”
- **변이 지시문(원문 도출)**: Insurance-only pattern: misstate coverage or hide limits/exclusions. Not generated.
- **gold articles**: 금소법 제22조
- **required_disclosures**: 보장내용 및 보장 제한·면책 사항

### `INS_PAYOUT_BASIS_UNCLEAR`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➋보험상품에 관한 표시·광고중 부당 사례
- **원문 인용**: “보험금 지급액의 산출기준을 밝히지 않거나 모호하게 표기”
- **변이 지시문(원문 도출)**: Insurance-only pattern: state payout without clear calculation basis. Not generated.
- **gold articles**: 금소법 제22조
- **required_disclosures**: 보험금 지급액 산출기준

### `INS_RIDER_WITHOUT_RIDER`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: high  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➋보험상품에 관한 표시·광고중 부당 사례
- **원문 인용**: “특약 가입없이 특약보장사항에 대하여 보장을 받을 수 있는 것처럼 표시”
- **변이 지시문(원문 도출)**: Insurance-only pattern: imply rider benefits apply without buying the rider. Not generated.
- **gold articles**: 금소법 제22조
- **required_disclosures**: 특약 가입 필요 여부

### `INS_SURRENDER_VALUE_HIDDEN`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: high  |  **routing**: reject
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➋보험상품에 관한 표시·광고중 부당 사례
- **원문 인용**: “중도해약시 해약환급금이 적게 지급되거나 지급되지 않는 사실을 숨기거나 허위로 표기”
- **변이 지시문(원문 도출)**: Insurance-only pattern: hide low/zero surrender value on early cancellation. Not generated.
- **gold articles**: 금소법 제22조
- **required_disclosures**: 중도해약 시 해약환급금 안내

### `SAVINGS_INSURANCE_TAX_ALWAYS`

- **적용 상품군**: 없음(생성 제외 — 보험 전용)  |  **category**: `insurance_specific`  |  **risk**: medium  |  **routing**: revise
- **출처**: 금융광고규제 가이드라인 참고2 (세부심사지침) 5가지 유형별 부당한 표시·광고 사례 — ➎부수적 혜택에 관한 표시·광고중 부당 사례
- **원문 인용**: “저축성 보험상품의 보험차익 비과세 혜택이 언제나 가능한 것처럼 표시”
- **변이 지시문(원문 도출)**: Insurance-only pattern: imply the tax-exemption of savings-insurance gains always applies. Not generated.
- **gold articles**: 금소법 제22조
- **required_disclosures**: 비과세 요건 및 한도

## 하드케이스 (1)

### `HARD_CASE_DEPOSIT_RATE_WITH_SAME_LEVEL_DISCLOSURE`

- **적용 상품군**: deposit  |  **category**: `hard_case_compliant`  |  **risk**: low  |  **routing**: pass_candidate
- **출처**: 은행 광고심의 기준 제16조·제17조 (준수 사례 — 오탐 검증용) — 제16조제1항제5호 / 제17조제4호 (준수)
- **원문 인용**: “최고 이자율 표시 시 우대조건·기간·산출기준을 동일 위계로 함께 표시하면 준수 (의무표시 충족)”
- **변이 지시문(원문 도출)**: Keep a high-rate claim but put preferential conditions, term, and product-document check at the same hierarchy.
- **gold articles**: —
- **required_disclosures**: 우대조건, 가입기간, 금리 산출기준, 예금자보호
