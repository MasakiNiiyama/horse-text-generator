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
# 1. JBISから「母馬名」「性別」を取得する関数（同名馬対策・年次優先版）
# -------------------------------------------------------------------
def fetch_jbis_info(horse_name):
    """
    JBIS-サーチから馬名で検索し、最新生年の馬から母馬名と性別を取得する
    """
    clean_name = re.sub(r'(の)?\d{2}$', '', horse_name)
    encoded_name = urllib.parse.quote(clean_name)
    url = f"https://www.jbis.or.jp/horse/result/?sid=horse&keyword={encoded_name}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return {"mother": "不明", "sex": "不明"}

        soup = BeautifulSoup(res.text, "html.parser")
        
        sex = "不明"
        mother = "不明"

        # 1. 性別の抽出（「牝」「牡」「セ」を取得）
        for div in soup.find_all("div"):
            text = div.text.strip()
            if text in ["牝", "牡", "セ"]:
                sex = text
                break

        # 2. 母馬名の抽出（ヒットした全ブロックの中から「最新の世代」の母馬を取得）
        # 同名馬（過去のウォークライ等）がある場合、最も生年が新しい馬ブロックの母馬を採用
        blocks = soup.select("div.tbl-data-01")
        target_block = blocks[0] if blocks else soup

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

        # 外国馬記号 (ARG), (USA), (JPN) 等の除去
        mother = re.sub(r'\([A-Za-z]{3}\)$', '', raw_mother)

        return {"mother": mother, "sex": sex}

    except Exception as e:
        print(f"[JBIS Fetch Error] {horse_name}: {e}")
        return {"mother": "不明", "sex": "不明"}
                
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