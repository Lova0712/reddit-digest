"""
SQLite 로 글의 처리 상태를 기록해서 같은 글을 두 번 처리하지 않게 하는 모듈.

status 값의 의미
- translated : 번역까지 끝났지만 메일·Notion 발송이 아직 안 된 글
               → 다음 실행 때 번역 결과(data)를 그대로 다시 써서 발송만 재시도 (번역 한도 절약)
- mailed     : 메일은 보냈지만 Notion 업로드가 실패한 글 → 다음에 Notion 만 재시도
- done       : 메일·Notion 모두 끝난 글 → 다시 처리하지 않음
- rejected   : Claude 유용도 평가에서 떨어진 글 → 다시 평가하지 않음
점수·댓글 수 같은 규칙 필터에서 떨어진 글은 기록하지 않습니다.
(시간이 지나 추천 수가 오르면 다음 실행 때 통과할 수 있으므로)
"""

import json
import sqlite3
from datetime import datetime


class Store:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id          TEXT PRIMARY KEY,  -- Reddit 글 id
                status      TEXT NOT NULL,     -- translated / done / rejected
                usefulness  INTEGER,           -- Claude 유용도 점수 (1~10)
                title       TEXT,              -- 원문 제목 (확인용)
                updated_at  TEXT NOT NULL,     -- 마지막으로 기록한 시각
                data        TEXT               -- 번역 결과 JSON (재발송용)
            )
            """
        )
        # 예전 버전에서 만든 DB 에는 data 칸이 없을 수 있으므로 추가
        columns = [row[1] for row in self.conn.execute("PRAGMA table_info(posts)")]
        if "data" not in columns:
            self.conn.execute("ALTER TABLE posts ADD COLUMN data TEXT")
        self.conn.commit()

    def is_processed(self, post_id):
        """이미 기록된 글(번역됨·완료·탈락)이면 True → 수집 단계에서 건너뜀."""
        row = self.conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
        return row is not None

    def mark(self, post_id, status, usefulness=None, title="", data=None):
        """글의 처리 상태를 저장한다. 이미 있으면 덮어쓴다 (data 를 안 주면 기존 값 유지)."""
        self.conn.execute(
            """
            INSERT INTO posts (id, status, usefulness, title, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                usefulness = COALESCE(excluded.usefulness, posts.usefulness),
                title = COALESCE(NULLIF(excluded.title, ''), posts.title),
                updated_at = excluded.updated_at,
                data = COALESCE(excluded.data, posts.data)
            """,
            (post_id, status, usefulness, title, datetime.now().isoformat(timespec="seconds"),
             json.dumps(data, ensure_ascii=False) if data is not None else None),
        )
        self.conn.commit()

    def save_translation(self, result):
        """번역 결과를 저장해 둔다 (발송 실패 시 다시 번역하지 않도록)."""
        self.mark(result["id"], "translated", result.get("usefulness"), result["original_title"], data=result)

    def pending_translations(self):
        """
        번역은 됐지만 발송이 다 끝나지 않은 글들의 번역 결과 목록.
        각 결과에 "mailed" (메일을 이미 보냈는지) 값을 붙여서 돌려준다.
        """
        rows = self.conn.execute(
            "SELECT data, status FROM posts WHERE status IN ('translated', 'mailed') AND data IS NOT NULL "
            "ORDER BY updated_at"
        ).fetchall()
        results = []
        for data, status in rows:
            r = json.loads(data)
            r["mailed"] = status == "mailed"
            results.append(r)
        return results

    def close(self):
        self.conn.close()
