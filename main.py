import os
import requests
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import google.generativeai as genai
from datetime import datetime, timezone, timedelta

# 환경 변수 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Gemini 모델 초기화
genai.configure(api_key=GEMINI_API_KEY)
# 최신 플래시 모델 사용
model = genai.GenerativeModel('gemini-2.5-flash')

def fetch_news(query, max_results=10, lang="ko", country="KR"):
    """Google News RSS 피드를 사용해 최신 뉴스를 가져온다 (API 키 불필요)."""
    results = []
    encoded_query = urllib.parse.quote(query)
    rss_url = (
        f"https://news.google.com/rss/search?q={encoded_query}"
        f"&hl={lang}&gl={country}&ceid={country}:{lang}"
    )
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
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
            results.append({
                "title": title,
                "url": link,
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
    response = model.generate_content(prompt)
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

## 🇰🇷 국내 시장 핵심 뉴스 (5선)

{kr_summary}

---

## 🌎 글로벌 시장 핵심 뉴스 (5선)

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

        # 안내 메시지 발송
        msg_payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✅ {today_str} AI 및 반도체 동향 요약 리포트가 생성되었습니다!"}
        requests.post(f"{url}/sendMessage", json=msg_payload)

        # 파일 발송
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
