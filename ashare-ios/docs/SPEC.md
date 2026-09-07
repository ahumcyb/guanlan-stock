# 观澜 iPhone 版规格

## 目标与已确认范围

用户希望在 iPhone 获得与现有 Mac 软件相同的选股效果，使用普通 Apple ID 在个人设备安装。使用原生 SwiftUI，最低 iOS 17，支持 iPhone 与 iPad。复用 Mac 的数据模型、四套盘后规则、报价和历史检验计算；不重新训练或更改策略。

核心流程：搜索 / 排序 / 精选和全部股票；切换四套盘后策略；30/60/120 日日 K、均线和成交量、触摸查看；条件依据和观察价格；设备内观察列表；CSV 系统分享；1/3/5 日研究统计和分月结果；查看数据日期和覆盖、同步结果、发起服务器重新计算及 ProMax 更新。

手机使用 HTTPS + 独立访问令牌连接 106.14.125.189。按用户追加要求，**Mac 优先更新和计算，然后上传结果；Mac 无法连接或执行中失联、租约过期时才由服务器接管**。手机校验并缓存研究报告，图表按股票下载。首次配对通过私有配置文件导入，令牌存钥匙串；不在 App 或 Git 中保存 root 密码、ProMax 密钥。观察列表首版随设备保存，策略与行情口径相同。

Mac 后台进程每 10 秒联络服务器，心跳有效期 45 秒；执行租约 90 秒，持续续租。任务只能由一个执行者持有有效租约，上传和发布都验证任务 ID 与租约令牌，迟到结果拒绝。服务器启动有 60 秒等待窗口。Mac 使用已有行情下载接口与本机 ProMax 钥匙串，服务器保留同引擎作为离线备用。手机与 Mac worker 使用不同凭据；worker 上传有固定文件白名单、大小 / 解压限额和 SHA-256 验证。

## 架构与接口

- `../ashare-mac/macos/Models.swift`：两端直接共用的模型与数字格式。
- `Sources/Core/`：HTTPS、校验、缓存、钥匙串、数据状态。
- `Sources/UI/`：工作台、股票详情、研究、数据管理，统一四个标签页。
- `Guanlan.xcodeproj`：无第三方 iOS 依赖，个人团队自动签名。
- `../ashare-mac/mobile_server/`：认证 HTTP API、任务协调、报告发布。
- Nginx 终结 HTTPS，内部 API 只监听 127.0.0.1；使用配对文件中的专用证书作为 App 信任锚，同时验证 IP、有效期和 TLS，不关闭证书检查。计算任务单队列、有限时长，更新失败保留旧报告。

API 采用 `/v1`，所有业务接口要求 `Authorization: Bearer <token>`。错误统一 `{"error":{"code":"...","message":"..."}}`，拒绝重定向和任意文件路径。

| 方法 | 路径 | 响应 / 行为 |
|---|---|---|
| GET | /health | 不含数据或凭据的健康状态 |
| GET | /v1/status | 当前数据日期、任务状态、更新能力 |
| GET | /v1/reports/{leaders,pullback,golden_pit,momentum_60}/current | 固定版本清单，报告大小、SHA-256、日期 |
| GET | /v1/reports/{strategy}/{generation}/report.json | 该版本完整研究快照，最大 12 MiB |
| GET | /v1/reports/{strategy}/{generation}/charts/{code}.json | 该快照最多120根 K 线，最大128 KiB |
| POST | /v1/jobs | `{"action":"recompute"或"refresh","request_id":"规范 UUID"}`，单任务、冷却、去重，返回202 |

报告全表是有大小上限的不可变离线快照，手机在本地搜索排序，无逐行网络请求；图表按需获取。图表请求固定报告版本，防止价格和信号日期混用。缓存按策略保存上次有效报告，图表有数量上限。

## 实施与验收

1. 建立 API 和报告清单：用真实 Mac 输出验证所有股票和1/3/5日统计一致；认证、路径穿越、限额和原子替换测试。
2. 实现手机共享状态和界面：用实际数据验证加载、搜索、观察、图表、分享及错误状态。
3. 部署 Mac 优先调度与服务器备用任务：测量资源，保持现有只读 SSH 下载可用；同数据版本报告、图表严格对齐；测试 Mac 优先、Mac 失联接管和迟到上传拒绝。
4. Xcode 工程与个人安装：优先真实 iOS 编译 / 模拟器验证；若本机尚缺 Xcode，完成可执行共享核心测试和 SwiftUI Mac 预览，明确未验证部分。

## 命令

```sh
cd /Users/bennie/quanta/ashare-ios
bash scripts/test.sh
bash scripts/build-ios.sh
```

## 约束

不接自动交易，不改变 Mac 的策略含义。API 限制授权、请求体、并发和任务时长；旧版本保留供下载和回滚。签名使用用户个人团队，不伪造证书或绕过系统保护。完整 Xcode、Apple ID 登录和 iPhone 开发者模式是最终真机安装的外部条件。

## 来源

- Apple Personal Team：https://developer.apple.com/help/account/basics/about-your-developer-account/
- Apple NavigationStack：https://developer.apple.com/documentation/swiftui/navigationstack
- Apple URLSession：https://developer.apple.com/documentation/foundation/urlsession
- Apple IP ATS：https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking
