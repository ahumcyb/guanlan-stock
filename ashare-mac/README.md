# 观澜选股

本机运行的 macOS 原生 A 股短线研究软件。SwiftUI 界面，Python 独立引擎；原始行情只读，策略没有导入 quanta 的旧算法或权重。

已增加 [iPhone / iPad 工程](../ashare-ios/README.md)：手机提交任务后，本机后台节点优先更新、计算并上传；只有 Mac 失联时，服务器才使用相同引擎接管。三套盘后策略和图表按版本校验后供手机读取。后台节点登录后运行，不依赖 Mac App 窗口开启；运行维护见 [手机与 Mac 调度说明](../ashare-ios/docs/OPERATIONS.md)。

## 打开

本机已安装到 **/Users/bennie/Applications/观澜选股.app**，可在 Finder 双击打开。也可以双击工程中的 **启动观澜.command**，或打开 **build/观澜选股.app**。本机已完成环境配置。

- **选股工作台**：切换“流动性趋势”、“缩量回踩转强”或“黄金坑”，查看精选、转强、等待和全部股票。搜索支持代码、名称和行业。
- **股票详情**：30 / 60 / 120 日 K 线、均线、条件匹配、回踩/突破/失效参考。星标加入个人观察列表。
- **历史检验**：1、3、5 个交易日的次日开盘事件收益，费用压力、流动性参照、分月统计和缺失审计。
- **数据管理**：切换“服务器 / 本地”数据源。服务器模式从 `106.14.125.189` 同步已发布的行情；本地模式通过 ProMax 补齐最近 120 个市场交易日的日线、复权因子和涨跌停价，并更新交易日历及股票列表。
- **导出 CSV**：导出当前筛选或观察列表。代码与名称可直接查阅。

“重新选股”使用当前数据源的本机缓存；服务器模式点击“同步服务器”，本地模式点击“更新数据”，完成后都会重新选股。进度显示在窗口底部，更新/计算过程中可取消，原先的有效报告保留。

本机已配置服务器模式，五张行情表部署到 `/srv/guanlan-data/current`，仅使用独立只读 SSH 密钥访问。计算仍在 Mac 上进行。服务器保存已发布快照；需要补齐行情并发布新版本时，在本机运行 `bash scripts/publish_server_data.sh --refresh`，按 SSH 提示完成管理员认证。密码与 ProMax 密钥不进入工程。部署、校验、回滚说明见 [docs/SERVER.md](docs/SERVER.md)。

## 策略与结论边界

用户指定 1–5 个交易日，默认观察 3 日。

| 规则 | 流动性趋势 | 缩量回踩转强 |
|---|---|---|
| 基础股票池 | 沪深、当前非 ST / 退市名称，80 根历史、60 个连续市场日、20 日均额 >= 1 亿、价格 >= 3 元、ATR <= 6% | 相同 |
| 核心逻辑 | 成交额前 20%、相对强度前 50%、中期趋势向上、短期延续且不过度远离均线 | 相对强度前 35%、趋势向上、近期回踩、量能收缩后收盘转强 |
| 市场过滤 | 基础池中 MA20 上方占比 >= 40% | 相同 |
| 组合约束 | 最多 10 个研究候选，每行业最多 2 个 | 相同 |
| 评分 | 流动性 35、强度 30、趋势 20、低波动 15 | 强度 30、趋势 20、位置 20、缩量 15、低波动 15 |

完整可执行规则见 [docs/SPEC.md](docs/SPEC.md) 和 `engine/strategy.py`。

软件可用与策略获利能力是两件事。首版回踩模型在初始可结算历史样本中没有跑赢简单流动性参照，因此加入固定的流动性趋势模型作对照；没有网格搜索参数，也没有把历史结果包装成“已验证优秀”。**这些模型仍是探索性研究，应以实际“历史检验”页面显示的结果为准。** 评分不是获利概率。

[2026-09-05 独立资金账本研究](research/reports/20260905/README.md) 已按用户确认的 10 万元本金，补齐历史交易约束，比较 8 种低波动、动量、反转与突破候选。没有候选通过预先规定的验证门槛，本轮不替换 App 策略。报告包含同口径旧策略对照、净值回撤、逐笔交易及代码/数据指纹；它与 App 现有事件收益页面的统计口径不同。研究工具和复现方法见 [research](research/README.md)。

历史检验在 D 日收盘形成信号，D+1 开盘进入，D+1+h 开盘退出。按实际复权因子校正收益；高开 >3% 或涨停不假定买入；已知跌停最多顺延 5 日。未知的退出日行情、限制价或复权因子单独标记为缺数，不补造成功成交。未走完退出观察窗的事件标记截尾。往返费用统一估计 0.30%，并报告 0.60% 的压力情形。

这是一项**事件研究**：多日信号可能重叠，未计入资金占用、整数手数、最小佣金、盘口冲击和盘中止损，不能当作实盘组合年化。当前名称与行业用于历史过滤，缺少逐日股票名单 / ST 状态，因此存在幸存者和行业状态偏差。分月统计不等于独立样本外验证。没有接入自动下单。

## 数据与 ProMax

默认只读 `/Users/bennie/quanta/data`：

```text
raw/daily.parquet
raw/adj_factor.parquet
raw/stk_limit.parquet
raw/stock_basic.parquet
raw/trade_cal.parquet
refreshes/YYYYMMDD/daily_*.parquet   # 排除 daily_basic
```

新工程新增数据位于 `ashare-mac/data/updates/YYYYMMDD/`，参考表位于 `data/reference/`。更新只请求需要的公开行情日期，不发送本地数据。按完整日期发布；出现空数据、冲突、分页重叠或覆盖不足时，该日期不发布，其他有效日期继续保存，缺口写入 `data/last_update.json`。三条独立请求并行，单次请求限时及有限重试。

ProMax 地址沿用现有数据接口文档：`https://pcd.mobcvb.cn/tushare/pro/{api_name}`，HTTPS GET，`X-API-Key` 请求头。凭据优先来自 `PROMAX_API_KEY` 环境变量，其次是 macOS Keychain 的 `quanta.promax.api-key`（当前系统账户）。密钥不进入命令行、URL、日志或 Git。

此次部署实测发现带 `fields` 及小分页的部分历史请求有重叠或缺数。更新器优先用单页 20,000 行请求覆盖完整日期，请求默认字段后在本地保留规范列。股票列表接口使用不带分页参数的完整列表请求，上市日期统一规范为 YYYYMMDD 字符串；交易日历优先复用本地完整年份，缺少时显式请求开市和休市两个集合并检查自然日连续性。页内完全相同的重复行可归一；冲突值和跨页重叠拒绝发布。日线和股票列表数量同时对照历史覆盖，不能仅以“返回了数据”宣告完整。`daily.pre_close` 是除权参考前收；成交额单位为千元，成交量单位为手。

原始日线中的少数股票可追溯更早年份；全市场研究的起点根据 >=4000 只股票的有效日线日期识别。实际覆盖、停留日期、当日缺因子 / 限制价的股票数均以软件报告为准。

## 开发与重建

本版适用于本机 Apple Silicon，macOS 14+。需要系统 Command Line Tools 中的 Swift 与 Python 3.9+。`.app` 引用本工程中的 Python 虚拟环境和引擎，**请保留工程目录**；移动工程后重新构建，以刷新运行路径。

```sh
cd /Users/bennie/quanta/ashare-mac
bash scripts/setup.sh
.venv/bin/python -m unittest discover -s tests -v
swiftc -parse-as-library macos/Models.swift tests/NativeModelTests.swift -o .cache/native-tests
.cache/native-tests
bash scripts/build.sh
open build/观澜选股.app
```

研究引擎可单独调用：

```sh
.venv/bin/python -m engine.update --data-root ../data --overlay data
.venv/bin/python -m engine.cli --data-root ../data --overlay data --output .cache/analysis --strategy leaders
.venv/bin/python -m engine.cli --data-root ../data --overlay data --output .cache/pullback --strategy pullback
```

`engine.update.update(root, overlay, through=None)` 是可复用的数据更新接口；`engine.cli.generate(root, overlay, output, strategy='leaders')` 是选股报告接口。更新按钮使用独立子进程，不阻塞界面。

每次成功计算生成一个不可变报告目录，包含 `report.json`、`candidates.csv`、`events.csv`、`charts/`。`.cache/analysis/current.json` 只有在读回校验成功后才切换，包含报告 SHA-256，应用读取时核验。源数据、补充数据、缓存和 `.venv` 都不提交 Git。

## 验证依据与来源

单元测试覆盖数据校验、除权连续价格、未来数据不改变过去信号、市场日缺口、T+1、涨停跳过、跌停延期、截尾、退出缺数、原子发布、分区重试及分页完整性。真实窗口验证搜索、K 线、自选与 CSV 导出。

- [Tushare 日线字段定义](https://tushare.pro/document/2?doc_id=27)
- [Tushare 复权因子](https://tushare.pro/document/2?doc_id=28)
- [Tushare 每日涨跌停价格](https://tushare.pro/document/2?doc_id=183)
- [上交所交易规则（2026 年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)
- [Apple SwiftUI](https://developer.apple.com/documentation/technologyoverviews/swiftui)
- 本地 ProMax 协议依据：上级工程 `docs/promax_provider.md`，仅复用数据协议和钥匙串服务名。

## 黄金坑盘后策略

已加入“黄金坑”：上升趋势中的 8%–20% 回撤、底部缩量和右侧放量确认。Mac 的策略说明页和 iPhone 选股页的“黄金坑策略说明”列出全部条件；个股详情展示高低点日期、坑深、反弹、缩量比和失效参考。规则、评分与验证见 [黄金坑说明](docs/GOLDEN_PIT.md)。
