# 运行与维护

## 当前拓扑

- Mac 后台：`local.guanlan.compute-worker`，登录后运行；工作区 `ashare-mac/.cache/mobile-worker`。
- 阿里云 ECS：`106.14.125.189`。公网仅新增 TCP 443 入站；阿里云安全组 `sg-uf60vjp79x4zqfmx2y80`，规则备注“观澜 iOS 私人行情接口 HTTPS 443”。
- Nginx：HTTPS 443 → `127.0.0.1:8787`，内部端口不向公网开放。
- API 服务：`guanlan-mobile-api.service`，以 `guanlan-api` 运行。
- 调度 / 备用计算：`guanlan-mobile-worker.service`，以 `guanlan-worker` 运行；限制 CPU 1 核、内存 1300M，并配置 4 GiB swap 及 vm.swappiness=60 以适应小内存服务器。取消 MemoryHigh 软限额，避免内存回收同时拖住协调心跳；保留 MemoryMax 硬限制。
- 盘中与每日总结调度：`guanlan-realtime.service`。每日总结有独立开关和心跳，详见 [每日总结运行说明](../../ashare-mac/docs/DAILY_SUMMARY.md)。
- 行情：`/srv/guanlan-data/current` → 不可变快照。原有只读 SSH 下载接口继续供 Mac 使用。
- 手机报告：`/srv/guanlan-mobile/current` → 同一版本的四套盘后策略及图表。
- 应用代码：`/opt/guanlan-app`，运行账号无权改写代码。

## 调度规则

Mac 每 10 秒心跳并领取任务，45 秒没有心跳则视为离线。单个计算任务只有一个执行者持有有效租约；租约 90 秒，执行者每 15 秒续约。服务器启动后先等 60 秒。Mac 在线时服务器只存储、校验与响应手机请求，不承担策略计算。

Mac 上传结果后，任务进入由服务器负责的发布阶段，有独立的 30 分钟校验上限；此时客户端不能重新上传、撤销或续约。ZIP 有压缩 / 解压大小、文件数量及路径白名单限制。发布进程先复制到 0700 私有目录，再验证 SHA-256、行情快照、四套盘后策略日期与版本和 K 线完整性。上传时连接中断、迟到结果、版本变更均不能覆盖现有手机报告。

行情目录和研究目录被 systemd 分别隔离；行情先复制到行情文件系统内的临时 staging，再在该文件系统内切换目录，避免跨挂载点 rename 失败。手机固定请求报告所绑定的图表版本。

手机可点击“重新选股”或“更新数据并选股”发起普通任务。开启收盘总结后，交易日 16:10 会自动提交指定当日的更新任务，重新抓取收盘三表并核验版本，再生成总结与提醒。Mac App 的窗口和后台节点分别运行；手机更新发布完成后，Mac App 点“同步服务器”可重新载入同一行情日期。

## 本机操作

```sh
cd /Users/bennie/quanta/ashare-mac
bash scripts/install_mobile_worker.sh
launchctl print "gui/$(id -u)/local.guanlan.compute-worker"
tail -n 20 .cache/mobile-worker/worker.log
```

停止后台节点（再次运行安装脚本恢复）：

```sh
launchctl bootout "gui/$(id -u)/local.guanlan.compute-worker"
```

后台节点连接设置保存在 `settings/mobile-worker.json`，权限必须为 600。行情登录由统一的达塔 supervisor 管理，Mac 优先，Linux 仅在 Mac 失联后接管；详见 [双机登录协调](../../ashare-mac/docs/DATTA_ONLY_V85.md)。移动工程后需重新运行安装脚本。

## 服务器操作

管理员完成 SSH 登录后可运行：

```sh
systemctl status guanlan-mobile-api.service guanlan-mobile-worker.service nginx
journalctl -u guanlan-mobile-worker.service -n 40 --no-pager
systemctl restart guanlan-mobile-worker.service
```

发布失败日志记录异常类型、errno 和代码阶段，不输出上传租约、请求体或访问凭据。手机“数据”页显示当前任务状态；任务失败后检查日志，再提交重试。保留的研究版本至少当前加前两个，并给旧版本 24 小时下载宽限；行情也有保留与回滚机制，见 Mac 工程 `docs/SERVER.md`。

代码更新先本机测试，再复制 `mobile_server/`、所需 `engine/` 和 `deployment/` 到 `/opt/guanlan-app`，最后重启相关服务。`deployment/setup_mobile.sh` 负责账号、目录权限、依赖和证书准备；Nginx 和两个 systemd 单元的模板也在 `deployment/` 中。修改服务单元后需 `systemctl daemon-reload`。不要在任务仍执行时强制覆盖其代码。

两个服务须使用 `UMask=0007`。`jobs` 和 `incoming` 属于共享组 `guanlan-control`，目录 2770；队列锁 0660。API 只能写这两个控制目录，发布进程才有行情及研究目录写权限。

## 连接凭据与证书

- 手机配对：`ashare-ios/settings/手机连接.guanlan`，只交给自己的设备；导入后存手机钥匙串。
- 手机令牌和 Mac worker 令牌分别设置，手机不能领取 worker 租约或上传结果。
- 服务器 API 配置：`/etc/guanlan-mobile/api.json`；数据供应商凭据：`/etc/guanlan-mobile/worker.env`。它们不进入 Git 或文档。
- 专用证书与私钥：`/etc/guanlan-mobile/tls/`。证书首次签发有效期 730 天，更新时需同步新的配对证书到 Mac 和手机；不要直接覆盖后忘记重新配对。

iOS 17 起将 IP 地址纳入 ATS。工程仅为 `106.14.125.189` 设置私有证书例外，连接层仍强制 HTTPS、TLS 1.2 以上、精确 IP、专用信任锚和有效期校验，并拒绝重定向。异步字节接口显式使用证书 task delegate。没有向系统钥匙串安装全局根证书。

依据：[Apple 的 IP 地址 ATS 规则](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking)、[自定义证书信任锚](https://developer.apple.com/documentation/security/configuring-a-trust)。
