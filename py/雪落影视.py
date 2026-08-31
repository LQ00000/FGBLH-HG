# coding=utf-8
import re
import json
import time
import gzip
import base64
import hashlib
import requests
from urllib.parse import urljoin, quote
from bs4 import BeautifulSoup
from base.spider import Spider

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad as _pad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

class Spider(Spider):
    def __init__(self):
        super().__init__()
        self.host = "https://v.xl.in.ua"
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/"
        }
        self.session.headers.update(self.headers)
        self.classes = [
            ("最新电影", "/s/all?type=0"),
            ("最新剧集", "/s/all?type=1"),
            ("动作", "/s/dongzuo"),
            ("爱情", "/s/aiqing"),
            ("喜剧", "/s/xiju"),
            ("科幻", "/s/kehuan"),
            ("恐怖", "/s/kongbu"),
            ("战争", "/s/zhanzheng"),
            ("武侠", "/s/wuxia"),
            ("魔幻", "/s/mohuan"),
            ("剧情", "/s/juqing"),
            ("动画", "/s/donghua"),
            ("惊悚", "/s/jingsong"),
            ("悬疑", "/s/xuanyi"),
            ("犯罪", "/s/fanzui"),
            ("纪录", "/s/jilu"),
            ("古装", "/s/guzhuang"),
            ("奇幻", "/s/qihuan"),
            ("国语", "/s/guoyu"),
            ("综艺", "/s/zongyi"),
            ("历史", "/s/lishi"),
            ("冒险", "/s/maoxian"),
            ("美剧", "/s/meiju"),
            ("韩剧", "/s/hanju"),
            ("国产剧集", "/s/guoju"),
            ("日剧", "/s/riju"),
            ("英剧", "/s/yingju"),
            ("德剧", "/s/deju"),
            ("泰剧", "/s/taiju"),
            ("港台剧", "/s/gangtaiju")
        ]

    def getName(self):
        return "雪落影视"

    def init(self, extend=""):
        return None

    def _get(self, url):
        try:
            r = self.session.get(urljoin(self.host, url), timeout=20)
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception:
            return ""

    def _url(self, url):
        return urljoin(self.host, url or "")

    def _text(self, node):
        return re.sub(r"\s+", " ", node.get_text(" ", strip=True) if node else "").strip()

    def _pic(self, img):
        if not img:
            return ""
        for key in ("data-src", "data-original", "data-lazy-src", "src"):
            value = img.get(key, "").strip()
            if value and not value.startswith("data:"):
                return self._url(value)
        return ""

    def _card(self, card):
        try:
            link = card.select_one("a.card-img[href]") or card.select_one("a[href]")
            if not link:
                return None
            href = link.get("href", "")
            if not href or href.startswith("javascript:"):
                return None
            title = self._text(card.select_one("h4")) or link.get("title", "")
            if not title:
                return None
            meta = self._text(card.select_one(".card-meta"))
            rating = self._text(card.select_one(".rating-badge"))
            remark = " ".join([x for x in (rating, meta) if x])
            return {
                "vod_id": href,
                "vod_name": title,
                "vod_pic": self._pic(card.select_one("img")),
                "vod_remarks": remark
            }
        except Exception:
            return None

    def _cards(self, html):
        soup = BeautifulSoup(html, "html.parser")
        result = []
        seen = set()
        for card in soup.select(".movie-card"):
            item = self._card(card)
            if item and item["vod_id"] not in seen:
                seen.add(item["vod_id"])
                result.append(item)
        return soup, result

    def _pagecount(self, soup, current):
        pages = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(r"/s/[^/]+/(\d+)(?:\?|$)", href)
            if m:
                pages.append(int(m.group(1)))
        return max(pages + [current])

    def homeContent(self, filter):
        return {"class": [{"type_id": path, "type_name": name} for name, path in self.classes]}

    def homeVideoContent(self):
        html = self._get("/")
        soup, items = self._cards(html)
        return {"list": items[:24]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        path = tid
        if page > 1 and path.startswith("/s/"):
            if "?" in path:
                path = path.replace("?", "/%d?" % page, 1)
            else:
                path = path.rstrip("/") + "/%d" % page
        html = self._get(path)
        soup, items = self._cards(html)
        count = self._pagecount(soup, page)
        return {"list": items, "page": page, "pagecount": count, "limit": 24, "total": count * 24}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        html = self._get(vid)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        title = self._text(soup.select_one(".detail-title, h1, h2"))
        if not title:
            title = soup.title.get_text(strip=True).split(" - ")[0] if soup.title else ""
        pic = ""
        og = soup.select_one('meta[property="og:image"]')
        if og:
            pic = self._url(og.get("content", ""))
        if not pic:
            pic = self._pic(soup.select_one(".detail-container img, .detail-content img, img"))
        desc = self._text(soup.select_one(".desc, .description, .detail-desc"))
        play = []
        for a in soup.select("a.play-item[href], a[href^='/play/']"):
            href = a.get("href", "")
            name = self._text(a) or "在线播放"
            if href and href not in [x[1] for x in play]:
                play.append((name, self._url(href)))
        vod = {
            "vod_id": vid,
            "vod_name": title or vid,
            "vod_pic": pic,
            "vod_content": desc,
            "vod_play_from": "雪落影视",
            "vod_play_url": "$$$".join([name + "$" + url for name, url in play])
        }
        return {"list": [vod]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        url = "/search/" + quote(key)
        if page > 1:
            url += "/%d" % page
        html = self._get(url)
        soup, items = self._cards(html)
        return {"list": items, "page": page, "pagecount": self._pagecount(soup, page), "limit": 24, "total": len(items)}

    def _sign(self, pid, t):
        """生成 AES ECB 签名 (与 xlplayer.js 的 getUrl/getLines 逻辑一致)"""
        plaintext = f"{pid}-{t}"
        key = hashlib.md5(plaintext.encode()).hexdigest()[:16].encode()
        cipher = AES.new(key, AES.MODE_ECB)
        encrypted = cipher.encrypt(_pad(plaintext.encode(), AES.block_size))
        return encrypted.hex().upper()

    def _get_pid(self, play_url):
        """从播放页 HTML 提取 pid"""
        html = self._get(play_url)
        m = re.search(r'var\s+pid\s*=\s*(\d+)', html)
        return (m.group(1), html) if m else (None, html)

    def _get_lines(self, pid):
        """调用 /lines/ API 获取播放线路"""
        t = str(int(time.time() * 1000))
        sg = self._sign(pid, t)
        try:
            r = self.session.get(
                self.host + "/lines/",
                params={"t": t, "sg": sg, "pid": pid},
                timeout=20
            )
            data = r.json()
            if data.get("code") == 0:
                return data.get("data", {})
        except Exception:
            pass
        return {}

    def _get_god_url(self, pid, code=666):
        """调用 /god/ API 获取直链"""
        t = str(int(time.time() * 1000))
        sg = self._sign(pid, t)
        url = f"{self.host}/god/{pid}"
        if code == 888:
            url += "?type=1"
        try:
            r = self.session.post(
                url,
                data={"t": t, "sg": sg, "verifyCode": str(code)},
                timeout=20
            )
            res = r.json()
            return res.get("url", "")
        except Exception:
            return ""

    def _deal_url(self, url):
        """处理直链 URL (与 dealUrl 逻辑一致)"""
        if "handler" in url:
            url += "/" + str(int(time.time() * 1000)) + ".mp4"
        url = url.replace("?rkey", "?mp4&rkey=" + str(int(time.time() * 1000)))
        if "bde4.cc" in url:
            url = url.replace("ftn_handler/", "?mp4=" + str(int(time.time() * 1000)))
            url = url.replace("bde4.cc", "weiyun.com")
        return url

    def _process_m3u8(self, m3u8_url):
        """下载、解密 m3u8 (与 dealM3u8 逻辑一致)"""
        url = m3u8_url.replace("www.bde4.cc", "v.xl.in.ua")
        url = url.replace("vod.xlys01.com", "v.xl.in.ua")
        try:
            r = self.session.get(url, timeout=20)
            data = r.content
            data = data[3354:]
            decompressed = gzip.decompress(data)
            m3u8_text = decompressed.decode("utf-8")
            if "su-4102" in url or "ac5634-us" in url:
                m3u8_text = re.sub(r'.*?\.ts', 'https://vod.xl01.me/hls/\g<0>', m3u8_text)
            else:
                m3u8_text = re.sub(r'.*?\.ts', 'https://vod.xl01.me/\g<0>', m3u8_text)
            return m3u8_text
        except Exception:
            return ""

    def playerContent(self, flag, id, vipFlags):
        result = {"parse": 1, "playUrl": "", "url": self._url(id), "header": self.headers}
        if not id:
            return result
        play_url = self._url(id) if not id.startswith("http") else id

        if not HAS_CRYPTO:
            return result

        try:
            pid, html = self._get_pid(play_url)
            if not pid:
                return result

            lines_data = self._get_lines(pid)
            if not lines_data:
                return result

            candidates = []
            if lines_data.get("m3u8"):
                candidates.append(("m3u8", lines_data["m3u8"]))
            if lines_data.get("m3u8_2"):
                for u in lines_data["m3u8_2"].split(","):
                    u = u.strip()
                    if u and "DFD45E4E4144454C" not in u and "64487B785C38CAF5" not in u:
                        candidates.append(("m3u8", u))
            if lines_data.get("url3"):
                for u in lines_data["url3"].split(","):
                    u = u.strip()
                    if u:
                        candidates.append(("mp4", u))
            if lines_data.get("ptoken"):
                candidates.append(("god", self.host + "/god/" + pid))
            if lines_data.get("tos"):
                candidates.append(("god", self.host + "/god/" + pid + "?type=1"))

            for ctype, curl in candidates:
                try:
                    if ctype == "m3u8":
                        m3u8_text = self._process_m3u8(curl)
                        if m3u8_text:
                            b64 = base64.b64encode(m3u8_text.encode("utf-8")).decode()
                            data_url = "data:application/vnd.apple.mpegurl;base64," + b64
                            result["parse"] = 0
                            result["url"] = data_url
                            result["header"] = json.dumps({
                                "User-Agent": self.headers["User-Agent"],
                                "Referer": self.host + "/",
                            })
                            return result
                    elif ctype == "mp4":
                        real_url = self._deal_url(curl)
                        result["parse"] = 0
                        result["url"] = real_url
                        result["header"] = json.dumps({
                            "User-Agent": self.headers["User-Agent"],
                            "Referer": self.host + "/",
                        })
                        return result
                    elif ctype == "god":
                        code = 888 if "type=1" in curl else 666
                        real_url = self._get_god_url(pid, code)
                        if real_url:
                            if "bde4.cc" in real_url or "handler" in real_url:
                                real_url = self._deal_url(real_url)
                            result["parse"] = 0
                            result["url"] = real_url
                            result["header"] = json.dumps({
                                "User-Agent": self.headers["User-Agent"],
                                "Referer": self.host + "/",
                            })
                            return result
                except Exception:
                    continue
        except Exception:
            pass

        return result

    def isVideoFormat(self, url):
        value = (url or "").lower()
        return ".m3u8" in value or ".mp4" in value or "/play/" in value

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
