"""
Claude Code CLI(`claude -p`)를 파이썬에서 호출하는 모듈.

- 종량제 API가 아니라 사용자의 Claude 구독(Pro/Max) 로그인으로 동작합니다.
- 그래서 호출할 때 ANTHROPIC_API_KEY 환경 변수를 반드시 지웁니다.
  (이 값이 있으면 CLI가 API 키로 과금하는 방식으로 바뀝니다.)
- 결과는 --json-schema 로 형식을 정해서 받기 때문에 파싱이 안정적입니다.
"""

import json
import os
import shutil
import subprocess
import tempfile


class ClaudeError(Exception):
    """claude 호출이 실패했을 때 쓰는 에러 (사용 한도 초과, 시간 초과 등)."""


def _clean_env():
    """과금 방식이 바뀌지 않도록 API 키 관련 환경 변수를 뺀 복사본을 만든다."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def ask_json(prompt, schema, system_prompt, model="sonnet", timeout=300, command="claude"):
    """
    claude 에게 prompt 를 보내고, schema 형식에 맞는 dict 를 돌려받는다.

    prompt        : 질문 내용 (글 본문 등, 길어도 됨 - 표준입력으로 전달)
    schema        : 받고 싶은 JSON 형식 (JSON Schema dict)
    system_prompt : Claude 의 역할 설명
    model         : "sonnet", "haiku" 같은 CLI 모델 별칭
    """
    exe = shutil.which(command) or command
    cmd = [
        exe,
        "-p",                              # 대화창 없이 한 번 답하고 종료
        "--model", model,
        "--output-format", "json",         # 결과를 JSON 으로 받기
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--system-prompt", system_prompt,  # 긴 기본 프롬프트 대신 짧은 역할 설명 (한도 절약)
        "--tools", "",                     # 파일 읽기/명령 실행 같은 도구는 쓰지 않음
        "--safe-mode",                     # CLAUDE.md, 플러그인 등을 불러오지 않음
        "--no-session-persistence",        # 대화 기록을 디스크에 남기지 않음
    ]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,                  # 긴 글은 명령줄 대신 표준입력으로 전달
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_clean_env(),
            timeout=timeout,
            cwd=tempfile.gettempdir(),     # 프로젝트 폴더 밖에서 실행
        )
    except FileNotFoundError:
        raise ClaudeError(f"'{command}' 명령을 찾을 수 없습니다. Claude Code가 설치되어 있는지 확인하세요.")
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"{timeout}초 안에 응답이 없어 중단했습니다.")

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:500]
        raise ClaudeError(f"claude 실행 실패 (코드 {result.returncode}): {detail}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(f"claude 응답을 JSON으로 읽을 수 없습니다: {result.stdout[:300]}")

    # 사용 한도 초과 같은 경우 is_error 가 True 로 옵니다.
    if data.get("is_error"):
        raise ClaudeError(f"claude 에러: {str(data.get('result'))[:500]}")

    output = data.get("structured_output")
    if isinstance(output, dict):
        return output

    # 혹시 structured_output 이 없으면 result 텍스트를 JSON 으로 읽어 본다.
    try:
        output = json.loads(data.get("result") or "")
    except json.JSONDecodeError:
        output = None
    if isinstance(output, dict):
        return output
    raise ClaudeError("claude 응답에 원하는 형식의 결과가 없습니다.")
