# 04 — 웹 프론트엔드

### F-06. 웹 아카이브 (Frontend)

**레퍼런스:** `https://taehyun108.github.io/KTH_01/news/`
기존 구조(정적 사이트 + `data/*.json` + 카드 그리드 + 다중선택 pills + 검색 + 즐겨찾기/숨김 + GitHub Issue 제출)를 **그대로 계승**하고 축만 바꾼다.

#### 4.6.1 기존 → 신규 매핑

| 기존 (KTH_01/news) | 신규 (posco-news) |
|---|---|
| 카테고리 = 거시경제 / 글로벌 정책·시사 / 글로벌 산업·시황 / 국내 정책·시사 / 국내 산업·시황 | **1차 축 = 트랙 3종**, **2차 축 = 카테고리 22종** |
| 채널 필터 = 유튜브 채널 | **언론사/출처 필터** |
| relation 배지 = 직접/간접/산업 | **tone + impact + track** 배지 |
| 유튜브 URL 제출 → GitHub Issue | **기사/정책 URL 제출 → GitHub Issue** |
| `data/reports.json` | `data/articles.json` (+ private `issues.json`) |
| 카드 = 영상 리포트 | 카드 = 기사 |
| `/trade/` (나라별 통상정책 현황) | **`/policy/` 탭으로 흡수 또는 상호 링크** (§4.6.6) |
| — | **신규 `/policy/` 탭, `/swot/` (private)** |

#### 4.6.2 상수 정의 (`posco-app.js`)

```js
const TRACKS = {
  'posco':   { label:'포스코 그룹',   emoji:'🏢', home:'/posco/'  },
  'battery': { label:'이차전지 산업', emoji:'🔋', home:'/posco/'  },
  'policy':  { label:'정책·산업동향', emoji:'📜', home:'/policy/' },
  'trade':   { label:'통상·규제',     emoji:'⚔️', home:'/trade/'  },
};

const CATEGORIES = {
  // ── T1 포스코 ──
  'holdings':      { track:'posco',   label:'포스코홀딩스',     short:'홀딩스',   emoji:'🏢' },
  'posco-steel':   { track:'posco',   label:'포스코(철강)',     short:'철강',     emoji:'🏭' },
  'futurem':       { track:'posco',   label:'포스코퓨처엠',     short:'퓨처엠',   emoji:'🔋' },
  'international': { track:'posco',   label:'포스코인터내셔널', short:'인터',     emoji:'🌐' },
  'enc':           { track:'posco',   label:'포스코이앤씨',     short:'이앤씨',   emoji:'🏗️' },
  'dx':            { track:'posco',   label:'포스코DX',         short:'DX',      emoji:'💻' },
  'group':         { track:'posco',   label:'그룹 전반',        short:'그룹',     emoji:'🧩' },
  // ── T2 이차전지 산업 ──
  'cell-kr':       { track:'battery', label:'국내 셀',          short:'국내셀',   emoji:'🇰🇷' },
  'cell-global':   { track:'battery', label:'해외 셀',          short:'해외셀',   emoji:'🌏' },
  'mat-kr':        { track:'battery', label:'국내 소재',        short:'국내소재', emoji:'⚗️' },
  'mat-global':    { track:'battery', label:'해외 소재',        short:'해외소재', emoji:'🧪' },
  'raw':           { track:'battery', label:'원료·광물',        short:'원료',     emoji:'⛏️' },
  'demand':        { track:'battery', label:'전방·응용',        short:'전방',     emoji:'🚗' },
  'tech':          { track:'battery', label:'기술·연구',        short:'기술',     emoji:'🔬' },
  'equip':         { track:'battery', label:'장비·공정',        short:'장비',     emoji:'🛠️' },
  // ── T3 정책·산업동향 ──
  'pol-kr':        { track:'policy',  label:'국내 정책',        short:'국내',     emoji:'🇰🇷' },
  'pol-us':        { track:'policy',  label:'미국',             short:'미국',     emoji:'🇺🇸' },
  'pol-eu':        { track:'policy',  label:'EU',               short:'EU',      emoji:'🇪🇺' },
  'pol-cn':        { track:'policy',  label:'중국',             short:'중국',     emoji:'🇨🇳' },
  'pol-global':    { track:'policy',  label:'기타 국가',        short:'기타국',   emoji:'🌍' },
  'pol-law':       { track:'policy',  label:'법령·행정예고',    short:'법령',     emoji:'⚖️' },
  'pol-trend':     { track:'policy',  label:'산업 현황·트렌드', short:'트렌드',   emoji:'📊' },
  // ── T4 통상·규제 (v1.2) ──
  'trade-tariff':  { track:'trade',   label:'관세·무역분쟁',    short:'관세',     emoji:'⚔️' },
  'trade-remedy':  { track:'trade',   label:'무역구제',         short:'구제',     emoji:'⚖️' },
  'trade-export':  { track:'trade',   label:'수출통제·제재',    short:'수출통제', emoji:'🚫' },
  'trade-origin':  { track:'trade',   label:'원산지·FTA',       short:'원산지',   emoji:'📑' },
  'trade-supply':  { track:'trade',   label:'공급망 규제',      short:'공급망',   emoji:'🔗' },
  'trade-country': { track:'trade',   label:'국가별 현황',      short:'국가별',   emoji:'🗺️' },
};

const DISPUTE_STAGE = {
  initiated:   { label:'조사개시', cls:'badge-dispute-initiated' },
  preliminary: { label:'예비판정', cls:'badge-dispute-preliminary' },
  final:       { label:'최종판정', cls:'badge-dispute-final' },
  in_force:    { label:'발효',     cls:'badge-dispute-inforce' },
  negotiating: { label:'협상중',   cls:'badge-dispute-negotiating' },
  terminated:  { label:'종료',     cls:'badge-dispute-terminated' },
};

const TONE = {
  positive:{label:'🟢 긍정',cls:'badge-tone-positive'},
  neutral: {label:'⚪ 중립',cls:'badge-tone-neutral'},
  negative:{label:'🔴 부정',cls:'badge-tone-negative'},
  crisis:  {label:'🚨 위기',cls:'badge-tone-crisis'},
};
const IMPACT = {
  high:{label:'중요도 상',cls:'badge-impact-high'},
  mid: {label:'중',       cls:'badge-impact-mid'},
  low: {label:'하',       cls:'badge-impact-low'},
};
const POLICY_STAGE = {
  discussion:{label:'논의',   cls:'badge-stage-discussion'},
  proposed:  {label:'예고',   cls:'badge-stage-proposed'},   // 가장 눈에 띄게
  enacted:   {label:'확정',   cls:'badge-stage-enacted'},
  effective: {label:'시행',   cls:'badge-stage-effective'},
  amended:   {label:'개정',   cls:'badge-stage-amended'},
};
```

#### 4.6.3 필터 아키텍처 (v1.0 수정)

> **문제:** v0.2는 "다중 필터가 `companies` 기준으로 동작"이라 했는데, T3 정책 기사에는 `companies`가 없다. 정책 기사가 필터에서 전부 사라진다. (§12 검증 4회차)

```js
// 통합 필터 키
article.facets = [
  ...companies.map(c => `co:${c}`),      // co:futurem, co:catl
  ...countries.map(c => `country:${c}`), // country:US
  ...topics.map(t => `topic:${t}`),      // topic:세액공제
  `cat:${category}`,
  `track:${track}`,
  ...also_tracks.map(t => `track:${t}`),
];
// 필터 = activeFacets(Set) 와 article.facets 의 교집합 판정 (OR 내부, AND 그룹간)
```

**모바일 pill 폭발 방지:** 트랙 3 × 카테고리 최대 8 = 최대 22개 pill이 한 줄에 뜨면 모바일에서 무너진다.
→ **트랙 세그먼트 선택 시 해당 트랙 카테고리만 렌더**, 미선택(전체) 시 트랙 pill 3개만 표시.

#### 4.6.4 카드 UI

```
┌────────────────────────────────────────────────┐
│ 📜 정책 · 🇺🇸 미국   ⚪ 중립  중요도 상  [예고]  │  ← 트랙·카테고리·논조·중요도·정책단계
│ ──────────────────────────────────────────────  │
│ 美 재무부, 45X 세액공제 음극재 적격비용 개정안   │  ← 제목 (원문 링크)
│ 공고                                            │
│                                                 │
│ 음극재 생산에 투입되는 원료비의 적격 범위를      │  ← summary
│ 축소하는 개정안을 관보에 공고했습니다.           │
│  • 의견수렴 60일                                │  ← bullets (접힘)
│  • 흑연 정제비용 제외 검토                      │
│                                                 │
│ 📰 Federal Register · 2026-08-26 · 🔗 원문      │
│ #세액공제 #45X #음극재 #미국                     │
│ [상세] [이 이슈 보기 ▸] [📋 카톡용] [⭐] [🙈]   │
└────────────────────────────────────────────────┘
```

> `💡 퓨처엠 시사점`은 **public 카드에서 제거**되고 private `/swot/` 및 인증된 상세 화면에서만 노출된다 (§4.4 공개여부 표 참조).

#### 4.6.5 `/policy/` 전용 탭 (v1.0 신규)

정책 트랙은 뉴스 카드만으로는 부족하다. **"지금 어느 나라의 어떤 제도가 어느 단계에 있는가"** 를 한눈에 봐야 한다.

**화면 구성 (상단→하단)**

```
① 정책 현황 보드 (Status Board)
   국가 × 이슈 매트릭스 — 각 셀에 최신 단계 배지
   ┌────────┬──────────┬──────────┬──────────┬──────────┐
   │        │ 세액공제  │ 원산지/  │ 탄소     │ 수출통제 │
   │        │          │ FEOC     │ 규제     │          │
   ├────────┼──────────┼──────────┼──────────┼──────────┤
   │ 🇰🇷 한국│ [시행]   │ —        │ [논의]   │ —        │
   │ 🇺🇸 미국│ [예고]🔴 │ [시행]   │ —        │ [확정]   │
   │ 🇪🇺 EU  │ [논의]   │ [확정]   │ [시행]🔴 │ —        │
   │ 🇨🇳 중국│ —        │ —        │ —        │ [시행]🔴 │
   └────────┴──────────┴──────────┴──────────┴──────────┘
   · 셀 클릭 → 해당 국가·이슈 기사 타임라인
   · 🔴 = sector_impact=direct 인 최신 변동 존재

② 정책 타임라인 (Timeline)
   가로축 = 시간, 세로축 = 국가. 정책 단계 전이를 점으로 표시
   → 벤치마킹 보고서용 "정책 변화 이력"을 그대로 캡처 가능

③ 산업 현황·트렌드 (pol-trend)
   시장 통계·전망 기사 카드 + 수치 하이라이트

④ 기사 카드 그리드
   국가·이슈·단계·기간 필터 적용
```

**`/policy/` 전용 필터:** 국가(다중) · 정책이슈(다중) · 단계(다중) · 기간 · 출처유형(뉴스/보도자료/관보/리포트)

**데이터:** `data/policies.json` (아래 §5.3) — 기사와 별개로 **정책 자체를 엔티티로 관리**한다. 기사는 정책의 "변동 이벤트"로 붙는다. 이것이 T3를 단순 뉴스 목록과 구분 짓는 핵심이다.

#### 4.6.6 기존 `/trade/` 페이지와의 관계

기존 KTH_01에 `나라별 통상정책 현황` 페이지가 이미 존재한다. → **v1.2에서 A안(흡수)로 확정. §4.6.8 참조.** 아래 비교표는 판단 근거로 남긴다.

| 안 | 내용 | 장단 |
|---|---|---|
| A. 흡수 | `/trade/`를 `/policy/`의 `pol-trade` 카테고리로 통합, 기존 URL은 리다이렉트 | 단일 진실원천 / 기존 수기 데이터 이관 필요 |
| B. 병행 | `/trade/`는 수기 큐레이션 유지, `/policy/`는 자동 수집. 상호 링크 | 이관 불필요 / 두 곳을 봐야 함 |
| C. 계층화 | `/policy/`가 자동 수집·타임라인, `/trade/`가 정제된 국가별 요약 상위뷰 | 역할 분리 명확 / 유지 부담 2배 |

**권장:** C → B → A 순. 자동 수집 품질이 안정될 때까지 수기 페이지를 남겨두는 편이 안전하다.

---

#### 4.6.7 `/trade/` 통상·규제 전용 탭 (v1.2 신규)

> 캐나다 관세 분쟁, 중국 흑연 수출통제처럼 **국가 간 조치**는 정책 지원제도와 성격이 완전히 다르다. "누가 누구에게 무엇을 걸었고, 지금 어느 단계이며, 언제 발효되는가"가 핵심이다.

**화면 구성**

```
① 분쟁 현황 보드 (Dispute Board)
   부과국 × 대상국 매트릭스 — 셀에 최신 단계 + 관세율
   ┌──────────┬──────────┬──────────┬──────────┐
   │ 부과국\대상│ 🇰🇷 한국  │ 🇨🇳 중국  │ 🇨🇦 캐나다│
   ├──────────┼──────────┼──────────┼──────────┤
   │ 🇺🇸 미국  │ [발효]25%│ [발효]사실상│[협상중]🔴│
   │ 🇨🇦 캐나다│ —        │ [발효]100%│ —        │
   │ 🇨🇳 중국  │ [조사개시]│ —        │[발효]보복│
   └──────────┴──────────┴──────────┴──────────┘
   · 🔴 = 최근 7일 내 단계 변동
   · 셀 클릭 → 해당 분쟁 타임라인

② 분쟁 타임라인
   제소 → 조사개시 → 예비판정 → 최종판정 → 발효 → (협상/종료)
   각 노드에 날짜·관세율·근거 기사

③ 우리 영향도 요약 (private에서만 상세)
   퓨처엠 수출입 품목(양극재·음극재·전구체·흑연)에 걸리는 조치만 필터

④ 기사 카드 그리드
   부과국·대상국·품목·단계·기간 필터
```

**데이터:** `private/data/disputes.json` — 정책과 동일하게 **분쟁을 엔티티로 관리**하고 기사를 상태 변화 이벤트로 붙인다.

```jsonc
{
  "disputes": [
    {
      "dispute_id": "ca-us-tariff-2026",
      "imposing_country": "US",
      "target_country": "CA",
      "measure_type": "tariff",
      "products": ["철강", "알루미늄"],
      "affects_futurem": false,
      "current_stage": "negotiating",
      "current_rate": "25%",
      "timeline": [
        { "date": "2026-03-04", "stage": "in_force", "rate": "25%", "article_ids": ["..."] },
        { "date": "2026-08-20", "stage": "negotiating", "article_ids": ["..."], "note": "면제 협상 개시" }
      ],
      "linked_issue_id": "2026-W35-ca-us-tariff"
    }
  ]
}
```

> `affects_futurem`이 **분쟁 필터의 핵심 필드**다. 세계 모든 관세 분쟁을 다 볼 필요는 없다. 양극재·음극재·전구체·흑연·리튬 품목에 걸리는 것만 상단 고정한다. 나머지는 "산업 배경" 수준으로 접어 둔다.

#### 4.6.8 기존 `/trade/` 페이지 처리 → P2-1 해소 (v1.2)

v1.0에서 미결로 남겨둔 **기존 `나라별 통상정책 현황` 페이지와의 중복** 문제는, 신규 T4 탭이 같은 주소를 쓰면서 자연스럽게 해소된다.

**확정: A안(흡수).** 기존 수기 큐레이션 내용을 `disputes.json`의 초기 시드로 이관하고, 이후는 자동 수집이 타임라인을 이어 붙인다. 기존 URL은 그대로 유지되므로 리다이렉트도 불필요하다.

---
