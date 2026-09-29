"""
글을 가져오는 출처(커뮤니티)들. 출처마다 파일 하나씩 있고, 모두 같은 모양의 글(dict)을 돌려준다.

글 1개의 모양
{
  "id"          : "reddit:1abcd" 처럼 "출처:원래id" (출처가 달라도 겹치지 않게)
  "source"      : config.yaml 의 sources 아래 이름 (reddit_rss / devto / stackexchange)
  "community"   : 화면에 보일 출처 이름 (예: "r/gamedev", "dev.to #gamedev", "GameDev SE")
  "title", "author", "created_utc"(초 단위 시각), "permalink"(원문 주소),
  "selftext"    : 본문 (일반 텍스트, 코드는 ``` 로 감쌈)
  "score"       : 추천/반응 수 (모르면 None - Reddit RSS 는 제공하지 않음)
  "num_comments": 댓글/답변 수 (모르면 None)
  "tags"        : 원문 태그 목록
  "comments"    : [{"author", "score", "body"}] - 아직 안 가져왔으면 None
}

각 출처 클래스는 아래 두 가지를 제공한다.
  fetch_posts()               → 글 목록
  fetch_comments(post, limit) → 그 글의 댓글 목록
"""
