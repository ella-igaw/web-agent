# ssg_paginate.py
import asyncio, json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import pandas as pd
from quick_check_ssg import grab  # 같은 폴더에 있는 grab() 사용

def set_qs(url: str, **params):
    u = urlparse(url)
    qs = parse_qs(u.query)
    for k, v in params.items():
        qs[k] = [str(v)]
    new_q = urlencode({k: v[0] for k, v in qs.items()}, doseq=False)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, u.fragment))

def item_key(row: dict) -> str:
    # itemId 우선 → 없으면 url → 제목+이미지
    url = (row.get("url") or "")
    if "itemId=" in url:
        return url.split("itemId=")[1].split("&")[0]
    if url:
        return url
    return f"t:{row.get('title','')}|i:{row.get('image','')}"

async def crawl_ssg(query_url: str, start_page=1, max_pages=5, max_items_per_page=80, headless=True):
    seen = set()
    out = []
    for p in range(start_page, start_page + max_pages):
        url_p = set_qs(query_url, page=p)
        items = await grab(url_p, max_items=max_items_per_page, headless=headless)
        added = 0
        for r in items:
            k = item_key(r)
            if k in seen: 
                continue
            seen.add(k)
            r["page"] = p
            out.append(r)
            added += 1
        print(f"[page {p}] got:{len(items)}  added:{added}  total:{len(out)}")
        if added == 0:  # 다음 페이지에 더 없을 가능성 ↑
            break
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--start_page", type=int, default=1)
    ap.add_argument("--max_pages", type=int, default=5)
    ap.add_argument("--per_page", type=int, default=80)
    ap.add_argument("--headless", action="store_true", help="헤드리스")
    ap.add_argument("--out", default="ssg_out")
    args = ap.parse_args()

    data = asyncio.run(
        crawl_ssg(args.url, args.start_page, args.max_pages, args.per_page, headless=args.headless or False)
    )
    print("TOTAL:", len(data))
    df = pd.DataFrame(data)
    df.to_csv(f"{args.out}.csv", index=False, encoding="utf-8-sig")
    with open(f"{args.out}.json","w",encoding="utf-8") as f:
        json.dump({"url": args.url, "total": len(data), "data": data}, f, ensure_ascii=False, indent=2)
    print(f"saved: {args.out}.csv / {args.out}.json")

