import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

PTT_URL = "https://www.ptt.cc/bbs/Drama-Ticket/index.html"
KEYWORD = r"ive"

SEEN_FILE = "seen.json"

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return []

    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_session():
    session = requests.Session()

    session.headers.update(HEADERS)

    # PTT over18
    session.post(
        "https://www.ptt.cc/ask/over18",
        data={
            "from": "/bbs/Drama-Ticket/index.html",
            "yes": "yes"
        }
    )

    return session


def get_articles():

    session = get_session()

    r = session.get(PTT_URL, timeout=10)

    soup = BeautifulSoup(
        r.text,
        "html.parser"
    )

    articles = []

    for item in soup.select(".r-ent"):

        title = item.select_one(".title")

        if not title:
            continue

        title = title.text.strip()

        if title == "":
            continue


        link = item.select_one("a")

        if not link:
            continue


        href = (
            "https://www.ptt.cc"
            + link["href"]
        )

        author = item.select_one(".author")
        date = item.select_one(".date")


        articles.append({

            "title": title,

            "url": href,

            "author":
                author.text.strip()
                if author else "",

            "date":
                date.text.strip()
                if date else ""

        })

    return articles



def send_discord(article):

    if not DISCORD_WEBHOOK:
        print("沒有設定 Discord webhook")
        return


    payload = {

        "embeds": [

            {

                "title":
                    "🎫 PTT IVE 搶票通知",

                "description":
                    article["title"],

                "url":
                    article["url"],

                "fields": [

                    {
                        "name": "作者",
                        "value":
                            article["author"],
                        "inline": True
                    },

                    {
                        "name": "日期",
                        "value":
                            article["date"],
                        "inline": True
                    }

                ],

                "timestamp":
                    datetime.utcnow().isoformat()

            }

        ]

    }


    requests.post(
        DISCORD_WEBHOOK,
        json=payload,
        timeout=10
    )



def main():

    print("開始檢查 PTT")

    seen = load_seen()

    articles = get_articles()

    print(
        f"抓到 {len(articles)} 篇文章"
    )


    new_seen = seen.copy()


    for article in articles:

        if article["url"] in seen:
            continue


        if re.search(
            KEYWORD,
            article["title"],
            re.IGNORECASE
        ):

            print(
                "找到 IVE:",
                article["title"]
            )

            send_discord(article)


        new_seen.append(
            article["url"]
        )


    save_seen(new_seen)


if __name__ == "__main__":
    main()
