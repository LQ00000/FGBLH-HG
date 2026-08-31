#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
# 一起看 yqk Spider（含广告清洗 + iOS appId 默认超清1080）
# 站点：https://yqk88.app / https://yqk.app
# 技术栈：Nuxt3 H5 + Flutter APP，两端同 API、同签名。
#   H5 域池: /js/baseUrlList.js   |   APP 域池: 远端 config.json（gp619.*/cos 等）
# 签名(MD5)：参数并入 appId/reqDomain/deviceInfo/version/requestId(32随机)/
#             cus1tom=aabbcc/udid(uuid-ts_hex) → key升序 → 拼'k=v&'(跳过空值)
#             → 尾接 appKey=<key> → md5 → sign。POST application/json。
# appId 双套：H5(720标清) | iOS/APP(默认解锁1080超清,playUrl 直返)
# 无会员墙：guestCanWatchCount=-1，直链明文 m3u8，无需登录。
# 广告清洗：剔 all Ad容器(adAction∈{2,3,7,9}/adImgType=2/startAd)、引导块、
#            外部actionContent；只保留 adAction=4(进详情)的真实剧集。
# 安装：放进 TVBox/影视仓/OK影视 的 py 源目录。
# =====================================================================
_DEBUG = False

try:
    from base.spider import Spider as _BaseSpider
    _HAS_BASE = True
except Exception:
    _HAS_BASE = False

import json, re, time, uuid, hashlib, random, string as _string
try:
    import requests as _requests
except Exception:
    _requests = None
import urllib.request, urllib.error

# ---------------- 常量 ----------------
VERSION = "1.2.7.164"
# 默认用 APP(iOS) appId 解锁 1080 超清；若想退回 720 可改 _APP_ID 为 H5 套件
_APP_ID = "4be6d572f00e45efaf3df65519e8bc64"
_APP_KEY = "30fc1106e60e4390a5bd56c5cc8f9e72"
_H5_APP_ID = "e6ddefe09e0349739874563459f56c54"
_H5_APP_KEY = "3359de478f8d45638125e446a10ec541"

# H5 域池（备用，随时轮询）
_H5_DOMAINS = [
    "https://yz260324.bzy42ezt.com",
    "https://yz250907.zazy3mc5.com",
    "https://yz250907.7k5jb8t9.com",
    "https://yz250907.3nyk7h9o.com",
    "https://yz1018.o5r52at9v.com",
]
# APP 域池（config.json 下发，缓存 + 兜底）
_APP_DOMAIN_LIST = [
    "https://yz260605.z5fl9630.com",
    "https://yz260324.z2g1uoqy.com",
    "https://yz260324.c628uthq.com",
    "https://yz260324.nv153kfl.com",
    "https://cfvip.eiq9rzoe.com",
    "https://yz260605.jpknq5ju.com",
]
_DOMAIN_CFG = [
    "https://gp619.y5imabr.com/config.json",
    "https://gp619.xat548o.com/config.json",
    "https://gp619.js4iotn.com/config.json",
]

# ---------------- 全局状态 ----------------
_UDID = None
_g_apipool = []        # 有序 API 域
_g_domain_idx = 0      # 当前轮询游标
_g_init_done = False
_g_env = {}            # extend 注入

def _log(*a):
    if _DEBUG:
        print("[yqk]", *a)

def _rnd32():
    return "".join(random.choice(_string.digits + _string.ascii_letters) for _ in range(32))

def _mkudid():
    return "%s-%s" % (uuid.uuid4(), format(int(time.time() * 1000), "x"))

def _load_domain_cfg():
    """拉远端 config.json 刷新 APP 域池，失败静默用缓存"""
    got = None
    for u in _DOMAIN_CFG:
        try:
            if _requests is not None:
                r = _requests.get(u, timeout=8)
                got = r.json() if r.status_code == 200 else None
            else:
                with urllib.request.urlopen(urllib.request.Request(u), timeout=8) as r:
                    got = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(got, list):
                return [x for x in got if x.startswith("http")]
        except Exception:
            continue
    return None

def _build_pool():
    global _g_apipool
    pool = []
    dync = _load_domain_cfg()
    if dync:
        pool = list(dync)
    pool += [x for x in (_APP_DOMAIN_LIST + _H5_DOMAINS) if x not in pool]
    # 去重保序
    seen, out = set(), []
    for x in pool:
        if x not in seen:
            seen.add(x); out.append(x)
    _g_apipool = out
    _log("域池", len(out), out[:3], "…")

def _sign(path, data, domain):
    global _UDID
    if _UDID is None:
        _UDID = _mkudid()
    d = dict(data)
    d["udid"] = _UDID
    try:
        reqdom = domain.split("//")[1].split("/")[0]
    except Exception:
        reqdom = "yqk.app"
    d.update({
        "appId": _APP_ID,
        "reqDomain": reqdom,
        "deviceInfo": "Android",
        "version": VERSION,
        "requestId": _rnd32(),
        "cus1tom": "aabbcc",
    })
    d = {k: d[k] for k in sorted(d)}
    raw = "".join("%s=%s&" % (k, v) for k, v in d.items() if str(v) != "")
    raw += "appKey=" + _APP_KEY
    d["sign"] = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return d

def _http_post(domain, path, body_dict, timeout=18):
    """单域 POST JSON，返回 (json, err)"""
    payload = _sign(path, body_dict, domain)
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) yqk/%s" % VERSION,
        "Referer": "https://yqk.app/",
        "Accept-Encoding": "gzip",
    }
    try:
        if _requests is not None:
            r = _requests.post(domain + path, data=data, headers=headers, timeout=timeout)
            try:
                return r.json(), None
            except Exception:
                return {"result": False}, "bad-json"
        req = urllib.request.Request(domain + path, data=data, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip as _gzip
                raw = _gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace")), None
    except Exception as e:
        return {"result": False}, repr(e)

def _api(path, data):
    """跨域轮询+重试，返回 data 或 None。快失败+可用域优先。"""
    global _g_domain_idx
    if not _g_apipool:
        _build_pool()
    n = len(_g_apipool)
    tried = []
    for t in range(n):
        dom = _g_apipool[(_g_domain_idx + t) % n]
        if dom in tried:
            continue
        tried.append(dom)
        js, err = _http_post(dom, path, data, timeout=12)
        if err is None and js.get("result") is True:
            _g_domain_idx = (_g_domain_idx + t) % n
            return js.get("data")
    return None

# ---------------- 广告清洗 ----------------
_AD_ACTION_BLOCK = {2, 3, 7, 9, 10, 11, 12}
_AD_IMG_GAME = {2}

def _is_ad_meta(m):
    """判断一个 广告/引导/推荐位 meta 是否该剔除"""
    if not isinstance(m, dict):
        return False
    act = m.get("adAction")
    atype = m.get("adImgType")
    if act in _AD_ACTION_BLOCK:
        return True
    if atype in _AD_IMG_GAME:
        return True
    ac = m.get("actionContent") or ""
    if ac and ("http" in str(ac) or not str(ac).isdigit()):
        return True
    title = str(m.get("title") or "").strip()
    if title in {"", ".", "ㅤ", "ㅤㅤ", "ㅤㅤㅤ"}:
        return True
    return False

def _clean_vod(item):
    """字段规整为 TVBox 列表项，剔除广告/无效项"""
    if not isinstance(item, dict):
        return None
    vod_id = item.get("vodId") or item.get("vod_id") or item.get("id")
    if vod_id is None:
        return None
    name = str(item.get("vodName") or item.get("vod_name") or "").strip()
    if not name:
        return None
    pic = str(item.get("coverImg") or item.get("vod_pic") or item.get("pic") or "").strip()
    if pic and (pic.startswith("//") or pic.startswith("http")):
        try:
            u = pic.split("/")[2] if "://" in pic else pic
        except Exception:
            u = ""
        if "ff1." in pic or "fff1." in pic or "ff." in pic:
            depth = len(pic.split("/")) - 1
            if depth <= 3:
                _log("剔除广告图", name)
                return None
    remark = ""
    for kk in ("remark", "updateRemark", "vod_remarks", "epg_data"):
        if item.get(kk):
            remark = str(item[kk])
            if kk == "epg_data":
                remark = str(_epg_remark(item[kk]) if item[kk] else "")
            break
    score = item.get("score")
    if score in (None, "0.0", "0"):
        score = ""
    return {
        "vod_id": str(vod_id),
        "vod_name": name,
        "vod_pic": pic,
        "vod_remarks": remark,
        "vod_year": str(item.get("year") or item.get("vod_year") or ""),
        "vod_area": str(item.get("areaName") or item.get("vod_area") or ""),
        "vod_content": str(item.get("intro") or item.get("vod_content") or "").replace("\r\n", "").strip(),
        "score": str(score),
    }

def _epg_remark(v):
    return str(v)

# ---------------- Spider ----------------
_BaseC = _BaseSpider if _HAS_BASE else object
class Spider(_BaseC):
    def __init__(self):
        self.siteName = "一起看"
        self.siteUrl = "https://yqk88.app/"

    # ---- 依赖库（必为可调用方法，不能是 None，否则壳 init_spider 报 NoneType not callable）----
    def getDependence(self):
        return ""

    def init(self, extend=""):
        global _g_init_done, _g_env, _APP_ID, _APP_KEY
        try:
            if extend:
                if isinstance(extend, str):
                    e = json.loads(extend)
                else:
                    e = extend
                if isinstance(e, dict):
                    _g_env = e
                    if e.get("appId"):
                        _APP_ID = str(e["appId"])
                    if e.get("appKey"):
                        _APP_KEY = str(e["appKey"])
                    if e.get("domains") and isinstance(e["domains"], (list, tuple)):
                        _g_apipool = [str(x) for x in e["domains"]]
        except Exception:
            pass
        if not _g_init_done:
            _build_pool()
            _g_init_done = True
        return ""

    # ---- 完整分类树（一级频道 → 二/三级分类）----
    _tree = None

    def _build_tree(self):
        """构建与 App 一致的完整分类列表：主频道二级分类 + 首页专题栏目，均能翻页。
        返回 {tid: {channelId, keyword, fallback, name, kind}}，tid 带前缀区分：
          M<cid>-<二级名>  主频道二级分类(用子分类名 keyword)
          T-<专题名>       首页专题栏目(用主题词 keyword)
        """
        if self._tree:
            return self._tree
        tree = {}
        # ① 主频道二级分类
        plan = {
            "2":  ("电影", ["科幻片","动作片","爱情片","喜剧片","恐怖片","灾难片","惊悚片","剧情片",
                            "冒险片","战争片","伦理片","纪录片","悬疑片","动画片","犯罪片","奇幻片","武侠片","邵氏电影"]),
            "3":  ("电视剧", ["国产剧","欧美剧","韩国剧","日本剧","香港剧","台湾剧","泰国剧","海外剧"]),
            "8":  ("动漫", ["国产动漫","日韩动漫","欧美动漫","港台动漫","海外动漫"]),
            "10": ("综艺", ["大陆综艺","日韩综艺","港台综艺","欧美综艺"]),
            "50": ("短剧", ["短剧"]),
            "56": ("韩剧", ["韩剧"]),
            "65": ("奈飞", ["奈飞"]),
            "5":  ("体育", ["足球","篮球","德州扑克"]),
        }
        for cid, (topname, subs) in plan.items():
            for sn in subs:
                if not sn:
                    continue
                tid = "C%s-%s" % (cid, sn)
                tree[tid] = {"channelId": cid, "keyword": sn,
                             "fallback": topname, "name": "%s/%s" % (topname, sn),
                             "kind": "channel"}
        # ② 首页专题栏目（用"频道+主题词" keyword 翻页，保证稳定）
        topic_cfg = [
            ("抖音up主推荐电影","2","电影"), ("抖音up主推荐电视剧","3","电视剧"), ("每日推荐","2","电影"),
            ("下饭短剧","50","短剧"), ("48小时飙升观影榜","2","电影"), ("经典TVB剧","3","TVB"),
            ("爱优腾芒","3","电视剧"), ("美剧热播","3","美剧"), ("毒舌电影","2","电影"),
            ("网络电影","2","网络电影"), ("爆笑喜剧","2","喜剧"), ("胆小误入","2","恐怖"),
            ("拳拳到肉","2","动作"), ("近10年韩国高分电影","2","韩剧"), ("情投意合","2","爱情"),
            ("刺激战场","2","战争"), ("十年经典","3","经典"), ("怀旧剧场","3","怀旧"),
            ("悬疑剧场","3","悬疑"), ("男人减速带","8","纪录"), ("热播日剧","3","日剧"),
            ("港片名导","2","港片"), ("好莱坞影视","2","好莱坞"), ("梦幻迪士尼","8","迪士尼"),
            ("DC世界","2","DC"), ("漫威宇宙","2","漫威"), ("灾难降临","2","灾难"),
        ]
        for tn, cid, kw in topic_cfg:
            tid = "T-%s" % tn
            tree[tid] = {"channelId": cid, "keyword": kw, "fallback": "",
                         "name": tn, "kind": "topic"}
        self._tree = tree
        return tree

    def _keyword_to_param(self, tid):
        """把 tid 映射为 (channelId, keyword, fallback)。"""
        t = self._build_tree()
        if tid in t:
            return t[tid]["channelId"], t[tid]["keyword"], t[tid].get("fallback", "")
        # 兼容旧格式: 频道id
        name_of = {"2":"电影","3":"电视剧","8":"动漫","10":"综艺","50":"短剧",
                   "56":"高清韩剧","65":"奈飞","5":"体育"}
        if tid in name_of:
            return tid, name_of[tid], ""
        return tid, "", ""

    # ---- 首页 ----
    def homeContent(self, filter=False):
        """返回与 App 一致的完整分类树（一级频道 → 二级分类平铺）。"""
        tree = self._build_tree()
        channel = []
        for key, v in tree.items():
            channel.append({"type_id": key, "type_name": v["name"]})
        return {"class": channel, "filters": {"type_id": [{"key": "type_id", "name": "内容"}]}}

    # ---- 视频列表(分类页) ----
    def _list_category(self, tid, pg):
        """按 tid 出该分类的影片列表，严格 nextVal 游标翻页，每页10条。"""
        try:
            pg_i = max(1, int(pg))
        except Exception:
            pg_i = 1
        cid, kw, fb = self._keyword_to_param(tid)
        # 先尝试细分词，翻页；若该页空则回退到父频道通用词兜底(保证翻页不碰空页)
        result = self._cursor_page(cid, kw, pg_i)
        if not result["list"] and fb and fb != kw:
            result = self._cursor_page(cid, fb, pg_i)
        return result

    def _cursor_page(self, cid, keyword, pg_i, size=10):
        """用 search + nextVal 游标取第 pg_i 页(绝对页号，自包含递增)。"""
        params = {"keyword": keyword, "page": 1, "pageSize": size}
        if cid not in (None, "", 0, "0"):
            params["channelId"] = cid
        cur = None
        latest = None
        for step in range(1, pg_i + 1):
            p = dict(params)
            if cur:
                p["nextVal"] = cur
            data = _api("/v1/api/search/search", p)
            if not data:
                break
            if step == pg_i:
                latest = data
                break
            cur = data.get("nextVal")
            if not cur:
                break
        items = []
        has_more = False
        if latest:
            for it in latest.get("items") or []:
                v = _clean_vod(it)
                if v:
                    items.append(v)
            has_more = bool(latest.get("hasNext"))
        total = -1 if has_more else (1 if items else 0)
        return {"list": items, "page": pg_i, "pagecount": total}

    # ---- 列表 / 搜索 ----
    def _list(self, cid, pg, channelId=None, filterObj=None, keyword=""):
        params = {"keyword": keyword, "page": int(pg), "pageSize": 24}
        cid_use = channelId if channelId is not None else cid
        if cid_use:
            params["channelId"] = cid_use
        if filterObj:
            for k, v in filterObj.items():
                if k not in ("page", "pageSize", "keyword"):
                    params[k] = v
        data = _api("/v1/api/search/search", params)
        items = []
        hasMore = False
        if data:
            for it in data.get("items") or []:
                v = _clean_vod(it)
                if v:
                    items.append(v)
            hasMore = bool(data.get("hasNext"))
        total = -1 if hasMore else (1 if items else 0)
        return {"list": items, "page": int(pg), "pagecount": total}

    def homeVideoContent(self):
        # 首页推荐：用 firstScreen 的热播真实列表
        data = _api("/v2/api/home/firstScreen", {})
        items = []
        if data:
            for v in data.get("hotVodList") or []:
                it = _clean_vod(v)
                if it:
                    items.append(it)
            for v in data.get("hotMudleList") or []:
                pass
        if not items:
            bo = _api("/v2/api/home/body", {"page": 1, "pageSize": 10})
            if bo:
                for tp in bo.get("vodTopicList") or []:
                    for v in tp.get("vodList") or []:
                        it = _clean_vod(v)
                        if it:
                            items.append(it)
        # 去重
        seen, clean = [], []
        for it in items:
            if it["vod_id"] not in seen:
                seen.append(it["vod_id"]); clean.append(it)
        return {"list": clean, "page": 1, "pagecount": 1}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        # 新架构：tid 是完整分类树里的分类 key（"顶级-二级"），严格 nextVal 翻页
        try:
            pg_i = int(pg)
        except Exception:
            pg_i = 1
        return self._list_category(str(tid), pg_i)

    def _channel_keyword(self, cid):
        """频道 → 分类关键词。只用分类树，不发试探请求。"""
        t = self._build_tree()
        for k, v in t.items():
            if v["channelId"] == str(cid) and v["keyword"]:
                return v["keyword"]
        return ""

    # ---- 搜索 ----
    def searchContent(self, key, quick=False):
        data = _api("/v1/api/search/search", {"keyword": key, "page": 1, "pageSize": 24})
        items = []
        if data:
            for it in data.get("items") or []:
                v = _clean_vod(it)
                if v:
                    items.append(v)
        return {"list": items, "page": 1, "pagecount": len(items)}

    # ---- 详情 ----
    def detailContent(self, ids):
        vid = str(ids) if not isinstance(ids, (list, tuple)) else (ids[0] if ids else "")
        data = _api("/v2/api/vodInfo/index", {"vodId": vid})
        if not data:
            return {"list": []}
        v = _clean_vod(data)
        if not v:
            return {"list": []}
        # 多线路：playerList 多个线路，用 $$$ 分隔；每线路内选集用 # 分隔
        pl = data.get("playerList") or []
        vod_play_from, vod_play_url = [], []
        for p in pl:
            pname = str(p.get("playerName") or "线路").strip()
            eps = p.get("epList") or []
            if not eps:
                continue
            fm = pname
            epstr = "#".join("%s$%s" % (str(e.get("epName") or "播放"), str(e.get("epId") or "")) for e in eps)
            vod_play_from.append(fm)
            vod_play_url.append(epstr)
        if not vod_play_from:
            return {"list": [dict(v)]}
        v["vod_play_from"] = "$$$".join(vod_play_from)
        v["vod_play_url"] = "$$$".join(vod_play_url)
        return {"list": [v]}

    # ---- 播放 ----
    def playerContent(self, flag, id, vipFlags=0):
        # id: epId
        epid = id
        froms, urls = str(flag), str(id)
        # 先用 epDetail 拿清晰度，选择可播放的最高档(优先超清/1080)
        reso = None
        ed = _api("/v2/api/vodInfo/epDetail", {"vodEpId": epid})
        use_res = None
        if ed:
            for r in ed:
                if not r.get("canPlay"):
                    continue
                cur = r.get("vodResolution")
                if use_res is None or int(cur) > int(use_res):
                    use_res = cur
                reso = r
            if use_res is None and reso:
                use_res = reso.get("vodResolution")
        if use_res is None:
            use_res = 1
        pu = _api("/v2/api/vodInfo/playUrl", {"epId": epid, "vodResolution": use_res})
        play_url = ""
        ext = {}
        if pu:
            play_url = str(pu.get("playUrl") or "")
            ext = pu
        if not play_url:
            # 兜底：线路返回的 checkM3u8 字段
            return {"parse": 0, "url": (ext.get("playUrl") or ""),
                    "header": {"Referer": "https://yqk.app/"}, "ext": json.dumps(ext, ensure_ascii=False)}
        return {"parse": 0, "url": play_url,
                "header": {"Referer": "https://yqk.app/"},
                "ext": json.dumps(ext, ensure_ascii=False)}

    def localProxy(self, param):
        # 本地代理占位（壳会调用，必须可调用）
        return ""

    def manualVideoCheck(self):
        return False
    def isVideoFormat(self, url):
        return url and (url.endswith(".m3u8") or "m3u8" in url or ".mp4" in url)
    def action(self, action):
        return ""
    def destroy(self):
        return ""

# ---------------- 自测 ----------------
if __name__ == "__main__":
    _DEBUG = True
    s = Spider()
    s.init()
    print("\n### homeContent 频道:")
    hc = s.homeContent()
    print(hc.get("class"))
    print("\n### homeVideoContent:")
    hv = s.homeVideoContent()
    print("条数", len(hv["list"]))
    for it in hv["list"][:5]:
        print("  ", it["vod_name"], it["vod_remarks"])
    print("\n### searchContent 凡人修仙传:")
    sc = s.searchContent("凡人修仙传")
    print("条数", len(sc["list"]))
    for it in sc["list"][:3]:
        print("  ", it["vod_id"], it["vod_name"])
    if sc["list"]:
        vid = sc["list"][0]["vod_id"]
        print("\n### detailContent", vid)
        dc = s.detailContent(vid)
        it = dc["list"][0]
        print("  线路:", it.get("vod_play_from")[:80])
        froms = it.get("vod_play_from", "").split("$$$")
        urls = it.get("vod_play_url", "").split("$$$")
        print("  已含", len(froms), "线路")
        if urls:
            first = urls[0].split("#")[0].split("$")
            epid = first[-1]
            print("\n### playerContent epId=", epid)
            pc = s.playerContent(froms[0], epid)
            print("  parse=%s url=%s" % (pc.get("parse"), pc.get("url")[:100]))
            print("  是否m3u8直链:", str(pc.get("url")).endswith(".m3u8"))
