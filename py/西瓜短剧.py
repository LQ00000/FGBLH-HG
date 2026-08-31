# -*- coding: utf-8 -*-
"""
西瓜短剧 (xgshort.com) - TVBox Python Spider

站点：Vue SPA + REST API，播放直链 MP4（Cloudflare CDN），无需签名。
登录：POST /api/auth/guest-login 拿 Bearer token，7 天有效。
API 主机：https://www.xgshort.com/api/*
"""
import json
import time
import urllib.parse
import urllib.request

HOST = "https://www.xgshort.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

BASE_HEADERS = {
    "User-Agent": UA,
    "Referer": HOST + "/",
    "Origin": HOST,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}

CATEGORY_MAP = {
    "1": "短剧",
    "2": "电影",
    "3": "电视剧",
    "71": "AI短剧",
}


def _http(method, path, params=None, body=None, token=None, timeout=20):
    qs = ""
    if params:
        parts = []
        for k, v in params.items():
            if v is None or v == "":
                continue
            parts.append("{}={}".format(k, urllib.parse.quote(str(v))))
        if parts:
            qs = "?" + "&".join(parts)
    url = HOST + path + qs
    headers = dict(BASE_HEADERS)
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except Exception:
                return {"_raw": raw[:500]}
    except Exception as e:
        return {"_error": str(e)}


def _extract_list(resp):
    """从常见 API 响应形态里拉出 list / total / page / size / hasMore。"""
    if not isinstance(resp, dict):
        return [], 0, 1, 20, False
    data = resp.get("data")
    if isinstance(data, list):
        return data, len(data), 1, len(data), False
    if isinstance(data, dict):
        lst = data.get("list") or []
        total = data.get("total") or 0
        page = data.get("page") or 1
        size = data.get("size") or 20
        has_more = bool(data.get("hasMore"))
        if not total and lst:
            total = len(lst)
        return lst, total, page, size, has_more
    lst = resp.get("list") or []
    total = resp.get("total") or 0
    page = resp.get("page") or 1
    size = resp.get("size") or 20
    has_more = bool(resp.get("hasMore"))
    return lst, total, page, size, has_more


def _vod_from_item(item, extra_category=None):
    """把 list/getfiltersdata/fuzzysearch 的 item 转成 TVBox vod 结构。"""
    if not isinstance(item, dict):
        return None
    short_id = item.get("shortId") or ""
    if not short_id:
        return None
    name = item.get("title") or ""
    cover = item.get("coverUrl") or ""
    score = item.get("score") or ""
    play_count = item.get("playCount") or 0
    up_status = item.get("upStatus") or ""
    is_serial = item.get("isSerial")
    tags = item.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    tag_str = " / ".join([str(t) for t in tags if t][:3])

    remarks_parts = []
    if score:
        remarks_parts.append("评分 {}".format(score))
    if up_status:
        remarks_parts.append(up_status)
    if tag_str:
        remarks_parts.append(tag_str)

    return {
        "vod_id": short_id,
        "vod_name": name,
        "vod_pic": cover,
        "vod_remarks": " | ".join(remarks_parts),
        "vod_year": (item.get("createdAt") or "")[:4] or "",
        "vod_area": item.get("type") or item.get("contentType") or extra_category or "",
        "vod_score": str(score),
        "vod_content": item.get("description") or "",
        "vod_play_from": "",
        "vod_play_url": "",
        "type_name": tag_str,
    }


def _pagecount(total, size):
    size = max(1, size or 20)
    return max(1, (int(total) + size - 1) // size)


class Spider:
    def init(self, extend=""):
        self._token = None
        self._token_expires = 0
        # extend 可以放一个静态 token 兜底，比如 {"token": "..."}
        if extend:
            try:
                e = json.loads(extend)
                if isinstance(e, dict) and e.get("token"):
                    self._token = e["token"]
                    self._token_expires = time.time() + 604800
            except Exception:
                pass

    # ---- token 管理 ----
    def _ensure_token(self):
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        r = _http("POST", "/api/auth/guest-login", body={})
        tok = r.get("access_token") if isinstance(r, dict) else None
        if tok:
            self._token = tok
            self._token_expires = time.time() + (r.get("expires_in") or 604800)
            return tok
        return None

    def _reset_token(self):
        self._token = None
        self._token_expires = 0

    # ---- 首页分类 ----
    def homeContent(self, filter):
        cls_list = []
        # 从 API 拉真实分类
        r = _http("GET", "/api/home/categories")
        items = r.get("data") if isinstance(r, dict) else None
        if not isinstance(items, list):
            items = []
        for it in items:
            cid = str(it.get("id"))
            name = it.get("name") or CATEGORY_MAP.get(cid, "分类{}".format(cid))
            cls_list.append({"type_id": cid, "type_name": name})
        if not cls_list:
            for cid, name in CATEGORY_MAP.items():
                cls_list.append({"type_id": cid, "type_name": name})
        return {"class": cls_list, "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("1", "1", False, {})

    # ---- 分类 ----
    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg or "1"))
        size = 20
        channeid = str(tid or "1")

        # 排序映射：TVBox filter 里可以塞 sort 参数
        sort_index = 0
        if isinstance(filter, dict):
            sort_index = filter.get("sort", 0)
            if isinstance(sort_index, str):
                try:
                    sort_index = int(sort_index)
                except Exception:
                    sort_index = 0

        # ids 参数：排序在前，题材/地区/语言/年份/状态默认 0
        ids_parts = [str(sort_index)] + ["0"] * 6
        ids = ",".join(ids_parts)

        params = {
            "channeid": channeid,
            "ids": ids,
            "page": page,
            "size": size,
        }
        r = _http("GET", "/api/list/getfiltersdata", params=params)
        lst, total, _, size2, has_more = _extract_list(r)

        category_name = CATEGORY_MAP.get(channeid, "")
        vod_list = []
        for item in lst:
            v = _vod_from_item(item, extra_category=category_name)
            if v:
                vod_list.append(v)

        pagecount = _pagecount(total, size2)
        return {
            "list": vod_list,
            "page": page,
            "pagecount": pagecount,
            "limit": size2,
            "total": total,
        }

    # ---- 详情 ----
    def detailContent(self, ids):
        id_str = ids[0] if isinstance(ids, list) else ids
        if not id_str:
            return {"list": []}
        token = self._ensure_token()
        if not token:
            return {"list": []}

        r = _http("GET", "/api/video/episodes",
                  params={"seriesShortId": id_str, "size": 500},
                  token=token)
        # token 过期兜底：刷新一次
        if isinstance(r, dict) and (r.get("statusCode") == 401 or r.get("_error")):
            self._reset_token()
            token = self._ensure_token()
            if not token:
                return {"list": []}
            r = _http("GET", "/api/video/episodes",
                      params={"seriesShortId": id_str, "size": 500},
                      token=token)

        data = r.get("data") if isinstance(r, dict) else None
        if not isinstance(data, dict):
            return {"list": []}

        s = data.get("seriesInfo") or {}
        tag_list = data.get("tags") or s.get("tags") or []
        if isinstance(tag_list, str):
            try:
                tag_list = json.loads(tag_list)
            except Exception:
                tag_list = []

        title = s.get("title") or ""
        cover = s.get("coverUrl") or ""
        description = s.get("description") or ""
        director = s.get("director") or ""
        actor = s.get("actor") or ""
        content_type = s.get("contentType") or s.get("channeName") or ""
        update_status = s.get("updateStatus") or ""
        score = s.get("score") or ""
        play_count = s.get("playCount") or 0
        post_time = s.get("postTime") or ""

        meta_lines = []
        if content_type:
            meta_lines.append("类型：{}".format(content_type))
        if update_status:
            meta_lines.append("状态：{}".format(update_status))
        if score:
            meta_lines.append("评分：{}".format(score))
        if play_count:
            if play_count >= 10000:
                pc = "{:.1f} 万".format(play_count / 10000.0)
            else:
                pc = str(play_count)
            meta_lines.append("播放：{}".format(pc))
        if post_time:
            meta_lines.append("更新：{}".format(post_time[:10]))
        if director:
            meta_lines.append("导演：{}".format(director))
        if actor:
            meta_lines.append("主演：{}".format(actor[:120]))
        tag_str = " / ".join([str(t) for t in tag_list if t])
        if tag_str:
            meta_lines.append("标签：{}".format(tag_str))

        # 播放地址：name$accessKey
        ep_list = data.get("list") or []
        play_parts = []
        for ep in ep_list:
            if not isinstance(ep, dict):
                continue
            ak = ep.get("episodeAccessKey") or ""
            if not ak:
                continue
            num = ep.get("episodeNumber")
            etitle = ep.get("episodeTitle") or ep.get("title") or ""
            name = ""
            if etitle and etitle != str(num or ""):
                name = "{} {}".format(num, etitle).strip() if num else etitle
            else:
                name = "第{}集".format(num) if num else (etitle or "第{}集".format(len(play_parts) + 1))
            play_parts.append("{}${}".format(name, ak))
        play_url = "#".join(play_parts)

        vod = {
            "vod_id": id_str,
            "vod_name": title,
            "vod_pic": cover,
            "vod_play_from": "西瓜短剧",
            "vod_play_url": play_url,
            "vod_remarks": " | ".join(meta_lines[:5]),
            "vod_content": description,
            "vod_actor": actor,
            "vod_director": director,
            "vod_score": str(score),
            "type_name": tag_str,
            "vod_year": (post_time or "")[:4],
            "vod_area": content_type,
            "vod_class": tag_str,
        }
        return {"list": [vod]}

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg):
        page = max(1, int(pg or "1"))
        size = 20
        params = {
            "keyword": key,
            "page": page,
            "size": size,
        }
        r = _http("GET", "/api/list/fuzzysearch", params=params)
        lst, total, _, size2, _ = _extract_list(r)

        # fuzzysearch 无 total 时用启发式
        if not total:
            total = len(lst) + (page - 1) * size2

        vod_list = []
        for item in lst:
            v = _vod_from_item(item)
            if v:
                vod_list.append(v)

        pagecount = _pagecount(total, size2)
        return {
            "list": vod_list,
            "page": page,
            "pagecount": pagecount,
            "limit": size2,
            "total": total,
        }

    # ---- 播放 ----
    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "url": "", "header": {}}

        # 兜底：id 本身已经是直链
        if id.startswith("http://") or id.startswith("https://"):
            return {
                "parse": 0,
                "url": id,
                "header": {"User-Agent": UA, "Referer": HOST + "/"},
            }

        # 期望格式：<accessKey>[|<quality>]，或 <seriesShortId>:<accessKey>
        access_key = id
        quality_hint = ""
        if "|" in id:
            parts = id.split("|")
            access_key = parts[0]
            quality_hint = parts[1] if len(parts) > 1 else ""
        if ":" in id and not access_key.startswith("http"):
            # shortId:accessKey
            parts = id.split(":", 1)
            access_key = parts[1]

        token = self._ensure_token()
        if not token:
            return {"parse": 0, "url": "", "header": {}}

        body = {"type": "episode", "accessKey": access_key}
        r = _http("POST", "/api/video/episode-url/query", body=body, token=token)
        if isinstance(r, dict) and (r.get("statusCode") == 401 or r.get("_error")):
            self._reset_token()
            token = self._ensure_token()
            if not token:
                return {"parse": 0, "url": "", "header": {}}
            r = _http("POST", "/api/video/episode-url/query", body=body, token=token)

        urls = None
        if isinstance(r, dict):
            data = r.get("data")
            if isinstance(data, dict):
                urls = data.get("urls") or []
        if not isinstance(urls, list) or not urls:
            return {"parse": 0, "url": "", "header": {}}

        # 选清晰度
        chosen = None
        # 排序：4K > 1440p > 1080p > 720p > 480p > 360p > 240p > 144p
        Q_ORDER = {"4k": 0, "1440p": 1, "1080p": 2, "720p": 3, "480p": 4,
                   "360p": 5, "240p": 6, "144p": 7}
        if quality_hint:
            for u in urls:
                if (u.get("quality") or "").lower() == quality_hint.lower():
                    chosen = u
                    break
        if not chosen:
            urls_sorted = sorted(urls,
                                 key=lambda x: Q_ORDER.get((x.get("quality") or "").lower(), 99))
            chosen = urls_sorted[0]

        cdn_url = chosen.get("cdnUrl") or chosen.get("ossUrl") or ""
        if not cdn_url:
            return {"parse": 0, "url": "", "header": {}}

        return {
            "parse": 0,
            "url": cdn_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
                "Origin": HOST,
            },
        }
