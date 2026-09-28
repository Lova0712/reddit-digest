# Reddit 게임개발 다이제스트

r/gamedev, r/indiedev, r/Unity3D 에서 입문 인디 개발자에게 유용한 글을 골라 **한국어로 번역·요약**하고,
매일 **PDF를 Gmail로 보내고 Notion 데이터베이스에 정리**하는 개인 학습용 도구입니다.

```
Reddit 수집 → 중복 제거 → 규칙 필터 → Claude 유용도 평가(1~10점) → 한국어 번역·요약
          → PDF 생성 → Gmail 발송 → Notion 업로드 → 처리 기록(SQLite)
```

- 번역은 Claude Code CLI(`claude -p`)를 호출해서 **Claude 구독(Pro/Max) 한도 안에서** 처리합니다. 종량제 API 요금이 나가지 않습니다.
- 결과물은 개인 학습용입니다. 원문 링크와 작성자를 항상 함께 표기하며, 외부 공개·재배포용이 아닙니다.
- Reddit 콘텐츠를 AI 모델 학습에 쓰지 않습니다.

---

## 1. 설치

필요한 것: Python 3.11 이상, [Claude Code](https://claude.com/claude-code) (구독 계정으로 로그인된 상태)

```powershell
git clone https://github.com/Lova0712/reddit-digest.git
cd reddit-digest
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # 그다음 .env 에 키를 채움 (아래 2번)
```

Mac/Linux 에서는 `.venv/bin/python`, `cp .env.example .env` 로 바꿔서 실행하세요.

> ⚠️ 키는 반드시 **`.env`** 에 넣으세요. `.env.example` 은 GitHub 에 올라가는 파일입니다.
> `.env` 에 `ANTHROPIC_API_KEY` 를 넣지 마세요. 넣으면 구독 대신 종량제 요금이 나갈 수 있습니다.

## 2. 키 발급

### Reddit (API 사용 승인 필요)
2025년 11월부터 Reddit API 는 개인 프로젝트도 **사전 승인**을 받아야 합니다 ([Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)).
1. https://www.reddit.com/prefs/apps 의 안내에 따라 API 사용 신청서를 제출합니다.
   분류는 *"I'm a developer and want to build a Reddit App that does not work in the Devvit ecosystem"* 입니다.
2. 승인되면 **script** 타입 앱을 만들고, 앱 이름 아래 문자열을 `REDDIT_CLIENT_ID`, `secret` 값을 `REDDIT_CLIENT_SECRET` 에 넣습니다.
3. `REDDIT_USER_AGENT` 는 `script:reddit-digest:v0.1 (by /u/내아이디)` 형식으로 적습니다.

승인 전에는 `samples/sample_posts.json` 의 **예시 글**로 전체 흐름을 시험할 수 있습니다 (아래 3번 `--sample`).

### Notion
1. https://www.notion.so/profile/integrations → **새 통합** → 유형 *내부(Internal)* → 저장 → **내부 통합 시크릿**을 복사해 `NOTION_TOKEN` 에 넣습니다.
2. Notion 에서 빈 페이지를 만들고, 오른쪽 위 **••• → 연결(Connections)** 에서 방금 만든 통합을 추가합니다.
3. 그 페이지의 링크를 복사해서 아래 명령을 한 번 실행합니다. 데이터베이스가 만들어지고 `NOTION_DATABASE_ID` 가 자동으로 채워집니다.
   ```powershell
   .\.venv\Scripts\python.exe setup_notion.py "<페이지 링크>"
   ```

### Gmail (앱 비밀번호)
1. https://myaccount.google.com/security 에서 **2단계 인증**을 켭니다.
2. https://myaccount.google.com/apppasswords 에서 앱 비밀번호를 만듭니다 (16자리).
3. `.env` 에 `GMAIL_USER`(보내는 주소), `GMAIL_APP_PASSWORD`(16자리), `GMAIL_TO`(받는 주소)를 넣습니다.

## 3. 실행

```powershell
.\.venv\Scripts\python.exe main.py                     # 전체 실행 (메일 + Notion)
.\.venv\Scripts\python.exe main.py --dry-run           # 수집·선별·번역·PDF 만 (발송 안 함)
.\.venv\Scripts\python.exe main.py --dry-run --limit 2 # 2개만 빠르게 시험
.\.venv\Scripts\python.exe main.py --sample --limit 2  # 예시 글로 실제 발송까지 시험
.\.venv\Scripts\python.exe -m pytest                   # 테스트 (외부 API 호출 없음)
```

결과물은 `output/` 에 저장됩니다.
- `reddit-digest-YYYY-MM-DD.pdf` : 메일에 첨부되는 PDF
- `digest-YYYY-MM-DD.md` : 번역 결과를 바로 읽을 수 있는 파일
- `digest.log` : 실행 기록 (자동 실행 결과도 여기서 확인)

Reddit 키가 없을 때 `--sample` 없이 실제 실행하면 **발송하지 않고 종료**합니다.
승인 전에 예시 글이 매일 발송되는 것을 막기 위해서입니다.

## 4. 설정 바꾸기 (`config.yaml`)

| 항목 | 설명 | 기본값 |
|---|---|---|
| `reddit.subreddits` | 가져올 서브레딧 | gamedev, indiedev, Unity3D |
| `filter.min_score` / `min_comments` | 최소 추천 수 / 댓글 수 | 20 / 5 |
| `filter.min_body_length` | 본문 최소 글자 수 | 300 |
| `filter.exclude_keywords` / `exclude_flairs` | 제외할 제목 문구 / 플레어 | 홍보 문구, Meme 등 |
| `filter.min_usefulness_score` | Claude 평가 기준 점수 (1~10) | 7 |
| `translate.max_posts_per_day` | 하루 최대 번역 글 수 (구독 한도 절약) | 10 |
| `translate.model` / `rating_model` | 번역 / 평가 모델 | sonnet / haiku |

## 5. 매일 자동 실행

### Windows (작업 스케줄러)
```powershell
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1              # 매일 20:30
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Time 07:30  # 시간 바꾸기
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Remove      # 해제
Start-ScheduledTask -TaskName RedditDigest                               # 지금 한 번 실행
```
- **로그인한 상태**에서만 실행됩니다 (claude 구독 로그인이 필요하기 때문).
- 그 시간에 컴퓨터가 꺼져 있었으면 **다음에 켰을 때 바로 실행**됩니다.
- 창 없이 실행되며, 결과는 `output/digest.log` 에서 확인합니다.
- 프로젝트 폴더를 옮기면 스크립트를 다시 실행해서 등록을 갱신하세요.

### Mac / Linux (cron)
`crontab -e` 를 열고 아래 한 줄을 추가합니다 (매일 20:30, 경로는 본인 것으로).
```cron
30 20 * * * cd /path/to/reddit-digest && .venv/bin/python main.py >> output/cron.log 2>&1
```
cron 은 PATH 가 짧아서 `claude` 를 못 찾을 수 있습니다. 그럴 때는 `which claude` 로 나온
전체 경로를 `config.yaml` 의 `translate.claude_command` 에 적어 주세요.
Mac 은 잠자기 중에는 cron 이 실행되지 않습니다.

## 6. 문제 해결

| 증상 (`output/digest.log`) | 해결 |
|---|---|
| `Reddit 키가 없어서 발송하지 않고 종료` | Reddit 승인 후 `.env` 에 키를 넣으면 해결 |
| `claude 에러` / `평가 실패` / `번역 실패` | 구독 사용 한도 초과일 수 있음. 그 글은 다음 실행 때 자동 재시도. 계속되면 `max_posts_per_day` 를 줄이기 |
| `'claude' 명령을 찾을 수 없습니다` | Claude Code 설치·로그인 확인, 또는 `claude_command` 에 전체 경로 |
| `Gmail 로그인 실패` | 앱 비밀번호 다시 만들기, 2단계 인증 켜져 있는지 확인 |
| `Notion 데이터베이스에 연결하지 못했습니다` | 페이지의 ••• → 연결에 통합이 추가되어 있는지 확인 |
| PDF 한글이 깨짐 | `fonts/` 에 NotoSansKR 폰트 파일이 있는지 확인 (`fonts/README.txt`) |

발송(메일·Notion)이 실패한 글은 번역 결과를 저장해 두었다가 **다음 실행 때 번역 없이 발송만 재시도**합니다.
같은 글이 메일로 두 번 가거나 Notion 에 중복으로 생기지 않습니다.

## 폴더 구조

```
main.py              전체 실행
setup_notion.py      Notion 데이터베이스 최초 생성
setup_schedule.ps1   Windows 자동 실행 등록
config.yaml          필터·번역·발송 설정
src/
  fetch.py           Reddit 수집 (praw)
  filter.py          규칙 필터 + Claude 유용도 평가
  translate.py       한국어 번역·요약
  claude_cli.py      claude -p 호출 (구독 사용)
  pdf_maker.py       PDF 생성 (reportlab + Noto Sans KR)
  mailer.py          Gmail 발송 (SMTP)
  notion_upload.py   Notion 업로드
  store.py           처리 기록 (SQLite)
samples/             Reddit 승인 전 테스트용 예시 글 (가짜 데이터)
fonts/               한글 폰트 (SIL Open Font License)
tests/               테스트 (외부 API 는 가짜로 대체)
```
