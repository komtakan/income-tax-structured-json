
"""
generate_law_text.py
e-Gov法令APIから指定条文を取得し、law_text.jsonを自動生成する

使用方法:
    python generate_law_text.py --law_id 340AC0000000033 --article_num 37
    python generate_law_text.py --law_id 340AC0000000033 --article_num 37,45,84,86
"""

import json
import hashlib
import os
import sys
import argparse
import requests
from datetime import date
from typing import List, Dict, Optional, Tuple

API_BASE_URL = "https://laws.e-gov.go.jp/api/2/law_data"
DEFAULT_OUTPUT_DIR = r"C:\法令API"

KANSUJI = "〇一二三四五六七八九"

def to_kansuji(n: int) -> str:
    if n <= 0:
        return str(n)
    s = ""
    if n >= 100:
        if n // 100 > 1:
            s += KANSUJI[n // 100]
        s += "百"
        n %= 100
    if n >= 20:
        s += KANSUJI[n // 10] + "十"
        n %= 10
    elif n >= 10:
        s += "十"
        n %= 10
    if n > 0:
        s += KANSUJI[n]
    return s


def fetch_law_full(law_id: str) -> dict:
    url = f"{API_BASE_URL}/{law_id}"
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.json()


def fetch_law_elm(law_id: str, elm_path: str) -> dict:
    url = f"{API_BASE_URL}/{law_id}"
    params = {"elm": elm_path, "json_format": "light"}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def find_all_articles(node: dict, ancestors: List[Tuple[str, str]] = None, depth: int = 0, max_depth: int = 10) -> List[dict]:
    results = []
    if depth > max_depth:
        return results
    if isinstance(node, dict):
        tag = node.get("tag", "")
        attr = node.get("attr", {})
        children = node.get("children", [])
        num = attr.get("Num", "")
        current_ancestors = list(ancestors) if ancestors else []
        if tag in ("Part", "Chapter", "Section", "Subsection", "Division") and num:
            current_ancestors.append((tag, num))
        if tag == "Article":
            title = ""
            caption = ""
            article_num_from_attr = attr.get("Num", "")
            for child in children:
                if isinstance(child, dict):
                    if child.get("tag") == "ArticleTitle":
                        tc = child.get("children", [])
                        if tc and isinstance(tc[0], str):
                            title = tc[0]
                    if child.get("tag") == "ArticleCaption":
                        cc = child.get("children", [])
                        if cc and isinstance(cc[0], str):
                            caption = cc[0]
            results.append({
                "title": title,
                "caption": caption,
                "ancestors": current_ancestors,
                "article_num": article_num_from_attr
            })
            return results
        for child in children:
            results.extend(find_all_articles(child, current_ancestors, depth+1, max_depth))
    elif isinstance(node, list):
        for item in node:
            results.extend(find_all_articles(item, ancestors, depth, max_depth))
    return results


def build_elm_path(article_num: str, ancestors: List[Tuple[str, str]]) -> str:
    parts = ["MainProvision"]
    for tag, num in ancestors:
        parts.append(f"{tag}_{num}")
    parts.append(f"Article_{article_num}")
    return "-".join(parts)


def find_article_by_num(articles: List[dict], article_num: str) -> Optional[dict]:
    num_str = article_num.strip()
    for article in articles:
        if article["ancestors"] and article.get("article_num") == num_str:
            return article
    for article in articles:
        if not article["ancestors"] and article.get("article_num") == num_str:
            return article
    return None


def compute_content_hash(raw_json: dict) -> str:
    raw_str = json.dumps(raw_json, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def extract_raw_json(article_data: dict) -> dict:
    law_full = article_data.get("law_full_text", {})
    if "Article" in law_full:
        return {"Article": law_full["Article"]}
    return {}


def build_law_text_json(law_id, law_name, law_name_kana, article_num, article_title, raw_json, elm_path, revision_id, effective_date):
    parts = article_num.split('_')
    padded_main = parts[0].zfill(3)
    padded = padded_main + ('_' + parts[1] if len(parts) > 1 else '')
    article_id = f"LAW-{padded}-000"    
    if '_' in article_num:
        main, sub = article_num.split('_')
        title_str = f"第{int(main)}条の{sub}"
    else:
        title_str = f"第{int(article_num)}条"
    return {
        "meta": {
            "version": "0.3.0",
            "source": "e-Gov法令API v2",
            "law_id": law_id,
            "law_name": law_name,
            "law_name_kana": law_name_kana,
            "retrieved_at": date.today().isoformat(),
            "api_url": f"{API_BASE_URL}/{law_id}",
            "elm_path": elm_path,
            "revision_id": revision_id,
            "effective_date": effective_date
        },
        "articles": [{
            "article_id": article_id,
            "article_num": title_str,
            "article_title": article_title,
            "content_hash": compute_content_hash(raw_json),
            "api_revision_id": revision_id,
            "effective_date": effective_date,
            "raw_json": raw_json
        }]
    }

def save_json(data: dict, article_num: str, output_dir: str) -> str:
    filename = f"law_text_{article_num.zfill(3)}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="e-Gov法令APIから条文を取得し、law_text.jsonを生成")
    parser.add_argument("--law_id", required=True, help="法令ID")
    parser.add_argument("--article_num", required=True, help="条番号（例: 37,45,84,86）")
    parser.add_argument("--output_dir", default=DEFAULT_OUTPUT_DIR, help="出力ディレクトリ")
    args = parser.parse_args()

    law_id = args.law_id
    article_nums = [a.strip() for a in args.article_num.split(",")]
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    print(f"法令ID: {law_id}")
    print(f"対象条文: {article_nums}")
    print(f"出力先: {output_dir}")
    print("-" * 50)

    print("法律全体を取得中...")
    law_full = fetch_law_full(law_id)

    revision_info = law_full.get("revision_info", {})
    law_name = revision_info.get("law_title", "")
    law_name_kana = revision_info.get("law_title_kana", "")
    revision_id = revision_info.get("law_revision_id", "")
    effective_date = revision_info.get("amendment_enforcement_date", "")

    print(f"法令名: {law_name}")
    print(f"リビジョンID: {revision_id}")

    print("条文索引を構築中...")
    full_text = law_full.get("law_full_text", {})
    all_articles = find_all_articles(full_text)
    print(f"  {len(all_articles)} 条文を検出")

    success_count = 0
    for article_num in article_nums:
        print(f"\n--- 第{article_num}条 ---")
        article = find_article_by_num(all_articles, article_num)
        if article is None:
            print(f"  [ERROR] 第{article_num}条が見つかりませんでした")
            continue

        title = article["title"]
        caption = article["caption"]
        ancestors = article["ancestors"]
        print(f"  タイトル: {title} {caption}")

        if not ancestors:
            print(f"  [WARNING] 本則ではなく附則の条文です")

        elm_path = build_elm_path(article_num, ancestors)
        print(f"  elm_path: {elm_path}")

        raw_json = None
        try:
            elm_data = fetch_law_elm(law_id, elm_path)
            raw_json = extract_raw_json(elm_data)
            print(f"  elm再取得成功（簡易版）")
        except Exception as e:
            print(f"  elm再取得失敗: {e}")

        if raw_json is None:
            print(f"  [ERROR] raw_jsonが抽出できませんでした")
            continue

        law_text = build_law_text_json(
            law_id=law_id,
            law_name=law_name,
            law_name_kana=law_name_kana,
            article_num=article_num,
            article_title=caption,
            raw_json=raw_json,
            elm_path=elm_path,
            revision_id=revision_id,
            effective_date=effective_date,
        )

        save_path = save_json(law_text, article_num, output_dir)
        print(f"  保存: {save_path}")
        success_count += 1

    print(f"\n{'=' * 50}")
    print(f"処理完了: {success_count}/{len(article_nums)} 件成功")


if __name__ == "__main__":
    main()
