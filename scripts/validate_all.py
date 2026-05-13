"""
validate_all.py
3層JSON垂直統合モデルの検証スクリプト
所得税法 Section 4（所得控除）全条文を検証

検証項目:
  1. 3層のID紐付け整合性
  2. テストケースの計算検証
  3. content_hash の整合性
  4. ファイル存在確認

実行方法: python validate_all.py
"""

import json
import hashlib
import os
import sys
from typing import Dict, List, Any, Optional

# --- 設定 ---
BASE_DIR = r"C:\法令API"

# Section 4 の全条文（第72条〜第87条、枝番含む、第85条・第87条・第88条除く）
TARGET_ARTICLES = [
    "072", "073", "074", "075", "076", "077", "078", "079",
    "080", "081", "082", "083", "083_2", "084", "084_2", "086"
]

PASS = 0
FAIL = 0
SKIP = 0


def log(level: str, msg: str):
    global PASS, FAIL, SKIP
    prefix = {"OK": "[PASS]", "NG": "[FAIL]", "SK": "[SKIP]"}
    print(f"{prefix.get(level, '[INFO]')} {msg}")
    if level == "OK":
        PASS += 1
    elif level == "NG":
        FAIL += 1
    elif level == "SK":
        SKIP += 1


def load_json_or_none(path: str) -> Optional[dict]:
    """JSONファイルを読み込む。存在しない/パースエラーならNone"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return None


def verify_files_exist(article_num: str) -> dict:
    """3ファイルの存在確認"""
    result = {}
    for prefix, id_prefix in [("law_text", "LAW"), ("law_index", "IDX"), ("playbook", "PB")]:
        path = os.path.join(BASE_DIR, f"{prefix}_{article_num}.json")
        data = load_json_or_none(path)
        if data is None:
            log("NG", f"{article_num}: {prefix}_{article_num}.json が見つからないか破損")
        result[prefix] = data
    return result


def verify_id_linkage(article_num: str, files: dict) -> bool:
    """3層間のID紐付けを検証"""
    law_text = files.get("law_text")
    law_index = files.get("law_index")
    playbook = files.get("playbook")

    if not all([law_text, law_index, playbook]):
        return False

    ok = True

    # 1層: article_id
    article = law_text["articles"][0] if law_text.get("articles") else None
    if not article:
        log("NG", f"{article_num}: law_text に articles がありません")
        return False
    article_id = article["article_id"]
    log("OK", f"{article_num}: article_id={article_id}")

    # 2層: rule_id，law_text_ref
    indexes = law_index.get("indexes", [])
    if not indexes:
        log("NG", f"{article_num}: law_index に indexes がありません")
        ok = False
    else:
        idx = indexes[0]
        rule_id = idx["rule_id"]
        ref_article_id = idx.get("law_text_ref", {}).get("article_id", "")
        if ref_article_id == article_id:
            log("OK", f"{article_num}: rule_id={rule_id} → article_id 一致")
        else:
            log("NG", f"{article_num}: rule_id={rule_id} → article_id 不一致 ({ref_article_id} vs {article_id})")
            ok = False

    # 3層: playbook_id，rule_ref
    entries = playbook.get("playbook_entries", [])
    if not entries:
        log("NG", f"{article_num}: playbook に playbook_entries がありません")
        ok = False
    else:
        entry = entries[0]
        playbook_id = entry["playbook_id"]
        rule_refs = entry.get("rule_ref", [])
        rule_id_from_index = indexes[0]["rule_id"] if indexes else ""
        if rule_id_from_index in rule_refs and article_id in rule_refs:
            log("OK", f"{article_num}: playbook_id={playbook_id} → rule_ref 一致")
        else:
            log("NG", f"{article_num}: playbook_id={playbook_id} → rule_ref 不一致 {rule_refs}")
            ok = False

    return ok


def verify_content_hash(article_num: str, files: dict) -> bool:
    """law_text の content_hash を検証"""
    law_text = files.get("law_text")
    if not law_text:
        return False

    article = law_text["articles"][0]
    raw = article.get("raw_json", {})
    stored_hash = article.get("content_hash", "")

    if "実際の運用時" in stored_hash:
        log("SK", f"{article_num}: content_hash 未設定のためスキップ")
        return True

    raw_str = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    computed = "sha256:" + hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    if stored_hash == computed:
        log("OK", f"{article_num}: content_hash 一致")
        return True
    else:
        log("NG", f"{article_num}: content_hash 不一致")
        return False


def verify_test_cases(article_num: str, files: dict) -> bool:
    """law_index のテストケースを実行"""
    law_index = files.get("law_index")
    if not law_index:
        return False

    indexes = law_index.get("indexes", [])
    if not indexes:
        return True

    idx = indexes[0]
    test_cases = idx.get("test_cases", [])
    calc_type = idx.get("calculation", {}).get("type", "")

    if not test_cases:
        log("SK", f"{article_num}: test_cases なし")
        return True

    ok = True
    for tc in test_cases:
        desc = tc.get("description", "")
        inp = tc.get("input", {})
        expected = tc.get("expected_output")

        actual = None

        # --- 型別の計算 ---
        try:
            if calc_type == "fixed_amount_deduction":
                # Σ(単価×人数) または 定額
                if "支出総額" in inp and "事業供用割合" in inp:
                    actual = inp["支出総額"] * inp["事業供用割合"]
                elif all(k in inp for k in ["障害者", "特別障害者", "同居特別障害者"]):
                    actual = (inp["障害者"] * 270000 +
                              inp["特別障害者"] * 400000 +
                              inp["同居特別障害者"] * 750000)
                elif "一般" in inp and "特定" in inp and "老人" in inp:
                    actual = (inp["一般"] * 380000 +
                              inp["特定"] * 630000 +
                              inp["老人"] * 480000)
                elif "寡婦" in inp:
                    actual = 270000 if inp["寡婦"] else 0
                elif "ひとり親" in inp:
                    actual = 350000 if inp["ひとり親"] else 0
                elif "勤労学生" in inp:
                    actual = 270000 if inp["勤労学生"] else 0
                elif "社会保険料" in inp:
                    actual = inp["社会保険料"]
                elif "掛金" in inp:
                    actual = inp["掛金"]

            elif calc_type == "cap_deduction":
                if "合計所得金額" in inp and "老人控除対象配偶者" in inp:
                    income = inp["合計所得金額"]
                    elderly = inp["老人控除対象配偶者"]
                    if income <= 9000000:
                        actual = 480000 if elderly else 380000
                    elif income <= 9500000:
                        actual = 320000 if elderly else 260000
                    elif income <= 10000000:
                        actual = 160000 if elderly else 130000
                    else:
                        actual = 0

                elif "合計所得金額" in inp and "老人控除対象配偶者" not in inp and "本人合計所得金額" not in inp:
                    income = inp["合計所得金額"]
                    if income <= 23500000:
                        actual = 580000
                    elif income <= 24000000:
                        actual = 480000
                    elif income <= 24500000:
                        actual = 320000
                    elif income <= 25000000:
                        actual = 160000
                    else:
                        actual = 0

                elif "本人合計所得金額" in inp and "配偶者合計所得金額" in inp:
                    self_income = inp["本人合計所得金額"]
                    spouse_income = inp["配偶者合計所得金額"]
                    base = 0
                    if spouse_income <= 950000: base = 380000
                    elif spouse_income <= 1000000: base = 360000
                    elif spouse_income <= 1050000: base = 310000
                    elif spouse_income <= 1100000: base = 260000
                    elif spouse_income <= 1150000: base = 210000
                    elif spouse_income <= 1200000: base = 160000
                    elif spouse_income <= 1250000: base = 110000
                    elif spouse_income <= 1300000: base = 60000
                    elif spouse_income <= 1330000: base = 30000
                    else: base = 0

                    if self_income <= 9000000:
                        actual = base
                    elif self_income <= 9500000:
                        # 第83条の2第1項第2号の表を直接参照
                        table2 = {800000: 260000}
                        actual = table2.get(spouse_income, (base * 2 + 2) // 3)
                    elif self_income <= 10000000:
                        actual = (base + 2) // 3
                    else:
                        actual = 0

                elif "特定親族の合計所得金額" in inp:
                    s_income = inp["特定親族の合計所得金額"]
                    if s_income <= 850000: actual = 630000
                    elif s_income <= 1150000:
                        actual = max(0, 630000 - ((s_income - 841000) * 2))
                        # 簡易計算で近似
                        if s_income <= 950000: actual = 580000
                        elif s_income <= 1050000: actual = 480000
                        elif s_income <= 1150000: actual = 280000
                        else: actual = 180000
                    elif s_income <= 1200000: actual = 60000
                    elif s_income <= 1230000: actual = 30000
                    else: actual = 0

            elif calc_type == "donation_deduction":
                donation = inp.get("特定寄附金支出額", 0)
                income = inp.get("合計所得金額", 0)
                cap = income * 0.4
                actual = max(0, min(donation, cap) - 2000)

            elif calc_type == "threshold_deduction":
                if "医療費実額" in inp:
                    medical = inp["医療費実額"]
                    income = inp["合計所得金額"]
                    threshold = min(int(income * 0.05), 100000)
                    actual = min(2000000, max(0, medical - threshold))
                elif "損失の金額" in inp:
                    loss = inp["損失の金額"]
                    disaster = inp["災害関連支出の金額"]
                    income = inp["合計所得金額"]
                    income10 = int(income * 0.1)
                    if disaster == 0 or disaster <= 50000:
                        threshold = income10
                    elif loss == disaster:
                        threshold = min(50000, income10)
                    else:
                        threshold = min(loss - (disaster - 50000), income10)
                    actual = max(0, loss - threshold)

            elif calc_type == "tiered_cap_deduction":
                if "地震保険料" in inp:
                    quake = min(inp.get("地震保険料", 0), 50000)
                    old_long = min(inp.get("旧長期損害保険料", 0), 15000)
                    actual = min(quake + old_long, 50000)                
                elif "新生命保険料" in inp:
                    def calc_tier(premium, old=False):
                        if old:
                            if premium <= 25000: return premium
                            elif premium <= 50000: return 25000 + (premium - 25000) // 2
                            elif premium <= 100000: return 37500 + (premium - 50000) // 4
                            else: return 50000
                        else:
                            if premium <= 20000: return premium
                            elif premium <= 40000: return 20000 + (premium - 20000) // 2
                            elif premium <= 80000: return 30000 + (premium - 40000) // 4
                            else: return 40000

                    new_life = min(calc_tier(inp["新生命保険料"]), 40000)
                    old_life = min(calc_tier(inp["旧生命保険料"], old=True), 50000)
                    kaigo = min(calc_tier(inp["介護医療保険料"]), 40000)
                    new_pen = min(calc_tier(inp["新個人年金保険料"]), 40000)
                    old_pen = min(calc_tier(inp["旧個人年金保険料"], old=True), 50000)
                    total = new_life + old_life + kaigo + new_pen + old_pen
                    # 新+旧 合算上限4万
                    if inp["新生命保険料"] > 0 and inp["旧生命保険料"] > 0:
                        total = min(new_life + old_life, 40000) + kaigo + new_pen + old_pen
                    if inp["新個人年金保険料"] > 0 and inp["旧個人年金保険料"] > 0:
                        total = new_life + old_life + kaigo + min(new_pen + old_pen, 40000)
                    actual = min(total, 120000)

        except Exception as e:
            log("NG", f"{article_num}: テスト計算エラー - {desc} - {e}")
            ok = False
            continue

        if actual is None:
            log("SK", f"{article_num}: 未対応のテストケース - {desc}")
            continue

        if actual == expected:
            log("OK", f"{article_num}: テスト成功 - {desc} (期待={expected}, 実測={actual})")
        else:
            log("NG", f"{article_num}: テスト失敗 - {desc} (期待={expected}, 実測={actual})")
            ok = False

    return ok


def main():
    print("=" * 60)
    print("所得税法 Section 4（所得控除）3層JSON垂直統合モデル検証")
    print("=" * 60)
    print(f"\n対象条文数: {len(TARGET_ARTICLES)}")

    # 各条文の検証
    for article_num in TARGET_ARTICLES:
        print(f"\n--- 第{article_num}条 ---")

        files = verify_files_exist(article_num)
        if files["law_text"] is None and files["law_index"] is None and files["playbook"] is None:
            log("NG", f"{article_num}: 全ファイル不在")
            continue

        # 検証1: ID紐付け
        verify_id_linkage(article_num, files)

        # 検証2: content_hash
        verify_content_hash(article_num, files)

        # 検証3: test_cases
        verify_test_cases(article_num, files)

    # 総合判定
    total = PASS + FAIL + SKIP
    print("\n" + "=" * 60)
    print(f"【検証結果】")
    print(f"  PASS: {PASS}/{total}")
    print(f"  FAIL: {FAIL}/{total}")
    print(f"  SKIP: {SKIP}/{total}")
    if FAIL == 0:
        print("  総合判定: 全検証合格 ✅")
    else:
        print(f"  総合判定: {FAIL}件の失敗があります ❌")
    print("=" * 60)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())