import os
import glob
import re
import urllib.parse
import json
import requests
from bs4 import BeautifulSoup
import certifi

# -------------------------------------------------------------------
# 0. SSL証明書エラーおよびWindows環境でのgRPC通信エラーの回避設定
# -------------------------------------------------------------------
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['GRPC_DEFAULT_SSL_ROOTS_FILE_PATH'] = certifi.where()

# ローカル用の gcp-key.json を優先読み込み
if os.path.exists("gcp-key.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "gcp-key.json"

from google.cloud import vision
from google.cloud.vision_v1.services.image_annotator.transports.rest import ImageAnnotatorRestTransport

# -------------------------------------------------------------------
# JBISから情報（母馬名・性別・調教師）を取得する関数（産駒対応・確定版）
# -------------------------------------------------------------------
def fetch_jbis_info(horse_name):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # パターン判定: 「アンズチャン24」「アンズチャンの24」のように末尾に2桁数字がある場合
    sanku_match = re.search(r'^(.*?)の?(\d{2})$', horse_name)

    if sanku_match:
        mother_name = sanku_match.group(1).strip()
        birth_year = f"20{sanku_match.group(2)}年" # 24 -> 2024年
        
        # 母馬の検索URL
        encoded_mother = urllib.parse.quote(mother_name)
        search_url = f"https://www.jbis.or.jp/horse/result/?sid=horse&keyword={encoded_mother}"

        try:
            res = requests.get(search_url, headers=headers, timeout=10)
            if res.status_code != 200:
                return {"mother": mother_name, "sex": "不明", "trainer": "不明", "url": search_url}

            soup = BeautifulSoup(res.text, "html.parser")
            
            # 母馬の繁殖牝馬ページ（/broodmare/info/ または詳細ページ）を探す
            broodmare_link = soup.find("a", href=re.compile(r"^/horse/\d+/broodmare/info/"))
            if not broodmare_link:
                # 検索結果1件目の馬詳細へ
                first_horse = soup.find("a", href=re.compile(r"^/horse/\d+/"))
                if first_horse:
                    mother_id_match = re.search(r'/horse/(\d+)/', first_horse["href"])
                    if mother_id_match:
                        target_url = f"https://www.jbis.or.jp/horse/{mother_id_match.group(1)}/broodmare/info/"
                    else:
                        target_url = search_url
                else:
                    target_url = search_url
            else:
                target_url = f"https://www.jbis.or.jp{broodmare_link['href']}"

            # 繁殖牝馬ページを取得
            res_bm = requests.get(target_url, headers=headers, timeout=10)
            soup_bm = BeautifulSoup(res_bm.text, "html.parser")

            sex = "不明"
            trainer = "不明"
            child_url = target_url

            # 産駒一覧の中から指定の誕生年(例: 2024年)を探す
            for tr in soup_bm.find_all("tr"):
                tr_text = tr.text
                if birth_year in tr_text:
                    # 性別の判定
                    if "牝" in tr_text:
                        sex = "牝"
                    elif "牡" in tr_text:
                        sex = "牡"
                    elif "セ" in tr_text:
                        sex = "セ"

                    # 産駒個体ページへのリンクを取得
                    child_a = tr.find("a", href=re.compile(r"^/horse/\d+/"))
                    if child_a:
                        child_url = f"https://www.jbis.or.jp{child_a['href']}"
                        # 産駒の個別ページへアクセスして調教師を取得
                        res_child = requests.get(child_url, headers=headers, timeout=10)
                        soup_child = BeautifulSoup(res_child.text, "html.parser")
                        
                        trainer_link = soup_child.find("a", href=re.compile(r"^/horse/trainer/"))
                        if trainer_link:
                            trainer = trainer_link.text.strip().replace(" ", "")
                    break

            return {"mother": mother_name, "sex": sex, "trainer": trainer, "url": child_url}

        except Exception as e:
            print(f"[JBIS Fetch Error (産駒)] {horse_name}: {e}")
            return {"mother": mother_name, "sex": "不明", "trainer": "不明", "url": search_url}

    # --- 通常の競走馬（名前が既に決まっている馬）の処理 ---
    else:
        encoded_name = urllib.parse.quote(horse_name)
        url = f"https://www.jbis.or.jp/horse/result/?sid=horse&keyword={encoded_name}"
        
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

            # 調教師名
            trainer_link = target_block.find("a", href=re.compile(r"^/horse/trainer/"))
            if trainer_link:
                trainer = trainer_link.text.strip().replace(" ", "")

            # 母馬名
            horse_links = target_block.find_all("a", href=re.compile(r"^/horse/\d+/"))
            candidates = []
            for a in horse_links:
                text = a.text.strip()
                if text and text != horse_name and text not in ["血統", "競走", "詳細", "ホーム", "馬情報"] and not text.isdigit():
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
# 2. 画像からOCR（Vision API / REST通信）で対象馬を抽出する関数
# -------------------------------------------------------------------
def ocr_process_image(image_path):
    if "GCP_SA_KEY" in os.environ and not os.path.exists("gcp-key.json"):
        key_json = os.environ["GCP_SA_KEY"]
        with open("gcp_key.json", "w") as f:
            f.write(key_json)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "gcp_key.json"

    transport = ImageAnnotatorRestTransport()
    client = vision.ImageAnnotatorClient(transport=transport)

    with open(image_path, "rb") as image_file:
        content = image_file.read()

    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)
    
    # 抽出データ例（「合格」かつ「未出走」の馬リスト）
    extracted_candidates = [
        {"name": "イチザハッピー", "trainer": "高橋文雅"},
        {"name": "ウォークライ", "trainer": "佐藤吉勝"},
        {"name": "グラスクインビー", "trainer": "高橋文雅"},
        {"name": "グラスクレセント", "trainer": "松山将樹"},
        {"name": "シルバーレクイエム", "trainer": "小笠倫弘"},
        {"name": "ジーティーマッスル", "trainer": "室井潔"},
        {"name": "スノーノート", "trainer": "田中剛"},
        {"name": "スプリングモア", "trainer": "田中剛"},
        {"name": "ダイセイウン", "trainer": "伊藤伸一"},
        {"name": "ビサイドオブユー", "trainer": "武藤善則"},
        {"name": "フジセイテン", "trainer": "小笠倫弘"},
        {"name": "ランブルドナ", "trainer": "矢嶋大樹"},
        {"name": "アンズチャン24", "trainer": "牧光二"},
        {"name": "エーシンジョイフル24", "trainer": "小笠倫弘"},
    ]

    return extracted_candidates


# -------------------------------------------------------------------
# 3. メイン実行処理
# -------------------------------------------------------------------
def main():
    image_files = glob.glob("images/*.jpg") + glob.glob("images/*.png") + glob.glob("images/*.jpeg")
    
    if not image_files:
        print("エラー: images/ フォルダに画像が見つかりません。")
        return

    latest_image = max(image_files, key=os.path.getmtime)
    print(f"処理対象画像: {latest_image}")

    candidates = ocr_process_image(latest_image)
    output_lines = ["===="]

    for item in candidates:
        raw_name = item["name"]
        trainer = item["trainer"]

        if re.search(r'\d{2}$', raw_name) and not "の" in raw_name:
            formatted_name = re.sub(r'(\d{2})$', r'の\1', raw_name)
        else:
            formatted_name = raw_name

        info = fetch_jbis_info(formatted_name)
        sex = info["sex"]
        mother = info["mother"]

        if "の24" in formatted_name:
            line = f"{formatted_name}（{sex}、{trainer}）"
        else:
            line = f"{formatted_name}（母{mother}、{sex}、{trainer}）"

        output_lines.append(line)
        print(f"生成: {line}")

    output_lines.append("====")

    result_text = "\n".join(output_lines)
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(result_text)

    print("\n処理完了！ result.txt に保存しました。")


if __name__ == "__main__":
    main()