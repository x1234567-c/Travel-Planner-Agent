# ✈️ 智能旅行规划 Agent

基于 **DeepSeek + ReAct 架构** 的旅行助手：输入目的地和需求，Agent 会自动查天气、找景点、推美食，最后汇总成一份旅行建议。

## 功能

- 三件工具：`get_weather`（实时天气）、`get_attraction`（按天气推荐景点）、`get_food`（特色美食）
- ReAct 循环：模型输出 `Thought / Action`，程序执行工具后把 `Observation` 回灌，直到 `Finish`
- 输出解析容错：格式不匹配时回灌提示让模型重试，不会让程序崩溃
- Streamlit 聊天界面：思考过程折叠展示，聊天历史保留

## 项目结构

```
├── app.py            # UI 层：页面配置、聊天记录、事件渲染（只依赖 streamlit）
├── agent_core.py     # 逻辑层：ReAct 循环、输出解析、工具调度（不依赖 streamlit）
├── prompts.py        # 提示词层：AGENT_SYSTEM_PROMPT
├── tools.py          # 工具层：天气 / 景点 / 美食 + available_tools 注册表
├── .env.example      # 环境变量模板（复制成 .env 后填 Key）
├── requirements.txt  # 依赖清单
└── .gitignore
```

依赖方向单向：`app.py → agent_core.py → prompts.py / tools.py`，无循环导入。

`agent_core.run_agent_streamlit()` 是一个事件生成器，`yield` 出
`thought / tool_call / observation / error / final` 五类事件，UI 层负责渲染，
因此核心逻辑可以脱离 Streamlit 单独测试。

## 快速开始

```bash
# 1. 克隆
git clone <your-repo-url>
cd <repo-name>

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 Key
cp .env.example .env        # Windows: Copy-Item .env.example .env
# 编辑 .env，填入下面两个 Key

# 4. 启动
python -m streamlit run app.py
```

浏览器打开 http://localhost:8501 。

## 环境变量

| 变量名 | 说明 | 获取地址 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 模型调用 | https://platform.deepseek.com |
| `TAVILY_API_KEY` | Tavily 联网搜索（景点 / 美食） | https://tavily.com |

代码中不包含任何明文 Key，缺少变量时会直接报错并提示配置方式。

## 使用示例

- `三亚今天天气怎么样？`
- `我想去成都玩，帮我看看天气并推荐3个景点`
- `西安有什么必吃的美食？`
- `我下周末去杭州，天气如何？顺便推荐景点和美食`

## 技术栈

Python · Streamlit · OpenAI SDK（兼容 DeepSeek）· Tavily · wttr.in · python-dotenv

## 说明

- 本次提交未包含 `.env`，请自行申请 Key。
- 天气数据来自 wttr.in，景点 / 美食答案由 Tavily 检索后总结，仅供参考。

## License

如无特殊说明，本项目仅用于课程作业 / 学习交流。
