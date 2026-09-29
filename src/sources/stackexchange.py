"""
Game Development Stack Exchange 공식 API 로 추천 많은 질문과 답변을 가져온다.

- 키 없이 하루 300회까지 무료 (우리는 하루 2회 정도만 씀)
- 콘텐츠는 CC BY-SA 라이선스: 작성자와 원문 링크를 표기하면 번역·재사용 가능
- 서버가 응답에 "backoff": N 을 주면 N초 기다린 뒤 다음 요청을 보내야 한다 (API 규칙)
"""

import logging
import time

from src import http_util
from src.text_util import clean_title, html_to_text

log = logging.getLogger(__name__)

API = "https://api.stackexchange.com/2.3"


class StackExchange:
    def __init__(self, cfg, user_agent):
        self.cfg = cfg
        self.user_agent = user_agent

    def _get_json(self, path, params):
        params = {"site": self.cfg["site"], "filter": "withbody", **params}
        data = http_util.get(f"{API}/{path}", self.user_agent, params=params).json()
        if data.get("backoff"):
            log.info("Stack Exchange 요청 간격 요구: %d초 대기", data["backoff"])
            time.sleep(data["backoff"])
        return data

    def fetch_posts(self):
        """
        mode 설정에 따라
        - classic : 역대 추천 많은 질문 (GameDev SE 는 새 질문이 적어서 기본값).
                    이미 처리한 질문은 DB 로 걸러지므로 매일 새로운 명작 Q&A 가 조금씩 나온다.
        - recent  : 최근 days 일 동안 올라온 질문
        """
        cfg = self.cfg
        params = {"order": "desc", "sort": "votes", "pagesize": cfg["max_questions"]}
        if cfg.get("mode") == "recent":
            params["fromdate"] = int(time.time()) - cfg["days"] * 86400
        try:
            data = self._get_json("questions", params)
        except Exception as e:
            log.error("Stack Exchange 질문을 가져오지 못했습니다: %s", e)
            return []

        questions = [q for q in data.get("items", [])
                     if q["score"] >= cfg["min_score"] and q.get("answer_count", 0) >= cfg["min_answers"]]
        log.info("GameDev SE: %d개 중 기준 통과 %d개", len(data.get("items", [])), len(questions))

        answers = self._fetch_answers([q["question_id"] for q in questions]) if questions else {}
        return [self._to_post(q, answers.get(q["question_id"], [])) for q in questions]

    def _fetch_answers(self, question_ids):
        """여러 질문의 답변을 한 번에 가져와서 {질문 id: [댓글 형식 답변]} 으로 돌려준다."""
        try:
            ids = ";".join(str(i) for i in question_ids[:100])
            data = self._get_json(f"questions/{ids}/answers", {"order": "desc", "sort": "votes", "pagesize": 100})
        except Exception as e:
            log.error("Stack Exchange 답변을 가져오지 못했습니다: %s", e)
            return {}
        grouped = {}
        for a in data.get("items", []):
            grouped.setdefault(a["question_id"], []).append(a)

        result = {}
        for qid, items in grouped.items():
            # 채택된 답변을 맨 앞에, 그다음 추천 많은 순
            items.sort(key=lambda a: (a.get("is_accepted", False), a["score"]), reverse=True)
            result[qid] = [{
                "author": clean_title(a.get("owner", {}).get("display_name", "익명")),
                "score": a["score"],
                "body": ("[채택된 답변] " if a.get("is_accepted") else "") + html_to_text(a.get("body", "")),
            } for a in items[:self.cfg["answers_per_question"]]]
        return result

    def _to_post(self, q, answers):
        return {
            "id": f"se:{q['question_id']}",
            "source": "stackexchange",
            "community": "GameDev SE",
            "title": clean_title(q["title"]),
            "author": clean_title(q.get("owner", {}).get("display_name", "익명")),
            "created_utc": q["creation_date"],
            "permalink": q["link"],
            "selftext": html_to_text(q.get("body", "")),
            "score": q["score"],
            "num_comments": q.get("answer_count", 0),
            "tags": q.get("tags", []),
            "comments": answers,  # 답변은 질문과 함께 이미 가져옴
        }

    def fetch_comments(self, post, limit):
        # 답변은 fetch_posts 에서 함께 가져오므로 따로 요청하지 않음
        return (post.get("comments") or [])[:limit]
