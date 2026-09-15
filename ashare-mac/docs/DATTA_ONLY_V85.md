# 达塔 v85 与双机接管

目标：所有新的行情请求只访问本机达塔。Mac 在线时优先持有登录权并计算；只有 Mac 失联且旧权限到期后 Linux 才能登录。Mac 恢复后等待 Linux 正在执行的任务结束，再交接登录权。历史市场包和提醒记录保留。

## 数据契约与实测

- 客户端来源为用户提供的 dat85.zip，SHA256 b1103fe3369a69348dc57e3fe93c37e97ef3da1b5d4a2888dd4da8047fe9b609。Mac ARM64 bundle 为 85.0.0 (85)。
- D6 日线保持人民币元、成交量股转换为手、成交额元转换为千元，校验日期、OHLC、量额。
- D4 instrument_list 提供全市场分页名录、上市日和行业。北交所在协议中可能使用 SZ920xxx，必须按北交所独立集合核对并转换为 .BJ，不能据此变成深圳股票。
- D101 快照价格使用 decimal_num；流通股本为万股，与 D6 的股数、市值交叉核验。涨跌停价只接受快照的明确交易日期，不能用于任意历史日期。
- 实测 D101 不再提供 K 线；D4 K 线历史股本返回异常巨数，不可用作昨日股本。每天收盘保存已核验的达塔股本，下一交易日按原有“前日流通股本”规则读取；缺失时明确暂停该策略，不能拿当前股本冒充昨日值。
- D6 adjustment 与 D4 后复权均包含加法现金调整，不能直接当作原有乘法 adj_factor。增量使用明确标注的“前收盘价连续链”：旧因子作为尺度锚点，F(t)=F(t-1)*Close(t-1)/PreClose(t)。每一步必须取得真实日线并严格按日期连接；新上市首日以 1 为尺度。该因子是本地计算的连续价格尺度，不宣称是供应商官方复权因子。
- 保留已验证的本地交易日历；未来日历不足时停止并报错，不用工作日猜测假期。

## 登录协调与安全

使用服务器持久化的唯一行情登录租约，与盘后和实时任务共同协调。登录/恢复/自动重连只能在持有有效租约时执行。Linux 已有活动任务时进入交接等待；不允许仅因 Mac 心跳恢复就中断 Linux 数据获取。失去租约必须停止本机数据服务并清除登录，不允许回退 ProMax/Sina。

管理端口及行情端口仅允许本机访问。凭据存放私有配置，不进入源代码、日志、进程参数或 Git。客户端的原生自动登录要由进程生命周期控制，不能绕过租约。安装前备份旧客户端，运行失败保留已有报告而不发布不完整数据。

## 验收

覆盖 Mac 正常、Mac 掉线、Linux 接管、Mac 在 Linux 作业中恢复、租约失效与迟到续约、盘后/实时并发、进程重启。数据覆盖须通过既有价格/连续因子/涨跌停三表检查，核验最新交易日发布结果；未通过项目不得宣称已完成部署。

## 无涨跌幅限制核验

仅当 D6 明确返回 0/0，且 D4 上市日与完整本地日历证明仍在允许的 IPO 窗口内才接受；其他股票的零值一律拒绝，不用它凑齐覆盖。沪深前五个交易日、北交所上市首日，其他重新上市等例外暂不推测。

规则来源：[深交所 2026 交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)、[北交所交易规则](https://www.bse.cn/jygl_list/200028217.html)。

## 当前运行配置

Mac 的 LaunchAgent 为 `local.guanlan.datta-owner`，运行 `python -m mobile_server.datta_supervisor --config settings/datta-supervisor.json`。配置字段为 `node=mac`、`executable`、`client_directory`、`credentials`（私有 JSON 路径）、`receipt`、`worker_config`。配置和凭据权限必须为 600。达塔原生自启动关闭，仅 supervisor 可启动登录。

Linux 使用 `guanlan-datta-owner.service`，原 `guanlan-datta.service` 保持禁用。配置使用 `node=server`、`server_root` 代替 `worker_config`，其他字段相同；必须沿用客户端所需的运行库隔离与 loopback 防火墙。`/srv/guanlan-datta/session.json` 允许计算用户读取，登录凭据仍仅客户端服务用户可读。

90 秒远端租约、45 秒本地请求凭证、120 秒 Mac 失联接管宽限。两类任务绑定 `datta_epoch`，续约与发布均按全局登录锁 → 任务锁的顺序校验。Mac 与 Linux 各只有一个客户端管理进程；同一机器的盘后和实时任务可以共享该会话。

跨进程时钟使用 `clock_gettime(CLOCK_MONOTONIC)`，不能换回这台 Mac Python 3.9 的 `time.monotonic()`（其原点按进程不同）。凭证带时钟版本与启动纪元，旧格式、过期代次或失效进程一律拒绝。

状态：`GET /v1/status` 的 `datta` 字段只返回 owner/phase/epoch/lease_until，不返回令牌。Mac 日志在 `.cache/datta-owner.log`；Linux 由现有服务日志记录状态。手机读取原 API，无需为此次后端修复重新签名安装。
