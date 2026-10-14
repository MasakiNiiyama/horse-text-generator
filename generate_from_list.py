import sys
import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# JBISから「母馬名」「性別」「調教師名」を取得する関数
# -------------------------------------------------------------------
def fetch_jbis_info(horse_name):
    clean_name = re.sub(r'(の)?\d{2}$', '', horse_name)
    encoded_name = urllib.parse.quote(clean_name)
    url = f"https://www.jbis.or.jp/horse/result/?sid=horse&keyword={encoded_name}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return {"mother": "不明", "sex": "不明", "trainer": "不明", "url": url}

        soup = BeautifulSoup(res.text, "html.parser")
        
        sex = "不明"
        mother = "不明"
        trainer = "不明"

        # 1. 性別の抽出
        for div in soup.find_all("div"):
            text = div.text.strip()
            if text in ["牝", "牡", "セ"]:
                sex = text
                break

        # 2. 最新世代のブロックから「母馬名」と「調教師名」を取得
        blocks = soup.select("div.tbl-data-01")
        target_block = blocks[0] if blocks else soup

        # 調教師名の抽出 (/horse/trainer/ のリンク)
        trainer_link = target_block.find("a", href=re.compile(r"^/horse/trainer/"))
        if trainer_link:
            trainer = trainer_link.text.strip().replace(" ", "")

        # 母馬名の抽出
        horse_links = target_block.find_all("a", href=re.compile(r"^/horse/\d+/"))
        candidates = []
        for a in horse_links:
            text = a.text.strip()
            if text and text != clean_name and text not in ["血統", "競走", "詳細", "ホーム", "馬情報"] and not text.isdigit():
                candidates.append(text)
        
        if len(candidates) >= 2:
            raw_mother = candidates[1]
        elif len(candidates) == 1:
            raw_mother = candidates[0]
        else:
            raw_mother = "不明"

        mother = re.sub(r'\([A-Za-z]{3}\)$', '', raw_mother)

        return {"mother": mother, "sex": sex, "trainer": trainer, "url": url}

    except Exception as e:
        print(f"[JBIS Fetch Error] {horse_name}: {e}")
        return {"mother": "不明", "sex": "不明", "trainer": "不明", "url": url}


# -------------------------------------------------------------------
# メイン処理
# -------------------------------------------------------------------
def main():
    horse_names = []

    # 方法A: コマンドライン引数にファイル名が渡された場合 (python generate_from_list.py list.txt)
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        file_path = sys.argv[1]
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line and not line.startswith("="):
                horse_names.append(line)

    # 方法B: コマンドライン引数に馬名が直接並べられた場合
    elif len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if not arg.startswith("="):
                horse_names.append(arg.strip())

    # 方法C: 引数がない場合、標準入力（対話形式）で受け取る
    else:
        print("馬名リストを入力してください（貼り付け後、Ctrl+D または Ctrl+Z で確定）:")
        try:
            lines = sys.stdin.read().splitlines()
            for line in lines:
                line = line.strip()
                if line and not line.startswith("="):
                    horse_names.append(line)
        except KeyboardInterrupt:
            return

    if not horse_names:
        print("エラー: 馬名が入力されていません。")
        return

    output_lines = ["===="]
    url_list = ["", "【確認用 JBIS URL一覧】"]

    print(f"\n{len(horse_names)} 頭の情報をJBISから取得中...\n")

    for raw_name in horse_names:
        # 「アンズチャン24」を「アンズチャンの24」に表記補正
        if re.search(r'\d{2}$', raw_name) and not "の" in raw_name:
            formatted_name = re.sub(r'(\d{2})$', r'の\1', raw_name)
        else:
            formatted_name = raw_name

        # JBIS検索 (母馬名・性別・調教師・URLを取得)
        info = fetch_jbis_info(formatted_name)
        sex = info["sex"]
        mother = info["mother"]
        trainer = info["trainer"]
        jbis_url = info["url"]

        # 一覧テキストの組み立て
        if "の24" in formatted_name:
            line = f"{formatted_name}（{sex}、{trainer}）"
        else:
            line = f"{formatted_name}（母{mother}、{sex}、{trainer}）"

        output_lines.append(line)
        url_list.append(f"{formatted_name}: {jbis_url}")
        print(line)

    output_lines.append("====")

    final_text = "\n".join(output_lines) + "\n" + "\n".join(url_list)

    # result_list.txt に保存
    with open("result_list.txt", "w", encoding="utf-8") as f:
        f.write(final_text)

    print("\n処理完了！ result_list.txt に出力しました。")


if __name__ == "__main__":
    main()