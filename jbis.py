import re, sys, time, urllib.parse
import requests
from bs4 import BeautifulSoup

BASE = "https://www.jbis.or.jp"
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
})
DEBUG = "--debug" in sys.argv


def get(url, tag=""):
    time.sleep(0.5)
    res = session.get(url, timeout=15)
    if DEBUG and tag:
        with open(f"debug_{tag}.html", "w", encoding="utf-8") as f:
            f.write(res.text)
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code} {url}")
    return BeautifulSoup(res.text, "html.parser")


def norm(s):
    s = re.sub(r"\s+", "", s)
    return re.sub(r"\([A-Za-z]{2,3}\)$", "", s)


def horse_id(href):
    m = re.search(r"/horse/(\d+)/?$", href or "")

    return m.group(1) if m else None


def sex_of(text):
    m = re.search(r"(牡|牝|セン|セ)", text)
    return ("セ" if m.group(1) == "セン" else m.group(1)) if m else ""


# ---------- 検索結果の1行(div構造) ----------
def search_rows(name):
    """検索結果から、馬名が完全一致する行を [{id, sex, trainer, mother, url}] で返す"""
    url = f"{BASE}/horse/result/?sid=horse&keyword={urllib.parse.quote(name)}"
    soup = get(url, "search_" + name)
    return parse_search(soup, name), url


def parse_search(soup, name):
    rows = []
    for a in soup.find_all("a", href=True):
        hid = horse_id(a["href"])
        if not hid or norm(a.get_text()) != name:
            continue
        head = a.find_parent("div", class_="jc-between")
        row = head.parent if head else None
        if row is None:
            continue
        # 性別
        sex = ""
        for d in row.find_all("div", recursive=False):
            t = d.get_text(strip=True)
            if t in ("牡", "牝", "セ", "セン"):
                sex = sex_of(t)

                break
        # 調教師
        ta = row.find("a", href=re.compile(r"/horse/trainer/"))
        trainer = norm(ta.get_text()) if ta else ""
        # 父・母(自分以外の馬リンクの最後が母)
        others = [x for x in row.find_all("a", href=True)
                  if horse_id(x["href"]) and horse_id(x["href"]) != hid]
        mother = norm(others[-1].get_text()) if len(others) >= 2 else ""
        rows.append({"id": hid, "sex": sex, "trainer": trainer, "mother": mother,
                     "url": f"{BASE}/horse/{hid}/"})
    rows.sort(key=lambda r: int(r["id"]), reverse=True)
    return rows


# ---------- 牝系情報(div.data-1__item) ----------
def find_foal(soup, mother_id, year):
    """母馬本人(深さ0)の直接の産駒(深さ1)だけを対象にする"""
    in_mother_block = False
    for item in soup.select("div.data-1__item"):
        depth = len(item.find_parents("div", class_="data-1__branch"))
        a = item.find("a", href=True)
        hid = horse_id(a["href"]) if a else None

        if depth == 0:
            in_mother_block = (hid == mother_id)  # 母本人のブロックの間だけ True
            continue
        if not in_mother_block or depth != 1:
            continue

        text = item.get_text(" ", strip=True)
        if f"{year}年" not in text or "産駒なし" in text:
            continue
        if not hid or hid == mother_id:
            continue
        sp = item.find("span", class_=re.compile(r"txt-(male|female|gelding)"))
        sex = sex_of(sp.get_text()) if sp else sex_of(text)
        return {"id": hid, "sex": sex}
    return None

def parse_trainer(soup):
    a = soup.find("a", href=re.compile(r"/horse/trainer/"))

    return norm(a.get_text()) if a else ""


def foal_info(mother_name, year):
    rows, surl = search_rows(mother_name)
    if not rows:
        raise RuntimeError(f"母馬が検索に完全一致なし: {surl}")
    for r in rows:
        bm = get(f"{BASE}/horse/{r['id']}/broodmare/info/", f"brood_{r['id']}")
        foal = find_foal(bm, r["id"], year)
        if not foal:
            continue
        url = f"{BASE}/horse/{foal['id']}/"
        page = get(url, f"foal_{foal['id']}")
        return foal["sex"] or "？", parse_trainer(page) or "未定", url
    raise RuntimeError(f"{mother_name}の{year}年産駒が見つからない")


def named_info(name):
    rows, surl = search_rows(name)
    if not rows:
        raise RuntimeError(f"検索に完全一致なし: {surl}")
    r = rows[0]
    return r["mother"] or "？", r["sex"] or "？", r["trainer"] or "？", r["url"]


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("--")), "horses.txt")
    with open(path, encoding="utf-8") as f:
        names = [l.strip() for l in f if l.strip()]
    out = []
    for raw in names:

        m = re.match(r"^(.*?)の?(\d{2})$", raw)
        try:
            if m:
                mother, yy = m.group(1).strip(), m.group(2)
                sex, trainer, url = foal_info(mother, 2000 + int(yy))
                line = f"{mother}の{yy}（{sex}、{trainer}）"
            else:
                mother, sex, trainer, url = named_info(raw)
                line = f"{raw}（母{mother}、{sex}、{trainer}）"
        except Exception as e:
            line, url = f"{raw}（取得失敗）", str(e)
        print(line, url)
        out.append(f"{line}\t{url}")
    with open("result.tsv", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("result.tsv を出力しました(B1セルから貼り付け)")


if __name__ == "__main__":
    main()