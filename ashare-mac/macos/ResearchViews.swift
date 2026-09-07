import SwiftUI
import Charts

struct ResearchView:View {
    @EnvironmentObject var store:AppStore
    private let statusNames=["settled":"已结算","pending":"待观察期结束","censored":"退出观察窗未结束","limit_up":"涨停未买入","gap":"高开未追入", "missing_signal":"信号日缺数据","missing_entry":"进入日缺数据/停牌","missing_exit":"退出日缺数据/停牌","unresolved":"跌停退出受阻"]
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:22) {
                pageTitle("历史检验",subtitle:"\(store.report?.strategyName ?? "") · 固定规则的信号事件研究。")
                if let report=store.report {
                    if let h=report.backtest.horizons.first(where:{$0.horizon==3}) {
                        Panel {
                            VStack(alignment:.leading,spacing:12) {
                                HStack {
                                    Image(systemName:"checkmark.shield").foregroundStyle(Palette.teal)
                                    Text(!report.isMomentum60 && (h.mean ?? -1)>0 && (h.mean ?? -1)>(h.benchmark.mean ?? 0) ? "出现正向历史信号，仍需样本外验证":"策略尚未通过验证")
                                        .font(.system(size:16,weight:.semibold))
                                    Spacer(); Badge(text:"研究阶段",color:Palette.amber)
                                }
                                Text("\(dateText(report.backtest.start)) — \(dateText(report.backtest.end))。收益按次日开盘进入计算；指标只统计已结算事件，缺失和退出受阻的数量单独披露。").font(.system(size:12)).foregroundStyle(Palette.muted).lineSpacing(4)
                            }
                        }
                    }
                    if report.isMomentum60 {
                        Text(Momentum60Guide.evidence + " 下列动态指标为另一口径的事后事件观察。").font(.system(size:12)).foregroundStyle(Palette.amber).lineSpacing(4)
                    }
                    HStack(alignment:.top,spacing:16) {
                        ForEach(report.backtest.horizons) { h in
                            Panel {
                                VStack(alignment:.leading,spacing:15) {
                                    HStack { Text("持有 \(h.horizon) 日").font(.system(size:14,weight:.semibold)); Spacer(); if h.horizon==3 { Badge(text:"默认") } }
                                    Text(percent(h.mean,signed:true)).font(.system(size:31,weight:.medium,design:.rounded)).foregroundStyle((h.mean ?? 0)>=0 ? Palette.up:Palette.down)
                                    Text("平均净收益 · 单次事件").font(.system(size:10)).foregroundStyle(Palette.muted)
                                    Divider()
                                    researchRow("正收益占比",percent(h.winRate))
                                    researchRow("已结算 / 总事件","\(h.count) / \(h.total)")
                                    researchRow("收益中位数",percent(h.median,signed:true))
                                    researchRow("成本翻倍后",percent(h.stressMean,signed:true))
                                    researchRow("最差单次",percent(h.worst,signed:true))
                                    Divider()
                                    researchRow("流动性参照",percent(h.benchmark.mean,signed:true))
                                    Text("参照已结算 \(h.benchmark.count) / \(h.benchmark.total)").font(.system(size:10)).foregroundStyle(Palette.muted)
                                }.frame(maxWidth:.infinity,alignment:.leading)
                            }
                        }
                    }
                    if report.backtest.horizons.isEmpty {
                        Panel { EmptyViewMessage(icon:"clock.badge.exclamationmark",title:"历史检验数据不足",message:"请先通过 ProMax 更新复权因子和涨跌停价。") }
                    }
                    Panel {
                        VStack(alignment:.leading,spacing:16) {
                            HStack { Text("分月表现 · 默认 3 日").font(.system(size:14,weight:.semibold)); Spacer(); Text("平均净收益，并非组合净值").font(.system(size:10)).foregroundStyle(Palette.muted) }
                            Chart(report.backtest.monthly) { month in
                                if let mean=month.mean {
                                    BarMark(x:.value("月份",month.displayMonth),y:.value("平均净收益 %",mean*100))
                                        .foregroundStyle(mean>=0 ? Palette.up.opacity(0.75):Palette.down.opacity(0.75))
                                        .annotation(position:mean>=0 ? .top:.bottom) { Text(percent(mean,signed:true)).font(.system(size:10)).foregroundStyle(Palette.muted) }
                                }
                                RuleMark(y:.value("零收益",0)).foregroundStyle(Palette.line)
                            }.frame(height:190)
                                .chartXScale(domain:report.backtest.monthly.map(\.displayMonth))
                                .chartYAxis { AxisMarks { value in AxisGridLine(); AxisValueLabel { if let v=value.as(Double.self) { Text("\(decimal(v,digits:1))%") } } } }
                            HStack { ForEach(report.backtest.monthly) { m in Text("\(m.displayMonth) \(m.sampleLabel)").font(.system(size:10)).foregroundStyle(Palette.muted); Spacer() } }
                        }
                    }
                    if let h=report.backtest.horizons.first(where:{$0.horizon==3}) {
                        Panel {
                            VStack(alignment:.leading,spacing:14) {
                                Text("成交与缺失审计 · 3 日").font(.system(size:14,weight:.semibold))
                                ForEach(h.statuses.keys.sorted(),id:\.self) { key in researchRow(statusNames[key] ?? key,String(h.statuses[key] ?? 0)) }
                            }
                        }
                    }
                    Text("费用假设：往返 0.30%，压力测试 0.60%，包含佣金、税费和滑点的统一研究估计。参照组：\(report.backtest.benchmarkLabel)。样本重叠、资金占用和整数手数未建模，不据此计算年化或夏普。分月不是独立样本外检验。").font(.system(size:11)).foregroundStyle(Palette.muted).lineSpacing(5)
                    Button("在 Finder 查看报告与逐笔事件") { store.revealReport() }.buttonStyle(.bordered)
                }
            }.padding(30)
        }
    }
    private func researchRow(_ title:String,_ value:String)->some View {
        HStack { Text(title).foregroundStyle(Palette.muted); Spacer(); Text(value).monospacedDigit() }.font(.system(size:11))
    }
}

func pageTitle(_ title:String,subtitle:String)->some View {
    VStack(alignment:.leading,spacing:8) {
        Text(title).font(.system(size:25,weight:.semibold))
        Text(subtitle).font(.system(size:12)).foregroundStyle(Palette.muted)
    }
}

struct DataView:View {
    @EnvironmentObject var store:AppStore
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:22) {
                pageTitle("数据管理",subtitle:store.remoteEnabled ? "从服务器同步完整行情，在 Mac 上执行选股。":"本地行情为基础，ProMax 补齐最近 120 个交易日的必要数据。")
                if store.serverConfigured {
                    Picker("行情来源",selection:Binding(get:{store.remoteEnabled},set:{store.changeDataSource($0)})) {
                        Text("服务器 \(store.serverHost)").tag(true)
                        Text("本地数据 / ProMax").tag(false)
                    }.pickerStyle(.segmented).disabled(store.busy)
                }
                Panel {
                    VStack(alignment:.leading,spacing:14) {
                        HStack { Text(store.remoteEnabled ? "服务器数据缓存":"数据位置").font(.system(size:14,weight:.semibold)); Spacer(); if !store.remoteEnabled { Button("更换目录") { store.chooseDataRoot() }.disabled(store.busy) } }
                        Text(store.activeDataRoot).font(.system(size:12,design:.monospaced)).textSelection(.enabled)
                        if !store.remoteEnabled { Text("新增数据：\(store.overlay.path)").font(.system(size:11,design:.monospaced)).foregroundStyle(Palette.muted).textSelection(.enabled) }
                        Divider()
                        HStack {
                            Label(store.remoteEnabled ? "行情服务器":"ProMax",systemImage:"network").font(.system(size:13,weight:.semibold))
                            Text(store.remoteEnabled ? "SSH 加密 · 只读连接":"读取 macOS 钥匙串凭据").font(.system(size:11)).foregroundStyle(Palette.muted)
                            Spacer()
                            Button(store.remoteEnabled ? "同步服务器并选股":"更新数据并重新选股") { store.run(update:true) }.buttonStyle(.borderedProminent).tint(Palette.teal).disabled(store.busy)
                        }
                        Text(store.remoteEnabled ? "同步服务器已发布的五张数据表，全部校验通过后切换版本。服务器模式使用独立缓存；切回本地模式可以通过 ProMax 更新行情。":"自动检查交易日历、日线、复权因子、涨跌停价及股票列表。按日期校验后保存，可重试。新数据存放于独立目录，原始行情保持只读。").font(.system(size:11)).foregroundStyle(Palette.muted).lineSpacing(4)
                    }
                }
                if let report=store.report {
                    Panel {
                        VStack(alignment:.leading,spacing:18) {
                            Text("已载入的数据覆盖").font(.system(size:14,weight:.semibold))
                            ForEach(report.sources) { source in
                                HStack {
                                    Image(systemName:"externaldrive").font(.system(size:20,weight:.light)).foregroundStyle(Palette.teal).frame(width:34)
                                    VStack(alignment:.leading,spacing:5) {
                                        Text(source.title).font(.system(size:13,weight:.medium))
                                        Text("\(dateText(source.start)) — \(dateText(source.end))").font(.system(size:11)).foregroundStyle(Palette.muted)
                                    }
                                    Spacer()
                                    VStack(alignment:.trailing,spacing:5) {
                                        Text("\(source.rows.formatted()) 行").font(.system(size:13,design:.rounded)).monospacedDigit()
                                        Text("\(source.files) 个源文件").font(.system(size:10)).foregroundStyle(Palette.muted)
                                    }
                                }
                            }
                        }
                    }
                    if let update=report.lastUpdate {
                        Panel {
                            VStack(alignment:.leading,spacing:12) {
                                HStack { Text("最近更新").font(.system(size:14,weight:.semibold)); Spacer(); Badge(text:update.validation=="ok" ? "校验通过":"部分完成",color:update.validation=="ok" ? Palette.teal:Palette.amber) }
                                Text("目标 \(dateText(update.through)) · 检查 \(update.checkedSessions) 个交易日 · 本次补齐 \(update.updatedDays) 日").font(.system(size:12))
                                ForEach(update.failures ?? []) { failure in Text("\(dateText(failure.date))  \(failure.error)").font(.system(size:11)).foregroundStyle(Palette.amber) }
                            }
                        }
                    }
                    Panel {
                        VStack(alignment:.leading,spacing:12) {
                            Text("使用边界").font(.system(size:14,weight:.semibold))
                            ForEach(report.warnings,id:\.self) { warning in
                                HStack(alignment:.top,spacing:9) { Image(systemName:"info.circle").foregroundStyle(Palette.amber); Text(warning).lineSpacing(4) }.font(.system(size:11)).foregroundStyle(Palette.muted)
                            }
                        }
                    }
                }
                if !store.historyLog.isEmpty {
                    Panel { VStack(alignment:.leading,spacing:10) { Text("本次运行记录").font(.system(size:13,weight:.semibold)); Text(store.historyLog).font(.system(size:10,design:.monospaced)).foregroundStyle(Palette.muted).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading) } }
                }
            }.padding(30)
        }
    }
}

struct StrategyView:View {
    @EnvironmentObject var store:AppStore
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:22) {
                pageTitle("策略说明",subtitle:"尾盘定时筛选与盘后研究 · 每项条件都有明确口径")
                Text("尾盘定时选股").font(.system(size:20,weight:.semibold))
                RealtimeStrategyDescriptions()
                Divider().padding(.vertical,10)
                Text("盘后研究策略").font(.system(size:20,weight:.semibold))
                Panel { VStack(alignment:.leading,spacing:13) {
                    HStack { Text("左侧低吸").font(.system(size:20,weight:.semibold)); Spacer(); Badge(text:"新增 · 研究",color:Palette.amber) }
                    Text(LeftReboundGuide.summary).font(.system(size:13)).foregroundStyle(Palette.muted).lineSpacing(5)
                    ForEach(LeftReboundGuide.rules,id:\.self) { Text($0).font(.system(size:12)).foregroundStyle(Palette.muted).lineSpacing(5) }
                } }
                Panel { VStack(alignment:.leading,spacing:13) {
                    HStack { Text("黄金坑").font(.system(size:20,weight:.semibold)); Spacer(); Badge(text:"新增") }
                    Text(GoldenPitGuide.summary).font(.system(size:13)).foregroundStyle(Palette.muted).lineSpacing(5)
                    ForEach(GoldenPitGuide.rules,id:\.self) { Text($0).font(.system(size:12)).foregroundStyle(Palette.muted).lineSpacing(5) }
                } }
                Panel { VStack(alignment:.leading,spacing:13) {
                    HStack { Text("流动性趋势").font(.system(size:20,weight:.semibold)); Spacer(); Badge(text:"默认方案") }
                    Text("在基础池中选择 20 日成交额前 20%、20 日相对强度前 50% 的股票。收盘 > MA20 > MA60，MA20 向上；高于 MA20 不超过 8%，5 日涨幅在 -3% 至 12%。收盘不低于 MA10 且单日涨幅 0–5% 时确认。市场宽度至少 40%。").font(.system(size:12)).foregroundStyle(Palette.muted).lineSpacing(5)
                    Text("评分：流动性 35、相对强度 30、趋势 20、低波动 15。与回踩模型共用基础池、次日执行和费用假设。增加此模型源于首版回踩检验未占优；因此后续历史结果仍属于探索性研究，不能冒称独立样本外。").font(.system(size:11)).foregroundStyle(Palette.muted).lineSpacing(5)
                } }
                Panel { VStack(alignment:.leading,spacing:13) {
                    Text("寻找上涨趋势里的短暂休息").font(.system(size:20,weight:.semibold))
                    Text("从有成交、趋势向上的股票中，寻找近期缩量回踩、收盘重新转强的机会。希望利用 1–5 日的趋势延续，同时限制追高、流动性和市场整体转弱的风险。这个逻辑是一项待验证的假设。").font(.system(size:13)).foregroundStyle(Palette.muted).lineSpacing(6)
                } }
                rule("01",title:"先保证股票与数据可用",body:"沪深 A 股，当前非 ST / 退市名称；至少 80 根日线，最近 60 个市场交易日连续有行情。价格不低于 3 元，20 日平均成交额至少 1 亿元，ATR / 价格不高于 6%。")
                rule("02",title:"趋势、回踩、量能同时满足",body:"收盘 > MA20 > MA60，MA20 向上；20 日强度位于基础池前 35%。距离 10 日最高价回撤 1%–10%，高于 MA20 不超过 8%；近 3 日平均成交额不超过 20 日均额的 95%，当天涨跌幅在 -1% 至 5%。")
                rule("03",title:"转强确认，再进入精选",body:"当天上涨且收盘位置位于日内振幅上部 45%。市场宽度至少 40%；不足时暂停新候选。按匹配分排序，精选最多 10 只，每个行业最多 2 只。条件不足时允许空仓观察。")
                rule("04",title:"匹配分有明确组成",body:"相对强度 30 分、趋势 20 分、回踩位置 20 分、量能收缩 15 分、低波动 15 分。分数反映形态匹配程度，不是获利概率。")
                rule("05",title:"进入、退出和检验边界",body:"D 日收盘信号，D+1 开盘进入，默认持有 3 个交易日后开盘退出，同时报告 1 / 5 日结果。高开超过 3% 或涨停不假定买入；已知跌停最多顺延 5 日，缺失行情或限制价单列为退出缺数。未走完延迟窗口标记截尾。盘中止损未纳入检验。")
                Text("价格形态使用日线 close / 除权参考前收构建的连续价格，K 线归一至最新收盘价；事件收益使用原始开盘价和当日复权因子。最新因子或限制价缺失时，软件会提示。历史验证状态请以“历史检验”页为准。").font(.system(size:11)).foregroundStyle(Palette.muted).lineSpacing(5)
            }.padding(30)
        }
    }
    private func rule(_ number:String,title:String,body:String)->some View {
        HStack(alignment:.top,spacing:20) {
            Text(number).font(.system(size:25,weight:.light,design:.rounded)).foregroundStyle(Palette.teal.opacity(0.5)).frame(width:38)
            VStack(alignment:.leading,spacing:9) { Text(title).font(.system(size:14,weight:.semibold)); Text(body).font(.system(size:12)).foregroundStyle(Palette.muted).lineSpacing(5) }
        }.padding(.vertical,8)
    }
}
