import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PTT_BASE_URL = "https://www.ptt.cc"
PTT_BOARD_PATH = "/bbs/Drama-Ticket/index.html"
PTT_URL = f"{PTT_BASE_URL}{PTT_BOARD_PATH}"

KEYWORD = r"\bive\b"

SEEN_FILE = Path("seen.json")

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = (10, 30)
MAX_SEEN_RECORDS = 3000


def load_seen() -> list[str]:
    """讀取已處理過的文章 URL。"""

    if not SEEN_FILE.exists():
        return []

    try:
        with SEEN_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            print("seen.json 格式錯誤，將重新建立")
            return []

        return [
            item
            for item in data
            if isinstance(item, str)
        ]

    except (json.JSONDecodeError, OSError) as error:
        print(f"讀取 seen.json 失敗：{error}")
        return []


def save_seen(data: list[str]) -> None:
    """儲存已處理過的文章 URL。"""

    # 去除重複項目，同時保留原本順序
    unique_data = list(dict.fromkeys(data))

    # 避免 seen.json 無限制增長
    unique_data = unique_data[-MAX_SEEN_RECORDS:]

    try:
        with SEEN_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                unique_data,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except OSError as error:
        print(f"寫入 seen.json 失敗：{error}")


def create_retry_session() -> requests.Session:
    """建立包含重試機制的 requests Session。"""

    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=frozenset([
            "GET",
            "POST",
        ]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(HEADERS)

    return session


def get_ptt_session() -> requests.Session:
    """建立可瀏覽 PTT 看板的 Session。"""

    session = create_retry_session()

    # 直接設定 PTT 年齡驗證 Cookie，
    # 避免額外呼叫 /ask/over18。
    session.cookies.set(
        name="over18",
        value="1",
        domain="www.ptt.cc",
        path="/",
    )

    return session


def get_articles() -> list[dict[str, str]]:
    """抓取 PTT Drama-Ticket 看板首頁文章。"""

    session = get_ptt_session()

    try:
        response = session.get(
            PTT_URL,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

    except requests.exceptions.Timeout:
        print("連線 PTT 逾時")
        return []

    except requests.exceptions.ConnectionError as error:
        print(f"無法連線至 PTT：{error}")
        return []

    except requests.exceptions.HTTPError as error:
        print(f"PTT 回傳 HTTP 錯誤：{error}")
        return []

    except requests.exceptions.RequestException as error:
        print(f"抓取 PTT 時發生錯誤：{error}")
        return []

    finally:
        session.close()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    # 如果被導向年齡驗證頁，代表 Cookie 沒有生效
    if soup.select_one("form[action='/ask/over18']"):
        print("PTT 年齡驗證 Cookie 未生效")
        return []

    articles: list[dict[str, str]] = []

    for item in soup.select(".r-ent"):
        title_element = item.select_one(".title a")

        # 文章被刪除時通常沒有連結
        if title_element is None:
            continue

        title = title_element.get_text(
            strip=True
        )

        href = title_element.get("href")

        if not title or not href:
            continue

        author_element = item.select_one(".author")
        date_element = item.select_one(".date")

        article = {
            "title": title,
            "url": f"{PTT_BASE_URL}{href}",
            "author": (
                author_element.get_text(strip=True)
                if author_element
                else "未知"
            ),
            "date": (
                date_element.get_text(strip=True)
                if date_element
                else "未知"
            ),
        }

        articles.append(article)

    return articles


def send_discord(article: dict[str, str]) -> bool:
    """將文章通知傳送到 Discord。"""

    if not DISCORD_WEBHOOK:
        print("沒有設定 DISCORD_WEBHOOK")
        return False

    payload: dict[str, Any] = {
        "embeds": [
            {
                "title": "🎫 PTT IVE 搶票通知",
                "description": article["title"],
                "url": article["url"],
                "fields": [
                    {
                        "name": "作者",
                        "value": article["author"] or "未知",
                        "inline": True,
                    },
                    {
                        "name": "日期",
                        "value": article["date"] or "未知",
                        "inline": True,
                    },
                ],
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        ]
    }

    session = create_retry_session()

    try:
        response = session.post(
            DISCORD_WEBHOOK,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        print(f"Discord 通知成功：{article['title']}")
        return True

    except requests.exceptions.Timeout:
        print("Discord webhook 連線逾時")
        return False

    except requests.exceptions.ConnectionError as error:
        print(f"無法連線至 Discord webhook：{error}")
        return False

    except requests.exceptions.HTTPError as error:
        response_text = ""

        if error.response is not None:
            response_text = error.response.text[:300]

        print(
            f"Discord webhook 回傳 HTTP 錯誤："
            f"{error}，內容：{response_text}"
        )
        return False

    except requests.exceptions.RequestException as error:
        print(f"傳送 Discord 通知失敗：{error}")
        return False

    finally:
        session.close()


def main() -> None:
    print("開始檢查 PTT")

    seen = load_seen()
    seen_set = set(seen)

    articles = get_articles()

    print(f"抓到 {len(articles)} 篇文章")

    if not articles:
        print("本次未取得文章，結束執行")
        return

    new_seen = seen.copy()

    for article in articles:
        article_url = article["url"]

        if article_url in seen_set:
            continue

        matched = re.search(
            KEYWORD,
            article["title"],
            re.IGNORECASE,
        )

        if matched:
            print(
                "找到 IVE：",
                article["title"],
            )

            notification_sent = send_discord(article)

            # Discord 傳送失敗時，不加入 seen。
            # 下次執行仍會再次嘗試通知。
            if not notification_sent:
                print(
                    "Discord 通知失敗，"
                    "暫不將文章標記為已處理"
                )
                continue

        # 非關鍵字文章，以及通知成功的文章，
        # 都加入 seen。
        new_seen.append(article_url)
        seen_set.add(article_url)

    save_seen(new_seen)

    print("檢查完成")


if __name__ == "__main__":
    main()
