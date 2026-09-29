"""
인터넷에서 데이터를 받아오는 공통 함수.

- 모든 요청에 우리 프로그램을 알리는 User-Agent 를 붙인다 (config.yaml 의 http.user_agent)
- 요청 제한(429)이나 서버 에러(5xx)면 기다렸다가 다시 시도한다 (지수 백오프)
- 서버가 "몇 초 뒤에 다시 와라"(Retry-After)라고 알려 주면 그만큼 기다린다
"""

import logging
import time

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = (429, 500, 502, 503, 504)


def get(url, user_agent, params=None, retries=3, base_delay=5, timeout=30):
    """GET 요청을 보내고 응답(requests.Response)을 돌려준다. 끝내 실패하면 예외."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": user_agent}, timeout=timeout)
        except requests.RequestException as e:
            if attempt == retries:
                raise
            wait = base_delay * (2 ** attempt)
            log.warning("요청 실패(%s), %d초 후 다시 시도: %s", type(e).__name__, wait, url)
            time.sleep(wait)
            continue

        if resp.status_code in RETRY_STATUS and attempt < retries:
            wait = base_delay * (2 ** attempt)
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = max(wait, int(retry_after))
            log.warning("응답 %d, %d초 후 다시 시도: %s", resp.status_code, wait, url)
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp
