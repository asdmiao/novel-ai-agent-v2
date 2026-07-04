# 小说AI 飞书 Bot —— 实现方法解析

> 本文从代码层面剖析「小说AI 飞书 Bot」的实现方法：模块分层、启动流程、消息流转、命令路由、长任务异步执行、与 NovelAgent 的集成等。
>
> 平台配置、SDK 踩坑请见同目录的《飞书Bot接入指南.md》。

---

## 一、总体定位

飞书 Bot 是小说AI 的**移动端入口**，定位是「随时随地记录灵感 + 查看写作进度 + 推进章节生成」，而不是替代 CLI/WebUI 做大段正文编辑。

它通过飞书开放平台的**长连接模式**（WebSocket）与用户交互，**不需要公网 IP/域名/服务器**，本地 `python feishu_bot.py` 即可运行。

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  飞书用户（手机/桌面端）                                       │
│        │  发消息：#下一章  /  自由对话                          │
│        ▼                                                       │
│  飞书开放平台（长连接 wss://msg-frontier.feishu.cn）            │
│        │  WebSocket 双向推送                                    │
└────────┼──────────────────────────────────────────────────────┘
         │
┌────────▼──────────────────────────────────────────────────────┐
│  feishu_bot.py  ::  FeishuBot                                  │
│  ─────────────────────────────────                             │
│   • lark.ws.Client 维持长连接                                  │
│   • EventDispatcherHandler 注册事件回调                         │
│   • _on_message() : 解析文本 → 路由 → 即时回复                  │
│   • _run_task_async() : 长任务开线程执行，完成后主动推送         │
│   • send_text() : 调 im.v1.message.create 发消息（自动分段）    │
└────────┬──────────────────────────────────────────────────────┘
         │ 把文本消息转给路由器
┌────────▼──────────────────────────────────────────────────────┐
│  novel_agent/feishu/commands.py :: CommandRouter              │
│  ─────────────────────────────────                             │
│   • 与飞书 SDK 完全解耦（可单元测试）                            │
│   • 正则解析 #命令 / 无前缀自由对话                              │
│   • 调 NovelAgent 各方法，产出 CommandResult                    │
│   • CommandResult.is_task 标记是否长任务                        │
└────────┬──────────────────────────────────────────────────────┘
         │ 调用业务能力
┌────────▼──────────────────────────────────────────────────────┐
│  novel_agent/agents/NovelAgent                                 │
│   • write_chapter / search / stats / cost_summary / backup ... │
│   • 内部 LLM 后端（OpenAI 兼容 / Ollama）                       │
│   • 知识库（bible / continuity / outline / ideas / ...）       │
└──────────────────────────────────────────────────────────────┘
```

**分层职责**：
- `feishu_bot.py`：**传输层**。只管「收消息 / 发消息 / 跑后台线程」，不知道业务。
- `novel_agent/feishu/commands.py`：**协议层**。把文本解析成命令、把执行结果格式化成文本，但不直接碰飞书 SDK。
- `NovelAgent`：**业务层**。所有写作、查询、状态管理都在这里。

这种分层的好处是 `CommandRouter` 可以脱离飞书 SDK 独立测试（见 `tests/`）。

---

## 三、涉及的文件

| 文件 | 角色 | 行数 | 主要内容 |
|------|------|------|---------|
| `feishu_bot.py` | 传输层入口 | ~260 | `FeishuBot` 类：长连接、事件回调、异步任务、消息发送 |
| `novel_agent/feishu/__init__.py` | 包导出 | 5 | 导出 `CommandRouter`、`CommandResult` |
| `novel_agent/feishu/commands.py` | 协议层路由 | ~480 | `CommandRouter`：命令解析与各命令实现 |
| `novel_agent/config.py` | 配置 | ~70 | `Config.feishu` 属性读取 `feishu:` 段 |
| `config.yaml` | 配置文件 | — | `feishu:` 段（app_id / default_project / max_msg_chars / task_timeout） |
| `.env` | 密钥 | — | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` |

---

## 四、配置加载

### 4.1 配置来源（优先级从高到低）

1. 环境变量（`.env`）：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`
2. `config.yaml` 的 `feishu:` 段
3. 代码内默认值

### 4.2 config.yaml 示例

```yaml
feishu:
  app_id: ${FEISHU_APP_ID}        # 从 .env 展开
  app_secret: ${FEISHU_APP_SECRET}
  default_project: demo           # 不指定项目时的默认项目
  max_msg_chars: 2800             # 单条消息最大字符（超长自动分段）
  task_timeout: 600               # 长任务超时秒数（仅提醒，不杀线程）
```

### 4.3 配置展开机制

`Config` 在加载 yaml 后，通过 `_expand()` 递归把所有 `${VAR}` 占位符替换成环境变量值（见 `config.py:17-25`），所以 yaml 里可以写 `${FEISHU_APP_ID}`，实际值从 `.env` 读取。

### 4.4 Bot 端的取值（`feishu_bot.py:53-62`）

```python
fcfg = self.config.feishu
self.app_id      = fcfg.get("app_id", "")
self.app_secret  = fcfg.get("app_secret", "")
self.task_timeout = int(fcfg.get("task_timeout", 600))
self.max_chars    = int(fcfg.get("max_msg_chars", 2800))
self.router       = CommandRouter(self.config)
```

启动时强校验：缺 App ID/Secret 直接 `raise RuntimeError`，避免静默失败。

---

## 五、启动流程

```
python feishu_bot.py
   │
   ├─ main() → FeishuBot() 构造
   │     ├─ 读取 config.feishu
   │     ├─ 校验 app_id / app_secret 非空
   │     ├─ new CommandRouter(config)
   │     └─ lark.Client.builder()...build()  ← 发消息用的 HTTP client
   │
   └─ bot.run()
         ├─ 构造 EventDispatcherHandler：
         │     register_p2_im_message_receive_v1(_on_message)     ← 接收消息
         │     register_p2_im_message_message_read_v1(_on_read)   ← 已读（避免 processor not found 噪音）
         │
         ├─ lark.ws.Client(app_id, app_secret, event_handler=handler)
         │
         └─ cli.start()  ← 阻塞，维持 WebSocket 长连接，自动重连
```

**关键设计**：
- **两个事件都要注册**：飞书在推送「接收消息」的同时也会推「消息已读」。如果只注册前者，后者会在日志里刷 `processor not found`。`_on_read` 只打印一行，不处理。
- **长连接靠 `lark.ws.Client`**：底层是 WebSocket，断线自动重连，无需自己实现心跳。

---

## 六、消息接收与处理流程

### 6.1 收到消息后的完整时序

```
飞书 ─(ws)─> _on_message(data)
   │
   ├─ 1. 取 chat_id，缓存到 self._recent_chat_id（便于异常时回退）
   │
   ├─ 2. 过滤：msg_type != "text" → 回复提示并返回
   │
   ├─ 3. json.loads(msg.content)，取 content["text"]  ⚠️ key 是 "text" 不是 "content"
   │
   ├─ 4. 去掉 @机器人 的占位符：re.sub(r"@_user_\d+", "", text)
   │
   ├─ 5. result = router.handle(text)
   │      ├─ 文本以 # 或 / 开头  → 命令模式
   │      └─ 否则                 → 自由对话模式（写作教练）
   │
   ├─ 6. send_text(chat_id, result.text)   ← 先给即时反馈
   │
   └─ 7. if result.is_task:
            _run_task_async(chat_id, result)   ← 后台跑写章，完成后推送
```

### 6.2 关键坑点（代码里有处理）

| 坑 | 处理位置 | 处理方式 |
|----|---------|---------|
| 文本消息 content 的 key 是 `text` 不是 `content` | `feishu_bot.py:134-135` | `content.get("text") or content.get("content")` 双兜底 |
| `@机器人` 会在文本里留下 `@_user_1` | `feishu_bot.py:137-139` | 正则 `@_user_\d+` 去除 |
| Windows 控制台默认 GBK，中文乱码 | `feishu_bot.py:28-37` | 启动时强制把 stdout/stderr 重包成 UTF-8 |
| chat_id 取不到 | `feishu_bot.py:158` | 异常分支用缓存的 `_recent_chat_id` 兜底 |
| 长任务期间用户长时间无反馈 | `feishu_bot.py:204-212` | 看门狗线程，超时发提醒（不杀任务） |

### 6.3 异常隔离

`_on_message` 整体包在 `try/except` 里，任何解析/路由异常都不会让长连接挂掉，而是把错误信息发回飞书：

```python
except Exception as e:
    traceback.print_exc()
    self.send_text(chat_id, f"⚠️ 处理出错：{e}")
```

---

## 七、命令路由：CommandRouter

`CommandRouter`（`novel_agent/feishu/commands.py`）是飞书与业务的桥梁，**完全独立于飞书 SDK**，只接受纯文本、返回 `CommandResult`，便于单元测试。

### 7.1 CommandResult 数据结构

```python
@dataclass
class CommandResult:
    text: str = ""          # 即时回复文本
    is_task: bool = False   # 是否长任务（需异步执行 + 推送）
    task_kind: str = ""     # 任务类型："write" 等
    task_args: dict = ...   # 任务参数（chapter_id / project）
    project: str = ""       # 命中/切换的项目名
```

**核心约定**：即时回复靠 `text`；需要后台跑的长任务把 `is_task=True` 抛给 bot 层，bot 层据此开线程。

### 7.2 命令解析逻辑（`handle()`，行 94-155）

```
text = "#下一章 mybook"
   │
   ├─ 正则匹配：^[#/]\s*([^\s]+)\s*(.*)$
   │     cmd  = "下一章"
   │     rest = "mybook"
   │
   ├─ _parse_project(rest)  ← 从参数末尾抠项目名
   │     project   = "mybook"
   │     rest_args = ""
   │
   ├─ handlers 表查找：cmd → _cmd_next_chapter
   │
   └─ handler(project, rest_args) → CommandResult
```

**无命令前缀**的消息走 `_chat()`，进入「自由对话模式」（见第八节）。

### 7.3 命令路由表

`handlers` 是一张 `dict[str, Callable]`，**中英双语 + 别名**同时支持（行 116-148）：

| 业务 | 中文命令 | 英文命令 | 别名 | 实现方法 | 是否长任务 |
|------|---------|---------|------|---------|-----------|
| 帮助 | `#帮助` | `#help` | `#?` `#？` | 内联 HELP_TEXT | ❌ |
| 切换项目 | `#项目` | `#project` | — | `_cmd_project` | ❌ |
| 记录灵感 | `#想法` | `#idea` | `#灵感` | `_cmd_idea` | ❌ |
| 灵感列表 | `#想法列表` | `#idealist` | — | `_cmd_idea_list` | ❌ |
| **写下一章** | `#下一章` | `#next` | — | `_cmd_next_chapter` | ✅ |
| 进度 | `#进度` | `#progress` | — | `_cmd_progress` | ❌ |
| 大纲 | `#大纲` | `#outline` | — | `_cmd_outline` | ❌ |
| 预览章节 | `#预览` | `#preview` | — | `_cmd_preview` | ❌ |
| 搜索 | `#搜索` | `#search` | — | `_cmd_search` | ❌ |
| 设定集 | `#设定` | `#bible` | — | `_cmd_bible` | ❌ |
| 连续性 | `#连续性` | `#continuity` | — | `_cmd_continuity` | ❌ |
| 节奏 | `#节奏` | `#pacing` | — | `_cmd_pacing` | ❌ |
| 文风 | `#文风` | `#style` | — | `_cmd_style` | ❌ |
| 知识库 | `#知识库` | `#kb` | — | `_cmd_kb` | ❌ |
| 成本 | `#成本` | `#cost` | — | `_cmd_cost` | ❌ |
| 备份 | `#备份` | `#backup` | — | `_cmd_backup` | ❌ |

未知命令 → 返回 `未知命令：#xxx`，提示发 `#帮助`。

### 7.4 项目名解析（`_parse_project`，行 158-166）

约定：**命令参数末尾的连续英文/数字/`_-` 标记符视为项目名**。例如：

```
#下一章 mybook          → cmd=下一章, project=mybook
#想法 主角觉醒 #转折     → cmd=想法, project=default, content="主角觉醒 #转折"
```

实现是正则 `\s+([A-Za-z0-9_\-]+)\s*$` 从末尾抠。抠不到就用默认项目。

### 7.5 灵感命令的特殊解析（`_cmd_idea`，行 198-224）

灵感命令的参数本身带 `#标签` 和 `@人物`，所以解析方式特殊：

```python
tags    = re.findall(r"#([^\s#@]+)", args)   # #转折 → 标签
chars   = re.findall(r"@([^\s#@]+)", args)   # @林尘 → 人物
content = re.sub(r"[#@][^\s#@]+", "", args)  # 剩下的就是正文
```

最终调 `agent.kb.add_idea(content, tags=tags, related_chars=chars, priority=3)`。

### 7.6 输出长度控制（`_truncate`，行 171-177）

飞书单条消息有长度限制，超过 `max_msg_chars`（默认 2800）就截断并附提示：

```
……（共 12345 字，已截断。用 CLI 查看完整内容）
```

---

## 八、自由对话模式（写作教练）

当消息**没有 `#` / `/` 前缀**时，`_chat()` 会进入自由对话模式：Bot 化身「小说写作教练」，回答用户的任何写作相关问题。

### 8.1 实现（`_chat`，行 422-453）

```python
messages = [
    Message("system", f"""你是一位资深的小说写作教练与创意伙伴 …
        {ctx}"""),               # ← 注入当前小说上下文
    Message("user", text),
]
reply = backend.chat(messages, temperature=0.85, max_tokens=1200)
```

### 8.2 上下文注入（`_build_chat_context`，行 455-480）

为了让 LLM 知道用户「在写什么书」，会注入当前项目的元信息：

- 书名、题材、logline、简介、世界观
- 主要人物列表
- 已完成 / 待写章节数

这样对话才有针对性——LLM 知道角色名、知道剧情进展。

### 8.3 后端延迟构建

```python
def _get_backend(self):
    if self._backend is None:
        from ..llm import build_backend
        self._backend = build_backend(self.config)
    return self._backend
```

LLM backend 是懒加载的：只有用户第一次发自由对话时才构造，避免启动慢和没用到的连接。

---

## 九、长任务异步执行（核心机制）

「写下一章」是 1-3 分钟的长任务，飞书的 WebSocket 长连接等不起。本项目用**「即时回复 + 后台线程 + 完成后主动推送」**模式解决。

### 9.1 触发链路

```
用户发 "#下一章"
   │
   ▼
CommandRouter._cmd_next_chapter()
   │ 找到下一个 pending 章节
   │ 不在这里跑写作（怕卡住连接）
   ▼
返回 CommandResult(
    text      = "⏳ 开始写 c005 《...》…",
    is_task   = True,
    task_kind = "write",
    task_args = {"chapter_id": "c005", "project": "demo"},
)
   │
   ▼
feishu_bot._on_message()
   ├─ 立刻 send_text("⏳ 开始写...")   ← 用户先看到反馈
   └─ _run_task_async(chat_id, result) ← 后台开干
```

### 9.2 后台执行（`_run_task_async`，行 163-212）

```python
def _worker():
    agent = NovelAgent.open(project, self.config)
    r = agent.write_chapter(chapter_id, review=True, verbose=False)
    # 组装结果消息：字数/用时/摘要/状态追踪/审校/正文预览
    self.send_text(chat_id, msg)

threading.Thread(target=_worker, daemon=True).start()
```

**daemon=True**：主进程退出时后台线程自动结束，不留僵尸。

### 9.3 看门狗（超时提醒）

```python
def _watchdog():
    time.sleep(self.task_timeout)   # 默认 600s
    if t.is_alive():
        self.send_text(chat_id, "⏰ 任务已运行 600s 仍在进行，DeepSeek 可能较慢，请稍候。")

threading.Thread(target=_watchdog, daemon=True).start()
```

注意：**看门狗只提醒，不杀任务**——因为写作中途杀线程会破坏数据一致性。如果用户想中断，得手动停服务。

### 9.4 完成后的推送消息格式

写完后主动推送一条富信息消息：

```
✅ 章节 c005 《觉醒》已完成（2512字，用时 87s）

📝 摘要：林尘在悬崖……

🔍 状态追踪：更新 3 人物，新增 5 条连续性记录

⚠️ 偏离大纲[轻微]：开篇节奏略快……
📋 审校评分：8/10
……

--- 正文预览（前 600 字）---
……
```

---

## 十、消息发送机制

### 10.1 发送 API（`send_text`，行 215-243）

```python
req = (CreateMessageRequest.builder()
       .receive_id_type("chat_id")          # 用 chat_id 定位会话
       .request_body(CreateMessageRequestBody.builder()
           .receive_id(chat_id)
           .msg_type("text")
           .content(json.dumps({"text": chunk}))   # ← key 必须是 "text"
           .build())
       .build())
resp = self.lark_client.im.v1.message.create(req)
```

要点：
- 用 `chat_id` 定位会话（来自收到消息的事件，**不需要存 open_id**）
- content 是 JSON 字符串，key 必须是 `"text"`
- 失败检查 `resp.success()`，失败打印 code/msg

### 10.2 自动分段（`_split`，行 245-252）

飞书单条消息有长度限制，超过 `max_msg_chars` 就按字符等分，**逐段发送，段间 sleep 0.3s** 避免触发频率限制：

```python
for chunk in chunks:
    ... send ...
    time.sleep(0.3)
```

### 10.3 主动推送 vs 被动回复

本项目**统一用 chat_id 发送**，不区分「被动回复」和「主动推送」——只要持有 chat_id 就能随时给用户发消息。chat_id 来自最近一次收到的消息事件，存在 `self._recent_chat_id`。

> ⚠️ 局限：bot 重启后 `_recent_chat_id` 丢失，得等用户再发一条消息才能恢复推送能力。如果需要 bot 重启后主动找用户，得持久化 chat_id 或改用 open_id。

---

## 十一、与 NovelAgent 的集成

`CommandRouter` 几乎每个命令都通过 `self._open(project)` 拿到一个 `NovelAgent` 实例再调用业务方法：

```python
def _open(self, project: str) -> NovelAgent:
    return NovelAgent.open(project or self.default_project, self.config)
```

各命令对应的 NovelAgent 方法：

| 命令 | NovelAgent 调用 |
|------|----------------|
| `#下一章` | `agent.outline.all_chapters()` 找 pending；后台 `agent.write_chapter(cid, review=True)` |
| `#进度` | `agent.stats()` |
| `#大纲` | `agent.outline.render_for_prompt()` |
| `#预览` | `agent.store.read_chapter()` / `agent.outline` |
| `#搜索` | `agent.search(kw, top_k=8)` |
| `#设定` | `agent.bible.render_for_prompt()` |
| `#连续性` | `agent.view_continuity()` |
| `#节奏` | `agent.view_pacing()` |
| `#文风` | `agent.view_style()` |
| `#知识库` | `agent.kb.render_full()` |
| `#成本` | `agent.cost_summary()` |
| `#备份` | `agent.backup()` |
| `#想法` | `agent.kb.add_idea(...)` |
| `#想法列表` | `agent.kb.ideas.available()` |
| 自由对话 | `backend.chat(...)` + `agent.outline/bible/project` 注入上下文 |

**注意**：`NovelAgent.open()` 每次调用都会重新从磁盘加载 JSON（bible/outline/...），保证看到最新数据；代价是命令处理有点 IO 开销，但飞书交互频率低，可接受。

---

## 十二、设计要点小结

1. **分层解耦**：传输层（`feishu_bot.py`）→ 协议层（`commands.py`）→ 业务层（`NovelAgent`）。协议层完全可单元测试。

2. **长连接替代 Webhook**：无需公网 IP，本地即可跑。代价是必须保持进程常驻。

3. **即时反馈 + 异步推送**：长任务先回「⏳ 开始写」，后台跑完再推结果，避免阻塞 WebSocket。

4. **看门狗不杀任务**：超时只提醒，因为写作中途强杀会破坏数据。

5. **统一 chat_id 发送**：简化模型——收到消息后就能随时回复，无需额外存 open_id。

6. **中英双语 + 别名命令**：`#下一章` = `#next`，`#想法` = `#idea` = `#灵感`，用户体验更宽容。

7. **自由对话兜底**：无命令前缀的消息进入「写作教练」模式，bot 不只是命令面板，还是创意伙伴。

8. **懒加载 + 异常隔离**：LLM backend 懒加载；`_on_message` 整体 try/except，任何错误都不会让长连接挂掉。

---

## 十三、可能的改进方向

- **chat_id 持久化**：重启后仍能主动推送（当前重启后丢失）。
- **任务队列**：用 `concurrent.futures.ThreadPoolExecutor(max_workers=N)` 限制并发写作，避免多用户同时写时 LLM 限流。
- **任务状态查询**：`#任务` 命令查看当前在跑哪些任务、进度几何。
- **流式输出**：长任务期间分段推送进度（如「正在生成正文… 50%」），提升等待体验。
- **富文本卡片**：用飞书 interactive card 代替纯文本，进度条/按钮交互更友好。
- **多用户隔离**：目前所有用户共享 `default_project`，可按用户 open_id 维护各自的项目映射。
