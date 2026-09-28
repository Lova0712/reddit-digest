"""
SQLite 로 "이미 처리한 글"을 기록해서 같은 글을 두 번 처리하지 않게 하는 모듈.

status 값의 의미
- done     : 번역하고 발송까지 끝난 글 → 다시 처리하지 않음
- rejected : Claude 유용도 평가에서 떨어진 글 → 다시 평가하지 않음 (한도 절약)
점수·댓글 수 같은 규칙 필터에서 떨어진 글은 기록하지 않습니다.
(시간이 지나 추천 수가 오르면 다음 실행 때 통과할 수 있으므로)
"""

import sqlite3
from datetime import datetime

# 이 상태인 글은 다음 실행 때 건너뜁니다.
SKIP_STATUSES = ("done", "rejected")


class Store:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id          TEXT PRIMARY KEY,  -- Reddit 글 id
                status      TEXT NOT NULL,     -- done / rejected
                usefulness  INTEGER,           -- Claude 유용도 점수 (1~10)
                title       TEXT,              -- 원문 제목 (확인용)
                updated_at  TEXT NOT NULL      -- 마지막으로 기록한 시각
            )
            """
        )
        self.conn.commit()

    def is_processed(self, post_id):
        """이미 처리했거나 평가에서 떨어진 글이면 True."""
        row = self.conn.execute("SELECT status FROM posts WHERE id = ?", (post_id,)).fetchone()
        return row is not None and row[0] in SKIP_STATUSES

    def mark(self, post_id, status, usefulness=None, title=""):
        """글의 처리 결과를 저장한다. 이미 있으면 덮어쓴다."""
        self.conn.execute(
            """
            INSERT INTO posts (id, status, usefulness, title, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                usefulness = excluded.usefulness,
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (post_id, status, usefulness, title, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
