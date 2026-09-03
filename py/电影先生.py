# -*- coding: utf-8 -*-

import sys, re, json, base64, html, os, threading, time, hashlib
from urllib.parse import quote, unquote, urljoin, urlparse
try: from lxml import etree
except ImportError: etree = None
try: import requests
except ImportError: requests = None
try:
    import cloudscraper
except ImportError:
    cloudscraper = None
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError: urllib3 = None
try: from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        def init(self, extend=""): self.extend = extend
        def homeContent(self, filter): return {'class': [], 'filters': {}}
        def homeVideoContent(self): return {'list': []}
        def categoryContent(self, tid, pg, filter, extend): return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 24, 'total': 0}
        def detailContent(self, ids): return {'list': []}
        def playerContent(self, flag, id, vipFlags=None): return {'parse': 0, 'playUrl': '', 'url': '', 'header': ''}
        def searchContent(self, key, quick, pg='1'): return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 24, 'total': 0}
        def isVideoFormat(self, url): return bool(url and ('.m3u8' in url or '.mp4' in url or '127.0.0.1' in url or '/proxy?' in url))
        def manualVideoCheck(self): return True
        def localProxy(self, param): return [404, 'text/plain', b'']

def fix_url(url, host):
    if not url: return ""
    if url.startswith("//"): return "https:" + url
    if url.startswith("/"): return urljoin(host, url)
    if url.startswith("http"): return url
    return urljoin(host, "/" + url)

def clean_text(text):
    if not text: return ""
    return html.unescape(re.sub(r'<[^>]+>', '', str(text))).strip()

def _page(pg):
    """安全页码：非法/空/<=0 一律归 1。"""
    try:
        v = int(str(pg or "").strip())
        return v if v > 0 else 1
    except (OSError, ValueError, AttributeError, TypeError):
        return 1


# ═══ 破甲增强：纯Python AES-CBC / 图片魔数 / PKCS7 / m3u8代理 ═══
# AES S-box 运行时计算（避免硬编码256字节常量）
def _gen_sbox():
    '''生成AES S-box。'''
    s = [0]*256; p=q=1
    while True:
        p = (p ^ (p>>1) ^ 0x1b if p & 0x80 else p<<1) & 0xff
        q ^= (q<<1) ^ 0x1b if q & 0x80 else q<<1
        q &= 0xff
        s[q] = s[p] = p ^ (p<<1) ^ (p<<2) ^ (p<<3) ^ (p<<4)
        s[p] = (s[p] ^ (s[p]>>7) ^ (0x63 if s[p]>>7 else 0)) & 0xff
        s[q] = (s[q] ^ (s[q]>>7) ^ (0x63 if s[q]>>7 else 0)) & 0xff
        if p == 1: break
    s[0] = 0x63
    return bytes(s)

def _inv_sbox(sbox):
    '''从S-box生成逆S-box。'''
    return bytes([sbox.index(i) for i in range(256)])

def _aes_decrypt(data, key, iv):
    '''AES-CBC解密（纯Python，无pycryptodome依赖）。'''
    import base64 as _b64
    try:
        raw = _b64.b64decode(data)
    except Exception:
        raw = data.encode() if isinstance(data, str) else data
    # 尝试pycryptodome
    try:
        from Crypto.Cipher import AES as _AES
        from Crypto.Util.Padding import unpad as _unpad
        c = _AES.new(key.encode() if isinstance(key, str) else key, _AES.MODE_CBC, iv.encode() if isinstance(iv, str) else iv)
        return _unpad(c.decrypt(raw), _AES.block_size).decode('utf-8')
    except ImportError:
        pass
    # 纯Python AES解密
    SBOX = _gen_sbox()
    INV_SBOX = _inv_sbox(SBOX)
    RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]
    def _xt(a): return ((a<<1)^0x1b)&0xff if a&0x80 else (a<<1)&0xff
    def _gm(a,b):
        r=0
        while b:
            if b&1: r^=a
            b>>=1; a=_xt(a)
        return r
    def _ke(k):
        nk=len(k)//4; w=[int.from_bytes(k[i:i+4],'big') for i in range(0,len(k),4)]
        for i in range(nk,44):
            t=w[i-1]
            if i%nk==0:
                t=((t<<8)|(t>>24))&0xffffffff
                t=((SBOX[(t>>24)&0xff]<<24)|(SBOX[(t>>16)&0xff]<<16)|(SBOX[(t>>8)&0xff]<<8)|SBOX[t&0xff])^(RCON[i//nk-1]<<24)
            w.append(w[i-nk]^t)
        return [[[(x>>24)&0xff,(x>>16)&0xff,(x>>8)&0xff,x&0xff] for x in w[rnd*4:rnd*4+4]] for rnd in range(11)]
    def _db(k,b):
        w=_ke(k); s=list(b)
        def ark(r):
            for c in range(4):
                for r2 in range(4): s[4*c+r2]^=w[r][c][r2]
        def isb():
            for i in range(16): s[i]=INV_SBOX[s[i]]
        def isr():
            t=s[:]
            for r in range(1,4):
                for c in range(4): s[4*c+r]=t[4*((c-r)%4)+r]
        def imc():
            for c in range(4):
                a0,a1,a2,a3=s[4*c],s[4*c+1],s[4*c+2],s[4*c+3]
                s[4*c]=_gm(a0,0x0e)^_gm(a1,0x0b)^_gm(a2,0x0d)^_gm(a3,0x09)
                s[4*c+1]=_gm(a0,0x09)^_gm(a1,0x0e)^_gm(a2,0x0b)^_gm(a3,0x0d)
                s[4*c+2]=_gm(a0,0x0d)^_gm(a1,0x09)^_gm(a2,0x0e)^_gm(a3,0x0b)
                s[4*c+3]=_gm(a0,0x0b)^_gm(a1,0x0d)^_gm(a2,0x09)^_gm(a3,0x0e)
        ark(10)
        for rd in range(9,0,-1): isr(); isb(); ark(rd); imc()
        isr(); isb(); ark(0)
        return bytes(s)
    out=bytearray(); prev=iv.encode() if isinstance(iv,str) else iv
    for i in range(0,len(raw),16):
        blk=raw[i:i+16]; out+=bytes(a^b for a,b in zip(_db(key.encode() if isinstance(key,str) else key,blk),prev)); prev=blk
    # PKCS7 unpad
    r=bytes(out)
    if r and 1<=r[-1]<=16 and r[-r[-1]:]==bytes([r[-1]])*r[-1]:
        return r[:-r[-1]].decode('utf-8')
    return r.decode('utf-8',errors='replace')

def _detect_image_mime(data):
    '''检测图片魔数。'''
    if not data or len(data)<4: return ''
    if data[:4]==b'\x89PNG' and data[1:4]==b'PNG': return 'image/png'
    if data[:2]==b'\xff\xd8': return 'image/jpeg'
    if data[:6] in (b'GIF87a',b'GIF89a'): return 'image/gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP': return 'image/webp'
    return ''

def _xor_decrypt_img(data, key=None):
    '''XOR解密图片，自动魔数检测。'''
    if key is None: key=b''
    if isinstance(key,str): key=key.encode()
    out=bytearray(b^key[i%len(key)] for i,b in enumerate(data))
    if _detect_image_mime(bytes(out)): return bytes(out)
    out2=bytearray(128^b for b in data)
    if _detect_image_mime(bytes(out2)): return bytes(out2)
    return data

def _rewrite_m3u8_proxy(m3u8_text, base_url, proxy_prefix):
    '''重写m3u8：相对路径→代理URL。'''
    lines=[]
    for line in m3u8_text.splitlines():
        s=line.strip()
        if not s: lines.append(line); continue
        if s.startswith('#'):
            if s.startswith('#EXT-X-KEY') and 'URI="' in s:
                import re as _re
                m=_re.search(r'URI="([^"]+)"', s)
                if m: lines.append(s.replace(m.group(1), proxy_prefix+__import__('urllib.parse').quote(urljoin(base_url,m.group(1)),safe='')))
                else: lines.append(line)
            else: lines.append(line)
        elif s.startswith('http://') or s.startswith('https://'):
            lines.append(proxy_prefix+__import__('urllib.parse').quote(s,safe=''))
        else:
            lines.append(proxy_prefix+__import__('urllib.parse').quote(urljoin(base_url,s),safe=''))
    return '\n'.join(lines)

def extract_pic(node, host):
    if node is None: return ""
    def _norm(u):
        if not u or not u.strip(): return ""
        u = u.strip()
        if " " in u or "," in u:  # data-srcset / 多 url 取首个
            u = re.split(r"[\s,]", u)[0].strip()
        if "url(" in u:  # 背景图 style="...url(x)"
            _m = re.search(r'url\([\'"]?([^\'")]+)', u)
            if _m: u = _m.group(1)
        if any(_k in u.lower() for _k in ["placeholder", "blank", "loading.gif", "lazy.gif", "/default_", "data:image", "1px"]):
            return ""
        return fix_url(u, host)
    # 1) 优先：位于 poster/cover/pic 容器内（含祖先）或自身带该类的主图
    for _img in node.xpath('.//img[ancestor-or-self::*[contains(@class,"poster") or contains(@class,"cover") or contains(@class,"pic")]]'):
        for _a in ("data-original", "data-src", "data-lazy-src", "src", "data-img"):
            _u = _norm(_img.get(_a, ""))
            if _u: return _u
    # 2) 列表项 / 通用：自身懒加载属性（跳过占位图）
    for _p in [".//img/@data-original", ".//img/@data-src", ".//img/@data-lazy-src", ".//img/@data-srcset", ".//img/@src", ".//img/@data-img"]:
        try:
            _r = node.xpath(_p)
        except Exception:
            _r = []
        if _r and isinstance(_r[0], str):
            _u = _norm(_r[0])
            if _u: return _u
    # 3) og:image / 背景图兜底
    for _p in ['.//meta[@property="og:image"]/@content', './/meta[@name="og:image"]/@content', './/div[contains(@class,"poster") or contains(@class,"cover")]/@style']:
        try:
            _r = node.xpath(_p)
        except Exception:
            _r = []
        if _r and isinstance(_r[0], str):
            _u = _norm(_r[0])
            if _u: return _u
    return ""

def extract_play(html, host, depth=0):
    m = re.search(r'(https?://[^\s\x22\x27]+\.m3u8[^\s\x22\x27]*)', html)
    if m: return m.group(1)
    m = re.search(r'(https?://[^\s\x22\x27]+\.mp4[^\s\x22\x27]*)', html)
    if m: return m.group(1)
    m = re.search(r'ENC2\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-+=/]+', html)
    if m: return "__ENC2__" + m.group(0)
    m = re.search(r'var\s*now\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'player_data\s*=\s*(\{.*?\})', html, re.DOTALL)
    if m:
        try: return json.loads(m.group(1)).get("url", "")
        except (OSError, ValueError, AttributeError, TypeError): m = None
    # 多 iframe 递归探测（部分站点用多个 iframe 嵌套播放器/广告页），限制递归深度避免死链
    if depth >= 5: return ""
    for _if in re.findall(r'<iframe[^>]+src=[\x22\x27]([^\x22\x27]+)[\x22\x27]', html):
        try:
            _t = requests.get(fix_url(_if, host), headers={"User-Agent":"Mozilla/5.0"}, timeout=10).text
            _r = extract_play(_t, host, depth + 1)
            if _r and _r.startswith("http"): return _r
        except Exception:
            pass
    m = re.search(r'eval\((.*?)\)', html, re.DOTALL)
    if m:
        _inner = m.group(1)
        _em = re.search(r'ENC2\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-+=/]+', _inner)
        if _em: return "__ENC2__" + _em.group(0)
        return "__JSJIAMI__" + _inner[:1024]
    m = re.search(r'videoSources\s*:\s*(\[.*?\])', html, re.DOTALL)
    if m:
        try: return json.loads(m.group(1))[0].get("file", "")
        except (OSError, ValueError, AttributeError, TypeError): m = None
    m = re.search(r'wvPlayer\.play\s*\(\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'location\.href\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'url\s*:\s*[\x22\x27]([^\x22\x27]+\.m3u8)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'var\s*playurl\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'var\s*player_aaaa\s*=\s*(\{.*?\})', html, re.DOTALL)
    if m:
        try: return json.loads(m.group(1)).get("url", "")
        except (OSError, ValueError, AttributeError, TypeError): m = None
    m = re.search(r'initPlayer\s*\(\s*[\x22\x27][^\x22\x27]*[\x22\x27]\s*,\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]\s*[,)]', html)
    if m: return m.group(1).replace(r'\/', '/')
    m = re.search(r'player\s*\.(?:config|setup)\(\s*[^)]*?source\s*:\s*[\x22\x27]([^\x22\x27]+\.m3u8)[\x22\x27]', html, re.DOTALL)
    if m: return m.group(1).replace(r'\/', '/')
    m = re.search(r'[\\\\\x22](?:src|source|file|vurl|v_url|url|playurl|play_url)[\\\\\x22]*\s*[:=]\s*[\\\\\x22]([^\\\\\x22]+\.(?:m3u8|mp4))[\\\\\x22]', html)
    if m: return m.group(1).replace(r'\/', '/')
    m = re.search(r'(?:episodeList|episodes|videoList)\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if m:
        try:
            _el = json.loads(m.group(1))
            for _ep in _el:
                _u = _ep.get("url") or _ep.get("src") or _ep.get("file") or ""
                if _u and ('.m3u8' in str(_u) or '.mp4' in str(_u)): return str(_u).replace(r'\/', '/')
        except (OSError, ValueError, AttributeError, TypeError): pass
    m = re.search(r'MacPlayerConfig\s*=\s*\{[^{}]*?\"url\"\s*:\s*\"([^\"]+)\"', html)
    if m: return m.group(1)
    m = re.search(r'new\s*DPlayer\(\{[^}]*?url\s*:\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'ckplayer\s*\([^)]*?[\x22\x27]([^\x22\x27]+\.(?:m3u8|mp4))[^\x22\x27]*[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'data-vid\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', html)
    if m: return m.group(1)
    m = re.search(r'<meta[^>]+property=[\x22\x27]og:video[\x22\x27][^>]+content=[\x22\x27]([^\x22\x27]+)[\x22\x27]', html, re.I)
    if m: return m.group(1)
    m = re.search(r'\"?(?:videoUrl|video_url|playUrl|play_url|url)\"?\s*[:=]\s*\"([^\x22\x27]+\.(?:m3u8|mp4|flv|mpd))\"', html)
    if m: return m.group(1)
    m = re.search(r'(https?://[^\s\x22\x27]+\.(?:m3u8|mp4|flv|mpd))', html)
    return m.group(1) if m else ""

def _dec_enc2(enc_str, enc_key="Mumu2026#"):
    import base64 as _b64
    if not isinstance(enc_str, str) or not enc_str.startswith("ENC2."):
        return enc_str
    _p = enc_str.split(".")
    if len(_p) != 3: return enc_str
    _iv, _blob = _p[1], _p[2]
    _s = _blob.replace(" ", "").replace("-", "+").replace("_", "/")
    _s += "=" * ((4 - len(_s) % 4) % 4)
    try:
        _ct = _b64.b64decode(_s)
    except (OSError, ValueError, AttributeError, TypeError):
        return enc_str
    _h = 2166136261
    for _b in (enc_key + "|" + _iv).encode("utf-8"):
        _h ^= _b
        _h = (_h * 16777619) & 0xFFFFFFFF
    _out = bytearray(len(_ct))
    _r = 0
    for _a in range(len(_ct)):
        if _a & 3 == 0:
            _h ^= (_h << 13) & 0xFFFFFFFF
            _h ^= (_h >> 17) & 0xFFFFFFFF
            _h ^= (_h << 5) & 0xFFFFFFFF
            _h &= 0xFFFFFFFF
            _r = _h
        _out[_a] = _ct[_a] ^ ((_r >> (8 * (_a & 3))) & 255)
    try:
        return _out.decode("utf-8", "replace")
    except (OSError, ValueError, AttributeError, TypeError):
        return ""

def _decode_jsjiami(cipher):
    _M = {"e":"P","w":"D","T":"y","+":"J","l":"!","t":"L","E":"E","@":"2","d":"a","b":"%","q":"l","X":"v","~":"R","5":"r","&":"X","C":"j","]":"F","a":")","^":"m",",":"~","}":"1","x":"C","c":"(","G":"@","h":"h",".":"*","L":"s","=":",","p":"g","I":"Q","1":"7","_":"u","K":"6","F":"t","2":"n","8":"=","k":"G","Z":"]",")":"b","P":"}","B":"U","S":"k","6":"i","g":":","N":"N","i":"S","%":"+","-":"Y","?":"|","4":"z","*":"-","3":"^","[":"{","(":"c","u":"B","y":"M","U":"Z","H":"[","z":"K","9":"H","7":"f","R":"x","v":"&","!":";","M":"_","Q":"9","Y":"e","o":"4","r":"A","m":".","O":"o","V":"W","J":"p","f":"d",":":"q","{":"8","W":"I","j":"?","n":"5","s":"3","|":"T","A":"V","D":"w",";":"O"}
    try:
        return "".join(_M.get(_ch, _ch) for _ch in cipher)
    except (OSError, ValueError, AttributeError, TypeError):
        return ""

def _auto_list_selectors(doc):
    if doc is None: return []
    try:
        from collections import Counter
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    _c = Counter()
    for _el in doc.iter():
        _tag = getattr(_el, "tag", None)
        if not isinstance(_tag, str): continue
        _href = _el.get("href", "")
        if _href and ("detail" in _href.lower() or "vod" in _href.lower() or "movie" in _href.lower() or "video" in _href.lower()):
            _cls = " ".join(_el.get("class", "").split())
            _c[(_tag, _cls)] += 1
    for (_tag, _cls), _n in _c.most_common(8):
        if _n < 2: break
        if _cls:
            _kw = ["item", "card", "video", "vod", "movie", "list", "post"]
            if any(_k in _cls.lower() for _k in _kw):
                return doc.xpath('//%s[contains(@class,"%s")]' % (_tag, _cls.split()[0]))
    return doc.xpath('//a[contains(@href,"detail") or contains(@href,"movie") or contains(@href,"vod") or contains(@href,"video")]')

def _auto_detail_panels(doc):
    if doc is None: return []
    _p = doc.xpath('//div[contains(@class,"play")]')
    if len(_p) >= 1: return _p
    return doc.xpath('//div[contains(@class,"tab")]')

def _auto_detail_title(doc):
    if doc is None: return ""
    for _p in ['//h1/text()', '//h2/text()', '//div[contains(@class,"title")]//h1/text()', '//div[contains(@class,"name")]/text()']:
        try:
            _r = doc.xpath(_p)
            if len(_r) > 0: return clean_text(_r[0])
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return ""

def _auto_detail_pic(doc):
    if doc is None: return ""
    for _p in ['//img[contains(@class,"poster")]/@src', '//img[contains(@class,"cover")]/@src', '//img[contains(@class,"pic")]/@src', '//img/@src']:
        try:
            _r = doc.xpath(_p)
            if len(_r) > 0: return _r[0]
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return ""


class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.host = "https://silidm.com"
        self.name = "ZheTianV4_nonstandard_video"
        self.s = requests.Session() if requests else None
        self.session = self.s
        self.ext = ""
        self.proxies = {}
        self.verify = False
        self.timeout = 15
        self.search_fallback = True
        self.search_fallback_pages = 1
        self.play_cache = {}
        self.media_cache = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/",
            "sec-ch-ua": "\x22Not_A Brand\x22;v=\x228\x22, \x22Chromium\x22;v=\x22120\x22"
        }
        self.cms_type = "nonstandard"
        self.content_type = "video"
        self.seen_ids = set()
        self.cookies = {}
        self._cf_cache = {}
        if self.s: self.s.headers.update(self.headers)

    def _parse_extend(self, extend):
        if isinstance(extend, dict): return dict(extend)
        text = str(extend or "").strip()
        if not text: return {}
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {"host": text} if text.startswith(("http://", "https://")) else {}

    def _as_bool(self, value, default=False):
        if isinstance(value, bool): return value
        if value is None: return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _set_proxy(self, proxy):
        p = str(proxy or "").strip()
        self.proxies = {"http": p, "https": p} if p.startswith(("http://", "https://")) else {}

    def setExtendInfo(self, extend):
        self.ext = extend or ""
        cfg = self._parse_extend(extend)
        host = str(cfg.get("host") or cfg.get("HOST") or "").strip().rstrip("/")
        if host.startswith(("http://", "https://")): self.host = host
        ua = str(cfg.get("userAgent") or cfg.get("User-Agent") or cfg.get("ua") or "").strip()
        if ua: self.headers["User-Agent"] = ua
        cookie = str(cfg.get("cookie") or cfg.get("Cookie") or "").strip()
        if cookie: self.headers["Cookie"] = cookie
        elif "Cookie" in self.headers: self.headers.pop("Cookie", None)
        referer = str(cfg.get("referer") or cfg.get("Referer") or "").strip()
        self.headers["Referer"] = referer if referer.startswith(("http://", "https://")) else self.host + "/"
        self.timeout = max(3, int(cfg.get("timeout", self.timeout) or self.timeout))
        self.verify = self._as_bool(cfg.get("verify"), False)
        self.search_fallback = self._as_bool(cfg.get("searchFallback"), True)
        self.search_fallback_pages = max(1, int(cfg.get("searchPages", 1) or 1))
        self._set_proxy(cfg.get("proxy"))
        if self.s: self.s.headers.update(self.headers)
        return None

    def init(self, extend=""):
        self.setExtendInfo(extend if extend else self.ext)
        return None

    def getDependence(self): return []
    def _get_scraper(self):
        if getattr(self, "_scraper", None) is None:
            self._scraper = None
            if cloudscraper is not None:
                try:
                    self._scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
                except Exception:
                    self._scraper = None
            if self._scraper is None and requests is not None:
                self._scraper = requests.Session()
                self._scraper.headers.update({"User-Agent": self.headers.get("User-Agent", "Mozilla/5.0")})
        return self._scraper
    def homeLayout(self): return 0
    def getHomeContent(self, filter=False): return self.homeContent(filter)
    def destroy(self):
        try:
            if self.s: self.s.close()
        except (OSError, AttributeError): pass

    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        value = str(url or "").lower()
        path = urlparse(value).path
        return any(x in path or x in value for x in [".m3u8", ".mp4", ".m4v", ".flv", ".webm", ".ts"])

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        _p = param if isinstance(param, dict) else {}
        _do = _p.get("do", "")
        url = unquote(_p.get("url", "")) if _p.get("url") else ""
        if not url:
            return [404, "text/plain", b""]
        # do=img / do=key：带 Referer 反防盗链代理（封面与加密 key）
        if _do in ("img", "key"):
            try:
                _h = dict(self.headers)
                _h["Referer"] = _p.get("referer", self.host + "/")
                _sess = self.s if self.s else requests
                _r = _sess.get(url, headers=_h, timeout=15)
                _ct = _r.headers.get("Content-Type", "application/octet-stream")
                return [200, _ct, _r.content, {"Access-Control-Allow-Origin": "*", "Content-Type": _ct}]
            except (OSError, ValueError, AttributeError, TypeError):
                return [404, "text/plain", b""]
        if ".m3u8" in url and self.s:
            try:
                raw = self.s.get(url, timeout=15).text
                cleaned = self._clean_m3u8(raw, url)
                return [200, "application/vnd.apple.mpegurl", cleaned.encode("utf-8"), {"Content-Type": "application/vnd.apple.mpegurl", "Access-Control-Allow-Origin": "*"}]
            except (OSError, ValueError, AttributeError, TypeError):
                return [404, "text/plain", b""]
        if any(x in url for x in [".jpg", ".png", ".webp", ".jpeg"]) and self.s:
            try:
                _r = self.s.get(url, headers={"Referer": self.host + "/", "User-Agent": self.headers.get("User-Agent", "Mozilla/5.0")}, timeout=15)
                return [200, "image/jpeg", _r.content]
            except (OSError, ValueError, AttributeError, TypeError):
                return [200, "image/gif", base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")]
        return [404, "text/plain", b""]

    def _request(self, url, method="GET", data=None, json_data=None, headers=None, referer="", retry=1, htmx=False, use_cffi=False):
        target = fix_url(str(url or ""), self.host)
        if not target: return None
        merged = dict(self.headers)
        if headers: merged.update(headers)
        if referer: merged["Referer"] = referer
        # 优先使用运行端(TVBox/dr_py/影视仓)注入的 fetch，适配 Android 代理与 CA 证书
        if method.upper() == "GET":
            _fetch = getattr(self, "fetch", None)
            if callable(_fetch):
                try:
                    _r = _fetch(target, headers=merged, timeout=self.timeout)
                    if _r is not None and getattr(_r, "text", ""):
                        try: _r.encoding = _r.apparent_encoding or "utf-8"
                        except Exception: pass
                        return _r
                except Exception as e:
                    print(f"[{self.name}] fetch 失败({target}): {e}")
        if not self.s and not use_cffi: return None
        if htmx:
            merged["HX-Request"] = "true"
            merged["HX-Target"] = "main"
            merged["HX-Current-URL"] = self.host + "/"
        for attempt in range(max(1, int(retry) + 1)):
            try:
                if use_cffi:
                    try: from curl_cffi import requests as _cffi
                    except ImportError:
                        print(f"[{self.name}] 未安装 curl_cffi（pip install curl_cffi），改用普通请求")
                        use_cffi = False
                    else:
                        resp = _cffi.request(method, target, data=data, json=json_data, headers=merged, timeout=self.timeout, impersonate="chrome", allow_redirects=True)
                        if resp.status_code < 500 or attempt >= int(retry): return resp
                        continue
                _sc = self._get_scraper() if not self.s or not hasattr(self.s, "request") else self.s
                if _sc is None: return None
                resp = _sc.request(method, target, data=data, json=json_data, headers=merged, timeout=self.timeout, verify=getattr(self, "verify", False), proxies=getattr(self, "proxies", None) or None, allow_redirects=True)
                if resp.status_code < 500 or attempt >= int(retry): return resp
            except (OSError, ValueError, AttributeError, TypeError) as e:
                if attempt >= int(retry):
                    print(f"[{self.name}] 请求失败: {target} - {e}")
                    return None
        return None

    def _looks_like_token(self, value):
        v = str(value or "").strip()
        return bool(re.match(r"^[A-Za-z0-9_-]{24,}$", v)) and not self._is_http(v)

    def _is_http(self, value):
        return str(value or "").strip().startswith(("http://", "https://"))

    def _media_headers(self, url=""):
        h = {"User-Agent": self.headers.get("User-Agent", "Mozilla/5.0"), "Referer": self.host + "/"}
        if "Cookie" in self.headers: h["Cookie"] = self.headers["Cookie"]
        return h

    def _page_headers(self, url=""):
        h = {"User-Agent": self.headers.get("User-Agent", "Mozilla/5.0"), "Referer": url or self.host + "/"}
        if "Cookie" in self.headers: h["Cookie"] = self.headers["Cookie"]
        if self.headers.get("Referer"): h["Referer"] = self.headers["Referer"]
        return h

    def _prep_play_id(self, value):
        """播放 ID 预处理：与 HKL 参考源一致，剥离头部拼接、协议简写与裸 token 尾部。"""
        v = str(value or "").strip()
        if "@Headers=" in v:
            v = v.split("@Headers=", 1)[0].strip()
        if "$" in v and not self._is_http(v) and not self._looks_like_token(v):
            v = v.rsplit("$", 1)[-1].strip()
        if v.startswith("//"):
            v = "https:" + v
        if not v.startswith("/") and "." in v.split("?",1)[0] and not v.startswith("http") and not self._looks_like_token(v):
            pass
        return v

    def _fetch(self, url):
        if not self.s: return ""
        try:
            _h = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc
            _ck = self._cf_cache.get(_h)
            if _ck: self.s.cookies.set("cf_clearance", _ck, domain=_h)
        except Exception: pass
        r = self._request(url, referer=self.host + "/", retry=1)
        if r is None: return ""
        if r.encoding is None or str(r.encoding).lower() in ("iso-8859-1", "ascii"):
            try: r.encoding = r.apparent_encoding or "utf-8"
            except (OSError, ValueError, AttributeError): r.encoding = "utf-8"
        txt = r.text
        if r.status_code in (403, 503, 429) and self._is_cf_challenge(txt):
            print(f"[{self.name}] 检测到反爬挑战，自动处理")
            b = self._cf_bypass(url)
            if b: txt = b
            try:
                _h = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc
                _cc = self.cookies.get("cf_clearance")
                if _cc: self._cf_cache[_h] = _cc
            except Exception: pass
        return txt

    def _is_cf_challenge(self, html):
        if not html: return False
        h = html.lower()
        return ("cf-browser-verification" in h or "__cf_bm" in h or
                "just a moment" in h or "checking your browser" in h or
                "challenge-platform" in h or "cf-chl" in h)

    def _cf_bypass(self, url):
        import requests as _rq
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        try:
            import cloudscraper
            sc = cloudscraper.create_scraper(delay=12, browser={'browser':'chrome','platform':'windows','desktop':True})
            sc.headers.update({'User-Agent': ua})
            r = sc.get(url, timeout=15)
            if r.ok:
                self.cookies.update(dict(r.cookies))
                if self.s: self.s.cookies.update(dict(r.cookies))
                _cc = dict(r.cookies).get("cf_clearance")
                if _cc:
                    try: self._cf_cache[__import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc] = _cc
                    except Exception: pass
                return r.text
        except Exception: pass
        try:
            from curl_cffi import requests as cffi
            r = cffi.get(url, impersonate='chrome', timeout=15, headers={'User-Agent': ua})
            if r.status_code == 200:
                self.cookies.update({k:v for k,v in r.cookies.items()})
                if self.s: self.s.cookies.update({k:v for k,v in r.cookies.items()})
                _cc = (dict(r.cookies) if hasattr(r.cookies, "items") else {}).get("cf_clearance")
                if _cc:
                    try: self._cf_cache[__import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc] = _cc
                    except Exception: pass
                return r.text
        except Exception: pass
        try:
            r = _rq.get(url, headers={'User-Agent': ua}, timeout=15, verify=False)
            self.cookies.update(dict(r.cookies))
            if self.s: self.s.cookies.update(dict(r.cookies))
            return r.text
        except Exception:
            return ""

    def _clean_m3u8(self, raw, m3u8_url):
        if not raw: return ""
        if "#EXT-X-STREAM-INF" in raw:
            out = []
            for line in raw.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(urljoin(m3u8_url, line))
                else:
                    out.append(line)
            return chr(10).join(out) + chr(10)
        lines_raw = [x.strip() for x in raw.replace(chr(13), "").split(chr(10)) if x.strip()]
        segs, header, tail = [], [], []
        pending, started = [], False
        for line in lines_raw:
            if line.startswith("#EXTINF"):
                started = True
                dur = 3.0
                import re as _re
                m = _re.search(r"#EXTINF:\s*([\d.]+)", line)
                if m: dur = float(m.group(1))
                segs.append({"tags": pending + [line], "dur": dur, "uri": ""})
                pending = []
            elif line.startswith("#EXT-X-ENDLIST"):
                tail.append(line)
            elif line.startswith("#"):
                if not started: header.append(line)
                else: pending.append(line)
            else:
                if segs: segs[-1]["uri"] = line
                pending = []
        if not segs: return raw
        ad_kw = ["ad", "ads", "advert", "sponsor", "gg", "promo", "commercial"]
        stat = {}
        for seg in segs:
            p = urlparse(urljoin(m3u8_url, seg.get("uri","")))
            key = (p.netloc.lower(), p.path.lower().rsplit("/",1)[0])
            stat[key] = stat.get(key, 0.0) + seg["dur"]
        main_key = max(stat.items(), key=lambda x: x[1])[0] if stat else ("","")
        cleaned = []
        for idx, seg in enumerate(segs):
            uri = seg.get("uri","")
            p = urlparse(urljoin(m3u8_url, uri))
            key = (p.netloc.lower(), p.path.lower().rsplit("/",1)[0])
            is_ad = any(w in uri.lower() for w in ad_kw)
            if not is_ad and idx < 12 and stat.get(key, 0) <= 90 and key != main_key:
                is_ad = True
            if not is_ad:
                cleaned.extend(seg.get("tags",[]))
                cleaned.append(urljoin(m3u8_url, uri))
        if not cleaned: cleaned = [seg.get("tags",[None])[0] for seg in segs if seg.get("tags")]
        def _abs_uri(line):
            if line.startswith("#EXT-X-KEY") or line.startswith("#EXT-X-MEDIA"):
                _m = re.search(r'URI="([^"]+)"', line)
                if _m and not _m.group(1).startswith("http"):
                    _abs = urljoin(m3u8_url, _m.group(1))
                    line = line.replace('URI="' + _m.group(1) + '"', 'URI="' + _abs + '"')
            return line
        header = [_abs_uri(h) for h in header]
        result = []
        if not any(h.startswith("#EXTM3U") for h in header): result.append("#EXTM3U")
        result.extend(header + cleaned + tail)
        return chr(10).join(result) + chr(10)

    def homeContent(self, filter):
        try:
            classes = [
                {"type_name": "电影", "type_id": "dy"},
                {"type_name": "剧集", "type_id": "juji"},
                {"type_name": "动漫", "type_id": "dongman"},
                {"type_name": "综艺", "type_id": "zongyi"},
            ]
            # 完整筛选体系: 地区/语言/类型/字母/年份/排序
            filters = {
                "dy": [
                    {"key": "area", "name": "地区", "value": [{"n":"全部","v":""},{"n":"大陆","v":"大陆"},{"n":"日本","v":"日本"},{"n":"美国","v":"美国"},{"n":"香港","v":"香港"},{"n":"台湾","v":"台湾"},{"n":"韩国","v":"韩国"},{"n":"英国","v":"英国"},{"n":"法国","v":"法国"},{"n":"德国","v":"德国"},{"n":"泰国","v":"泰国"},{"n":"印度","v":"印度"},{"n":"意大利","v":"意大利"},{"n":"加拿大","v":"加拿大"},{"n":"西班牙","v":"西班牙"},{"n":"其他","v":"其他"}]},
                    {"key": "lang", "name": "语言", "value": [{"n":"全部","v":""},{"n":"国语","v":"国语"},{"n":"日语","v":"日语"},{"n":"粤语","v":"粤语"},{"n":"英语","v":"英语"},{"n":"法语","v":"法语"},{"n":"德语","v":"德语"},{"n":"韩语","v":"韩语"},{"n":"普通话","v":"普通话"},{"n":"其他","v":"其他"}]},
                    {"key": "genre", "name": "类型", "value": [{"n":"全部","v":""},{"n":"剧情","v":"剧情"},{"n":"喜剧","v":"喜剧"},{"n":"动作","v":"动作"},{"n":"爱情","v":"爱情"},{"n":"科幻","v":"科幻"},{"n":"恐怖","v":"恐怖"},{"n":"战争","v":"战争"}]},
                    {"key": "letter", "name": "字母", "value": [{"n":"全部","v":""},{"n":"A","v":"A"},{"n":"B","v":"B"},{"n":"C","v":"C"},{"n":"D","v":"D"},{"n":"E","v":"E"},{"n":"F","v":"F"},{"n":"G","v":"G"},{"n":"H","v":"H"},{"n":"I","v":"I"},{"n":"J","v":"J"},{"n":"K","v":"K"},{"n":"L","v":"L"},{"n":"M","v":"M"},{"n":"N","v":"N"},{"n":"O","v":"O"},{"n":"P","v":"P"},{"n":"Q","v":"Q"},{"n":"R","v":"R"},{"n":"S","v":"S"},{"n":"T","v":"T"},{"n":"U","v":"U"},{"n":"V","v":"V"},{"n":"W","v":"W"},{"n":"X","v":"X"},{"n":"Y","v":"Y"},{"n":"Z","v":"Z"},{"n":"0-9","v":"0-9"}]},
                    {"key": "year", "name": "年份", "value": [{"n":"全部","v":""},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"2014","v":"2014"},{"n":"2013","v":"2013"},{"n":"2012","v":"2012"}]},
                    {"key": "by", "name": "排序", "value": [{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]},
                ],
                "juji": [
                    {"key": "area", "name": "地区", "value": [{"n":"全部","v":""},{"n":"大陆","v":"大陆"},{"n":"日本","v":"日本"},{"n":"美国","v":"美国"},{"n":"香港","v":"香港"},{"n":"台湾","v":"台湾"},{"n":"韩国","v":"韩国"},{"n":"英国","v":"英国"},{"n":"法国","v":"法国"},{"n":"德国","v":"德国"},{"n":"泰国","v":"泰国"},{"n":"印度","v":"印度"},{"n":"意大利","v":"意大利"},{"n":"加拿大","v":"加拿大"},{"n":"西班牙","v":"西班牙"},{"n":"其他","v":"其他"}]},
                    {"key": "lang", "name": "语言", "value": [{"n":"全部","v":""},{"n":"国语","v":"国语"},{"n":"日语","v":"日语"},{"n":"粤语","v":"粤语"},{"n":"英语","v":"英语"},{"n":"法语","v":"法语"},{"n":"德语","v":"德语"},{"n":"韩语","v":"韩语"},{"n":"普通话","v":"普通话"},{"n":"其他","v":"其他"}]},
                    {"key": "genre", "name": "类型", "value": [{"n":"全部","v":""},{"n":"剧情","v":"剧情"},{"n":"喜剧","v":"喜剧"},{"n":"动作","v":"动作"},{"n":"爱情","v":"爱情"},{"n":"科幻","v":"科幻"},{"n":"恐怖","v":"恐怖"},{"n":"战争","v":"战争"}]},
                    {"key": "letter", "name": "字母", "value": [{"n":"全部","v":""},{"n":"A","v":"A"},{"n":"B","v":"B"},{"n":"C","v":"C"},{"n":"D","v":"D"},{"n":"E","v":"E"},{"n":"F","v":"F"},{"n":"G","v":"G"},{"n":"H","v":"H"},{"n":"I","v":"I"},{"n":"J","v":"J"},{"n":"K","v":"K"},{"n":"L","v":"L"},{"n":"M","v":"M"},{"n":"N","v":"N"},{"n":"O","v":"O"},{"n":"P","v":"P"},{"n":"Q","v":"Q"},{"n":"R","v":"R"},{"n":"S","v":"S"},{"n":"T","v":"T"},{"n":"U","v":"U"},{"n":"V","v":"V"},{"n":"W","v":"W"},{"n":"X","v":"X"},{"n":"Y","v":"Y"},{"n":"Z","v":"Z"},{"n":"0-9","v":"0-9"}]},
                    {"key": "year", "name": "年份", "value": [{"n":"全部","v":""},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"},{"n":"2017","v":"2017"},{"n":"2016","v":"2016"},{"n":"2015","v":"2015"},{"n":"2014","v":"2014"},{"n":"2013","v":"2013"},{"n":"2012","v":"2012"}]},
                    {"key": "by", "name": "排序", "value": [{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]},
                ],
                "dongman": [
                    {"key": "area", "name": "地区", "value": [{"n":"全部","v":""},{"n":"大陆","v":"大陆"},{"n":"日本","v":"日本"},{"n":"美国","v":"美国"},{"n":"其他","v":"其他"}]},
                    {"key": "lang", "name": "语言", "value": [{"n":"全部","v":""},{"n":"日语","v":"日语"},{"n":"国语","v":"国语"},{"n":"英语","v":"英语"},{"n":"其他","v":"其他"}]},
                    {"key": "genre", "name": "类型", "value": [{"n":"全部","v":""},{"n":"剧情","v":"剧情"},{"n":"喜剧","v":"喜剧"},{"n":"动作","v":"动作"},{"n":"科幻","v":"科幻"},{"n":"奇幻","v":"奇幻"}]},
                    {"key": "letter", "name": "字母", "value": [{"n":"全部","v":""},{"n":"A","v":"A"},{"n":"B","v":"B"},{"n":"C","v":"C"},{"n":"D","v":"D"},{"n":"E","v":"E"},{"n":"F","v":"F"},{"n":"G","v":"G"},{"n":"H","v":"H"},{"n":"I","v":"I"},{"n":"J","v":"J"},{"n":"K","v":"K"},{"n":"L","v":"L"},{"n":"M","v":"M"},{"n":"N","v":"N"},{"n":"O","v":"O"},{"n":"P","v":"P"},{"n":"Q","v":"Q"},{"n":"R","v":"R"},{"n":"S","v":"S"},{"n":"T","v":"T"},{"n":"U","v":"U"},{"n":"V","v":"V"},{"n":"W","v":"W"},{"n":"X","v":"X"},{"n":"Y","v":"Y"},{"n":"Z","v":"Z"},{"n":"0-9","v":"0-9"}]},
                    {"key": "year", "name": "年份", "value": [{"n":"全部","v":""},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"},{"n":"2019","v":"2019"},{"n":"2018","v":"2018"}]},
                    {"key": "by", "name": "排序", "value": [{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]},
                ],
                "zongyi": [
                    {"key": "area", "name": "地区", "value": [{"n":"全部","v":""},{"n":"大陆","v":"大陆"},{"n":"香港","v":"香港"},{"n":"美国","v":"美国"},{"n":"韩国","v":"韩国"},{"n":"其他","v":"其他"}]},
                    {"key": "lang", "name": "语言", "value": [{"n":"全部","v":""},{"n":"国语","v":"国语"},{"n":"粤语","v":"粤语"},{"n":"英语","v":"英语"},{"n":"韩语","v":"韩语"},{"n":"其他","v":"其他"}]},
                    {"key": "genre", "name": "类型", "value": [{"n":"全部","v":""},{"n":"真人秀","v":"真人秀"},{"n":"脱口秀","v":"脱口秀"},{"n":"歌舞","v":"歌舞"},{"n":"竞演","v":"竞演"}]},
                    {"key": "letter", "name": "字母", "value": [{"n":"全部","v":""},{"n":"A","v":"A"},{"n":"B","v":"B"},{"n":"C","v":"C"},{"n":"D","v":"D"},{"n":"E","v":"E"},{"n":"F","v":"F"},{"n":"G","v":"G"},{"n":"H","v":"H"},{"n":"I","v":"I"},{"n":"J","v":"J"},{"n":"K","v":"K"},{"n":"L","v":"L"},{"n":"M","v":"M"},{"n":"N","v":"N"},{"n":"O","v":"O"},{"n":"P","v":"P"},{"n":"Q","v":"Q"},{"n":"R","v":"R"},{"n":"S","v":"S"},{"n":"T","v":"T"},{"n":"U","v":"U"},{"n":"V","v":"V"},{"n":"W","v":"W"},{"n":"X","v":"X"},{"n":"Y","v":"Y"},{"n":"Z","v":"Z"},{"n":"0-9","v":"0-9"}]},
                    {"key": "year", "name": "年份", "value": [{"n":"全部","v":""},{"n":"2024","v":"2024"},{"n":"2023","v":"2023"},{"n":"2022","v":"2022"},{"n":"2021","v":"2021"},{"n":"2020","v":"2020"}]},
                    {"key": "by", "name": "排序", "value": [{"n":"时间","v":"time"},{"n":"人气","v":"hits"},{"n":"评分","v":"score"}]},
                ],
            }
            return {"class": classes, "filters": filters}
        except (OSError, ValueError, AttributeError, TypeError) as e:
            print(f"[{self.name}] 首页失败: {e}")
            return {"class": [], "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("dy", "1", False, {})

    def categoryContent(self, tid, pg, filter, extend):
        page = _page(pg)
        try:
            result = {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}
            url = f"{self.host}/type/{tid}.html-{page}.html" if page > 1 else f"{self.host}/type/{tid}.html"
            html_text = self._fetch(url)
            if not html_text: return result
            doc = etree.HTML(html_text) if etree else None
            if doc is None: return result
            items = doc.xpath('//div[contains(@class,"module-item")]')
            print(f"[{self.name}] 分类列表匹配到 {len(items)} 个视频")
            self.seen_ids.clear()
            for item in items:
                try:
                    # 提取所有video链接
                    video_links = item.xpath('.//a[contains(@href,"/video/")]')
                    if not video_links: continue
                    # 取第一个video链接作为主链接
                    main_link = video_links[0]
                    href = main_link.xpath('./@href')[0]
                    title = main_link.xpath('./@title')[0] if main_link.xpath('./@title') else ""
                    if not title:
                        title_text = main_link.xpath('./text()')
                        title = clean_text(title_text[0]) if title_text else ""
                    title = clean_text(title)
                    vid_match = re.search(r'/video/(\d+)', href)
                    vid = vid_match.group(1) if vid_match else ""
                    if not vid: continue
                    if vid in self.seen_ids: continue
                    self.seen_ids.add(vid)
                    # 提取图片 (在 module-item-cover 中)
                    covers = item.xpath('.//div[contains(@class,"module-item-cover")]')
                    cover = covers[0] if covers else None
                    pic = ""
                    if cover:
                        pic_nodes = cover.xpath('.//img/@data-src | .//img/@src')
                        pic = pic_nodes[0] if pic_nodes else ""
                    if pic and not pic.startswith("http"):
                        pic = self.host + pic
                    result["list"].append({"vod_id": vid, "vod_name": title, "vod_pic": pic})
                except (OSError, ValueError, AttributeError, TypeError) as e:
                    print(f"[{self.name}] 单条解析失败: {e}")
                    continue
            # 提取分页
            pc = doc.xpath('//div[contains(@class,"pagination")]//a[last()-1]/text()')
            if pc:
                try: result["pagecount"] = int(pc[0].strip())
                except: pass
            return result
        except (OSError, ValueError, AttributeError, TypeError) as e:
            print(f"[{self.name}] 分类爬取失败: {e}")
            return {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}

    def detailContent(self, ids):
        raw_ids = ids if isinstance(ids, (list, tuple)) else [ids]
        vid = str(raw_ids[0] if raw_ids else "").strip()
        if not vid: return {"list": []}
        try:
            result = {"list": []}
            url = f"{self.host}/video/{vid}.html"
            html_text = self._fetch(url)
            if not html_text: return result
            doc = etree.HTML(html_text) if etree else None
            title = ""
            pic = ""
            if doc is not None:
                title_nodes = doc.xpath('//h1//text()')
                title = clean_text(title_nodes[0]) if title_nodes else ""
                if not title:
                    title_node = doc.xpath('//h1/a/text()')
                    title = clean_text(title_node[0]) if title_node else ""
                pic_nodes = doc.xpath('//img[@alt]/@src | //img[contains(@class,"lazy")]/@data-src | //img[contains(@class,"lazy")]/@src')
                pic = pic_nodes[0] if pic_nodes else ""
                if pic and not pic.startswith("http"):
                    pic = self.host + pic
            # 提取播放源和剧集 - 直接从页面找所有 /play/ 链接
            sources = []
            play_urls = []
            if doc is not None:
                # 按 play-source-content 分组提取
                containers = doc.xpath('//div[contains(@class,"play-source-content")]')
                if len(containers) > 0:
                    for i, container in enumerate(containers):
                        try:
                            sname = f"线路{i+1}"
                            eps = container.xpath('.//a[contains(@href,"/play/")]')
                            ep_list = []
                            for ep in eps:
                                try:
                                    ep_href = ep.xpath('./@href')[0] if len(ep.xpath('./@href')) else ""
                                    ep_title = ep.xpath('./text()')[0].strip() if len(ep.xpath('./text()')) else ""
                                    if not ep_title:
                                        ep_title = re.search(r'第(\d+)集', ep.text_content())
                                        ep_title = f"第{ep_title.group(1)}集" if ep_title else f"第{len(ep_list)+1}集"
                                    if not ep_href.startswith("http"):
                                        ep_href = self.host + ep_href if ep_href.startswith("/") else ep_href
                                    ep_list.append(f"{clean_text(ep_title)}${ep_href}")
                                except Exception:
                                    continue
                            if len(ep_list) > 0:
                                sources.append(sname)
                                play_urls.append("#".join(ep_list))
                        except Exception as e:
                            print(f"[{self.name}] 播放源解析失败: {e}")
                            continue
                # fallback: 提取所有 play 链接
                if len(sources) == 0:
                    all_plays = doc.xpath('//a[contains(@href,"/play/")]')
                    if len(all_plays) > 0:
                        ep_list = []
                        for ep in all_plays[:50]:
                            try:
                                ep_href = ep.xpath('./@href')[0] if len(ep.xpath('./@href')) else ""
                                ep_title = ep.xpath('./text()')[0].strip() if len(ep.xpath('./text()')) else ""
                                if not ep_title:
                                    ep_title = re.search(r'第(\d+)集', ep.text_content())
                                    ep_title = f"第{ep_title.group(1)}集" if ep_title else "播放"
                                if not ep_href.startswith("http"):
                                    ep_href = self.host + ep_href if ep_href.startswith("/") else ep_href
                                ep_list.append(f"{ep_title}${ep_href}")
                            except Exception:
                                continue
                        if len(ep_list) > 0:
                            sources.append("默认")
                            play_urls.append("#".join(ep_list))
            print(f"[{self.name}] 详情页提取到 {len(sources)} 个播放源")
            result["list"].append({
                "vod_id": vid, "vod_name": title, "vod_pic": pic,
                "vod_play_from": "$$$".join(sources) if sources else "默认",
                "vod_play_url": "$$$".join(play_urls) if play_urls else f"播放${vid}"
            })
            if result["list"] and sources:
                _safe = []
                for item in result["list"][0]["vod_play_url"].split("$$$"):
                    if len(item) >= 5:
                        _safe.append(item)
                if _safe:
                    result["list"][0]["vod_play_url"] = "$$$".join(_safe)
            return result
        except (OSError, ValueError, AttributeError, TypeError) as e:
            print(f"[{self.name}] 详情解析失败: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            result = {"parse": 0, "playUrl": "", "url": "", "header": ""}
            pid = self._prep_play_id(id)
            if self.isVideoFormat(pid):
                result["url"] = pid
                result["header"] = self._media_headers(pid)
                print(f"[{self.name}] 播放解析: {flag} -> {pid[:50]}...")
                return result
            if isinstance(pid, str) and pid.startswith("ENC2."):
                _dec = _dec_enc2(pid)
                if _dec and _dec.startswith("http"):
                    result["url"] = _dec
                    result["header"] = self._media_headers(_dec)
                    print(f"[{self.name}] 播放解析(ENC2): {flag} -> {_dec[:50]}...")
                    return result
            html_text = self._fetch(pid) if (isinstance(pid, str) and pid.startswith("http")) else ""
            if html_text:
                # 尝试提取 player_aaaa JSON
                pa_match = re.search(r'var\s+player_aaaa\s*=\s*(\{[^;]+\})', html_text)
                if pa_match:
                    try:
                        pa_data = json.loads(pa_match.group(1).replace('\\/', '/'))
                        url = pa_data.get('url', '')
                        if url and url.startswith('http'):
                            result["url"] = url
                            result["header"] = self._media_headers(url)
                            print(f"[{self.name}] 播放解析(player_aaaa): {flag} -> {url[:50]}...")
                            return result
                    except Exception as e:
                        print(f"[{self.name}] player_aaaa 解析失败: {e}")
                # 尝试通用提取
                play_url = extract_play(html_text, self.host)
                if play_url:
                    if play_url.startswith("__ENC2__"):
                        play_url = _dec_enc2(play_url[8:])
                    elif play_url.startswith("__JSJIAMI__"):
                        play_url = _decode_jsjiami(play_url[11:])
                    if play_url and play_url.startswith("http"):
                        result["url"] = play_url
                        result["header"] = self._media_headers(play_url)
                        print(f"[{self.name}] 播放解析(解密): {flag} -> {play_url[:50]}...")
                        return result
            result["url"] = pid
            return result
        except (OSError, ValueError, AttributeError, TypeError) as e:
            print(f"[{self.name}] 播放解析失败: {e}")
            return {"parse": 0, "playUrl": "", "url": pid if isinstance(pid, str) else id, "header": ""}

    def searchContent(self, key, quick, pg="1"):
        page = _page(pg)
        try:
            result = {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}
            url = f"{self.host}/search/-------------.html?wd={quote(key)}&page={page}"
            html_text = self._fetch(url)
            if not html_text: return result
            doc = etree.HTML(html_text) if etree else None
            if doc is None: return result
            items = []
            items = doc.xpath('//a[contains(@href,"/video/") and @title]')
            print(f"[{self.name}] 搜索匹配到 {len(items)} 个结果")
            self.seen_ids.clear()
            for item in items:
                try:
                    href = item.xpath('./@href')[0] if item.xpath('./@href') else ""
                    title = item.xpath('./@title')[0] if item.xpath('./@title') else ""
                    title = clean_text(title)
                    vid_match = re.search(r'/video/(\d+)', href)
                    vid = vid_match.group(1) if vid_match else ""
                    if not vid: continue
                    if vid in self.seen_ids: continue
                    self.seen_ids.add(vid)
                    # 提取图片 (使用 extract_pic 并向上查找)
                    pic = ""
                    node = item
                    for _ in range(5):
                        pic = extract_pic(node, self.host)
                        if pic: break
                        parent = node.getparent()
                        if parent is None: break
                        node = parent
                    result["list"].append({"vod_id": vid, "vod_name": title, "vod_pic": pic})
                except (OSError, ValueError, AttributeError, TypeError) as e:
                    print(f"[{self.name}] 搜索单条失败: {e}")
                    continue
            return result
        except (OSError, ValueError, AttributeError, TypeError) as e:
            print(f"[{self.name}] 搜索失败: {e}")
            return {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}

    def _cf_request(self, method, url, data=None, json=None, headers=None, timeout=15, verify=False, retry=2):
        if not self.s:
            class _R: text = ""; status_code = 0
            return _R()
        try:
            _h = urlparse(url).netloc
        except Exception:
            _h = ""
        _ck = self._cf_cache.get(_h)
        if _ck:
            try: self.s.cookies.set("cf_clearance", _ck, domain=_h)
            except Exception: pass
        _hd = dict(self.headers)
        if headers: _hd.update(headers)
        if not _hd.get("User-Agent"):
            _hd["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        _kw = {"timeout": timeout, "headers": _hd, "verify": verify}
        if data is not None: _kw["data"] = data
        if json is not None: _kw["json"] = json
        try:
            resp = self.s.request(method.upper(), url, **_kw)
        except Exception as e:
            print(f"[{self.name}] 请求异常 {url}: {e}")
            class _R: text = ""; status_code = 0
            return _R()
        if resp.status_code in (403, 503, 429) and self._is_cf_challenge(resp.text):
            print(f"[{self.name}] 检测到反爬挑战，自动处理: {url}")
            for _ in range(max(1, retry)):
                b = self._cf_bypass(url)
                if b:
                    try:
                        _hh = urlparse(url).netloc
                        _cc = self.cookies.get("cf_clearance")
                        if _cc: self._cf_cache[_hh] = _cc
                    except Exception: pass
                    try: resp = self.s.request(method.upper(), url, **_kw)
                    except Exception: pass
                    if not (resp.status_code in (403, 503, 429) and self._is_cf_challenge(resp.text)):
                        break
        return resp

    def cf_get(self, url, headers=None, timeout=15, verify=False):
        return self._cf_request("GET", url, headers=headers, timeout=timeout, verify=verify).text

    def cf_post(self, url, data=None, json=None, headers=None, timeout=15, verify=False):
        return self._cf_request("POST", url, data=data, json=json, headers=headers, timeout=timeout, verify=verify).text


# ═══ 直接调用入口：不依赖影视框架，单独运行本文件也能爬 ═══
try:
    _spider = Spider()
except Exception:
    _spider = None

def cf_fetch(url, headers=None, timeout=15, verify=False):
    """直接调用：GET 并自动绕过 Cloudflare，返回页面文本。"""
    if _spider is None: return ""
    return _spider.cf_get(url, headers=headers, timeout=timeout, verify=verify)

def cf_post(url, data=None, json=None, headers=None, timeout=15, verify=False):
    """直接调用：POST 并自动绕过 Cloudflare，返回响应文本。"""
    if _spider is None: return ""
    return _spider.cf_post(url, data=data, json=json, headers=headers, timeout=timeout, verify=verify)

def cf_request(method, url, data=None, json=None, headers=None, timeout=15, verify=False, retry=2):
    """直接调用：任意方法(GET/POST/...)请求，自动绕过 Cloudflare，返回 response 对象。"""
    if _spider is None: return None
    return _spider._cf_request(method, url, data=data, json=json, headers=headers, timeout=timeout, verify=verify, retry=retry)

def cf_clear_cache():
    """清空已缓存的 Cloudflare 绕过凭证（cf_clearance 过期时调用）。"""
    if _spider is not None: _spider._cf_cache.clear()
