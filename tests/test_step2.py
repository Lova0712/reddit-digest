"""
2단계(수집·중복·선별·번역) 테스트.
실제 Reddit·Claude 를 부르지 않도록 가짜(mock) 함수를 사용합니다.
실행: python -m pytest
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from src import claude_cli, fetch, filter as post_filter, translate
from src.store import Store

ROOT = Path(__file__).parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def sample_posts():
    return fetch.load_sample_posts(ROOT / "samples" / "sample_posts.json")


# ───────────── store ─────────────

def test_store_skips_done_and_rejected(tmp_path):
    store = Store(tmp_path / "test.db")
    assert not store.is_processed("a")
    store.mark("a", "done", 9, "제목")
    store.mark("b", "rejected", 3)
    assert store.is_processed("a")
    assert store.is_processed("b")
    store.close()


# ───────────── filter (규칙) ─────────────

def test_rule_filter_keeps_useful_and_drops_junk():
    passed = post_filter.rule_filter(sample_posts(), CFG["filter"])
    ids = {p["id"] for p in passed}
    assert ids == {"sample01", "sample02", "sample05"}  # 포스트모템, 튜토리얼, 좋은 Q&A


def test_rule_filter_reasons():
    posts = {p["id"]: p for p in sample_posts()}
    f = CFG["filter"]
    assert "키워드" in post_filter.check_rules(posts["sample03"], f)  # 위시리스트 홍보
    assert "플레어" in post_filter.check_rules(posts["sample04"], f)  # 밈
    assert "추천 수" in post_filter.check_rules(posts["sample06"], f)  # 추천 수 부족


def test_wishlist_marketing_post_is_not_excluded():
    """'wishlist' 가 들어간 좋은 마케팅 글은 제외 키워드에 걸리면 안 된다."""
    post = sample_posts()[0]
    post["title"] = "How I got 7,000 wishlists before launch"
    assert post_filter.check_rules(post, CFG["filter"]) is None


# ───────────── filter (Claude 평가, mock) ─────────────

def fake_rating(prompt, schema, system_prompt, **kwargs):
    # 제목에 Postmortem 이 있으면 9점, 아니면 5점을 주는 가짜 평가
    return {"score": 9 if "Postmortem" in prompt else 5, "reason": "테스트"}


def test_rate_and_select():
    passed = post_filter.rule_filter(sample_posts(), CFG["filter"])
    rated = post_filter.rate_posts(passed, CFG["translate"], ask=fake_rating)
    selected = post_filter.select_posts(rated, min_score=7, max_count=10)
    assert [p["id"] for p in selected] == ["sample01"]


def test_rate_continues_after_one_failure():
    """한 글의 평가가 실패해도 나머지는 계속 평가된다."""
    calls = []

    def flaky(prompt, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise claude_cli.ClaudeError("사용 한도 초과")
        return {"score": 8, "reason": "ok"}

    passed = post_filter.rule_filter(sample_posts(), CFG["filter"])
    rated = post_filter.rate_posts(passed, CFG["translate"], ask=flaky)
    assert len(rated) == len(passed) - 1


# ───────────── translate (mock) ─────────────

def test_translate_post_keeps_source_info():
    post = sample_posts()[1]

    def fake_translate(prompt, schema, system_prompt, **kwargs):
        return {
            "title_ko": "오브젝트 풀링(Object Pooling)으로 GC 스파이크 줄이기",
            "summary": ["a", "b", "c", "d", "e", "f"],  # 6개 → 5개로 잘려야 함
            "body_ko": "번역",
            "comments": [{"author": "x", "summary": "요약"}],
            "tags": ["Unity", "없는태그"],  # 목록에 없는 태그는 빠져야 함
        }

    r = translate.translate_post(post, CFG["translate"], ask=fake_translate)
    assert r["permalink"] == post["permalink"]
    assert r["author"] == post["author"]
    assert len(r["summary"]) == 5
    assert r["tags"] == ["Unity"]


def test_translate_prompt_truncates_long_body():
    post = dict(sample_posts()[0], selftext="x" * 20000)
    prompt = translate.build_translate_prompt(post, max_body_chars=8000)
    assert "이후 생략됨" in prompt
    assert len(prompt) < 12000


# ───────────── claude_cli (subprocess mock) ─────────────

def test_claude_cli_removes_api_key(monkeypatch):
    """API 키가 환경에 있어도 claude 에는 전달되지 않아야 한다 (과금 방지)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["env"] = kwargs["env"]
        out = {"is_error": False, "structured_output": {"score": 7, "reason": "r"}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = claude_cli.ask_json("p", {}, "s")
    assert result == {"score": 7, "reason": "r"}
    assert "ANTHROPIC_API_KEY" not in seen["env"]


def test_claude_cli_raises_on_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        out = {"is_error": True, "result": "usage limit reached"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(claude_cli.ClaudeError):
        claude_cli.ask_json("p", {}, "s")
