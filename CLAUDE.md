# Reddit 게임개발 다이제스트 자동화

## 프로젝트 개요
r/gamedev, r/indiedev, r/Unity3D에서 유용한 글을 골라 한국어로 번역·요약하고,
1) PDF로 만들어 내 Gmail로 보내고 2) Notion 데이터베이스에 자동으로 올리는 개인용 파이프라인.
사용자는 코딩 입문자이므로 코드는 단순하게, 주석은 한국어로 충분히 달 것.

## 기술 스택
- Python 3.11+
- Reddit: `praw` (공식 Reddit API, OAuth 스크립트 앱). HTML 크롤링/스크래핑 금지.
- 번역·요약: Claude Code CLI(`claude -p`)를 `subprocess`로 호출 — 사용자의 Claude 구독(Pro/Max) 한도 안에서 동작, 종량제 API 요금 없음.
  - `anthropic` 패키지/API 키는 쓰지 않는다.
  - 호출 시 환경 변수에서 `ANTHROPIC_API_KEY`를 반드시 제거한다 (있으면 CLI가 API 과금으로 전환됨).
  - 모델은 CLI 별칭(`sonnet`, `haiku`)으로 지정, 결과는 `--output-format json`으로 받아 파싱.
- PDF: `reportlab` + 한글 폰트(Noto Sans KR, `fonts/` 폴더에 ttf 포함). 한글 깨짐 반드시 확인.
- Gmail: SMTP(`smtplib`, smtp.gmail.com:465) + 앱 비밀번호. Gmail API(OAuth)는 개인용 테스트 앱의 토큰이 7일마다 만료돼 매일 자동 발송에 부적합하여 쓰지 않음.
- Notion: `notion-client` (Notion 공식 API, 통합(Integration) 토큰)
- 중복 방지: `sqlite3` (표준 라이브러리)
- 설정: `.env` + `python-dotenv`, 필터 규칙은 `config.yaml`

## 폴더 구조
```
reddit-digest/
├── CLAUDE.md
├── .env.example        # 키 이름만, 값은 비움
├── config.yaml         # 서브레딧, 필터 기준, 발송 설정
├── main.py             # 전체 파이프라인 실행 진입점
├── src/
│   ├── fetch.py        # Reddit 글 수집
│   ├── filter.py       # "쓸만한 글" 선별
│   ├── translate.py    # 한국어 번역·요약
│   ├── pdf_maker.py    # PDF 생성
│   ├── mailer.py       # Gmail 발송
│   ├── notion_upload.py# Notion 업로드
│   ├── store.py        # SQLite 중복 체크
│   └── claude_cli.py   # claude -p 호출 (구독 사용, API 키 제거)
├── samples/
│   └── sample_posts.json # Reddit API 승인 전 테스트용 가짜 예시 글
├── fonts/
├── output/             # 생성된 PDF (git 제외)
└── tests/
```

## 파이프라인
1. **수집**: 각 서브레딧의 `top`(기간: week) + `hot`에서 글을 가져온다. 서브레딧당 최대 개수는 config에서 설정.
2. **중복 제거**: SQLite에 이미 처리한 post id가 있으면 건너뛴다.
3. **선별** (config.yaml로 조정 가능한 기준):
   - 점수(upvote) 최소값, 댓글 수 최소값
   - 제외: 밈/짤, 단순 자기 홍보, 스크린샷만 있는 글, 본문이 너무 짧은 글
   - 우선: 튜토리얼, 포스트모템, 마케팅/출시 경험담, 기술 Q&A 중 답변이 좋은 글, Unity 팁
   - 규칙 필터 통과 후 Claude로 "입문 인디 개발자에게 유용한가" 1~10점 평가, 기준 점수 이상만 채택
4. **번역·요약**: 글마다 아래 형식으로 생성
   - 한국어 제목
   - 3~5줄 핵심 요약
   - 본문 한국어 번역 (길면 핵심 부분 위주로 요약 번역)
   - 유용한 댓글 1~3개 요약
   - 원문 링크, 서브레딧, 작성자, 작성일
   - 게임 개발 용어는 괄호로 원어 병기 (예: 오브젝트 풀링(Object Pooling))
5. **PDF**: 하루치 글을 한 파일로 묶는다. 표지(날짜, 글 개수) → 목차 → 글별 섹션. 파일명 `reddit-digest-YYYY-MM-DD.pdf`
6. **Gmail**: PDF 첨부 + 본문에 글 제목 목록과 원문 링크. 받는 주소는 `.env`의 `GMAIL_TO`.
7. **Notion**: 데이터베이스에 글 1개당 페이지 1개 생성.
   - 속성: 제목(title), 서브레딧(select), 원문 링크(url), 점수(number), 유용도(number), 태그(multi_select), 날짜(date)
   - 본문 블록: 요약 → 번역 → 댓글 요약
   - Notion 제한 주의: rich_text 하나당 2000자, 요청당 블록 100개 → 자동으로 쪼개서 보낼 것
8. **기록**: 성공한 post id를 SQLite에 저장. 실패한 단계는 로그에 남기고 다음 실행 때 재시도.

## 실행
- `python main.py` : 전체 실행
- `python main.py --dry-run` : 수집·선별·번역만 하고 메일/Notion 발송 안 함 (결과는 output/에 저장)
- `python main.py --limit 3` : 테스트용 개수 제한
- `python setup_notion.py <페이지 링크>` : Notion 데이터베이스를 처음 한 번 만들고 `.env`에 ID 저장 (완료됨)
- `python main.py --sample` : Reddit 대신 samples/ 예시 글 사용 (`.env`에 Reddit 키가 없으면 자동 적용)
- Reddit API는 Responsible Builder Policy에 따라 사전 승인이 필요함 (2026-09-29 신청). 승인 전까지는 예시 글로 개발.
- 자동 실행: 매일 아침 1회. Windows면 작업 스케줄러, Mac/Linux면 cron 설정 방법을 README에 정리.

## 환경 변수 (.env)
```
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=reddit-digest/0.1 by <reddit 아이디>
GMAIL_TO=
GMAIL_USER=
GMAIL_APP_PASSWORD=
NOTION_TOKEN=
NOTION_DATABASE_ID=
```
`.env`는 git에 올리지 않는다. 키를 `.env.example`에 넣지 않도록 주의 (그 파일은 git에 올라감).

## 규칙
- API 키·토큰은 절대 코드에 하드코딩하지 않는다. `.env`, `credentials.json`, `token.json`, `output/`, `*.db`는 `.gitignore`에 추가.
- Reddit API 이용 규칙과 요청 제한(rate limit)을 지킨다. 요청 사이에 적절한 대기, 에러 시 지수 백오프.
- 결과물은 개인 학습용. 원문 링크와 작성자를 항상 함께 표기하고, 외부 공개/재배포용으로 만들지 않는다.
- 구독 사용 한도를 아끼기 위해: 선별을 먼저 하고 번역은 채택된 글만. 하루 최대 번역 글 수를 config로 제한.
- 사용 한도 초과 등으로 `claude` 호출이 실패하면 그 글은 건너뛰고 다음 실행 때 재시도 (유료 API로 대체하지 않는다).
- 각 모듈은 독립적으로 테스트 가능하게 작성하고, 외부 API는 테스트에서 mock 처리.
- 에러가 나도 한 글 때문에 전체가 멈추지 않게 글 단위로 try/except.
- 새 패키지를 추가하면 `requirements.txt`에 반영.
- 코드 수정 후에는 `--dry-run --limit 2`로 한 번 돌려서 확인하고 결과를 알려줄 것.

## 작업 순서 (처음 세팅 시)
1. 폴더 구조, requirements.txt, .env.example, config.yaml 생성
2. fetch → filter → translate를 먼저 만들고 dry-run으로 확인
3. PDF 생성 (한글 폰트 확인)
4. Notion 업로드
5. Gmail 발송
6. 스케줄러 설정 + README 작성
각 단계 끝날 때마다 사용자에게 필요한 키 발급 방법(Reddit 앱 생성, Notion 통합 연결, Gmail API 활성화)을 쉽게 안내할 것.
