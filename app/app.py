# app.py
"""
界面层（Streamlit UI）
----------------------
职责：只负责"长什么样"——页面配置、聊天历史、输入框、把 agent_core 的事件画出来。
这里不出现任何 Prompt、API Key、工具实现、正则解析。

启动方式（在本文件所在目录执行）：
    streamlit run app.py
"""

import streamlit as st

# 只从核心层拿"逻辑"，UI 不碰 tools / prompts
from agent_core import run_agent_streamlit


def render_agent(prompt: str) -> str:
    """
    消费 agent_core 产出的事件流，把它们渲染成网页上的思考过程。
    返回最终答案字符串，供调用方写入聊天历史。
    """
    final_answer = ""

    try:
        with st.status("🤖 智能体正在思考中...", expanded=True) as status:
            for event in run_agent_streamlit(prompt):
                kind = event.get("type")

                if kind == "thought":
                    # 把模型这一步的 Thought/Action 打印在折叠框里
                    st.markdown(event["content"])

                elif kind == "tool_call":
                    st.write(f"⚙️ 正在调用工具: `{event['name']}`...")

                elif kind == "observation":
                    st.write(f"📋 工具返回: {event['content']}")

                elif kind == "error":
                    st.error(event["content"])

                elif kind == "final":
                    final_answer = event["content"]
                    status.update(
                        label="✅ 思考完成！", state="complete", expanded=False
                    )
    except Exception as e:
        st.error(f"运行出错：{e}")

    return final_answer or "抱歉，本次没有生成有效回答。"


def main() -> None:
    st.set_page_config(page_title="AI 旅行助手", page_icon="✈️")
    st.title("✈️ 智能旅行规划 Agent")
    st.caption("基于 DeepSeek + ReAct 架构 | 考核展示版")

    # 初始化聊天历史
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 渲染历史聊天记录（刷新页面后仍然保留）
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 聊天输入框
    if prompt := st.chat_input("例如：我想去三亚玩，帮我看看天气和推荐景点"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            final_result = render_agent(prompt)
            st.markdown(final_result)

        st.session_state.messages.append(
            {"role": "assistant", "content": final_result}
        )


if __name__ == "__main__":
    main()
