import sys
import os
import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup

# --- セッションの作成（Botブロック回避用の通信設定） ---
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.jbis.or.jp/"
})


def fetch_jbis_info(horse_name):
    # パターン1: 「コスタネラ24」「コスタネラの24」等の幼駒（産駒）処理
    sanku_match = re.search(r'^(.*?)の?(\d{2})$', horse_name)

    if sanku_match:
        mother_name = sanku_match.group(1).strip()
        target_year = f"20{sanku_match.group(2)}"  # 24 -> 2024
        
        encoded_mother = urllib.parse.quote(mother_name)
        search_url = f"https://www.jbis.or.jp/horse/result/?sid=horse&keyword={encoded_mother}"

        try:
            res = session.get(search_url, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            
            mother_id = None
            
            # 検索結果から母馬（牝）のIDを検索
            for tr in soup.find_all(["tr", "li", "div"]):
                tr_text = tr.text
                if mother_name in tr_text and "牝" in tr_text:
                    a_tag = tr.find("a", href=re.compile(r"^/horse/\d+/"))
                    if a_tag:
                        m = re.search(r'/horse/(\d+)/', a_tag["href"])
                        if m:
                            mother_id = m.group(1)
                            break

            # 1件目の馬詳細からIDを取得（ダイレクト遷移含む）
            if not mother_id:
                m = re.search(r'/horse/(\d+)/', res.url)
                if m:
                    mother_id = m.group(1)
                else:
                    a_tag = soup.find("a", href=re.compile(r"^/horse/\d+/"))
                    if a_tag:
                        m = re.search(r'/horse/(\d+)/', a_tag["href"])
                        if m:
                            mother_id = m.group(1)

            if mother_id:
                # 1. 母馬の繁殖牝馬情報 (/broodmare/info/) ページを開く
                broodmare_url = f"https://www.jbis.or.jp/horse/{mother_id}/broodmare/info/"
                time.sleep(0.5)
                res_bm = session.get(broodmare_url, timeout=10)
                soup_bm = BeautifulSoup(res_bm.text, "html.parser")

                sex = "不明"
                trainer = "未定"
                child_url = broodmare_url

                # 2. 産駒一覧から 2024年 生まれの行を探す
                for tr in soup_bm.find_all("tr"):
                    tr_text = tr.text
                    if f"{target_year}年" in tr_text:
                        # 産駒詳細ページへのリンクを取得
                        child_a = tr.find("a", href=re.compile(r"^/horse/\d+/"))
                        if child_a:
                            child_url = f"https://www.jbis.or.jp{child_a['href']}"
                            time.sleep(0.5)
                            res_child = session.get(child_url, timeout=10)
                            soup_child = BeautifulSoup(res_child.text, "html.parser")
                            
                            # 性別の取得（個体ページのプロファイル要素等から）
                            child_full_text = soup_child.text
                            if " 牡 " in child_full_text or "｜牡｜" in child_full_text or "牡" in tr_text:
                                sex = "牡"
                            elif " 牝 " in child_full_text or "｜牝｜" in child_full_text or "牝" in tr_text:
                                sex = "牝"
                            elif " セ " in child_full_text or "｜セ｜" in child_full_text or "セ" in tr_text:
                                sex = "セ"

                            # 調教師名の取得
                            trainer_link = soup_child.find("a", href=re.compile(r"^/horse/trainer/"))
                            if trainer_link:
                                trainer = trainer_link.text.strip().replace(" ", "")
                            else:
                                # テキスト（例: 伊藤 圭三 (美 浦) など）から調教師名を解析
                                tr_match = re.search(r'([一-龥]{2,4})\s*\((?:美\s*浦|栗\s*東|地方|大\t井|名\t古\t屋)\)', child_full_text)
                                if tr_match:
                                    trainer = tr_match.group(1).replace(" ", "")
                        break

                return {"mother": mother_name, "sex": sex, "trainer": trainer, "url": child_url}

        except Exception as e:
            print(f"[JBIS Fetch Error (産駒)] {horse_name}: {e}")

        return {"mother": mother_name, "sex": "不明", "trainer": "未定", "url": search_url}

    # パターン2: 通常の競走馬（インディゴアワー、ドゥルガーなど）
    else:
        encoded_name = urllib.parse.quote(horse_name)
        search_url = f"https://www.jbis.or.jp/horse/result/?sid=horse&keyword={encoded_name}"
        
        try:
            res = session.get(search_url, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 馬の個別ページへリダイレクトされた場合、または一覧から最新の馬を選択
            target_url = res.url
            if "/horse/result/" in res.url:
                rows = soup.find_all("tr")
                target_row = None
                for tr in reversed(rows):
                    if horse_name in tr.text:
                        target_row = tr
                        break

                if target_row:
                    horse_a = target_row.find("a", href=re.compile(r"^/horse/\d+/"))
                    if horse_a:
                        target_url = f"https://www.jbis.or.jp{horse_a['href']}"

            # 対象馬の個別ページに直接アクセスして正確な情報を取得
            if "/horse/000" in target_url:
                time.sleep(0.5)
                res_horse = session.get(target_url, timeout=10)
                soup_horse = BeautifulSoup(res_horse.text, "html.parser")
            else:
                soup_horse = soup

            sex = "不明"
            mother = "不明"
            trainer = "不明"

            # 性別
            horse_text = soup_horse.text
            if " 牡 " in horse_text or "｜牡｜" in horse_text or "牡" in horse_text:
                sex = "牡"
            elif " 牝 " in horse_text or "｜牝｜" in horse_text or "牝" in horse_text:
                sex = "牝"
            elif " セ " in horse_text or "｜セ｜" in horse_text or "セ" in horse_text:
                sex = "セ"

            # 調教師
            trainer_link = soup_horse.find("a", href=re.compile(r"^/horse/trainer/"))
            if trainer_link:
                trainer = trainer_link.text.strip().replace(" ", "")

            # 母馬名
            horse_links = soup_horse.find_all("a", href=re.compile(r"^/horse/\d+/"))
            candidates = []
            for a in horse_links:
                t = a.text.strip()
                if t and t != horse_name and t not in ["血統", "競走", "詳細", "ホーム", "馬情報"] and not t.isdigit():
                    candidates.append(t)
            
            if len(candidates) >= 2:
                mother = re.sub(r'\([A-Za-z]{3}\)$', '', candidates[1])
            elif len(candidates) == 1:
                mother = re.sub(r'\([A-Za-z]{3}\)$', '', candidates[0])

            return {"mother": mother, "sex": sex, "trainer": trainer, "url": target_url}

        except Exception as e:
            print(f"[JBIS Fetch Error] {horse_name}: {e}")
            return {"mother": "不明", "sex": "不明", "trainer": "不明", "url": search_url}


def main():
    horse_names = []

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            for line in f:
                l = line.strip()
                if l and not l.startswith("="):
                    horse_names.append(l)
    elif len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if not arg.startswith("="):
                horse_names.append(arg.strip())
    else:
        print("馬名リストを入力してください:")
        try:
            for line in sys.stdin.read().splitlines():
                l = line.strip()
                if l and not l.startswith("="):
                    horse_names.append(l)
        except KeyboardInterrupt:
            return

    if not horse_names:
        print("エラー: 馬名が入力されていません。")
        return

    output_lines = ["===="]
    url_list = ["", "【確認用 JBIS URL一覧】"]

    print(f"\n{len(horse_names)} 頭の情報をJBISから取得中...\n")

    for raw_name in horse_names:
        if re.search(r'\d{2}$', raw_name) and not "の" in raw_name:
            formatted_name = re.sub(r'(\d{2})$', r'の\1', raw_name)
        else:
            formatted_name = raw_name

        info = fetch_jbis_info(formatted_name)
        sex = info["sex"]
        mother = info["mother"]
        trainer = info["trainer"]
        jbis_url = info["url"]

        if "の24" in formatted_name:
            line = f"{formatted_name}（{sex}、{trainer}）"
        else:
            line = f"{formatted_name}（母{mother}、{sex}、{trainer}）"

        output_lines.append(line)
        url_list.append(f"{formatted_name}: {jbis_url}")
        print(line)

    output_lines.append("====")

    final_text = "\n".join(output_lines) + "\n" + "\n".join(url_list)

    with open("result_list.txt", "w", encoding="utf-8") as f:
        f.write(final_text)

    print("\n処理完了！ result_list.txt に出力しました。")


if __name__ == "__main__":
    main()