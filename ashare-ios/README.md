# 观澜选股 · iPhone / iPad

iOS 1.5.0（7）将第四项改为「左侧低吸」，并修正收盘总结的策略表现：按上一交易日保存的精选计算本日观察涨跌。首页进入查看市场量价、行业、昨日精选结算与 DeepSeek 解读，右上角「设置」可更换 API Key。交易日 16:10 由后台启动，Mac 优先计算，离线时服务器接管；Bark 提醒可直达对应日期。支持历史与离线阅读。详见 [每日总结说明](../ashare-mac/docs/DAILY_SUMMARY.md) 和 [本次验收](../ashare-mac/docs/VERIFICATION_20260908.md)。

原生 SwiftUI 应用，iOS 17 起可用。手机与 Mac 共用同一研究引擎、四套盘后规则和数据模型，适合 1–5 个交易日的盘后观察。支持股票搜索、策略切换、精选列表、K 线、观察列表、CSV 分享、历史检验和 ProMax 数据更新。

## 日常使用

- **选股**：切换“流动性趋势”、“缩量回踩转强”、“黄金坑”或第四项“左侧低吸”，搜索代码、名称或行业，查看匹配条件和参考价格。展开左侧策略说明可查看超跌、缩量、均线偏离及风险约束；当前历史样本未显示盈利优势，保留为研究观察。
- **观察**：查看本设备保存的星标股票。首版观察列表分别保存在手机和 Mac，行情与策略口径一致。
- **检验**：查看 1 / 3 / 5 日事件收益、成本压力、流动性参照和分月统计。
- **数据**：“同步最新结果”下载已发布报告；“重新选股”提交计算任务；“ProMax 更新数据并选股”先补数据，再计算四套盘后策略。

任务优先由本机后台计算节点执行，Mac App 窗口可以关闭。Mac 无法联系服务器时，服务器才接管。报告、四套盘后策略和 K 线必须通过同版本校验后才发布；失败时保留上次报告。已同步的报告和最近查看的 K 线可离线阅读。

本机后台节点在用户登录后自动启动。Mac 睡眠、关机、注销或断网时会失去心跳；服务器等待 45 秒确认离线。正在运行的 Mac 任务有 90 秒租约并持续续约，失联后才允许重新接管，旧执行者的迟到结果会被拒绝。

## 安装到自己的 iPhone

本机已安装 Xcode，工程不需要任何第三方 iOS 依赖。普通 Apple ID 通过 Xcode 的 Personal Team 安装，无需上架。

1. 用数据线连接并解锁 iPhone，接受手机上的“信任此电脑”。
2. 双击本目录 **打开 iPhone 工程.command**。在 Xcode → Settings → Apple Accounts 添加自己的 Apple ID。
3. 在项目导航选择 **Guanlan** → TARGETS **Guanlan** → **Signing & Capabilities**，保持 **Automatically manage signing**，Team 选择自己的 **Personal Team**。
4. Xcode 顶部运行目标选自己的 iPhone，点击 ▶ Run。按手机提示启用“设置 → 隐私与安全性 → 开发者模式”；必要时在“设置 → 通用 → VPN 与设备管理”信任个人开发者。
5. 将本机 `settings/手机连接.guanlan` 通过 AirDrop 发给自己的 iPhone，选择观澜选股打开；也可在 App 的“数据 → 导入连接配置”选择该文件。导入后访问凭据存入手机钥匙串。

配对文件含私人接口访问凭据，请只保存在自己的设备；不要公开分享。App 不包含服务器管理员密码或 ProMax 密钥。个人团队的描述文件有效期为 **7 天**，到期后连接 Mac，再次在 Xcode 点击 Run 更新签名。说明依据 [Apple 开发者账户与 Personal Team](https://developer.apple.com/help/account/basics/about-your-developer-account/)。

本机另有 **安装或续签 iPhone.command**：首次安装配置好个人团队后，双击即可重新编译、签名并安装到已保存的个人 iPhone，同时自动导入本机配对文件。手机保持解锁，已配对后可用同一 Wi-Fi；首次信任个人开发者仍需在手机上完成。

未签名的 device 构建仅验证真机 SDK 编译，不能直接装到 iPhone。首次安装需要本人 Apple ID 登录及设备端确认。

**不需要一直连接数据线。** 首次配对完成后，可以在同一 Wi-Fi 网络中通过 Xcode 无线安装和更新；日常使用 App 只需要手机能访问互联网，蜂窝网络也可用，不要求手机与 Mac 在同一网络。参见 [Apple 设备配对与无线运行](https://developer.apple.com/documentation/xcode/pairing-your-devices-with-your-mac)。

## 开发验证

```sh
cd /Users/bennie/quanta/ashare-ios
bash scripts/test.sh
bash scripts/build-ios.sh simulator
bash scripts/build-ios.sh device
```

网络回读验证（私有配置只通过文件读取）：

```sh
bash scripts/test.sh ../ashare-mac/.cache/mobile-bootstrap/mobile/current settings/手机连接.guanlan
```

`Guanlan.xcodeproj` 已生成；变更文件列表或构建设置后可运行 `python3 scripts/generate_project.py`。模拟器开发构建使用 ad hoc 签名以支持钥匙串；正常真机运行由 Xcode 的个人团队签名。`DEBUG` 版本可从模拟器沙盒的 `Documents/Pairing.guanlan` 导入测试配置，成功存入钥匙串后删除该临时文件；发布版本不包含这一测试入口。

手机的 `Sources/Core` 校验报告 SHA-256、大小、数据版本及 K 线，`Sources/UI` 是原生界面；模型直接引用 `../ashare-mac/macos/Models.swift`。服务端和 Mac 后台节点位于 `../ashare-mac/mobile_server`。详情见 [接口规格](docs/SPEC.md) 与 [运行维护](docs/OPERATIONS.md)。

2026-09-05 已在个人 iPhone 完成安装和数据回读，并通过 Mac 优先、服务器离线接管的完整实测；见 [验收记录](docs/VERIFICATION.md)。

## 研究范围

四套盘后策略仍是探索性研究，没有完成独立样本外检验。匹配分不是获利概率，历史事件收益不是实盘组合收益；规则、成本、缺数与偏差说明见 [Mac 版策略说明](../ashare-mac/README.md)。App 不接自动下单。

## 黄金坑盘后策略

已加入“黄金坑”：上升趋势中的 8%–20% 回撤、底部缩量和右侧放量确认。Mac 的策略说明页和 iPhone 选股页的“黄金坑策略说明”列出全部条件；个股详情展示高低点日期、坑深、反弹、缩量比和失效参考。规则、评分与验证见 [黄金坑说明](../ashare-mac/docs/GOLDEN_PIT.md)。
