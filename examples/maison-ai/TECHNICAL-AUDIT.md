# 教学技术栈与 Agent 自主性检查

日期：2026-10-30。

## 本次纠正的问题

此前为了压缩响应时间，把普通对话限制成 plan_dining_request 的固定意图枚举，再由 callback 调度业务并返回预写说明。这使“你可以做什么”也被迫选择菜单等流程。虽然 ADK、AG-UI 和 A2UI 协议真实运行，但 Agent 的对话判断被应用覆盖，不能作为合格的自主 Agent 交付。该路由及预写回复路径已删除。

## 当前分工

- **Agent**：使用 ADK LlmAgent 和 AUTO function calling，自行决定直接回答、澄清、调用哪些工具，以及是否需要界面。调用工具后，继续读取结果并用用户的语言组织回复。
- **FunctionTools**：提供实际菜单、菜品详情、推荐条件、购物车、热量、预订和报价等业务能力。不存在一个必须调用的意图分类工具。
- **Hooks**：保留真实工具事实，剔除界面传输 JSON，并完成 Agent 已选业务工具的界面契约；组件图由模型生成。hook 不返回预写的普通对话答案，不按自然语言关键词替模型路由。
- **明确按钮动作**：从经 schema 校验的 AG-UI forwardedProps 读取，ADK 执行准确动作一次，模型再解释结果。该回合不允许重复该按钮的副作用。
- **业务层**：校验价格来源、库存、选项、人数、报价过期、购物车版本、确认 token 和幂等。聊天文字不能绕过明确下单确认。

界面默认 dynamic：Agent 选中的界面业务工具通过异步 after-tool hook 在同一结果中返回模型组合的组件图；generate_a2ui 也可独立调用。生成器返回 JSON，经目录 schema、图引用及业务值校验后发出标准 A2UI v0.9 消息；不是服务器按意图选择预设页面。预定义的是可组合组件（包含通用 Form / Field），而不是完整页面。旧 fixed 模式及显式 Mock 教学示例仍可主动选择。

## 保留的协议与页面修复

- 前端使用 HttpAgent 消费真实 AG-UI SSE，业务按钮不再绕过协议访问独立 REST actions 端点，不伪造 tool result。
- A2UI v0.9 createSurface 不再错误进入等待队列，自定义按钮使用正确的 event dispatch 结构。
- Developer Inspector 展示真实工具调用、事件和 A2UI 消息。
- 较矮窗口的输入框固定；新回答开头自动进入可见区。
- Next.js 16.4.3、React / ReactDOM 19.3.1；新用户配置默认 Gemini，个人 .env 未改动。

## 验证及边界

当前后端 40 项测试通过，前端类型检查通过。此前针对强制意图流程的测试已替换为自主回答、工具后模型续答、能力问答无 UI、工具事实保留等检查，不以旧测试数量代表新行为正确。

此前固定 schema 的六项回归不能代表本次动态组合验收；本次实时结果以 .local/agent-behavior-report.json 和 .local/checkout-regression-report.json 的最终状态为准。真实点餐六步链路的较早记录与本次结账回归分别保留。详见 VERIFICATION.md 及本地 JSON 报告。模型回复可能仍有表达或事实错误；这些场景通过不代表任意开放问题都已穷尽验证。

当前界面采用演示 GPT “Now” 的居中消息流，工具结果对应的 A2UI 直接内嵌对话，不再置于右侧工作区。普通推荐此前被模型当成文字问卷；已纠正工具说明与 render_ui 的契约，没有增加自然语言关键词路由。DOT 仍偶发不遵循此指令，不能把一次通过视为稳定。浏览器已实测表单到三项推荐的真实更新。

本项目保存本地 Demo Orders，没有支付、真实厨房、配送或实时制作接口。预算约束按每个候选的建议份数总价检查，候选是替代选项。热量是基础配方乘数量的估算，不含定制选项变化。项目绑定 loopback，没有生产级认证，CopilotKit 当前路径的生产许可需另行核对。本次没有发布、部署或推送。

## 官方依据

- [ADK callbacks](https://github.com/google/adk-docs/blob/main/docs/callbacks/types-of-callbacks.md)
- [AG-UI architecture](https://docs.ag-ui.com/concepts/architecture)
- [ADK A2UI 固定与动态 schema](https://docs.showcase.copilotkit.ai/google-adk/generative-ui/a2ui/index)
- [Next.js 安全公告](https://nextjs.org/blog/nextjs-security-update-october-14-2026)

动态组合新增检查：无效组件、重复/循环/缺失引用、伪造总价和确认参数会被拒绝。JSON 格式修复仅处理编码及代码围栏，不补写页面内容；生成错误返回给模型修正。已移除额外执行审查模型和补调循环；由工具结果契约直接完成组合，generate_a2ui 内部仅允许一次图校验修正。

当前 DOT 动态行为回归仍有未通过项，详见 VERIFICATION.md。模型生成失败及输出预算问题保留为实际失败，没有以固定页面回退来掩盖，也没有将协议/样式单项通过当作全部 Agent 稳定性通过。


## 本轮 DOT 排查

直接 HTTP 与 LiteLLM 的合成请求对照证明，DOT 支持真实函数调用与 JSON 组件生成，但推荐意图的工具选择并不稳定。已去掉同时发送的 max_tokens / max_completion_tokens；JSON 模式通过请求上下文隔离，普通无工具回复不受影响。界面组合器使用服务端数据绑定，报价 token 不交给模型复制；生成数据不能覆盖业务数据。完整可修复错误包含真实菜品 ID 映射。Form 的重复提交按钮和嵌套 Form 会被拒绝并交模型修正。网络故障保留业务结果并报告界面失败。

本轮六项实际对话检查有一轮全部通过；后续浏览器推荐仍出现只承诺打开表单、实际未调用工具的失败。结账/纠错曾通过完整五步，但含糊的“需要”在最新回归中仍被误解为加菜；未降低断言或用固定话术改写答案。DOT 的语义行为尚未完整验收。预算案例自动检查验证了界面和数据源，人工检查还发现文字组合总价误算，故不能用自动绿色状态代表整段回复事实无误。
