import requests as r
import json
import sys
import re
import time
from bs4 import BeautifulSoup as BS

# কনফিগারেশন
BASE_URL = "https://watchanimeworld.in/series/page/"
AJAX_URL = "https://watchanimeworld.in/wp-admin/admin-ajax.php" # AJAX এর জন্য এই URL লাগবে
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest" # সার্ভারকে বোঝানোর জন্য যে এটি একটি AJAX রিকোয়েস্ট
}

def clean_url(u):
    """URL ক্লিন করে"""
    if not u: return ""
    u = u.strip()
    if u.startswith("//"): u = "https:" + u
    return u.replace("https:https://", "https://")

def format_label(label):
    """'1x1' -> 'S01EP01' ফরম্যাট করে"""
    match = re.search(r'(\d+)\s*x\s*(\d+)', label.lower())
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        return f"S{season:02d}EP{episode:02d}"
    return label.strip()

def get_video_url(episode_link):
    """এপিসোড পেজ থেকে ভিডিও সোর্স বের করে"""
    try:
        resp = r.get(episode_link, headers=HEADERS, timeout=8)
        if resp.status_code != 200: return ""
        soup = BS(resp.content, 'html.parser')
        iframe = soup.find('iframe')
        if iframe:
            return clean_url(iframe.get('src'))
        return ""
    except: return ""

def get_all_season_html(soup, post_id):
    """
    যদি মাল্টিপল সিজন থাকে, তবে AJAX কল করে সব সিজনের HTML নিয়ে আসে।
    যদি না থাকে, তবে বর্তমান পেজের HTML ফেরত দেয়।
    """
    # সিজন লিস্ট চেক করা (যেমন: Season 1, Season 2 বাটন আছে কিনা)
    season_links = soup.select('.choose-season .sub-menu li a')
    
    html_contents = []
    
    if season_links and post_id:
        # যদি সিজন বাটন পাওয়া যায়, প্রতিটি সিজনের জন্য লুপ চালানো হবে
        # print(f"// Found {len(season_links)} seasons via AJAX...", file=sys.stderr)
        for s_link in season_links:
            season_num = s_link.get('data-season')
            
            # AJAX Payload তৈরি
            payload = {
                'action': 'action_select_season',
                'season': season_num,
                'post': post_id
            }
            
            try:
                # সার্ভারের কাছে ডাটা চাওয়া হচ্ছে
                ajax_resp = r.post(AJAX_URL, data=payload, headers=HEADERS, timeout=5)
                if ajax_resp.status_code == 200:
                    html_contents.append(ajax_resp.content)
            except Exception as e:
                # print(f"// Error fetching season {season_num}: {e}", file=sys.stderr)
                pass
    else:
        # যদি সিজন বাটন না থাকে (যেমন মুভি বা ১ সিজনের সিরিজ), তবে মেইন পেজের কন্টেন্টই যথেষ্ট
        html_contents.append(str(soup))
        
    return html_contents

def main():
    print("let data = [")
    page_num = 1
    
    while True:
        current_page_url = f"{BASE_URL}{page_num}/"
        try:
            resp = r.get(current_page_url, headers=HEADERS, timeout=10)
            if resp.status_code == 404: break 
            
            soup = BS(resp.content, 'html.parser')
            articles = soup.find_all('article')
            if not articles: break

            for article in articles:
                link_tag = article.find('a')
                img_tag = article.find('img')
                if not (link_tag and img_tag): continue
                
                series_url = link_tag['href']
                title = img_tag.get('alt', 'Unknown').replace('Image ', '', 1).strip()
                img_src = clean_url(img_tag.get('src') or img_tag.get('data-src'))
                
                # --- সিরিজ ডিটেইল পেজ ---
                try:
                    s_resp = r.get(series_url, headers=HEADERS, timeout=10)
                    s_soup = BS(s_resp.content, 'html.parser')
                    
                    # Post ID বের করা (AJAX কলের জন্য জরুরি)
                    # সাধারণত <a data-post="1101"> এমন থাকে
                    post_id = None
                    post_id_elem = s_soup.find(attrs={"data-post": True})
                    if post_id_elem:
                        post_id = post_id_elem.get("data-post")
                    
                    # সব সিজনের HTML সংগ্রহ (AJAX বা নরমাল)
                    all_html_sources = get_all_season_html(s_soup, post_id)
                    
                    episode_urls = []
                    seen_links = set()
                    
                    # প্রতিটি সিজনের সোর্স থেকে এপিসোড বের করা
                    for source in all_html_sources:
                        # source string হতে পারে বা bytes, তাই BS এ কনভার্ট
                        temp_soup = BS(source, 'html.parser')
                        all_links = temp_soup.find_all('a', class_='lnk-blk')
                        
                        for a_tag in all_links:
                            href = a_tag.get('href', '')
                            if '/episode/' not in href: continue
                            if href in seen_links: continue
                            
                            seen_links.add(href)
                            
                            # এপিসোড নম্বর খোঁজা
                            # এটি কখনো প্যারেন্ট এলিমেন্টেও থাকতে পারে, তাই চেক করা হচ্ছে
                            label_text = "Extras"
                            # 1. চেক করি লিঙ্কটি কোনো article এর মধ্যে আছে কিনা
                            parent_article = a_tag.find_parent('article')
                            if parent_article:
                                ep_span = parent_article.find('span', class_='num-epi')
                                if ep_span: label_text = ep_span.text.strip()
                            
                            # 2. যদি না পাওয়া যায়, URL থেকে 1x1 বের করি
                            if label_text == "Extras":
                                match = re.search(r'[-/](\d+x\d+)', href)
                                if match: label_text = match.group(1)
                            
                            video_src = get_video_url(href)
                            if video_src:
                                formatted_label = format_label(label_text)
                                episode_urls.append([video_src, formatted_label])

                    if episode_urls:
                        # সাজানো (Sort)
                        episode_urls.sort(key=lambda x: x[1])
                        
                        json_obj = {
                            "TITLE": title,
                            "IMG": img_src,
                            "URL": episode_urls
                        }
                        print(json.dumps(json_obj, indent=4) + ",")
                        sys.stdout.flush()

                except Exception as e:
                    # print(f"// Error in series {title}: {e}", file=sys.stderr)
                    continue

            page_num += 1

        except Exception as e:
            # print(f"// Critical error: {e}", file=sys.stderr)
            break

    print("];")

if __name__ == "__main__":
    main()

















import requests as r, json, sys, re
from bs4 import BeautifulSoup as BS

# ==================================
# START/END PAGE CONFIGURATION
START_PAGE = 1
END_PAGE = 2 # আপনি যত নম্বর পেজ পর্যন্ত স্ক্র্যাপ করতে চান, সেই সংখ্যাটি এখানে দিন
# ==================================

BASE = "https://watchanimeworld.in/series/page/"
AJAX = "https://watchanimeworld.in/wp-admin/admin-ajax.php"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", "X-Requested-With": "XMLHttpRequest"}

def clean_url(u):
    if not u: return ""
    u = u.strip()
    if u.startswith("//"): u = "https:" + u
    return u.replace("https:https://", "https://")

def format_label(l):
    m = re.search(r'(\d+)\s*x\s*(\d+)', l.lower())
    return f"S{int(m.group(1)):02d}EP{int(m.group(2)):02d}" if m else "Extras"

def get_video_url(link):
    try:
        s = BS(r.get(link, headers=H, timeout=8).content, 'html.parser').find('iframe').get('src')
        return clean_url(s)
    except: return ""

def get_all_season_html(s, pid):
    links = s.select('.choose-season .sub-menu li a')
    contents = []
    if links and pid:
        for l in links:
            sn = l.get('data-season')
            payload = {'action': 'action_select_season', 'season': sn, 'post': pid}
            try:
                resp = r.post(AJAX, data=payload, headers=H, timeout=5)
                if resp.status_code == 200: contents.append(resp.content)
            except: pass
    else: contents.append(str(s))
    return contents

def main():
    print("let data = [")
    for pn in range(START_PAGE, END_PAGE + 1):
        url = f"{BASE}{pn}/"
        try:
            resp = r.get(url, headers=H, timeout=10)
            if resp.status_code != 200: break
            
            s = BS(resp.content, 'html.parser')
            articles = s.find_all('article')
            if not articles: break

            for a in articles:
                l = a.find('a'); i = a.find('img')
                if not (l and i): continue
                
                s_url = l['href']
                title = i.get('alt', 'Unknown').replace('Image ', '', 1).strip()
                img_src = clean_url(i.get('src') or i.get('data-src'))
                
                try:
                    s_resp = r.get(s_url, headers=H, timeout=10)
                    s_soup = BS(s_resp.content, 'html.parser')
                    
                    pid = (s_soup.find(attrs={"data-post": True}) or {}).get("data-post")
                    html_sources = get_all_season_html(s_soup, pid)
                    
                    ep_urls, seen = [], set()
                    
                    for src in html_sources:
                        t_soup = BS(src, 'html.parser')
                        links = t_soup.find_all('a', class_='lnk-blk')
                        
                        for tag in links:
                            href = tag.get('href', '')
                            if '/episode/' not in href or href in seen: continue
                            seen.add(href)
                            
                            label = "Extras"
                            art = tag.find_parent('article')
                            if art and art.find('span', class_='num-epi'):
                                label = art.find('span', class_='num-epi').text.strip()
                            else:
                                m = re.search(r'[-/](\d+x\d+)', href)
                                if m: label = m.group(1)
                            
                            v_src = get_video_url(href)
                            if v_src:
                                ep_urls.append([v_src, format_label(label)])

                    if ep_urls:
                        ep_urls.sort(key=lambda x: x[1])
                        print(json.dumps({"TITLE": title, "IMG": img_src, "URL": ep_urls}, indent=4) + ",")
                        sys.stdout.flush()

                except: continue

        except: break

    print("];")

if __name__ == "__main__":
    main()