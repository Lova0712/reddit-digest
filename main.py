"""
Reddit 게임개발 다이제스트 - 전체 파이프라인 실행 파일

사용법
  python main.py                  전체 실행 (Notion 업로드, Gmail 발송까지)
  python main.py --dry-run        수집·선별·번역·PDF 만 하고 결과를 output/ 에 저장 (발송 안 함)
  python main.py --limit 3        번역할 글 개수를 3개로 제한 (테스트용)
  python main.py --sample         Reddit 대신 samples/sample_posts.json 예시 글 사용

Reddit 키(.env)가 없으면 자동으로 예시 글을 사용합니다.
"""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import fetch, filter as post_filter, notion_upload, pdf_maker, translate
from src.store import Store

ROOT = Path(__file__).parent
SAMPLE_PATH = ROOT / "samples" / "sample_posts.json"
log = logging.getLogger("main")


def parse_args():
    parser = argparse.ArgumentParser(description="Reddit 게임개발 다이제스트")
    parser.add_argument("--dry-run", action="store_true", help="메일/Notion 발송 없이 결과만 저장")
    parser.add_argument("--limit", type=int, help="번역할 글 최대 개수 (테스트용)")
    parser.add_argument("--sample", action="store_true", help="Reddit 대신 예시 글 사용")
    return parser.parse_args()


def setup_logging(log_path):
    """화면과 로그 파일에 같이 기록한다."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    # Notion 라이브러리가 요청마다 남기는 기록은 숨김 (경고 이상만 표시)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def collect_posts(cfg, use_sample):
    """글 수집 (Reddit 또는 예시 파일)."""
    if use_sample:
        log.info("예시 글(samples/sample_posts.json)을 사용합니다.")
        return fetch.load_sample_posts(SAMPLE_PATH), None
    reddit = fetch.make_reddit()
    return fetch.fetch_listings(reddit, cfg["reddit"]), reddit


def select_and_translate(cfg, args, store, use_sample, record):
    """수집 → 중복 제거 → 선별 → 번역. 새로 번역한 결과 목록을 돌려준다."""
    # 1. 수집
    posts, reddit = collect_posts(cfg, use_sample)
    log.info("수집: %d개", len(posts))

    # 2. 중복 제거 (이미 기록된 글 제외). 예시 글은 테스트용이라 기록과 상관없이 매번 처리
    if not use_sample:
        posts = [p for p in posts if not store.is_processed(p["id"])]
        log.info("중복 제거 후: %d개", len(posts))

    # 3-1. 규칙 필터
    fcfg = cfg["filter"]
    candidates = post_filter.rule_filter(posts, fcfg)

    # 번역 개수 제한: config 의 하루 최대치와 --limit 중 작은 값
    max_count = cfg["translate"]["max_posts_per_day"]
    if args.limit:
        max_count = min(max_count, args.limit)

    # 평가할 글 수 제한 (--limit 을 주면 그 3배까지만 평가해서 빠르게 테스트)
    max_rate = fcfg["max_candidates_to_rate"]
    if args.limit:
        max_rate = min(max_rate, args.limit * 3)
    candidates = candidates[:max_rate]

    # 평가 전에 댓글 가져오기 (예시 글에는 이미 들어 있음)
    if reddit:
        for p in candidates:
            try:
                p["comments"] = fetch.fetch_comments(reddit, p, cfg["reddit"]["comments_per_post"], cfg["reddit"])
            except Exception as e:
                log.error("댓글 가져오기 실패 (%s): %s", p["id"], e)

    # 3-2. Claude 유용도 평가 → 채택
    rated = post_filter.rate_posts(candidates, cfg["translate"])
    selected = post_filter.select_posts(rated, fcfg["min_usefulness_score"], max_count)
    log.info("채택: %d개 (기준 %d점 이상)", len(selected), fcfg["min_usefulness_score"])

    # 기준 점수에 못 미친 글은 다음에 다시 평가하지 않도록 기록
    if record:
        for p in rated:
            if p["usefulness"] < fcfg["min_usefulness_score"]:
                store.mark(p["id"], "rejected", p["usefulness"], p["title"])

    # 4. 번역·요약 (글 단위로 실패해도 계속 진행)
    results = []
    for p in selected:
        try:
            log.info("번역 중: %s", p["title"][:60])
            r = translate.translate_post(p, cfg["translate"])
            results.append(r)
            if record:
                store.save_translation(r)  # 발송이 실패해도 다음에 번역 없이 재시도
        except Exception as e:
            log.error("번역 실패 (%s): %s", p["id"], e)
    return results


def save_results(results, out_dir, today):
    """번역 결과를 JSON 과 Markdown(눈으로 확인용)으로 저장한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"digest-{today}.json"
    md_path = out_dir / f"digest-{today}.md"

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Reddit 게임개발 다이제스트 {today}", f"총 {len(results)}개 글", ""]
    for i, r in enumerate(results, 1):
        lines += [
            f"## {i}. {r['title_ko']}",
            f"*{r['original_title']}*",
            f"r/{r['subreddit']} · u/{r['author']} · {r['created_date']} · "
            f"추천 {r['score']} · 유용도 {r['usefulness']}/10 · 태그: {', '.join(r['tags'])}",
            f"원문: {r['permalink']}",
            "",
            "### 핵심 요약",
            *[f"- {s}" for s in r["summary"]],
            "",
            "### 본문 번역",
            r["body_ko"],
            "",
            "### 댓글 요약",
            *([f"- **{c['author']}**: {c['summary']}" for c in r["comments"]] or ["- (없음)"]),
            "",
        ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def upload_to_notion(cfg, results, today):
    """7. Notion 업로드. 성공한(또는 이미 있던) 글 id 집합을 돌려준다."""
    if not cfg["notion"]["enabled"]:
        log.info("Notion 업로드가 꺼져 있습니다 (config.yaml).")
        return {r["id"] for r in results}

    token, database_id = os.getenv("NOTION_TOKEN"), os.getenv("NOTION_DATABASE_ID")
    if not token or not database_id:
        log.error(".env 에 NOTION_TOKEN / NOTION_DATABASE_ID 가 없어 Notion 업로드를 건너뜁니다.")
        return set()

    client = notion_upload.make_client(token)
    try:
        data_source_id = notion_upload.get_data_source_id(client, database_id)
    except Exception as e:
        log.error("Notion 데이터베이스에 연결하지 못했습니다: %s", e)
        return set()

    ok = set()
    for r in results:
        try:
            url = notion_upload.upload_post(client, data_source_id, r, today)
            if url:
                log.info("Notion 업로드: %s", r["title_ko"][:40])
            ok.add(r["id"])
        except Exception as e:
            log.error("Notion 업로드 실패 (%s): %s", r["id"], e)
    return ok


def main():
    # 윈도우 콘솔에서도 한글이 깨지지 않게 UTF-8 로 출력
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    setup_logging(ROOT / cfg["storage"]["log_path"])

    use_sample = args.sample or not fetch.has_reddit_keys()
    if not args.sample and use_sample:
        log.warning(".env 에 Reddit 키가 없어서 예시 글을 사용합니다.")

    # DB 에 기록하는 경우: 실제 실행 + 실제 Reddit 글일 때만
    # (dry-run 이나 예시 글은 테스트라서 기록하지 않음)
    record = not args.dry_run and not use_sample

    store = Store(ROOT / cfg["storage"]["db_path"])
    try:
        # 지난번에 번역했지만 발송이 실패한 글이 있으면 함께 보냄
        pending = store.pending_translations() if record else []
        if pending:
            log.info("지난번 발송 실패한 글 %d개를 다시 보냅니다.", len(pending))

        results = pending + select_and_translate(cfg, args, store, use_sample, record)

        today = date.today().isoformat()
        out_dir = ROOT / cfg["output"]["pdf_dir"]
        json_path, md_path = save_results(results, out_dir, today)
        log.info("저장 완료: %s, %s", json_path.name, md_path.name)

        # 5. PDF 만들기
        ocfg = cfg["output"]
        pdf_path = pdf_maker.make_pdf(results, out_dir, today, ROOT / ocfg["font_path"], ROOT / ocfg["font_bold_path"])
        log.info("PDF 생성: %s", pdf_path.name)

        if args.dry_run:
            log.info("dry-run 이라 Notion/메일 발송은 하지 않습니다.")
            return 0
        if not results:
            log.info("보낼 글이 없습니다.")
            return 0

        # 6. Gmail 발송 - 5단계에서 추가 예정
        log.warning("Gmail 발송은 아직 준비 중입니다 (5단계).")

        # 7. Notion 업로드
        notion_ok = upload_to_notion(cfg, results, today)

        # 8. 기록: 발송이 끝난 글만 done. 실패한 글은 translated 로 남아 다음에 재시도
        if record:
            for r in results:
                if r["id"] in notion_ok:
                    store.mark(r["id"], "done")
        failed = len(results) - len(notion_ok)
        log.info("완료: 성공 %d개, 실패 %d개", len(notion_ok), failed)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
