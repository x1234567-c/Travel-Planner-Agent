# verify.py
"""
地点交叉验证层（Anti-hallucination）
------------------------------------
目的：模型推荐的地点可能是编造的。这里用"外部真实数据"给每个地点打分，
      结论回灌给模型，让它只推荐有据可查的地方。

数据源：
  1. Tavily 站内检索（必须有 TAVILY_API_KEY）：
     统计小红书 / 大众点评 / 马蜂窝 / 携程 / 知乎 / 微博 / B站 / 百度百科 等
     平台上是否真的有人提到这个地点 —— 多源提及 = 强证据。
  2. 高德地图 POI（可选，配置 AMAP_API_KEY 后启用）：
     官方 POI 库，命中基本可以确定"这个地方真实存在"。

为什么不直连小红书/抖音 API：
  这些平台没有面向个人的公开搜索 API，微博开放平台需要企业资质审核。
  站内检索是普通开发者唯一稳定可行的"社交平台内容"入口；高德则提供权威兜底。

判定：
  得分 = 高德命中(3) + 多平台提及(1~3) + 正文出现名称(1)
  >=3 已验证 / 2 较可信 / 1 存疑 / 0 未找到
"""

import os
import re
from urllib.parse import urlparse

from tools import http_get, tavily_search

# 域名 -> 展示名。命中越多，说明这个地点在越多独立平台上被真实讨论过。
# 除了纯社交平台，也纳入旅游 UGC 和百科：它们同样是"有人真实去过"的旁证。
SOCIAL_SITES = {
    "xiaohongshu.com": "小红书",
    "dianping.com": "大众点评",
    "meituan.com": "美团",
    "mafengwo.cn": "马蜂窝",
    "qyer.com": "穷游",
    "ctrip.com": "携程",
    "qunar.com": "去哪儿",
    "tuniu.com": "途牛",
    "ly.com": "同程",
    "trip.com": "Trip.com",
    "youxiake.com": "游侠客",
    "zhihu.com": "知乎",
    "weibo.com": "微博",
    "bilibili.com": "B站",
    "douyin.com": "抖音",
    "facebook.com": "Facebook",
    "instagram.com": "Instagram",
    "youtube.com": "YouTube",
    "tiktok.com": "TikTok",
    "baike.baidu.com": "百度百科",
    "baidu.com": "百度",
    "sohu.com": "搜狐",
    "wikipedia.org": "维基百科",
}

AMAP_KEY = os.getenv("AMAP_API_KEY")

MAX_PLACES = 5          # 一次最多核实几个地点，控制搜索配额
MAX_RESULTS = 8         # 每个地点取多少条搜索结果

__all__ = ["verify_place", "verify_places", "SOCIAL_SITES"]


def _site_of(url: str) -> str | None:
    """把 URL 映射成平台名，不在列表里返回 None。"""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, label in SOCIAL_SITES.items():
        if host == domain or host.endswith("." + domain):
            return label
    return None


def _amap_lookup(place: str, city: str) -> dict | None:
    """高德 POI 检索；没配 AMAP_API_KEY 或请求失败时返回 None。"""
    if not AMAP_KEY:
        return None
    try:
        response = http_get(
            "https://restapi.amap.com/v3/place/text",
            timeout=8,
            params={
                "key": AMAP_KEY,
                "keywords": place,
                "city": city,
                "citylimit": "true",
                "offset": 3,
                "extensions": "base",
            },
        )
        data = response.json()
        pois = data.get("pois") or []
        if not pois:
            return None
        poi = pois[0]
        return {
            "name": poi.get("name", ""),
            "type": poi.get("type", ""),
            "address": poi.get("address", ""),
        }
    except Exception:
        return None


def _social_check(place: str, city: str) -> tuple[list[str], list[str], bool, int]:
    """
    返回 (命中的平台列表, 来源链接, 正文是否出现地点名, 结果总数)。

    关键：只有"页面里真的出现了这个地名"才算一次提及。
    否则搜索引擎返回的无关页面（比如通用的成都攻略）会把虚构地点也判成可信。
    """
    query = f"{city} {place} 好玩吗 攻略 游记".strip()
    response = tavily_search(query, include_answer=False, max_results=MAX_RESULTS)
    results = response.get("results") or []

    keyword = place.replace(" ", "")
    sites: list[str] = []
    sources: list[str] = []
    name_seen = False

    for item in results:
        url = item.get("url", "")
        blob = f"{item.get('title', '')} {item.get('content', '')} {url}".replace(" ", "")
        if not keyword or keyword not in blob:
            continue
        name_seen = True
        site = _site_of(url)
        if site and site not in sites:
            sites.append(site)
            sources.append(url)

    return sites, sources, name_seen, len(results)


def verify_place(place: str, city: str = "") -> dict:
    """核实单个地点，返回结构化结论。"""
    place = place.strip()
    sites, sources, name_seen, total = _social_check(place, city)
    amap = _amap_lookup(place, city)

    score = 0
    evidence: list[str] = []

    if amap:
        score += 3
        poi_type = f"（{amap['type']}）" if amap.get("type") else ""
        evidence.append(f"高德 POI 命中「{amap['name']}」{poi_type}")

    if len(sites) >= 3:
        score += 3
        evidence.append("多个平台提及：" + "、".join(sites))
    elif len(sites) == 2:
        score += 2
        evidence.append("两个平台提及：" + "、".join(sites))
    elif len(sites) == 1:
        score += 1
        evidence.append("单一平台提及：" + sites[0])

    if name_seen:
        score += 1
        evidence.append("搜索结果正文出现该名称")

    if not evidence:
        evidence.append(f"检索了 {total} 条结果，没有任何社交平台或百科记录")

    if score >= 3:
        verdict, label = "verified", "✅ 已验证"
    elif score == 2:
        verdict, label = "likely", "🟢 较可信"
    elif score == 1:
        verdict, label = "weak", "🟡 存疑"
    else:
        verdict, label = "unverified", "❌ 未找到"

    return {
        "place": place,
        "city": city,
        "verdict": verdict,
        "label": label,
        "score": score,
        "evidence": evidence,
        "sources": sources[:3],
        "amap": amap,
    }


def verify_places(places: str, city: str = "") -> str:
    """
    Agent 调用的工具入口：一次核实多个地点，返回给模型看的文本报告。

    参数：
        places: 地点名称，用逗号 / 顿号 / 分号分隔，例如 "宽窄巷子、锦里、人民公园"
        city:   所在城市，用于提高检索命中率
    """
    names = [n.strip() for n in re.split(r"[,，、;；/\n]+", places or "") if n.strip()]
    if not names:
        return "错误：没有解析到要核实的地点名称，请用逗号分隔。"

    truncated = len(names) > MAX_PLACES
    names = names[:MAX_PLACES]

    results = [verify_place(name, city) for name in names]
    good = sum(1 for r in results if r["verdict"] in ("verified", "likely"))

    lines = [f"地点交叉验证结果（城市：{city or '未指定'}，共 {len(names)} 个，可信 {good} 个）"]
    for r in results:
        lines.append(f"{r['label']} {r['place']}：{'；'.join(r['evidence'])}")
        if r["sources"]:
            lines.append("    来源：" + " | ".join(r["sources"]))

    lines.append("")
    lines.append("判定说明：✅ 已验证 / 🟢 较可信 / 🟡 存疑 / ❌ 未找到。")
    lines.append("请只推荐 ✅ 和 🟢 的地点；🟡 需注明“未能充分验证”；❌ 必须从推荐中删除，不要编造理由。")
    if truncated:
        lines.append(f"（一次最多核实 {MAX_PLACES} 个地点，其余请再次调用）")

    return "\n".join(lines)
