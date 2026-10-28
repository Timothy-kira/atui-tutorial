# atui教学

这份仓库整理了本次 A2UI 餐厅 Agent 活动的基础材料，供课后阅读、运行和继续修改。

## 材料入口

- [活动图文讲义](docs/A2UI餐厅Agent图文稿.md)：按章节整理的讲解与 42 张页面、长回答和交互截图。
- [餐厅 Agent 示例](examples/maison-ai/README.md)：ADK、AG-UI 与 A2UI 的前后端集成代码，包含菜单数据、业务工具、组件目录和启动脚本。
- [动手步骤](examples/maison-ai/WORKSHOP.md)：课堂操作流程与练习。
- [前端交互演示](showcase/index.html)：Explore、Recommend、Explain、Order 的展示界面和本地图片。

## 先体验前端交互

前端展示使用本地模拟数据，无需 API Key，不会向真实餐厅提交订单。

在仓库根目录运行：

```sh
python -m http.server 8080 --bind 127.0.0.1
```

浏览器打开 http://127.0.0.1:8080/showcase/index.html 。可以浏览菜单，切换到 Agent，调整推荐条件、查看菜品详情和确认模拟自取订单。

## 运行完整 Agent 示例

环境要求：Python 3.12、uv、Node.js 22 和 pnpm。

```sh
cd examples/maison-ai
cp .env.example .env
python scripts/jobs.py start install
python scripts/jobs.py status install
```

Windows PowerShell 可用 `Copy-Item .env.example .env` 复制配置。依赖安装完成后：

```sh
python scripts/dev.py --background --mock
python scripts/dev.py --status
```

浏览器打开 http://127.0.0.1:3008 。Mock 模式使用脚本化模型；后端仍通过 ADK、AG-UI 和 A2UI 渲染链路运行。需要实时模型时，按示例 README 配置自己的服务端 API Key。

## 目录

```text
docs/                活动图文讲义和配套图片
examples/maison-ai/   完整餐厅 Agent 教学示例
showcase/            独立前端模拟展示
assets/logos/        展示指针素材
```

教学示例与成片中的前端模拟展示分别保留。完整视频、配音、个人凭据和本地订单数据不在本仓库中。菜品照片的来源见 `examples/maison-ai/frontend/public/images/sources.json`；照片仅用于示意。
