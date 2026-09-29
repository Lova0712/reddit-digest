# 게임개발 커뮤니티 다이제스트 자동화 (저장소 이름: reddit-digest)

## 프로젝트 개요
게임개발 커뮤니티(Reddit r/gamedev·r/indiedev·r/Unity3D, dev.to, GameDev Stack Exchange)에서
유용한 글을 골라 한국어로 번역·요약하고,
1) PDF로 만들어 내 Gmail로 보내고 2) Notion 데이터베이스에 자동으로 올리는 개인용 파이프라인.
사용자는 코딩 입문자이므로 코드는 단순하게, 주석은 한국어로 충분히 달 것.

## 기술 스택
- Python 3.11+
- 수집 (모두 로그인·승인 없이 쓰는 공식 피드/API. HTML 크롤링/스크래핑 금지):
  - Reddit: 공개 RSS 피드 (`/r/<sub>/top/.rss?t=week`, 댓글은 `<글주소>/.rss?sort=top`).
    Reddit Data API는 Responsible Builder Policy 사전 승인이 필요한데 2026-09 신청이 거절되어 쓰지 않음 (`praw` 제거).
    RSS에는 추천·댓글 수가 없음 → `score`/`num_comments`는 None, top 목록 순위(`rank`)로 대신.
    로그인 없는 요청 제한이 약 1분 1회로 매우 엄격 → `x-ratelimit-remaining/reset` 헤더를 읽어 대기. 댓글은 최종 채택된 글만 가져옴.
  - dev.to: 공식 API (`/api/articles?tag=&top=`, 본문 `/api/articles/<id>`, 댓글 `/api/comments?a_id=`)
  - GameDev Stack Exchange: 공식 API 2.3 (키 없이 하루 300회, 응답의 `backoff` 준수, CC BY-SA → 작성자·링크 표기)
  - HTTP는 `requests` (`src/http_util.py`에서 User-Agent·재시도 공통 처리). User-Agent는 `config.yaml`의 `http.user_agent`.
- 번역·요약: Claude Code CLI(`claude -p`)를 `subprocess`로 호출 — 사용자의 Claude 구독(Pro/Max) 한도 안에서 동작, 종량제 API 요금 없음.
  - `anthropic` 패키지/API 키는 쓰지 않는다.
  - 호출 시 환경 변수에서 `ANTHROPIC_API_KEY`를 반드시 제거한다 (있으면 CLI가 API 과금으로 전환됨).
  - 모델은 CLI 별칭(`sonnet`, `haiku`)으로 지정, 결과는 `--output-format json` + `--json-schema`의 `structured_output`으로 받음.
- PDF: `reportlab` + 한글 폰트(Noto Sans KR, `fonts/` 폴더에 ttf 포함). 한글 깨짐 반드시 확인.
- Gmail: SMTP(`smtplib`, smtp.gmail.com:465) + 앱 비밀번호. Gmail API(OAuth)는 개인용 테스트 앱의 토큰이 7일마다 만료돼 매일 자동 발송에 부적합하여 쓰지 않음.
- Notion: `notion-client` 3.x (API 2025-09-03: 데이터베이스 안의 data source에 페이지 생성)
- 중복 방지: `sqlite3` (표준 라이브러리)
- 설정: `.env` + `python-dotenv`, 출처·필터 규칙은 `config.yaml`

## 폴더 구조
```
reddit-digest/
├── CLAUDE.md
├── README.md
├── .env.example        # 키 이름만, 값은 비움
├── config.yaml         # 출처별 설정, 필터 기준, 발송 설정
├── main.py             # 전체 파이프라인 실행 진입점
├── setup_notion.py     # Notion 데이터베이스 최초 생성
├── setup_schedule.ps1  # Windows 작업 스케줄러 등록 (UTF-8 BOM으로 저장)
├── src/
│   ├── sources/        # 출처별 수집 (모두 같은 모양의 글 dict 반환, __init__.py에 형식 설명)
│   │   ├── reddit_rss.py
│   │   ├── devto.py
│   │   └── stackexchange.py
│   ├── fetch.py        # 켜진 출처들에서 모으기 + 채택 글 댓글 채우기 + 예시 글 읽기
│   ├── filter.py       # "쓸만한 글" 선별 (본문 길이·제외 키워드 → Claude 평가)
│   ├── translate.py    # 한국어 번역·요약
│   ├── pdf_maker.py    # PDF 생성
│   ├── mailer.py       # Gmail 발송
│   ├── notion_upload.py# Notion 업로드 (칸 구성 자동 갱신 포함)
│   ├── store.py        # SQLite 처리 상태 기록
│   ├── claude_cli.py   # claude -p 호출 (구독 사용, API 키 제거)
│   ├── http_util.py    # 공통 GET (User-Agent, 재시도)
│   └── text_util.py    # HTML→텍스트, 출처 한 줄 요약(byline)
├── samples/
│   └── sample_posts.json # 테스트용 가짜 예시 글
├── fonts/
├── output/             # 생성된 PDF·로그 (git 제외)
└── tests/
```

## 파이프라인
1. **수집**: `config.yaml`의 `sources`에서 켜진 출처마다 인기 글을 가져온다.
   - 추천·댓글 수 기준(dev.to `min_reactions`, SE `min_score`/`min_answers`)은 각 출처 모듈이 먼저 거른다.
2. **중복 제거**: SQLite에 이미 기록된 id(`reddit:…`, `devto:…`, `se:…`)는 건너뛴다.
3. **선별**:
   - 규칙 필터: 본문 최소 길이(링크·이미지·짧은 글 제외), 제목 제외 키워드(자기 홍보 문구, 밈)
   - 우선 키워드가 있는 글을 앞으로, 출처끼리 번갈아 섞은 뒤 `max_candidates_to_rate`개까지만 평가
   - Claude(haiku)로 "입문 인디 개발자에게 유용한가" 1~10점 평가, 기준 점수 이상만 채택 (하루 최대 `max_posts_per_day`)
   - 채택된 글만 댓글을 가져온다 (SE 답변은 수집 때 함께, 채택 답변 우선)
4. **번역·요약**: 한국어 제목, 3~5줄 요약, 본문 번역(길면 요약 번역), 유용한 댓글 1~3개 요약, 원문 링크·출처·작성자·작성일.
   게임 개발 용어는 괄호로 원어 병기 (예: 오브젝트 풀링(Object Pooling))
5. **PDF**: 표지(날짜, 글 개수, 출처) → 목차 → 글별 섹션. 파일명 `reddit-digest-YYYY-MM-DD.pdf`
6. **Gmail**: PDF 첨부 + 본문에 글 제목 목록과 원문 링크. 받는 주소는 `.env`의 `GMAIL_TO`.
7. **Notion**: 글 1개당 페이지 1개.
   - 속성: 제목(title), 출처(select), 원문 링크(url), 점수(number, 모르면 빈칸), 유용도(number), 태그(multi_select), 날짜(date, 수집한 날), 작성자(rich_text)
   - 예전 "서브레딧" 칸은 실행 시 `ensure_schema`가 "출처"로 자동 변경
   - Notion 제한: rich_text 하나당 2000자, 요청당 블록 100개 → 자동으로 쪼개서 보냄. 같은 원문 링크가 있으면 건너뜀.
8. **기록**: 상태 `translated`(번역만 됨) → `mailed`(메일만 됨) → `done`. 평가 탈락은 `rejected`.
   발송 실패 글은 다음 실행 때 번역 없이 발송만 재시도, 메일 중복 발송 없음.

## 실행
- `python main.py` : 전체 실행
- `python main.py --dry-run` : 수집·선별·번역·PDF만 하고 메일/Notion 발송 안 함 (결과는 output/에 저장)
- `python main.py --limit 3` : 테스트용 개수 제한
- `python main.py --sample` : 실제 수집 대신 samples/ 예시 글 사용 (DB에 기록하지 않음)
- `python setup_notion.py <페이지 링크>` : Notion 데이터베이스를 처음 한 번 만들고 `.env`에 ID 저장 (완료됨)
- 자동 실행: 매일 20:30 1회. Windows 작업 스케줄러에 `setup_schedule.ps1`로 등록됨 (작업 이름 `RedditDigest`, 로그인 시에만, 놓치면 다음 부팅 때 실행, pythonw로 창 없이). Mac/Linux cron 방법은 README에 정리.
- `setup_schedule.ps1`은 Windows PowerShell 5.1이 한글을 읽도록 UTF-8 BOM으로 저장해야 함.

## 환경 변수 (.env)
```
GMAIL_TO=
GMAIL_USER=
GMAIL_APP_PASSWORD=
NOTION_TOKEN=
NOTION_DATABASE_ID=
```
`.env`는 git에 올리지 않는다. 키를 `.env.example`에 넣지 않도록 주의 (그 파일은 git에 올라감).

## 규칙
- API 키·토큰은 절대 코드에 하드코딩하지 않는다. `.env`, `output/`, `*.db`는 `.gitignore`에 추가.
- 각 출처의 이용 규칙과 요청 제한을 지킨다. 요청 사이에 적절한 대기, 에러 시 지수 백오프, 서버가 알려 준 대기 시간(Retry-After, ratelimit 헤더, SE backoff) 준수.
- Reddit RSS는 개인 피드 리더 수준으로만 쓴다 (하루 1회, 목록 3개 + 채택 글 댓글). 요청 수를 늘리는 변경은 하지 않는다.
- 결과물은 개인 학습용. 원문 링크와 작성자를 항상 함께 표기하고, 외부 공개/재배포용으로 만들지 않는다. 수집한 글을 AI 학습에 쓰지 않는다.
- 구독 사용 한도를 아끼기 위해: 선별을 먼저 하고 번역은 채택된 글만. 하루 최대 번역 글 수를 config로 제한.
- 사용 한도 초과 등으로 `claude` 호출이 실패하면 그 글은 건너뛰고 다음 실행 때 재시도 (유료 API로 대체하지 않는다).
- 각 모듈은 독립적으로 테스트 가능하게 작성하고, 외부 API는 테스트에서 mock 처리.
- 에러가 나도 한 글(한 출처) 때문에 전체가 멈추지 않게 글 단위·출처 단위로 try/except.
- 새 패키지를 추가하면 `requirements.txt`에 반영.
- 코드 수정 후에는 `--dry-run --limit 2`로 한 번 돌려서 확인하고 결과를 알려줄 것.
