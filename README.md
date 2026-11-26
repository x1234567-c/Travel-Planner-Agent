# ✈️ 智能旅行规划 Agent

基于 **DeepSeek + ReAct 架构** 的旅行助手：输入目的地和需求，Agent 会自动查天气、找景点、推美食，并在推荐前对地点做交叉验证，最后汇总成一份旅行建议。

## 功能

- 三件工具：`get_weather`（实时天气）、`get_attraction`（按天气推荐景点）、`get_food`（特色美食）
- 防幻觉：推荐地点前先用 `verify_places` 交叉验证，查不到的地方会被剔除
- ReAct 循环：模型输出 `Thought / Action`，程序执行工具后把 `Observation` 回灌，直到 `Finish`
- 输出解析容错：格式不匹配时回灌提示让模型重试，不会让程序崩溃
- Streamlit 聊天界面：思考过程折叠展示，聊天历史保留

## 界面展示
<img width="1275" height="734" alt="屏幕截图 2026-11-26 191810" src="https://github.com/user-attachments/assets/e45e2fbb-5922-4ab6-a1fe-441f29ef79d3" />


## 项目结构

```
├── app.py           # UI 层：Streamlit 页面、聊天记录、事件渲染
├── agent_core.py    # 逻辑层：ReAct 循环、输出解析、工具调度（不依赖 UI）
├── prompts.py       # 提示词层：AGENT_SYSTEM_PROMPT
├── tools.py         # 工具层：天气 / 景点 / 美食 + available_tools 注册表
├── verify.py        # 防幻觉层：地点交叉验证（社交平台检索 + 可选高德 POI）
├── .env.example     # 环境变量模板（复制成 .env 后填 Key）
├── requirements.txt # 依赖清单
└── .gitignore
```

依赖方向单向：`app.py → agent_core.py → prompts.py / tools.py / verify.py`，无循环导入。

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
| `AMAP_API_KEY`（可选） | 高德 POI 校验，不填也能用 | https://lbs.amap.com/dev/key |

代码中不包含任何明文 Key，缺少变量时会直接报错并提示配置方式。

## 防幻觉：地点交叉验证

大模型会一本正经地推荐不存在的地方。`verify.py` 在推荐前做一次外部核验：

| 数据源 | 作用 | 是否必需 |
|---|---|---|
| Tavily 站内检索 | 统计小红书 / 大众点评 / 马蜂窝 / 携程 / 知乎 / B站 / 百度百科 等平台上是否**真的有页面提到该地名** | 必需（用已有 Key） |
| 高德 POI | 官方 POI 库，命中基本可确认地点存在 | 可选，配 `AMAP_API_KEY` |

判定规则：页面必须真的出现该地名才算一次提及（防止通用攻略页让虚构地点蒙混过关）。

```
得分 = 高德命中(3) + 多平台提及(1~3) + 正文出现名称(1)
✅ 已验证 ≥3   🟢 较可信 =2   🟡 存疑 =1   ❌ 未找到 =0
```

提示词里强制要求：推荐前先调 `verify_places`，只写 ✅/🟢 的地点，❌ 必须删除。

**已知边界**：只能验证“地点真实存在”，不能保证“值得去”；小众地点在社交平台曝光少，
可能被判 🟡/❌，属于漏杀（假阴性），可配置高德 Key 提高召回。小红书/抖音没有对个人
开放的搜索 API，站内检索是唯一稳定可行的入口。

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
