# 观澜选股

面向 A 股研究与尾盘定时筛选的 macOS 和 iPhone 原生应用。SwiftUI 界面、Python 引擎、ProMax 行情，Mac 优先计算并上传结果，Mac 失联时服务器接管。交易日14:30、14:45、14:50自动筛选，完成后通过 Bark 提醒手机，点击进入观澜查看结果。

新增交易日 16:10 的每日收盘总结：核验当日行情与四策略结果，生成量价事实和 DeepSeek 解读，完成后通过 Bark 提醒；Mac 和 iPhone 的总结设置均可更换 API Key。

2026-09-08 更新：第四项替换为日线「左侧低吸」，旧动量历史保留；每日总结改为上一交易日已保存精选到本日收盘的复权观察涨跌。ProMax 实时请求改为明确代码批次，缺时点报价由完整有效的备用报价替换。Mac 1.6.0（7）和 iOS 1.5.0（7）已安装，服务端 228 项测试通过。

| 目录 | 内容 |
|---|---|
| [ashare-mac](ashare-mac/README.md) | Mac 应用、独立策略、历史检验、行情更新、服务器部署及 Mac 后台计算节点 |
| [ashare-ios](ashare-ios/README.md) | iPhone / iPad 应用、股票搜索、K 线、观察列表、CSV 分享与个人签名安装 |
| [运行维护](ashare-ios/docs/OPERATIONS.md) | Mac 优先调度、服务器接管、连接配置与维护命令 |
| [验收记录](ashare-ios/docs/VERIFICATION.md) | 真机安装、数据回读、两端一致性及 82 项测试记录 |
| [实时策略](ashare-mac/docs/REALTIME_STRATEGIES.md) | 两篇来源的规则定义、行情时间与覆盖校验 |
| [实时运行与通知](ashare-mac/docs/REALTIME_OPERATIONS.md) | 定时执行、Bark 配置、可选 DeepSeek、103项测试及手机通知验证 |
| [黄金坑盘后策略](ashare-mac/docs/GOLDEN_PIT.md) | 峰谷顺序、缩量与右侧确认；三策略同步、116 项测试及两端计算一致性 |
| [10 万元短线策略研究](ashare-mac/research/reports/20260905/README.md) | 八候选未通过门槛；历史 ST / 涨跌停约束、资金账本、145 项测试、封存结果及逐笔导出 |
| [首页第四策略](ashare-mac/docs/LEFT_REBOUND.md) | 左侧低吸日线形态；首次历史检验未显示盈利优势，透明保留规则和事件统计 |
| [原动量历史](ashare-mac/docs/MOMENTUM_60.md) | 原 60 日风险调整动量的封存研究与验证限制 |
| [无信号月份](ashare-mac/docs/EMPTY_MONTHS.md) | 展示完整检验月份；2026 年 6 月原三策略受市场宽度门槛影响，无信号月份不再缺席 |
| [每日收盘总结](ashare-mac/docs/DAILY_SUMMARY.md) | 指定日期收盘更新、Mac 优先、持久化复盘、DeepSeek 设置与手机提醒 |
| [每日总结实测](ashare-mac/docs/DAILY_VERIFICATION_20260907.md) | 192 项测试、V4 Pro 实际解读、Mac 与模拟器结果回读、真机升级及当日总结回读 |
| [本次升级验收](ashare-mac/docs/VERIFICATION_20260908.md) | 228 项测试、昨日精选结算、新策略发布、实际安装和锁屏界面验收边界 |

## 工程与数据

本仓库独立保存观澜工程及其开发提交历史。两个应用目录需保持并列，iOS 工程直接引用 Mac 目录中的共享模型。

行情文件、运行缓存、虚拟环境、构建产物、服务器密码、ProMax 密钥、手机配对文件与签名私钥不在仓库中。换机器使用时，需要按各应用说明配置本地数据、运行环境和私有连接信息。

当前本机运行工程位于 `/Users/bennie/quanta/ashare-mac` 和 `/Users/bennie/quanta/ashare-ios`；独立 GitHub 发布副本位于 `/Users/bennie/guanlan-stock`。此备份保留目录结构，不改变已安装应用引用的本机路径。

## 研究边界

盘后策略为“流动性趋势”、“缩量回踩转强”、“黄金坑”和“左侧低吸”；尾盘有“一夜持股·正文版”和“黄金半小时·七步法”。均属探索性研究，未完成独立样本外与模拟实盘盈利验证。缺失的分时、公告条件保留待核验状态。匹配分不是获利概率，历史事件收益不能视为实盘组合收益。可选 DeepSeek 只解释量价与结果，不改变规则。软件不接自动下单。
