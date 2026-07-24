import os
import re
import html
import asyncio
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx

# Try importing cloudscraper
HAS_CLOUDSCRAPER = False
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# Try importing curl_cffi
HAS_CURL_CFFI = False
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# Try importing playwright
HAS_PLAYWRIGHT = False
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

DEFAULT_HEADERS = {
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1"
}

def unescape_string(text: str) -> str:
    """Unescape html entities and escaped slashes in JS strings."""
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace(r"\/", "/")
    text = text.replace(r"\u0026", "&")
    return text

def find_m3u8_in_text(content: str, base_url: str) -> List[str]:
    """Find all absolute m3u8 URLs in raw text/HTML."""
    clean_text = unescape_string(content)
    results = []
    
    # 1. Specific JS variable patterns commonly used in video players (Jable, HLS.js, DPlayer, DP, etc.)
    js_patterns = [
        r'var\s+hlsUrl\s*=\s*[\'"]([^\'"]+)[\'"]',
        r'var\s+url\s*=\s*[\'"]([^\'"]+\.m3u8[^\'"]*)[\'"]',
        r'var\s+video_url\s*=\s*[\'"]([^\'"]+\.m3u8[^\'"]*)[\'"]',
        r'source\s*:\s*[\'"]([^\'"]+\.m3u8[^\'"]*)[\'"]',
        r'file\s*:\s*[\'"]([^\'"]+\.m3u8[^\'"]*)[\'"]',
        r'<source[^>]+src=["\']([^"\']+\.m3u8[^"\']*)["\']',
    ]
    for pattern in js_patterns:
        js_matches = re.findall(pattern, clean_text, re.IGNORECASE)
        for m in js_matches:
            full = urllib.parse.urljoin(base_url, m)
            if full not in results:
                results.append(full)

    # 2. General Absolute m3u8 URLs regex
    abs_pattern = r'https?://[^\s"\'<>\\`]+?\.m3u8(?:\?[^\s"\'<>\\`]*)*'
    matches = re.findall(abs_pattern, clean_text, re.IGNORECASE)
    
    # 3. Relative m3u8 URLs regex
    rel_pattern = r'["\'](/[^"\']+\.m3u8(?:\?[^"\']*)?)["\']'
    rel_matches = re.findall(rel_pattern, clean_text, re.IGNORECASE)
    for rel in rel_matches:
        full = urllib.parse.urljoin(base_url, rel)
        matches.append(full)
        
    for m in matches:
        m = m.rstrip(";,)'\"")
        if m not in results:
            results.append(m)
            
    return results

def find_iframes(content: str, base_url: str) -> List[str]:
    """Find iframe src URLs that might embed video players."""
    clean_text = unescape_string(content)
    iframe_pattern = r'<iframe[^>]+?src=["\']([^"\']+)["\']'
    raw_iframes = re.findall(iframe_pattern, clean_text, re.IGNORECASE)
    
    iframes = []
    for src in raw_iframes:
        if src.startswith("//"):
            src = "https:" + src
        elif not src.startswith("http://") and not src.startswith("https://"):
            src = urllib.parse.urljoin(base_url, src)
            
        if not any(domain in src for domain in ["google.com", "facebook.com", "disqus.com", "doubleclick.net"]):
            if src not in iframes:
                iframes.append(src)
                
    return iframes

def fetch_page_content(url: str, headers: Dict[str, str]) -> tuple[int, str, str]:
    """Fetch HTML page using cloudscraper, curl_cffi, or httpx fallback."""
    if HAS_CLOUDSCRAPER:
        try:
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'darwin', 'desktop': True}
            )
            r = scraper.get(url, headers=headers, timeout=15)
            if r.status_code == 200 and "Just a moment..." not in r.text:
                return r.status_code, r.text, str(r.url)
        except Exception as e:
            print(f"cloudscraper error: {e}")

    if HAS_CURL_CFFI:
        try:
            r = curl_requests.get(url, headers=headers, impersonate="chrome120", timeout=15)
            if r.status_code == 200 and "Just a moment..." not in r.text:
                return r.status_code, r.text, str(r.url)
        except Exception as e:
            print(f"curl_cffi error: {e}")

    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
            r = client.get(url)
            return r.status_code, r.text, str(r.url)
    except Exception as e:
        return 500, str(e), url

async def extract_with_playwright(page_url: str) -> tuple[str, List[str]]:
    """Use Playwright stealth browser to bypass Cloudflare Turnstile & intercept M3U8 streams."""
    m3u8_found: List[str] = []
    page_title: str = ""

    if not HAS_PLAYWRIGHT:
        return page_title, m3u8_found

    try:
        exec_path = "/Users/doudou/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        
        async with async_playwright() as p:
            launch_kwargs = {
                "headless": True,
                "args": [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-infobars',
                    '--window-size=1920,1080'
                ]
            }
            if os.path.exists(exec_path):
                launch_kwargs["executable_path"] = exec_path
                
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="zh-CN"
            )
            page = await context.new_page()
            
            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
            except ImportError:
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            def handle_request(req):
                if ".m3u8" in req.url:
                    if req.url not in m3u8_found:
                        m3u8_found.append(req.url)

            page.on("request", handle_request)

            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                
                # Check title & wait for Cloudflare challenge bypass
                for _ in range(8):
                    title = await page.title()
                    if title and "Just a moment" not in title:
                        page_title = title
                        break
                    await asyncio.sleep(1)

                await page.wait_for_timeout(3500)

                content = await page.content()
                dom_found = find_m3u8_in_text(content, page_url)
                for u in dom_found:
                    if u not in m3u8_found:
                        m3u8_found.append(u)

            finally:
                await browser.close()
    except Exception as e:
        print(f"Playwright extraction error: {e}")

    return page_title, m3u8_found

async def extract_m3u8_from_url(page_url: str, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = DEFAULT_HEADERS.copy()
    if custom_headers:
        headers.update(custom_headers)
        
    headers["referer"] = page_url
    
    found_urls: List[str] = []
    page_title: str = ""
    
    try:
        clean_input = page_url.strip()
        if clean_input.lower().endswith(".m3u8") or ".m3u8?" in clean_input.lower():
            return {
                "status": "success",
                "title": "M3U8 直链",
                "m3u8_urls": [clean_input],
                "page_url": clean_input
            }

        # 1. Fast HTTP request attempt
        status_code, text, final_url = fetch_page_content(clean_input, headers)
        
        is_cf_blocked = (status_code == 403 or "Just a moment..." in text or "cf-mitigated" in text)

        if not is_cf_blocked and status_code == 200:
            og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', text, re.IGNORECASE)
            if og_title:
                page_title = html.unescape(og_title.group(1)).strip()
            else:
                title_match = re.search(r'<title>(.*?)</title>', text, re.IGNORECASE | re.DOTALL)
                if title_match:
                    page_title = html.unescape(title_match.group(1)).strip()
                    
            found = find_m3u8_in_text(text, final_url)
            for url in found:
                if url not in found_urls:
                    found_urls.append(url)
                    
            iframes = find_iframes(text, final_url)
            for iframe_url in iframes[:5]:
                try:
                    iframe_headers = {**headers, "referer": final_url}
                    sub_status, iframe_text, sub_final = fetch_page_content(iframe_url, iframe_headers)
                    if sub_status == 200 and "Just a moment..." not in iframe_text:
                        iframe_found = find_m3u8_in_text(iframe_text, sub_final)
                        for url in iframe_found:
                            if url not in found_urls:
                                found_urls.append(url)
                except Exception:
                    pass

        # 2. If no M3U8 found or Cloudflare blocked, trigger Playwright Stealth Headless Browser fallback!
        if not found_urls and HAS_PLAYWRIGHT:
            pw_title, pw_m3u8s = await extract_with_playwright(clean_input)
            if pw_title and not page_title:
                page_title = pw_title
            for u in pw_m3u8s:
                if u not in found_urls:
                    found_urls.append(u)

        # Clean title suffixes
        if page_title:
            page_title = re.sub(r'[\r\n\t]', ' ', page_title)
            page_title = re.sub(r'\s*[\-_\|]\s*(Jable\.TV|jable|免费高清|在线观看|影片).*$', '', page_title, flags=re.IGNORECASE).strip()

        return {
            "status": "success" if found_urls else "warning",
            "title": page_title or "网页提取视频",
            "m3u8_urls": found_urls,
            "page_url": page_url,
            "message": f"成功提取到 {len(found_urls)} 个 M3U8 视频流" if found_urls else "未在网页中检测到有效的 M3U8 视频播放流，请检查网页地址是否包含 HTML5 视频播放器。"
        }

    except Exception as e:
        return {
            "status": "error",
            "title": "",
            "m3u8_urls": [],
            "page_url": page_url,
            "message": f"解析网页失败: {str(e)}"
        }
