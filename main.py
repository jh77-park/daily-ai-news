import os
import re
import json
import requests
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from google import genai
from datetime import datetime, timezone, timedelta

# 환경 변수 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Gemini 클라이언트 초기화 (google-genai SDK)
client = genai.Client(api_key=GEMINI_API_KEY)
# 사용할 모델
MODEL_NAME = "gemini-2.5-flash"

# 공통 HTTP 헤더
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def resolve_google_news_url(google_url, timeout=15):
    """Google News RSS 리다이렉트 링크를 실제 기사 원본 URL로 변환한다.

    Google News의 batchexecute API를 호출하여 토큰을 실제 URL로 해독한다.
    실패하면 원본 google_url 그대로 반환(fallback)한다.
    """
    if not google_url or "news.google.com" not in google_url:
        return google_url

    try:
        # 1) 토큰 추출
        token = google_url.split("/articles/")[1].split("?")[0]

        # 2) 기사 페이지에서 서명(signature)과 타임스탬프 획득
        art_url = "https://news.google.com/rss/articles/" + token
        req = urllib.request.Request(art_url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        sig_m = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts_m = re.search(r'data-n-a-ts="([^"]+)"', html)
        if not sig_m or not ts_m:
            return google_url
        sig = sig_m.group(1)
        ts = ts_m.group(1)

        # 3) batchexecute 호출로 실제 URL 해독
        inner = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
              None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            token, ts, sig
        ])
        freq = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        data = urllib.parse.urlencode({"f.req": freq}).encode("utf-8")
        be_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
        be_req = urllib.request.Request(
            be_url, data=data,
            headers={**_HEADERS,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        )
        with urllib.request.urlopen(be_req, timeout=timeout) as be_resp:
            be_text = be_resp.read().decode("utf-8", errors="ignore")

        # 응답에서 실제 URL 추출
        m = re.search(r'(https?://[^"\\]+)', be_text.split("Fbv4je")[-1] if "Fbv4je" in be_text else be_text)
        if m:
            real = m.group(1)
            if "news.google.com" not in real:
                return real
    except Exception as e:
        print(f"URL 변환 실패(fallback 사용): {e}")

    return google_url


def fetch_news(query, max_results=10, lang="ko", country="KR"):
    """Google News RSS 피드를 사용해 최신 뉴스를 가져온다 (API 키 불필요)."""
    results = []
    encoded_query = urllib.parse.quote(query)
    rss_url = (
        f"https://news.google.com/rss/search?q={encoded_query}"
        f"&hl={lang}&gl={country}&ceid={country}:{lang}"
    )
    try:
        req = urllib.request.Request(rss_url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        items = root.findall(".//item")
        for item in items[:max_results]:
            title = item.findtext("title", default="")
            link = item.findtext("link", default="")
            pub_date = item.findtext("pubDate", default="")
            source_el = item.find("source")
            source = source_el.text if source_el is not None else ""
            # Google News 리다이렉트 링크를 실제 기사 URL로 변환
            real_url = resolve_google_news_url(link)
            results.append({
                "title": title,
                "url": real_url,
                "date": pub_date,
                "source": source,
            })
    except Exception as e:
        print(f"뉴스 수집 중 오류 발생: {e}")
    return results


def summarize_news(news_items, today_str):
    prompt = f"""
다음은 최근 AI 및 반도체 관련 뉴스 기사들입니다. 이 기사들을 분석하여 가장 중요한 5개의 뉴스를 선별하고,
아래의 마크다운 포맷에 맞게 한국어로 요약해 주세요. (해외 뉴스의 경우 한국어로 자연스럽게 번역해 주세요.)
반드시 5개의 뉴스를 선별해야 하며, 지정된 포맷을 엄격하게 지켜주세요.
출처 URL은 반드시 제공된 뉴스 데이터의 url 값을 그대로 사용하세요 (임의로 생성하지 마세요).
포맷:
### [뉴스 제목]
- **작성일**: {today_str}
- **핵심 요약**: (3줄 이내로 핵심만 명확하게 요약)
- **보존할 핵심 내용**: (전체 원문 또는 요약된 핵심 내용)
- **분류 후보 도메인**: 업무 / AI학습 / 바이브코딩 / 투자관리 / 건강관리 / 기타 중 택 1
- **출처**: [URL]
- **매체명**: [매체명]
뉴스 데이터:
{news_items}
"""
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    return response.text


def main():
    # 한국 시간(KST) 기준 날짜 구하기
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime('%Y-%m-%d')
    print(f"[{today_str}] 뉴스 수집 시작...")

    # 1. 뉴스 검색 (Google News RSS)
    kr_news = fetch_news("AI 반도체", max_results=15, lang="ko", country="KR")
    gl_news = fetch_news("AI semiconductor", max_results=15, lang="en", country="US")

    # 2. LLM 요약
    kr_summary = summarize_news(kr_news, today_str) if kr_news else "관련 뉴스를 찾지 못했습니다."
    gl_summary = summarize_news(gl_news, today_str) if gl_news else "관련 뉴스를 찾지 못했습니다."

    # 3. 마크다운 문서 생성
    markdown_content = f"""# {today_str} AI 및 반도체 동향 요약 리포트
---
## 국내 시장 핵심 뉴스 (5선)
{kr_summary}
---
## 글로벌 시장 핵심 뉴스 (5선)
{gl_summary}
"""

    # 4. 파일 저장
    out_dir = "MyWiki/_Inbox"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{today_str}_AI_반도체_동향.md")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"마크다운 파일 저장 완료: {out_file}")

    # 5. 텔레그램 발송 (마크다운 파일 자체를 Document로 전송)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print("텔레그램으로 파일 전송 중...")
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

        msg_payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"{today_str} AI 및 반도체 동향 요약 리포트가 생성되었습니다!"}
        requests.post(f"{url}/sendMessage", json=msg_payload)

        with open(out_file, "rb") as doc:
            files = {'document': (f"{today_str}_AI_반도체_동향.md", doc, 'text/markdown')}
            data = {'chat_id': TELEGRAM_CHAT_ID}
            resp = requests.post(f"{url}/sendDocument", data=data, files=files)
            if resp.status_code == 200:
                print("텔레그램 전송 성공!")
            else:
                print(f"텔레그램 전송 실패: {resp.text}")
    else:
        print("텔레그램 토큰 또는 챗 아이디가 설정되지 않아 발송을 건너뜁니다.")


if __name__ == "__main__":
    main()
