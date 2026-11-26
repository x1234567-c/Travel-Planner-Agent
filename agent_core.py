# agent_core.py
"""
Agent 核心层（Reasoning Loop）
------------------------------
职责：ReAct 循环本身——调模型、解析输出、执行工具、把 Observation 喂回去。

关键设计：
  这里 **不 import streamlit**。
  run_agent_streamlit() 保留原函数名，但已改成一个"事件生成器"（generator）：
  它 yield 出 {type, ...} 字典，由 app.py 决定怎么画（st.status / st.write / 终端 print 都行）。
  这样做的好处：
    - 可以脱离网页做单元测试 / 命令行调试
    - 以后想换成 Gradio、FastAPI 或纯终端，只改 UI 层即可

事件协议（app.py 按 type 分发）：
  {"type": "thought",     "content": str}         模型这一步的完整输出
  {"type": "tool_call",   "name": str, "args": {}} 即将执行哪个工具
  {"type": "observation", "content": str}         工具返回值或错误提示
  {"type": "error",       "content": str}         调用模型失败，或输出解析失败（已兜底，不崩溃）
  {"type": "final",       "content": str}         最终答案（一定会是最后一个事件）
"""

import inspect
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from prompts import AGENT_SYSTEM_PROMPT
from tools import available_tools
from verify import verify_places

# 与 tools.py 同理：先加载 .env，再读 Key。
# 两个模块各加载一次是无害的（load_dotenv 幂等），好处是任何模块单独被 import 都自洽。
# 显式指定路径，保证"从任何目录启动"都能读到本文件同级的 .env。
# 代码里不保留任何明文兜底 Key：读不到就直接报错，避免把密钥写进源码。
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "缺少环境变量 DEEPSEEK_API_KEY：请在项目根目录创建 .env 文件"
        "（可复制 .env.example 并填入 Key），或设置系统环境变量后重新运行。"
    )

MODEL_NAME = "deepseek-chat"
# 多了一步"地点交叉验证"，步数上限从 5 提到 6：
# 天气 → 景点 → 验证 → 结束，留一次容错
MAX_STEPS = 6

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 备用客户端：忽略系统代理。
# 有些环境设置了系统代理但代理程序没启动，此时只走 client 会直接 ProxyError。
_direct_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    http_client=httpx.Client(trust_env=False),
)


def _is_proxy_error(exc: Exception) -> bool:
    """判断是不是"连不上"类错误（含代理挂掉被包装成 Connection error 的情况）。"""
    try:
        from openai import APIConnectionError, APITimeoutError

        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return True
    except ImportError:  # pragma: no cover
        pass

    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, httpx.ProxyError):
            return True
        cause = cause.__cause__

    text = f"{type(exc).__name__} {exc}".lower()
    return "proxy" in text or "127.0.0.1" in text


def _chat(messages: list):
    """调模型；遇到连接类错误（典型是系统代理没开）时退回直连重试一次。"""
    kwargs = dict(model=MODEL_NAME, messages=messages, stop=["\nObservation:"])
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        if not _is_proxy_error(exc):
            raise
        return _direct_client.chat.completions.create(**kwargs)

# verify_places 依赖 tools 的搜索封装（tools → verify 会成环），
# 所以在核心层把它注册进同一张工具表；UI 层和提示词都不用感知差异。
available_tools["verify_places"] = verify_places

# ---------------------------------------------------------------------------
# 正则：从模型输出里抠出 Action
# ---------------------------------------------------------------------------
FINISH_RE = re.compile(r"Finish\s*\[(.*)\]", re.DOTALL)
ACTION_RE = re.compile(r"Action\s*[:：]\s*(.+)", re.IGNORECASE)
CALL_RE = re.compile(r"(\w+)\s*\((.*?)\)", re.DOTALL)
# key="value" / key='value' / key=value 都能匹配，值内部允许带逗号（只要加引号）
ARG_RE = re.compile(r"(\w+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^,]*)")

# 解析失败时回灌给模型的固定 Observation。
# 必须以 "Observation: " 开头：一方面和 stop=["\nObservation:"] 的协议一致，
# 另一方面模型看到这句话会知道"上一轮格式错了"，从而重新按格式输出。
PARSE_ERROR_TEXT = "工具解析失败，请检查输出格式"
PARSE_ERROR_OBSERVATION = f"Observation: {PARSE_ERROR_TEXT}"

__all__ = [
    "run_agent_streamlit",
    "extract_finish",
    "parse_action",
    "parse_step",
    "build_messages",
]


def build_messages(user_query: str) -> list:
    """构造本轮对话的初始 messages。"""
    return [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]


# ---------------------------------------------------------------------------
# 输出解析
# ---------------------------------------------------------------------------
def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _split_args(raw: str) -> list:
    """按逗号切参数，但忽略引号内部的逗号（如 weather="多云, 有小雨"）。"""
    parts, buf, quote = [], "", None
    for ch in raw:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _parse_args(raw: str, func_name: str) -> dict:
    """
    把 `city="三亚", weather="晴"` 解析成 {"city": "三亚", "weather": "晴"}。
    兼容模型偶尔写成位置参数的形式：`get_weather("三亚")`。
    """
    kwargs = {
        m.group(1): _strip_quotes(m.group(2)) for m in ARG_RE.finditer(raw)
    }
    if kwargs:
        return kwargs

    # 位置参数兜底：按函数签名顺序对应
    func = available_tools.get(func_name)
    if func is not None and raw.strip():
        param_names = list(inspect.signature(func).parameters)
        return {
            name: _strip_quotes(value)
            for name, value in zip(param_names, _split_args(raw))
        }
    return {}


def _normalize_text(text: str) -> str:
    """模型偶尔把换行写成字面量 "\\n"（两个字符），这里还原成真正的换行。"""
    return text.replace("\\r\\n", "\n").replace("\\n", "\n")


def extract_finish(reply: str):
    """如果这一步是 Finish[...]，返回最终答案；否则返回 None。"""
    match = FINISH_RE.search(reply)
    if match:
        return _normalize_text(match.group(1).strip())
    # 兜底：模型写了 Finish 但没有方括号，就把整段当答案（保持原逻辑）
    if "Finish" in reply:
        return _normalize_text(reply.strip())
    return None


def parse_action(reply: str):
    """解析 `Action: func_name(arg=value)`，返回 (func_name, args)；解析不出来返回 None。"""
    action_match = ACTION_RE.search(reply)
    if not action_match:
        return None

    call_match = CALL_RE.search(action_match.group(1).strip())
    if not call_match:
        return None

    func_name, raw_args = call_match.group(1), call_match.group(2)
    return func_name, _parse_args(raw_args, func_name)


def parse_step(reply: str):
    """
    把模型这一步的完整输出归类，返回三元组：
      ("finish", 最终答案)   -> 模型用 Finish[...] 收尾了
      ("action", (工具名, 参数)) -> 模型要调用工具
      ("invalid", None)      -> 既不是 Finish 也不是合法 Action（格式错误）

    注意：这个函数对"格式不对"是返回 invalid 而不是抛异常；
    真正的意外（比如 content 不是字符串）会在 run_agent_streamlit 里被 try 捕获。
    """
    answer = extract_finish(reply)
    if answer is not None:
        return "finish", answer

    action = parse_action(reply)
    if action is None:
        return "invalid", None
    return "action", action


# ---------------------------------------------------------------------------
# 核心循环
# ---------------------------------------------------------------------------
def run_agent_streamlit(user_query: str):
    """
    ReAct 主循环。注意：这是一个**生成器**，必须用 for 迭代才会真正执行。

    用法：
        for event in run_agent_streamlit("我想去三亚"):
            print(event["type"], event["content"])

    旧的 `run_agent_streamlit(prompt)` 直接 return 字符串的用法已经不再适用，
    对应的渲染逻辑搬到了 app.py 的 render_agent()。
    """
    messages = build_messages(user_query)

    for _step in range(MAX_STEPS):
        # 1) 让模型思考 + 决定动作
        try:
            response = _chat(messages)
        except Exception as e:
            yield {"type": "error", "content": f"调用大模型失败：{e}"}
            yield {"type": "final", "content": "抱歉，调用大模型失败，请稍后重试。"}
            return

        # 2) 解析这一步的输出：既可能是 Finish[...]，也可能是 Action: xxx(...)
        #    正则提取 + 类型兜底全部放进 try：
        #    - 格式不匹配：parse_step 返回 invalid，不抛异常
        #    - 意外情况（content 是 list/dict、正则内部报错等）：被 except 接住
        #    两种情况都统一回灌一条 Observation，让模型重新思考，绝不让程序崩掉。
        try:
            raw_content = response.choices[0].message.content
            reply = (raw_content or "").strip()
            if not reply:
                raise ValueError("模型返回内容为空")
            kind, payload = parse_step(reply)
        except Exception as e:
            # 情况 A：解析过程本身抛异常（比如 content 不是字符串）
            yield {"type": "error", "content": f"解析模型输出失败：{e}"}
            # 尽量把原始输出记进对话，保持 user/assistant 交替
            raw_text = raw_content if isinstance(raw_content, str) else str(raw_content or "")
            if raw_text.strip():
                messages.append({"role": "assistant", "content": raw_text.strip()})
            messages.append({"role": "user", "content": PARSE_ERROR_OBSERVATION})
            yield {"type": "observation", "content": PARSE_ERROR_TEXT}
            continue

        # 解析成功后才记录 assistant 回复，避免坏数据污染历史
        messages.append({"role": "assistant", "content": reply})
        yield {"type": "thought", "content": reply}

        # 2.1) 模型宣布结束
        if kind == "finish":
            yield {"type": "final", "content": payload}
            return

        # 2.2) 格式错误：Action 匹配失败，不是崩溃，而是提示模型重来
        if kind == "invalid":
            messages.append({"role": "user", "content": PARSE_ERROR_OBSERVATION})
            yield {"type": "observation", "content": PARSE_ERROR_TEXT}
            continue

        # 3) 执行工具
        func_name, args = payload

        if func_name not in available_tools:
            observation = f"没有找到名为 {func_name} 的工具，请重试。"
            messages.append({"role": "user", "content": f"Observation: {observation}"})
            yield {"type": "observation", "content": observation}
            continue

        yield {"type": "tool_call", "name": func_name, "args": args}
        try:
            observation = str(available_tools[func_name](**args))
        except Exception as e:
            observation = f"工具报错: {e}"
        yield {"type": "observation", "content": observation}
        messages.append({"role": "user", "content": f"Observation: {observation}"})

    # 4) 步数用尽
    yield {"type": "final", "content": "抱歉，思考次数超限，未能得出结论。"}
