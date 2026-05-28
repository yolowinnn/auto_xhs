# auto_xhs

一套可复用的小红书自动发布 pipeline：每天把素材(视频/图片)和一份 `brief` 丢进去，
自动生成**竖屏视频(配音+字幕)** 或 **图文轮播**，经审核后一键/定时发布到小红书。

```
素材 + brief.yaml
   └─▶ 脚本生成(LLM 可选, 无 key 用手写稿)
        └─▶ 配音 edge-tts(免费, 带句级时间戳)
             └─▶ 合成 ffmpeg(统一 9:16 / 拼接 / 混音)
                  └─▶ 烧字幕 + 封面大字(libass .ass)
                       └─▶ 发布 xiaohongshu-mcp(审核闸门 / 全自动)
                            └─▶ cron 每日调度 + 状态记录(不重复发)
```

## 技术选型(为什么这么搭)
- **发布**：[`xpzouying/xiaohongshu-mcp`](https://github.com/xpzouying/xiaohongshu-mcp) —— 扫码登录一次、cookie 持久化，支持图文+视频，用真实网页 JS 生成签名(绕过签名难题)，本地起 REST 服务(`:18060`)。官方开放平台只对企业开放，个人发不了，故不用。
- **配音**：[edge-tts](https://pypi.org/project/edge-tts/) —— 免费、中文自然、零账号；中文音色会吐**句级时间戳**，字幕据此切分对齐，无需再跑 Whisper。要更高音质可后续切火山引擎/Fish Audio。
- **视频**：`ffmpeg`(subprocess 驱动)。字幕和封面大字统一用带样式的 `.ass`(libass 渲染 CJK 干净、可描边/加底框)。
- **脚本**：可接 Anthropic API 自动写文案;没有 key 就用 `brief.yaml` 里手写的 `script`，pipeline 照常跑。

## 一次性安装

```bash
bash scripts/setup.sh        # 装 Python 依赖、ffmpeg-full、下载 xhs-mcp 二进制、生成配置
python run.py login          # 启动服务后用此命令取二维码，用小红书 App 扫码登录
bash scripts/start_mcp.sh    # 启动发布服务(保持运行); 后台运行加 --bg
python run.py doctor         # 自检：ffmpeg(libass)/edge-tts/字体/登录态 全绿即可
```

> 关键依赖：小红书发布服务需要一个带 `libass` 的 ffmpeg。`setup.sh` 会装 Homebrew 的
> `ffmpeg-full`(keg-only，代码自动识别其路径 `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`)。

## 每天的用法

```bash
python run.py new 2026-05-28          # 在 input/2026-05-28/ 生成 brief.yaml 模板
# 把当天的视频/图片拷到 input/2026-05-28/，编辑 brief.yaml
python run.py generate 2026-05-28     # 生成成片到 output/2026-05-28/ (--preview 顺便打开)
python run.py preview  2026-05-28     # 打开成片并打印标题/正文/标签
python run.py publish  2026-05-28     # 审核后发布(默认会让你确认; --auto 跳过确认)
```

`brief.yaml` 写法见 [`examples/brief.video.yaml`](examples/brief.video.yaml) 和
[`examples/brief.carousel.yaml`](examples/brief.carousel.yaml)。`type` 支持 `video` / `carousel` /
`auto`(有视频素材走视频，否则走图文)。封面大字用 `hook`，文案用 `body`/`script`。

## 发布模式与可见范围
- `config.yaml` 里 `publish.mode`：
  - `review`(默认)——生成后需人工确认才发；非交互(cron)环境下只生成、留给你手动 `publish`。
  - `auto`——直接发布。或在命令后加 `--auto`。
- `visibility`：`公开可见`(默认) / `仅自己可见` / `仅互关好友可见`。
  **首次建议用 `仅自己可见` 发一条真机验证**，确认效果后再公开。
- 平台硬限制：标题 ≤20 字、正文 ≤1000 字、每天别超 ~50 条(代码已做截断保护)。

## 定时发布(cron)

```bash
bash scripts/install_cron.sh          # 每天 10:00 只生成、等你审核(匹配 review 模式)
HOUR=9 MIN=30 bash scripts/install_cron.sh
AUTO=1 bash scripts/install_cron.sh    # 生成并自动发布(需发布服务常驻+已登录)
```

全自动发布还可用小红书原生**定时发布**：`python run.py publish <DATE> --schedule 2026-05-28T20:00:00`。

## 配置速览(`config/config.yaml`)
- `tts.voice`：`zh-CN-XiaoxiaoNeural`(女·温暖) / `zh-CN-YunxiNeural`(男·阳光) / `zh-CN-XiaoyiNeural`(女·年轻)；`rate: "+8%"` 让语速更适合短视频。
- `captions`：字幕/封面大字的字号、颜色、描边、底框、位置；`max_chars_per_cue` 控制单条字幕长度。
- `ffmpeg.encoder`：`libx264`(画质，默认) 或 `h264_videotoolbox`(草稿快出)；`ken_burns: true` 给图片加缓慢推拉。
- `llm`：`provider: anthropic` + 设 `ANTHROPIC_API_KEY`(或根目录放 `.anthropic_key`)即开启自动写文案；`prompts/system_prompt.md` 是可改的“系统提示词”。

## 排错
- `doctor` 显示 ffmpeg 缺 `ass` 滤镜 → `brew install ffmpeg-full`。
- 发布报“not logged in” → cookie 过期，重跑 `python run.py login` 扫码。
- edge-tts 偶发 403 → 是按 IP 限流，代码已串行+退避重试；别并发狂调。
- 发布服务首次启动会下载约 150MB 无头浏览器，第一次调用登录相关接口会慢，属正常。

## 目录结构
```
autoxhs/      核心模块: ingest / script / tts / captions / assemble / carousel / publish / pipeline
prompts/      系统提示词模板(脚本生成)
config/       config.example.yaml(模板) → config.yaml(本地, 不入库)
scripts/      setup / login / start_mcp / install_cron
input/        每日素材 input/<DATE>/ (不入库)
output/       成片 output/<DATE>/ (不入库)
state/        posted.json 发布记录 + 日志 (不入库)
vendor/       xiaohongshu-mcp 二进制 (不入库)
run.py        命令行入口
```
```bash
python run.py --help     # 查看全部子命令
```
