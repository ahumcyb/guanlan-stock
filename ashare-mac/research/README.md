# 观澜独立策略研究

本目录与在线选股和定时推送分离，不更改 App 策略注册。研究结论及后续准入边界见 [2026-09-05 报告](reports/20260905/README.md)，事先定义的数值规则见 [PLAN.md](PLAN.md) 和 [protocol.json](protocol.json)。

## 重现已经完成的研究

原始代码所在本地提交为 `0efbea3`，后续报告导出不会改变被封存的计算文件。GitHub 的独立备份提交号可能不同，以报告内 `frozen.json` 的各文件 SHA-256 为准。所有命令在 `ashare-mac` 中执行，用工程 `.venv/bin/python`（Python 3.9、pandas 2.3.3、numpy 2.0.2）。

本机不可变数据位于 `.cache/mobile-worker/market/releases/20260904-c0eccf474694bb2b`；历史约束缓存位于 `.cache/strategy-research/constraints`。报告带有输入和约束指纹，行情本体不进 Git。换机器须取得同一不可变版本和同一约束文件；重新向供应商获取的历史数据可能有修订，不应假定与本次相同。

```sh
# 已有面板和缓存时，使用一个不存在的结果目录，保留首次封存记录。
.venv/bin/python -m research.experiment freeze \
  --panel .cache/strategy-research/panel-v2.npz \
  --output .cache/strategy-research/reproduction-20260905
.venv/bin/python -m research.experiment development \
  --panel .cache/strategy-research/panel-v2.npz \
  --output .cache/strategy-research/reproduction-20260905
.venv/bin/python -m research.experiment holdout \
  --panel .cache/strategy-research/panel-v2.npz \
  --output .cache/strategy-research/reproduction-20260905
```

重现属于对已观察历史的复算，不能再次称为新样本外验证。源码、面板或选择记录变化会拒绝解封；已有选型/留出结果拒绝覆盖。原 `run-20260905` 无效预检和 `run-20260905-v2` 记录保留，最终有效记录在 `run-20260905-v3`，详情见 [AUDIT.md](AUDIT.md)。

已有原始数据但缺研究约束时，可用授权的 ProMax 接口增量补齐；凭据由 `engine.provider.ProMax` 从环境或 Keychain 获取，不写入命令。每日期涨跌停和每月份逐日 ST 均校验覆盖、唯一键和哈希；饱和 ST 响应按日期拆分，不能把截断页当完整区间。

```sh
.venv/bin/python -m research.acquire \
  --root .cache/mobile-worker/market/releases/20260904-c0eccf474694bb2b \
  --cache .cache/strategy-research/constraints
.venv/bin/python -m research.prepare \
  --root .cache/mobile-worker/market/releases/20260904-c0eccf474694bb2b \
  --constraints .cache/strategy-research/constraints \
  --output .cache/strategy-research/rebuilt-panel.npz
```

`prepare` 只计算因果特征和候选，不计算收益。它不会读取当前股票名单决定历史入池；历史 ST 日期缺失、涨跌停价/因子缺失的股票不能进入该日基础池。代码/行情一致而压缩归档字节不一致时，应逐数组比较并另建重现记录，不覆盖原封存面板。

## 结果与报告

资金账本包含最低佣金、整数手、T+1、空仓、跌停延迟及阶段末未解决仓位。各相位独立出资 10 万元，不能把合并成交数或均值净值当单账户实盘。

`reports/20260905/experiment-records.zip` 包含全部 29 份实验输出及原始逐笔/净值 CSV；`verification.json` 记录对账及哈希。解压仅用于查看原结果，不能凭修改报告数值重新选择候选。

```sh
.venv/bin/python -m research.report \
  --run .cache/strategy-research/run-20260905-v3 \
  --panel .cache/strategy-research/panel-v2.npz \
  --constraints .cache/strategy-research/constraints \
  --output .cache/strategy-research/report-reproduction
```

加 `--render` 需要 Matplotlib；本机仅在隔离的 `.cache/strategy-research/plot-runtime` 安装了绘图依赖，生产虚拟环境无需新增依赖。报告导出只读取已封存结果，不调用仿真或评估其他候选。此报告文字针对本次失败结论，换候选或通过准入门槛时会拒绝导出，要求重新审查文案。

测试：`.venv/bin/python -m unittest discover -s tests`。除单元测试外，还进行了选定策略信号重建、逐笔成交与现金/净值的独立复算，详见报告中的 `REVIEW.md`。
