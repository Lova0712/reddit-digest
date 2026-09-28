"""
Notion 데이터베이스를 처음 한 번 만드는 스크립트.

사용법
  python setup_notion.py <Notion 페이지 링크>

미리 할 일
  1) .env 에 NOTION_TOKEN 입력
  2) 그 Notion 페이지의 ••• → 연결(Connections) 에 통합(reddit-digest) 추가

실행하면 페이지 안에 데이터베이스가 만들어지고, .env 의 NOTION_DATABASE_ID 가 자동으로 채워집니다.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv, set_key

from src import notion_upload

ENV_PATH = Path(__file__).parent / ".env"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("사용법: python setup_notion.py <Notion 페이지 링크>")
        return 1

    load_dotenv(ENV_PATH)
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print(".env 에 NOTION_TOKEN 이 없습니다.")
        return 1
    if os.getenv("NOTION_DATABASE_ID"):
        print("이미 NOTION_DATABASE_ID 가 있습니다. 새로 만들려면 .env 에서 그 값을 지우고 다시 실행하세요.")
        return 1

    page_id = notion_upload.page_id_from_url(sys.argv[1])
    client = notion_upload.make_client(token)
    try:
        db_id = notion_upload.create_database(client, page_id)
    except Exception as e:
        print(f"데이터베이스를 만들지 못했습니다: {e}")
        print("→ 페이지의 ••• → 연결(Connections) 에 통합을 추가했는지 확인하세요.")
        return 1

    set_key(str(ENV_PATH), "NOTION_DATABASE_ID", db_id, quote_mode="never")
    print(f"완료! 데이터베이스를 만들고 .env 에 NOTION_DATABASE_ID 를 저장했습니다. ({db_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
