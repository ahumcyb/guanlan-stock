# 观澜选股

2026-09-12：新增日/周/月交互 K 线、大图、缩放平移、MA/MACD/RSI、原始价切换和提醒/日报定位。Mac 1.10.0（13）已安装；服务器新接口已发布，原生回读412根日线，旧120根接口保持兼容。Mac与服务器各309项Python测试、完整原生测试通过。iOS 1.9.0（13）已构建，原免费签名于今天14:51到期，需恢复Xcode账号后续签安装；新版尚未装入手机。详见[本次验收](ashare-mac/docs/KLINE_VERIFICATION_20260912.md)。

2026-09-10：每日收盘总结新增昨日三个实时策略的今日收益，分列昨收至今收与提醒价至今收，支持来源轮次、逐股价格和缺数说明。Mac 1.9.0（12）已安装，iOS 1.8.0（12）已安装到配对手机，设备回读版本一致并成功启动；新版通知已被 Bark 接受。301项测试在Mac和服务器通过，今天总结已补算。详见[验收记录](ashare-mac/docs/REALTIME_DAILY_VERIFICATION_20260910.md)。

面向 A 股研究与尾盘定时筛选的 macOS 和 iPhone 原生应用。SwiftUI 界面、Python 引擎、达塔行情与 ProMax 备用，Mac 优先计算并上传结果，Mac 失联时服务器接管。交易日14:30、14:45、14:50自动筛选，完成后通过 Bark 提醒手机，点击进入观澜查看结果。

新增交易日 16:10 的每日收盘总结：核验当日行情与四策略结果，生成量价事实和 DeepSeek 解读，完成后通过 Bark 提醒；Mac 和 iPhone 的总结设置均可更换 API Key。

2026-09-08 更新：Mac 1.7.1（9）与 iOS 1.6.1（9）均已安装，交易日14:30「底部放量」已调整为 **累计量至少2.5倍且当日上涨**。服务器及两端规则一致，259 项 Python 测试与原生产品测试通过。四策略读取统一发布结果，自选逐条同步，通知可回到固定轮次，首页与日报更聚焦变化。当天实时失败的 1 KiB 网关限制已定位并修复。

| 目录 | 内容 |
|---|---|
| [ashare-mac](ashare-mac/README.md) | Mac 应用、独立策略、历史检验、行情更新、服务器部署及 Mac 后台计算节点 |
| [ashare-ios](ashare-ios/README.md) | iPhone / iPad 应用、股票搜索、K 线、观察列表、CSV 分享与个人签名安装 |
| [运行维护](ashare-ios/docs/OPERATIONS.md) | Mac 优先调度、服务器接管、连接配置与维护命令 |
| [达塔行情接入](ashare-mac/docs/DATTA_MIGRATION.md) | Mac 实时、分钟和日线使用达塔；历史参考数据与服务器备用路径保留 |
| [批量模式](ashare-mac/docs/D101_BATCH.md) | D101 全池初筛、D6 候选复核、异常回退、性能与部署验收 |
| [达塔接入验收](ashare-mac/docs/DATTA_VERIFICATION_20260909.md) | 4,983 只报价、5,548 条日线、分红前后历史价格核对及 272 项测试 |
| [验收记录](ashare-ios/docs/VERIFICATION.md) | 真机安装、数据回读、两端一致性及 82 项测试记录 |
| [实时策略](ashare-mac/docs/REALTIME_STRATEGIES.md) | 两篇来源的规则定义、行情时间与覆盖校验 |
| [实时运行与通知](ashare-mac/docs/REALTIME_OPERATIONS.md) | 定时执行、Bark 配置、可选 DeepSeek、103项测试及手机通知验证 |
| [黄金坑盘后策略](ashare-mac/docs/GOLDEN_PIT.md) | 峰谷顺序、缩量与右侧确认；三策略同步、116 项测试及两端计算一致性 |
| [10 万元短线策略研究](ashare-mac/research/reports/20260905/README.md) | 八候选未通过门槛；历史 ST / 涨跌停约束、资金账本、145 项测试、封存结果及逐笔导出 |
| [首页第四策略](ashare-mac/docs/LEFT_REBOUND.md) | 左侧低吸日线形态；首次历史检验未显示盈利优势，透明保留规则和事件统计 |
| [原动量历史](ashare-mac/docs/MOMENTUM_60.md) | 原 60 日风险调整动量的封存研究与验证限制 |
| [无信号月份](ashare-mac/docs/EMPTY_MONTHS.md) | 展示完整检验月份；2026 年 6 月原三策略受市场宽度门槛影响，无信号月份不再缺席 |
| [K线升级](ashare-mac/docs/KLINE_UPGRADE.md) | 共享图表、500根扩展协议、指标与历史提醒定位 |
| [K线验收](ashare-mac/docs/KLINE_VERIFICATION_20260912.md) | 309项测试、服务端发布、原生回读与待续签说明 |
| [昨日实时收益](ashare-mac/docs/REALTIME_DAILY_VERIFICATION_20260910.md) | 三策略两个收益口径、固定昨日归档、程序摘要和新版通知 |
| [每日收盘总结](ashare-mac/docs/DAILY_SUMMARY.md) | 指定日期收盘更新、Mac 优先、持久化复盘、DeepSeek 设置与手机提醒 |
| [每日总结实测](ashare-mac/docs/DAILY_VERIFICATION_20260907.md) | 192 项测试、V4 Pro 实际解读、Mac 与模拟器结果回读、真机升级及当日总结回读 |
| [产品优化验收](ashare-mac/docs/PRODUCT_VERIFICATION_20260908.md) | 257 项测试、统一缓存、自选共享、原始通知、日报变化及 Mac 实测 |
| [底部放量2.5倍上涨](ashare-mac/docs/BOTTOM_VOLUME.md) | 14:30独立检查、近60日低位、累计量至少2.5倍且当日上涨 |
| [底部放量参数更新验收](ashare-mac/docs/BOTTOM_VOLUME_25_VERIFICATION.md) | Mac/手机安装、服务器部署、259项测试与新旧归档兼容 |
| [9月8日新规则收盘复核](ashare-mac/research/reports/20260908/bottom-volume-25-up-close-review.md) | 新潮能源、新兴铸管符合2.5倍上涨条件；不作为14:30历史快照 |
| [原3倍规则历史复核](ashare-mac/research/reports/20260908/bottom-volume-close-review.md) | 康欣新材、东兴证券符合原收盘口径；因当日下跌不满足新规则 |
| [9月8日实时故障](ashare-mac/docs/REALTIME_FAILURE_20260908.md) | Nginx 1 KiB 限制造成413；精确路由修复和无状态探测验证 |
| [此前升级验收](ashare-mac/docs/VERIFICATION_20260908.md) | 左侧日线策略与昨日精选结算的历史验收 |

## 工程与数据

本仓库独立保存观澜工程及其开发提交历史。两个应用目录需保持并列，iOS 工程直接引用 Mac 目录中的共享模型。

行情文件、运行缓存、虚拟环境、构建产物、服务器密码、ProMax 密钥、手机配对文件与签名私钥不在仓库中。换机器使用时，需要按各应用说明配置本地数据、运行环境和私有连接信息。

当前本机运行工程位于 `/Users/bennie/quanta/ashare-mac` 和 `/Users/bennie/quanta/ashare-ios`；独立 GitHub 发布副本位于 `/Users/bennie/guanlan-stock`。此备份保留目录结构，不改变已安装应用引用的本机路径。

## 研究边界

盘后策略为“流动性趋势”、“缩量回踩转强”、“黄金坑”和“左侧低吸”；实时策略有“一夜持股·正文版”、“黄金半小时·七步法”和“底部放量·2.5倍上涨”。均属探索性研究，未完成独立样本外与模拟实盘盈利验证。缺失的分时、公告条件保留待核验状态。匹配分不是获利概率，历史事件收益不能视为实盘组合收益。可选 DeepSeek 只解释量价与结果，不改变规则。软件不接自动下单。
