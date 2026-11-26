# tools.py
"""
工具层（Tool Layer）
--------------------
职责：只负责"能做什么"——天气、景点、美食三个外部数据查询。
特点：
  1. 不 import streamlit（可以被 pytest / 脚本直接调用）
  2. 不参与 Agent 的推理流程（不知道 ReAct、不知道 prompt）
  3. 对外只暴露 4 个名字：get_weather / get_attraction / get_food / available_tools

依赖：requests、tavily-python、python-dotenv
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from tavily import TavilyClient

# 显式指定 .env 位置（本文件所在目录），这样无论从哪个目录启动 streamlit 都能读到。
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# ⚠️ 只在这里定义一次 Tavily Key（原文件里 get_attraction / get_food 各硬编码了一次）。
# 不在代码里存明文密钥：只从环境变量 / .env 读取，缺失时由 _tavily() 给出明确提示。
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

WEATHER_TIMEOUT = 5

__all__ = ["get_weather", "get_attraction", "get_food", "available_tools"]

# ---------------------------------------------------------------------------
# Tavily 客户端只创建一次（懒加载），避免每次调用工具都重新 new 一个对象
# ---------------------------------------------------------------------------
_tavily_client = None


def _tavily():
    global _tavily_client
    if _tavily_client is None:
        if not TAVILY_API_KEY:
            # 这里抛错会被 agent_core 的 try/except 转成一条 Observation 回灌给模型，
            # 同时也会显示在网页上，不会让整个页面红屏。
            raise RuntimeError(
                "缺少环境变量 TAVILY_API_KEY：请在项目根目录创建 .env 文件"
                "（可复制 .env.example 并填入 Key），或设置系统环境变量后重新运行。"
            )
        _tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily_client


# ---------------------------------------------------------------------------
# 工具 1：天气
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """查询指定城市的实时天气。"""
    url = f"https://wttr.in/{city}?format=j1"
    try:
        response = requests.get(url, timeout=WEATHER_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        current = data["current_condition"][0]
        desc = current["weatherDesc"][0]["value"]
        return f"{city}当前天气：{desc}，气温 {current['temp_C']} 摄氏度。"
    except Exception as e:
        return f"错误：查询天气时遇到网络问题 -> {e}"


# ---------------------------------------------------------------------------
# 工具 2：景点
# ---------------------------------------------------------------------------
def get_attraction(city: str, weather: str) -> str:
    """根据城市和天气，搜索合适的旅游景点。"""
    query = f"{city} 在 {weather} 天气下，最适合去哪些旅游景点？请推荐3个。"
    try:
        response = _tavily().search(query=query, include_answer=True)
        return response.get("answer", "抱歉，没有找到相关的景点信息。")
    except Exception as e:
        return f"错误：执行Tavily搜索时失败 -> {e}"


# ---------------------------------------------------------------------------
# 工具 3：美食
# ---------------------------------------------------------------------------
def get_food(city: str) -> str:
    """查询指定城市的特色美食。"""
    query = f"{city} 有哪些必吃的特色美食？请推荐3个并简单说明。"
    try:
        response = _tavily().search(query=query, include_answer=True)
        return response.get("answer", "抱歉，没有找到美食推荐。")
    except Exception as e:
        return f"错误：执行美食搜索时失败 -> {e}"


# ---------------------------------------------------------------------------
# 注册表：Agent 通过函数名 -> 函数对象 的映射来执行 Action
# 新增工具时，只要在这里加一行（再在 prompts.py 的提示词里补一行说明）
# ---------------------------------------------------------------------------
available_tools = {
    "get_weather": get_weather,
    "get_attraction": get_attraction,
    "get_food": get_food,
}
