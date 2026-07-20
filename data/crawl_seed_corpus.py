"""爬取乘联会（cpcaauto.com）行业新闻作为种子语料（路②公共底座）。

用法：python data/crawl_seed_corpus.py
产出：data/seed_corpus/*.md（种子语料 markdown 文件）
依赖：scrapling（需专用 venv）

注意：仅爬有文字正文的 news 页面，图片/视频类跳过。会做质量校验。
"""
import json
import re
import time
import random
from pathlib import Path

OUT_DIR = Path(__file__).parent / "seed_corpus"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.cpcaauto.com/",
}


def crawl_news_list():
    """爬取乘联会新闻列表页，返回文章 URL 列表。"""
    try:
        from scrapling import Playwright
    except ImportError:
        print("[warn] scrapling 未安装，跳过在线爬取。"
              "已有种子语料 8 篇在 data/seed_kb/。要追加可用专用 venv 运行本脚本。")
        return []

    articles = []
    with Playwright(headless=True) as p:
        page = p.new_page(headers=HEADERS)
        for page_num in range(1, 4):  # 前3页
            url = f"https://www.cpcaauto.com/newslist.php?p={page_num}"
            try:
                resp = page.get(url)
                text = resp.body.decode("utf-8", errors="ignore")
                # 匹配链接
                hrefs = re.findall(r'href="(news\d+\.php[^"]*)"', text)
                for h in hrefs:
                    articles.append(f"https://www.cpcaauto.com/{h}")
            except Exception as e:
                print(f"  page {page_num} fail: {e}")
            time.sleep(random.uniform(1, 2))
    return list(set(articles))


def crawl_article(url: str, page):
    """爬单篇文章，返回 (title, content) 或 None（质量不合格）。"""
    try:
        resp = page.get(url)
        text = resp.body.decode("utf-8", errors="ignore")

        # 提取正文
        body_match = re.search(r'<div\s+class="content"[^>]*>(.*?)</div>', text, re.DOTALL)
        if not body_match:
            return None

        raw = body_match.group(1)
        # 去 HTML 标签
        clean = re.sub(r'<[^>]+>', '', raw)
        clean = re.sub(r'\s+', ' ', clean).strip()

        # 质量校验：正文 > 200 字
        if len(clean) < 200:
            return None
        # 去重：过滤纯导航页
        if any(kw in clean[:50] for kw in ["导航", "目录", "列表", "上一页"]):
            return None

        title_match = re.search(r'<title>(.*?)</title>', text)
        title = title_match.group(1).strip() if title_match else url.rsplit("/", 1)[-1]

        return title, clean
    except Exception as e:
        print(f"    ❌ {url}: {e}")
        return None


def run():
    articles = crawl_news_list()
    if not articles:
        return

    print(f"发现 {len(articles)} 篇文章，开始采集...\n")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from scrapling import Playwright
    except ImportError:
        return

    ok = 0
    with Playwright(headless=True) as p:
        page = p.new_page(headers=HEADERS)
        for i, url in enumerate(articles[:50]):  # 限50篇
            label = f"[{i+1}/{min(len(articles), 50)}]"
            result = crawl_article(url, page)
            if result is None:
                continue
            title, content = result
            # 文件名
            slug = re.sub(r'[\\/*?:"<>|]', '', title)[:60]
            fname = f"{i+1:02d}-{slug}.md"
            fpath = OUT_DIR / fname
            fpath.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
            ok += 1
            print(f"  {label} ✅ {fname} ({len(content)} 字)")
            time.sleep(random.uniform(0.5, 1.5))

    print(f"\n完成！{ok} 篇有效文章 → {OUT_DIR}")


if __name__ == "__main__":
    run()
