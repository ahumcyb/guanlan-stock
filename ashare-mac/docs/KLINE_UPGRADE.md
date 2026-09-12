# K 线改进规格与验收计划

用户已确认一并完成此前梳理的两阶段范围。独立工作目录开发，验证后合回本机运行目录；不改选股规则、成交假设或历史提醒内容。

## 数据与兼容契约

- 旧 `charts/CODE.json` 继续返回最多120根连续价格日线，旧手机保持可读。
- 新 `charts-extended/CODE.json` 返回最多500根；发布时使用 `charts-extended/CODE.json.gz` 压缩侧文件，接口有限解压为JSON。不修改现有归档，缺扩展文件时新版明确退回旧120根。
- 扩展对象：`schema_version=1, ts_code, as_of, data_revision, price_basis=continuous_latest_close, volume_unit=lot, bars`。每根保留旧9字段，增加 `raw_open/raw_high/raw_low/raw_close/raw_pre_close/amount`（金额为千元）。日线原始单位与现有日线表一致。
- 每个侧文件解压最多512KiB、压缩最多128KiB，并拒绝非规范填充。ZIP成员总量上限仍512MiB；计入内层gzip后的累计实际数据上限1GiB。成员上限21000，只允许既定目录/代码/大小；扩展集合必须完整且四策略一致。旧包不要求扩展集合。
- 数量以实际历史为准。本机当前发布版本有412个交易日，不能将不足500根称为500日完整历史。
- 周/月K由同一数据版本日线聚合：首开、末收、最高/最低、量额求和。标注实际起止日期和“末根截至数据日”；均线按聚合周期重算，历史不足为空。
- 连续价/原始价切换明确标注口径。历史提醒价是原始快照价，叠加连续价图时按该日连续价/原始价比例转换；找不到该日时只提示，不能贴到别的日期。

## 分步任务

1. 扩展数据发布、接收、API与旧版兼容。验收：500根与原价字段、体积实测、压缩限额/非法字段/旧包回归，Python测试通过。
2. 共享图表模型、周/月聚合、MA/MACD/RSI、刻度/窗口/定位。验收：独立原生计算测试覆盖交易周跨年、缺日、常价、缩放边界、历史不足、两种价格口径。
3. 共享图表视图与两端大图。验收：完整OHLC/变化/量额/均线读数，日期和价格十字线、量柱、参考/失效边缘提示、缩放平移及回到最新；窄屏与大图可读。
4. 提醒/日报逐股入口和加载边界。验收：来源日期/价格可追溯、不同请求身份之间的成功/失败均不能串写；旧120根及离线缓存有清晰状态。
5. 集成发布。验收：Python/原生测试、Mac/iOS构建与真实界面检查，扩展包实测并部署，更新应用、记录结果、Git备份回读。

## 实现边界

- 采用已有 SwiftUI Canvas 与共享 Swift 计算，不增加绘图库。Mac采用悬停查价与拖拽浏览；手机通过 UIKit 手势代理在识别前拒绝纵向 pan，让外层 ScrollView 接管；长按后查价，横向浏览，双指缩放。大图保留当前周期、指标、价格口径、窗口和选中日期。
- 增加 MACD(12,26,9) 与 RSI14 作为可选副图；MACD柱使用 `2×(DIF−DEA)`，明确标注。EMA以首值递推，前33个周期不展示MACD；RSI以14期平均涨跌作种子、Wilder递推；常价RSI为50，缺少历史为空。
- 指标仅显示已有价格序列计算结果，不增加自动交易或获利承诺。
- API继续使用已有证书、认证、固定版本和路径校验。密钥、设备标识、数据及签名包不进入Git。

## 验证命令与来源

- Python：`cd ashare-mac && .venv/bin/python -m unittest discover -s tests -q`
- 原生：`cd ashare-ios && bash scripts/test-product.sh`，并补共享图表计算/加载测试。
- 构建：`bash ashare-mac/scripts/build.sh`；iOS运行项目生成脚本后用已配置个人团队签名构建。
- [Apple SwiftUI手势组合](https://developer.apple.com/documentation/swiftui/composing-swiftui-gestures)
- [Apple 手势识别前的方向判断](https://developer.apple.com/documentation/uikit/uigesturerecognizerdelegate/gesturerecognizershouldbegin(_:))
- [Apple MagnifyGesture](https://developer.apple.com/documentation/swiftui/magnifygesture)
- [Fidelity RSI公式](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI)
- [Fidelity EMA说明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema)

版本目标：Mac 1.10.0（13）、iOS 1.9.0（13）。
