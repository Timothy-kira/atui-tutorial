# atui教学

本仓库用于整理 A2UI 餐厅 Agent 活动的配套材料。

仓库中的 `examples/maison-ai` 是可运行的参考实现；后续会补充精简的学员起始代码。

为了方便大家，如果 token 不够的话，可以以这个项目为基础开始构建。但是，我建议大家自己从 0 搭建。

教学主入口是完整 ADK、AG-UI 与 A2UI 应用。视频录制用的纯前端模拟页面不作为技术实现依据。

## 材料入口

- [活动图文讲义](docs/A2UI餐厅Agent图文稿.md)：按章节整理的讲解与 42 张页面、长回答和交互截图。
- [餐厅 Agent 参考示例](examples/maison-ai/README.md)：ADK、AG-UI 与 A2UI 的前后端集成参考，包含菜单数据、业务工具、组件目录和启动脚本。
- [动手步骤](examples/maison-ai/WORKSHOP.md)：课堂操作流程与练习。
- [本地启动说明页](showcase/index.html)：引导启动完整应用，不模拟 Agent 回复。

## 运行完整 Agent 示例

环境要求：Python 3.12、uv、Node.js 22 和 pnpm。

```sh
cd examples/maison-ai
cp .env.example .env
python scripts/jobs.py start install
python scripts/jobs.py status install
```

Windows PowerShell 可用 `Copy-Item .env.example .env` 复制配置。在 `.env` 中设置 `GOOGLE_API_KEY`，默认 `MODEL_PROVIDER=gemini`。依赖安装完成后：

```sh
python scripts/dev.py --background
python scripts/dev.py --status
```

浏览器打开 http://127.0.0.1:3008 。API Key 只在 Python 服务端读取。没有模型 Key 时可显式使用 `python scripts/dev.py --mock --background`；此模式会显示 Mock Mode，模型决策是脚本化的，ADK 执行、AG-UI 事件、A2UI 渲染及数据库仍然真实运行。不会静默回退为假对话。

## Hands-on 练习

希望大家结合移动端的实际使用情况，优化页面布局和交互，并按照自己的理解改进功能、重新设计界面，做出自己的版本。

## 实际技术链路

```text
React / CopilotKit + A2UI renderer
  ↔ AG-UI HttpAgent / SSE
  ↔ FastAPI + ag-ui-adk
  ↔ Google ADK Agent / FunctionTools
  ↔ 菜单 JSON、SQLite 购物车和订单
```

默认采用动态 A2UI：ADK Agent 读取实际业务记录后，可调用 generate_a2ui，由模型选择、组合组件图，再经校验发送给官方 renderer。预定义的是组件目录，完整页面由模型生成。界面可包含通用 Form / Field、两列菜品卡片、表格、订单确认或纠错内容。hook 完成已选工具的界面契约及业务检查，不按自然语言关键词替模型分派页面，也不预写聊天答案。按钮仍通过同一 AG-UI 流的 forwardedProps 由真实 ADK 工具执行。

默认 MAISON_UI_MODE=dynamic 使用模型 JSON 组合器，避免当前兼容服务复杂函数参数生成的问题；不是早期的固定页面映射或实验私有 SDK 包装。MAISON_UI_MODE=fixed 可显式选择保留的固定 schema 教学路径。正常聊天及要求不要卡片时仍可只回答文字。

本项目固定使用与 renderer 匹配的 **A2UI v0.9**。讲义中简化的 JSON 是概念示例，不能直接当作 v0.9 消息复制。组件目录和固定 schema 是 A2UI 的合法使用方式，与纯前端模拟对话不同。

价格、库存和热量由后端数据计算；下单需要明确确认、有效报价、未变化的购物车和幂等键。推荐预算针对每个候选的建议份数总价，候选之间是替代关系，不代表把所有候选相加的一顿饭。订单和预订只保存到本地，没有支付、真实厨房或实时制作状态接口。

## 目录

```text
docs/                活动图文讲义和配套图片
examples/maison-ai/   完整餐厅 Agent 教学示例
showcase/            完整应用的本地启动入口及历史录制素材
assets/logos/        展示指针素材
```

教学应用与成片录制素材分别保留。`showcase` 入口已不加载旧模拟脚本；原视频工程的 `video/showcase` 保持录制用途。本地 loopback 教学应用没有生产级身份认证，不能直接作为公共点餐服务部署。完整视频、配音、个人凭据和本地订单数据不在本仓库中。菜品照片的来源见 `examples/maison-ai/frontend/public/images/sources.json`；照片仅用于示意。
