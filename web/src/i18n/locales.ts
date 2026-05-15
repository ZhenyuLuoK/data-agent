// All UI strings live here. Keys are flat strings to keep usage as `t('home.title')`.
// Adding a new locale = duplicate the object, translate values, register in `LOCALES`.

export type LocaleKey = 'zh' | 'en';

export interface LocaleDict {
  // Common
  'common.cancel': string;
  'common.save': string;
  'common.confirm': string;
  'common.close': string;
  'common.delete': string;
  'common.refresh': string;
  'common.retry': string;
  'common.loading': string;
  'common.open': string;
  'common.download': string;
  'common.openInNewTab': string;
  'common.search': string;
  'common.actions': string;
  'common.optional': string;
  'common.required': string;
  'common.all': string;
  'common.empty': string;
  'common.error': string;
  'common.notGenerated': string;

  // App / nav
  'app.brand.tag': string;
  'nav.tasks': string;
  'nav.upload': string;
  'nav.runs': string;
  'nav.docs': string;
  'nav.settings': string;
  'nav.docs.architecture': string;
  'nav.docs.papers': string;
  'nav.docs.workflow': string;
  'lang.switch': string;
  'lang.zh': string;
  'lang.en': string;

  // Home
  'home.tag.console': string;
  'home.title.before': string;
  'home.title.after': string;
  'home.subtitle': string;
  'home.cta.start': string;
  'home.cta.upload': string;
  'home.cta.configure': string;
  'home.entries.tasks.title': string;
  'home.entries.tasks.desc': string;
  'home.entries.upload.title': string;
  'home.entries.upload.desc': string;
  'home.entries.runs.title': string;
  'home.entries.runs.desc': string;
  'home.entries.docs.title': string;
  'home.entries.docs.desc': string;
  'home.connector.title': string;
  'home.connector.desc.before': string;
  'home.connector.link': string;
  'home.connector.desc.after': string;

  // Home — architecture overview
  'home.arch.title': string;
  'home.arch.subtitle': string;
  'home.arch.stat.nodes': string;
  'home.arch.stat.routers': string;
  'home.arch.stat.budgets': string;
  'home.arch.stat.roles': string;
  'home.arch.pipeline.title': string;
  'home.arch.pipeline.plan': string;
  'home.arch.pipeline.plan.desc': string;
  'home.arch.pipeline.schedule': string;
  'home.arch.pipeline.schedule.desc': string;
  'home.arch.pipeline.execute': string;
  'home.arch.pipeline.execute.desc': string;
  'home.arch.pipeline.reflect': string;
  'home.arch.pipeline.reflect.desc': string;
  'home.arch.workflow.title': string;
  'home.arch.workflow.desc': string;
  'home.arch.readMore': string;

  // Home — deep architecture sections
  'home.arch.overview.title': string;
  'home.arch.overview.subtitle': string;
  'home.arch.overview.gap.title': string;
  'home.arch.overview.gap.subtitle': string;
  'home.arch.overview.gap.context': string;
  'home.arch.overview.gap.wander': string;
  'home.arch.overview.gap.deadloop': string;
  'home.arch.overview.solution.title': string;
  'home.arch.overview.solution.subtitle': string;
  'home.arch.overview.solution.plan': string;
  'home.arch.overview.solution.planDesc': string;
  'home.arch.overview.solution.exec': string;
  'home.arch.overview.solution.execDesc': string;
  'home.arch.overview.solution.review': string;
  'home.arch.overview.solution.reviewDesc': string;
  'home.arch.overview.solution.scaffold': string;
  'home.arch.overview.solution.scaffoldDesc': string;

  'home.arch.topology.title': string;
  'home.arch.topology.subtitle': string;
  'home.arch.topology.scheduler': string;
  'home.arch.topology.schedulerDesc': string;
  'home.arch.topology.executor': string;
  'home.arch.topology.executorDesc': string;
  'home.arch.topology.reflector': string;
  'home.arch.topology.reflectorDesc': string;
  'home.arch.topology.nodeFailure': string;
  'home.arch.topology.nodeFailureDesc': string;
  'home.arch.topology.nudge': string;
  'home.arch.topology.nudgeDesc': string;
  'home.arch.topology.finalize': string;
  'home.arch.topology.finalizeDesc': string;

  'home.arch.budget.title': string;
  'home.arch.budget.subtitle': string;
  'home.arch.budget.l1.title': string;
  'home.arch.budget.l1.desc': string;
  'home.arch.budget.l2.title': string;
  'home.arch.budget.l2.desc': string;
  'home.arch.budget.l3.title': string;
  'home.arch.budget.l3.desc': string;
  'home.arch.budget.l4.title': string;
  'home.arch.budget.l4.desc': string;

  'home.arch.antiHallucination.title': string;
  'home.arch.antiHallucination.subtitle': string;
  'home.arch.antiHallucination.without': string;
  'home.arch.antiHallucination.withoutDesc': string;
  'home.arch.antiHallucination.with': string;
  'home.arch.antiHallucination.withDesc': string;

  // Step timeline
  'steps.title': string;
  'steps.empty': string;
  'steps.executing': string;
  'steps.plan': string;
  'steps.toolCall': string;
  'steps.elapsed': string;
  'steps.tab.log': string;
  'steps.tab.steps': string;

  // Agent Graph (LangGraph node visualization)
  'agentGraph.title': string;
  'agentGraph.empty': string;
  'agentGraph.planner': string;
  'agentGraph.scheduler': string;
  'agentGraph.executor': string;
  'agentGraph.tools': string;
  'agentGraph.reflector': string;
  'agentGraph.replanner': string;
  'agentGraph.finalize': string;
  'agentGraph.nudge': string;
  'agentGraph.nodeFailure': string;
  'agentGraph.reasoning': string;

  // Tasks
  'tasks.title': string;
  'tasks.subtitle': string;
  'tasks.searchPlaceholder': string;
  'tasks.count': string;
  'tasks.empty.title': string;
  'tasks.empty.desc': string;
  'tasks.col.id': string;
  'tasks.col.difficulty': string;
  'tasks.col.question': string;
  'tasks.col.context': string;
  'tasks.contextFiles': string;
  'tasks.runWithCurrent': string;
  'tasks.run': string;
  'tasks.drawer.question': string;
  'tasks.drawer.contextFiles': string;
  'tasks.drawer.noContext': string;
  'tasks.detailLoadFailed': string;

  // Upload
  'upload.title': string;
  'upload.subtitle': string;
  'upload.taskId': string;
  'upload.taskIdPlaceholder': string;
  'upload.difficulty': string;
  'upload.question': string;
  'upload.questionPlaceholder': string;
  'upload.contextFiles': string;
  'upload.dropzoneTitle': string;
  'upload.dropzoneHint': string;
  'upload.pickFiles': string;
  'upload.pickFolder': string;
  'upload.filesSummary': string;
  'upload.tooLargeTotal': string;
  'upload.uploading': string;
  'upload.uploaded': string;
  'upload.action': string;
  'upload.runNow': string;
  'upload.reset': string;
  'upload.errors.questionRequired': string;
  'upload.errors.fileRequired': string;
  'upload.errors.fixFiles': string;
  'upload.errors.failed': string;
  'upload.success': string;
  'upload.fileError.path': string;
  'upload.fileError.pathSlash': string;
  'upload.fileError.ext': string;
  'upload.fileError.size': string;

  // Runs list
  'runs.title': string;
  'runs.subtitle': string;
  'runs.empty.title': string;
  'runs.empty.desc': string;
  'runs.empty.cta': string;
  'runs.col.runId': string;
  'runs.col.task': string;
  'runs.col.source': string;
  'runs.col.status': string;
  'runs.col.started': string;
  'runs.col.duration': string;
  'runs.view': string;

  // Run detail
  'run.back': string;
  'run.cancel': string;
  'run.cancelling': string;
  'run.confirmCancel': string;
  'run.cancelSent': string;
  'run.cancelFailed': string;
  'run.rerun': string;
  'run.refresh': string;
  'run.refreshFailed': string;
  'run.expandHint': string;

  // Log panel
  'log.follow': string;
  'log.following': string;
  'log.pause': string;
  'log.resume': string;
  'log.filterPlaceholder': string;
  'log.connection': string;
  'log.downloadRaw': string;
  'log.truncated': string;
  'log.loadFull': string;
  'log.loadFullSuccess': string;
  'log.loadFullFailed': string;

  // DAG
  'dag.empty': string;
  'dag.node': string;
  'dag.final': string;
  'dag.goal': string;
  'dag.expectedOutput': string;
  'dag.suggestedTools': string;
  'dag.dependsOn': string;
  'dag.outputSummary': string;
  'dag.latestStep': string;
  'dag.thought': string;
  'dag.action': string;
  'dag.actionInput': string;
  'dag.observation': string;

  // Artifacts
  'artifact.prediction': string;
  'artifact.trace': string;
  'artifact.dagSvg': string;
  'artifact.rawLog': string;
  'artifact.predictionMissing': string;
  'artifact.traceMissing': string;
  'artifact.dagMissing': string;
  'artifact.parseFailed': string;
  'artifact.empty': string;
  'artifact.svgUnsupported': string;
  'artifact.first200': string;
  'artifact.metaLoading': string;

  // Run config modal
  'runcfg.title': string;
  'runcfg.task': string;
  'runcfg.model': string;
  'runcfg.apiBase': string;
  'runcfg.apiKey': string;
  'runcfg.apiKeyHasDefault': string;
  'runcfg.apiKeyNoDefault': string;
  'runcfg.maxSteps': string;
  'runcfg.temperature': string;
  'runcfg.timeout': string;
  'runcfg.voteRounds': string;
  'runcfg.saveAsDefault': string;
  'runcfg.saveAsDefaultHint': string;
  'runcfg.show': string;
  'runcfg.hide': string;
  'runcfg.submit': string;
  'runcfg.submitting': string;
  'runcfg.warnApiKey': string;
  'runcfg.warnApiKeyDesc': string;
  'runcfg.runCreated': string;
  'runcfg.loadDefaultsFailed': string;
  'runcfg.submitFailed': string;

  // Settings
  'settings.title': string;
  'settings.subtitle': string;
  'settings.privacy.title': string;
  'settings.privacy.desc.before': string;
  'settings.privacy.desc.warn': string;
  'settings.saveLabel': string;
  'settings.saved': string;
  'settings.savedMemoryOnly': string;
  'settings.savedPersisted': string;
  'settings.clear': string;
  'settings.cleared': string;
  'settings.serverDefaults': string;

  // Docs
  'docs.openInNewTab': string;

  // Empty / loading
  'empty.loadFailed': string;

  // Toast — generic backend errors
  'wsError.title': string;
  'wsBufferDrop.title': string;
  'wsBufferDrop.desc': string;
  'wsRunNotFound': string;
  'wsRunNotFoundDesc': string;
  'wsMaxReconnect': string;
  'wsMaxReconnectDesc': string;
}

const zh: LocaleDict = {
  'common.cancel': '取消',
  'common.save': '保存',
  'common.confirm': '确认',
  'common.close': '关闭',
  'common.delete': '删除',
  'common.refresh': '刷新',
  'common.retry': '重试',
  'common.loading': '加载中…',
  'common.open': '打开',
  'common.download': '下载',
  'common.openInNewTab': '在新标签页打开',
  'common.search': '搜索',
  'common.actions': '操作',
  'common.optional': '可选',
  'common.required': '必填',
  'common.all': '全部',
  'common.empty': '空',
  'common.error': '错误',
  'common.notGenerated': '(待生成)',

  'app.brand.tag': 'console',
  'nav.tasks': 'Tasks',
  'nav.upload': 'Upload',
  'nav.runs': 'Runs',
  'nav.docs': 'Docs',
  'nav.settings': 'Settings',
  'nav.docs.architecture': 'Agent 架构',
  'nav.docs.papers': '研究论文',
  'nav.docs.workflow': '工作流 SVG',
  'lang.switch': '语言',
  'lang.zh': '中文',
  'lang.en': 'EN',

  'home.tag.console': 'data-agent baseline',
  'home.title.before': '推理过程可视化的',
  'home.title.after': '开发者控制台',
  'home.subtitle':
    '连接你的模型、提交数据问题、实时观察 Agent 的工具调用与 DAG 演化。为基线评估与生产化部署提供同一套 UI。',
  'home.cta.start': 'Start a run',
  'home.cta.upload': '上传自定义任务',
  'home.cta.configure': '配置模型',
  'home.entries.tasks.title': 'Browse tasks',
  'home.entries.tasks.desc': '从内置任务库挑选基线问题，一键触发 Agent 推理。',
  'home.entries.upload.title': 'Upload your own',
  'home.entries.upload.desc':
    '上传 csv / json / parquet / sqlite，定义自己的数据问题。',
  'home.entries.runs.title': 'Inspect runs',
  'home.entries.runs.desc': '查看历史 run 的实时日志、DAG 与产物，可重跑/取消。',
  'home.entries.docs.title': 'Read the docs',
  'home.entries.docs.desc': '架构总览、推理协议、研究材料一应俱全。',
  'home.connector.title': 'Connector status',
  'home.connector.desc.before':
    '右上角始终显示当前选中的 model 与 api_base。api_key 默认仅保留在内存中；进入 ',
  'home.connector.link': 'Settings',
  'home.connector.desc.after': ' 可显式 Save as default 持久化到本浏览器。',

  'home.arch.title': 'Agent 架构概览',
  'home.arch.subtitle': '一份针对数据分析任务深度加固的工业级 Agent —— 把传统 ReAct 折弯为 Plan–Schedule–Execute–Reflect 闭环。',
  'home.arch.stat.nodes': '类节点',
  'home.arch.stat.routers': '条件路由器',
  'home.arch.stat.budgets': '层同心预算',
  'home.arch.stat.roles': '独立 LLM 角色',
  'home.arch.pipeline.title': '四阶段闭环',
  'home.arch.pipeline.plan': '规划',
  'home.arch.pipeline.plan.desc': '将复杂任务显式分解为 DAG 子节点，每个节点有独立的目标、工具与输出约束。',
  'home.arch.pipeline.schedule': '调度',
  'home.arch.pipeline.schedule.desc': '根据 DAG 依赖拓扑与上游输出，选择就绪节点调度执行。',
  'home.arch.pipeline.execute': '执行',
  'home.arch.pipeline.execute.desc': '单节点独立 ReAct 循环，工具调用沙箱化，自带步数与超时预算。',
  'home.arch.pipeline.reflect': '反思',
  'home.arch.pipeline.reflect.desc': '执行结果交由监督模块校验，失败触发降级、重规划或紧急提交。',
  'home.arch.workflow.title': 'Agent 工作流',
  'home.arch.workflow.desc': 'LangGraph 节点拓扑与状态流转的完整可视化。',
  'home.arch.readMore': '查看完整架构文档',

  'home.arch.overview.title': '这是一个怎样的 Agent',
  'home.arch.overview.subtitle': '把"通用 LLM Agent"折弯为针对数据分析任务做了大量定向加固的工业级流水线。',
  'home.arch.overview.gap.title': '传统 ReAct 的失效模式',
  'home.arch.overview.gap.subtitle': '单一 LLM ↔ Tools 自循环，"思考 + 调度 + 执行 + 终止"全揉在一段对话里',
  'home.arch.overview.gap.context': '上下文涣散 — 长任务中对话不断膨胀，LLM 注意力被无关历史稀释。',
  'home.arch.overview.gap.wander': '漫游 / 跳步 / 漏做 — 没有显式分解，多步任务中容易跳过中间环节。',
  'home.arch.overview.gap.deadloop': '死循环 / 卡死 — 没有外部预算与降级路径，task 撞 1800s 硬杀。',
  'home.arch.overview.solution.title': 'Plan–Schedule–Execute–Reflect 闭环',
  'home.arch.overview.solution.subtitle': '把"思考 / 调度 / 执行 / 审阅"四件事分给四种角色，把"流程推进"交给确定性代码。',
  'home.arch.overview.solution.plan': '全局规划',
  'home.arch.overview.solution.planDesc': '一个 LLM 通看问题 + 真实数据画像，产出 DAG 计划。',
  'home.arch.overview.solution.exec': '局部执行',
  'home.arch.overview.solution.execDesc': '另一个 LLM 在每个 DAG 节点的聚焦提示里推进、调工具。',
  'home.arch.overview.solution.review': '最终审阅',
  'home.arch.overview.solution.reviewDesc': '第三个 LLM 检查答案的结构、单位、行列形态，决定 OK / RETRY。',
  'home.arch.overview.solution.scaffold': '控制流脚手架',
  'home.arch.overview.solution.scaffoldDesc': '调度器、重规划、失败处理、空轮纠偏，全部为纯代码节点。',

  'home.arch.topology.title': '9 类节点，4 大职责层',
  'home.arch.topology.subtitle': '按"职责"把节点划成规划 / 调度 / 执行 / 监督降级四层。',
  'home.arch.topology.scheduler': '调度器 scheduler',
  'home.arch.topology.schedulerDesc': '整张图的"心脏"——不调 LLM，只做依赖检查、焦点切换、终止判定。纯代码、零幻觉。',
  'home.arch.topology.executor': '执行器 executor',
  'home.arch.topology.executorDesc': '绑定全部工具的 ChatLLM，只看到聚焦提示 + 之前几轮对话，专注当前一个 DAG 节点。',
  'home.arch.topology.reflector': '反思器 reflector',
  'home.arch.topology.reflectorDesc': '在 executor 提交 answer 后触发，检查列数/行数/单位/空值/大小写，结论 OK 或 RETRY。',
  'home.arch.topology.nodeFailure': '节点失败 node_failure',
  'home.arch.topology.nodeFailureDesc': '节点超步预算后进入：未到尝试上限 → 软重试；超过 → 标 failed → 走 replanner。',
  'home.arch.topology.nudge': '空轮纠偏 nudge',
  'home.arch.topology.nudgeDesc': '应对模型偶发空 AIMessage，提醒一次且不消耗节点步数预算。',
  'home.arch.topology.finalize': '终结 finalize',
  'home.arch.topology.finalizeDesc': 'no-op 叶子节点，所有路径最终汇聚到这里接入 END。',

  'home.arch.budget.title': '四层同心圆预算',
  'home.arch.budget.subtitle': '每一处可能"陷进去"的地方都有显式预算，任何 LLM 失败都不能让整体卡死。',
  'home.arch.budget.l1.title': '① 单工具调用层',
  'home.arch.budget.l1.desc': '检测连续 N 次相同参数的同一工具、对同一份长文档过度分页，注入一次性 SystemMessage 警告。',
  'home.arch.budget.l2.title': '② 单节点层',
  'home.arch.budget.l2.desc': '每个 DAG 节点有 max_steps_per_node 个回合预算 + max_node_attempts 次整轮重试机会。',
  'home.arch.budget.l3.title': '③ 整体规划层',
  'home.arch.budget.l3.desc': 'max_replans 限制整个任务最多被重新规划几次，耗尽则直接 finalize。',
  'home.arch.budget.l4.title': '④ 整体反思层',
  'home.arch.budget.l4.desc': 'max_reflections 限制 reflector 最多让 executor 重交几次答案，防止弹乒乓。',

  'home.arch.antiHallucination.title': '前置数据画像 — 让规划基于事实',
  'home.arch.antiHallucination.subtitle': 'planner 和 replanner 被调用前，先离线扫描 context/ 目录，把真实文件清单压成"数据集画像"。',
  'home.arch.antiHallucination.without': '没有数据画像时',
  'home.arch.antiHallucination.withoutDesc': '约 80% 的失败是 planner/executor 虚构了不存在的文件路径、表名。',
  'home.arch.antiHallucination.with': '注入数据画像后',
  'home.arch.antiHallucination.withDesc': '规划阶段就看到真实文件清单 + 表名 + CSV 头 + JSON 前缀，从源头压制路径幻觉。',

  'steps.title': '执行链路',
  'steps.empty': '尚无执行步骤 — Agent 还在启动中…',
  'steps.executing': '正在执行第 {index} 个节点：{desc}',
  'steps.plan': '📋 任务规划',
  'steps.toolCall': '🔧 {action}',
  'steps.elapsed': '{ms}ms',
  'steps.tab.log': '日志',
  'steps.tab.steps': '执行链路',

  'agentGraph.title': 'Agent 拓扑',
  'agentGraph.empty': '等待 Agent 启动…',
  'agentGraph.planner': '规划器',
  'agentGraph.scheduler': '调度器',
  'agentGraph.executor': '执行器',
  'agentGraph.tools': '工具节点',
  'agentGraph.reflector': '反思器',
  'agentGraph.replanner': '重规划器',
  'agentGraph.finalize': '终结器',
  'agentGraph.nudge': '唤醒器',
  'agentGraph.nodeFailure': '失败处理',
  'agentGraph.reasoning': '推理器',

  'tasks.title': 'Tasks',
  'tasks.subtitle': '内置任务库 · 选中后可直接以当前默认模型配置触发 Agent',
  'tasks.searchPlaceholder': '搜索 task_id 或 question…',
  'tasks.count': '{count} 个任务',
  'tasks.empty.title': '没有匹配的任务',
  'tasks.empty.desc': '试着清空搜索或切换 difficulty。',
  'tasks.col.id': 'Task ID',
  'tasks.col.difficulty': 'Difficulty',
  'tasks.col.question': 'Question',
  'tasks.col.context': 'Context',
  'tasks.contextFiles': '{count} 个文件',
  'tasks.runWithCurrent': '以当前配置运行',
  'tasks.run': 'Run',
  'tasks.drawer.question': 'Question',
  'tasks.drawer.contextFiles': 'Context 文件',
  'tasks.drawer.noContext': '暂无 context 文件',
  'tasks.detailLoadFailed': '加载任务详情失败',

  'upload.title': '上传自定义任务',
  'upload.subtitle': '定义一个属于你自己的数据问题，附带上下文文件后即可触发 Agent 推理。',
  'upload.taskId': 'Task ID（可选）',
  'upload.taskIdPlaceholder': '留空则自动生成 task_upload_<timestamp>',
  'upload.difficulty': 'Difficulty',
  'upload.question': 'Question',
  'upload.questionPlaceholder': '用一段话描述你想让 Agent 解决的问题…',
  'upload.contextFiles': 'Context 文件',
  'upload.dropzoneTitle': '拖拽文件 / 文件夹至此',
  'upload.dropzoneHint':
    '支持 csv, tsv, json, jsonl, xlsx, xls, parquet, db, sqlite, sqlite3, txt, md · 单文件 ≤ 200 MB · 总量 ≤ 1 GB',
  'upload.pickFiles': '选择文件',
  'upload.pickFolder': '选择文件夹',
  'upload.filesSummary': '{count} 个文件 · {mb} MB',
  'upload.tooLargeTotal': '总量超过 1 GB',
  'upload.uploading': '上传中…',
  'upload.uploaded': '已上传 ✓',
  'upload.action': 'Upload',
  'upload.runNow': '立即运行',
  'upload.reset': '重新上传',
  'upload.errors.questionRequired': 'Question 必填',
  'upload.errors.fileRequired': '至少上传 1 个 context 文件',
  'upload.errors.fixFiles': '请先解决标红的文件',
  'upload.errors.failed': '上传失败',
  'upload.success': '上传成功',
  'upload.fileError.path': '路径包含 ..',
  'upload.fileError.pathSlash': '路径不能以 / 开头',
  'upload.fileError.ext': '不支持的扩展名 .{ext}',
  'upload.fileError.size': '单文件超过 200 MB',

  'runs.title': 'Runs',
  'runs.subtitle': '最近的 Agent 运行记录 · 实时刷新请进入详情页',
  'runs.empty.title': '还没有 run',
  'runs.empty.desc': '去 Tasks 选一个任务、或者上传你自己的数据，开始第一次推理。',
  'runs.empty.cta': '浏览任务',
  'runs.col.runId': 'Run ID',
  'runs.col.task': 'Task',
  'runs.col.source': 'Source',
  'runs.col.status': 'Status',
  'runs.col.started': 'Started',
  'runs.col.duration': 'Duration',
  'runs.view': '查看',

  'run.back': '← runs',
  'run.cancel': 'Cancel',
  'run.cancelling': '取消中…',
  'run.confirmCancel': '确定取消此 run 吗？',
  'run.cancelSent': '取消请求已发送',
  'run.cancelFailed': '取消失败',
  'run.rerun': 'Re-run',
  'run.refresh': '刷新元信息',
  'run.refreshFailed': '刷新失败',
  'run.expandHint': '点击展开/折叠',

  'log.follow': '跟随尾部',
  'log.following': '跟随中',
  'log.pause': '暂停',
  'log.resume': '继续',
  'log.filterPlaceholder': '过滤关键字…',
  'log.connection': 'WS 连接状态',
  'log.downloadRaw': '下载完整 agent.log',
  'log.truncated': '快照已截断为最后 1 MiB；建议加载完整日志查看历史。',
  'log.loadFull': '加载完整日志',
  'log.loadFullSuccess': '已加载完整日志',
  'log.loadFullFailed': '加载失败',

  'dag.empty': 'DAG 尚未生成 — Agent 仍在规划中…',
  'dag.node': 'Node',
  'dag.final': 'FINAL',
  'dag.goal': 'Goal',
  'dag.expectedOutput': 'Expected output',
  'dag.suggestedTools': 'Suggested tools',
  'dag.dependsOn': 'Depends on',
  'dag.outputSummary': 'Output summary',
  'dag.latestStep': 'Latest step',
  'dag.thought': 'thought',
  'dag.action': 'action',
  'dag.actionInput': 'action_input',
  'dag.observation': 'observation',

  'artifact.prediction': 'Prediction CSV',
  'artifact.trace': 'Trace JSON',
  'artifact.dagSvg': 'DAG SVG',
  'artifact.rawLog': 'Raw agent.log',
  'artifact.predictionMissing': 'prediction.csv 暂未生成',
  'artifact.traceMissing': 'trace.json 暂未生成',
  'artifact.dagMissing': 'dag.svg 暂未生成',
  'artifact.parseFailed': '解析失败：{message}',
  'artifact.empty': '空文件',
  'artifact.svgUnsupported': '无法渲染 SVG',
  'artifact.first200': '仅展示前 200 行 · 下载完整文件查看更多',
  'artifact.metaLoading': 'Run 元信息加载中…',

  'runcfg.title': 'Run',
  'runcfg.task': 'Task',
  'runcfg.model': 'Model',
  'runcfg.apiBase': 'API Base',
  'runcfg.apiKey': 'API Key',
  'runcfg.apiKeyHasDefault': '使用服务端默认 key（可覆盖）',
  'runcfg.apiKeyNoDefault': '必填：未在服务端配置默认 key',
  'runcfg.maxSteps': 'Max Steps',
  'runcfg.temperature': 'Temperature',
  'runcfg.timeout': 'Task Timeout (s, 0 = ∞)',
  'runcfg.voteRounds': 'Vote Rounds',
  'runcfg.saveAsDefault': '保存为默认值',
  'runcfg.saveAsDefaultHint': '（包含 API Key 时仅写入本浏览器 localStorage）',
  'runcfg.show': 'Show',
  'runcfg.hide': 'Hide',
  'runcfg.submit': '使用以上配置运行',
  'runcfg.submitting': '提交中…',
  'runcfg.warnApiKey': '需要 API Key',
  'runcfg.warnApiKeyDesc': '服务端未配置默认 key，请在此填写',
  'runcfg.runCreated': 'Run 已创建',
  'runcfg.loadDefaultsFailed': '加载默认配置失败',
  'runcfg.submitFailed': '提交失败',

  'settings.title': 'Settings',
  'settings.subtitle':
    '默认 model / api_base / api_key 与运行参数。这些值会作为 Run 配置弹窗的预填值。',
  'settings.privacy.title': '隐私提醒',
  'settings.privacy.desc.before':
    'API Key 仅存储在你当前浏览器的 localStorage 中，绝不会被上报到日志。',
  'settings.privacy.desc.warn': '如使用公共电脑，请勿勾选 Save as default。',
  'settings.saveLabel': '保存 API Key 为默认值（写入本浏览器 localStorage）',
  'settings.saved': '已保存',
  'settings.savedMemoryOnly': 'API Key 仅保留在内存',
  'settings.savedPersisted': 'API Key 已写入本浏览器 localStorage',
  'settings.clear': '清除本地配置',
  'settings.cleared': '已清除本地配置',
  'settings.serverDefaults': 'Server defaults',

  'docs.openInNewTab': '在新标签页打开',

  'empty.loadFailed': '加载失败',

  'wsError.title': 'Agent error',
  'wsBufferDrop.title': '日志缓冲跌出',
  'wsBufferDrop.desc': '服务端事件缓冲区已滚动，正在重新拉取快照…',
  'wsRunNotFound': 'Run 不存在',
  'wsRunNotFoundDesc': 'run_id={runId} 已被服务器拒绝',
  'wsMaxReconnect': '实时流断开',
  'wsMaxReconnectDesc': '已达到最大重连次数，请刷新页面重试',
};

const en: LocaleDict = {
  'common.cancel': 'Cancel',
  'common.save': 'Save',
  'common.confirm': 'Confirm',
  'common.close': 'Close',
  'common.delete': 'Delete',
  'common.refresh': 'Refresh',
  'common.retry': 'Retry',
  'common.loading': 'Loading…',
  'common.open': 'Open',
  'common.download': 'Download',
  'common.openInNewTab': 'Open in new tab',
  'common.search': 'Search',
  'common.actions': 'Actions',
  'common.optional': 'Optional',
  'common.required': 'Required',
  'common.all': 'All',
  'common.empty': 'Empty',
  'common.error': 'Error',
  'common.notGenerated': '(not yet)',

  'app.brand.tag': 'console',
  'nav.tasks': 'Tasks',
  'nav.upload': 'Upload',
  'nav.runs': 'Runs',
  'nav.docs': 'Docs',
  'nav.settings': 'Settings',
  'nav.docs.architecture': 'Agent Architecture',
  'nav.docs.papers': 'Research Papers',
  'nav.docs.workflow': 'Workflow SVG',
  'lang.switch': 'Language',
  'lang.zh': '中文',
  'lang.en': 'EN',

  'home.tag.console': 'data-agent baseline',
  'home.title.before': 'A reasoning-first',
  'home.title.after': 'developer console',
  'home.subtitle':
    'Connect your model, submit a data question, and watch tool calls & DAG evolution in real time. One UI for benchmarking and production rollout.',
  'home.cta.start': 'Start a run',
  'home.cta.upload': 'Upload custom task',
  'home.cta.configure': 'Configure model',
  'home.entries.tasks.title': 'Browse tasks',
  'home.entries.tasks.desc': 'Pick a baseline question from the built-in library and run it instantly.',
  'home.entries.upload.title': 'Upload your own',
  'home.entries.upload.desc': 'Bring csv / json / parquet / sqlite to define your own data problem.',
  'home.entries.runs.title': 'Inspect runs',
  'home.entries.runs.desc': 'Browse historical runs with live log, DAG, artifacts; cancel or re-run.',
  'home.entries.docs.title': 'Read the docs',
  'home.entries.docs.desc': 'Architecture overview, reasoning protocol, and research material.',
  'home.connector.title': 'Connector status',
  'home.connector.desc.before':
    'The current model and api_base are always shown in the top-right. The api_key stays in memory by default; visit ',
  'home.connector.link': 'Settings',
  'home.connector.desc.after': ' to opt into "Save as default" for this browser.',

  'home.arch.title': 'Architecture Overview',
  'home.arch.subtitle': 'An industrial-grade agent hardened for data-analysis tasks — bending vanilla ReAct into a Plan–Schedule–Execute–Reflect loop.',
  'home.arch.stat.nodes': 'Node types',
  'home.arch.stat.routers': 'Routers',
  'home.arch.stat.budgets': 'Budget layers',
  'home.arch.stat.roles': 'LLM roles',
  'home.arch.pipeline.title': 'Four-stage loop',
  'home.arch.pipeline.plan': 'Plan',
  'home.arch.pipeline.plan.desc': 'Decompose complex tasks into DAG sub-nodes, each with its own goal, tools, and output constraints.',
  'home.arch.pipeline.schedule': 'Schedule',
  'home.arch.pipeline.schedule.desc': 'Select ready nodes based on DAG dependency topology and upstream outputs.',
  'home.arch.pipeline.execute': 'Execute',
  'home.arch.pipeline.execute.desc': 'Per-node sandboxed ReAct loop with individual step and timeout budgets.',
  'home.arch.pipeline.reflect': 'Reflect',
  'home.arch.pipeline.reflect.desc': 'Results verified by a supervisor; failures trigger fallback, re-planning, or emergency submission.',
  'home.arch.workflow.title': 'Agent Workflow',
  'home.arch.workflow.desc': 'Full visualization of LangGraph node topology and state transitions.',
  'home.arch.readMore': 'Read full architecture docs',

  'home.arch.overview.title': 'What kind of Agent is this?',
  'home.arch.overview.subtitle': 'Bending a vanilla LLM Agent into an industrial-grade pipeline hardened for data-analysis tasks.',
  'home.arch.overview.gap.title': 'Failure modes of vanilla ReAct',
  'home.arch.overview.gap.subtitle': 'Single LLM ↔ Tools self-loop — thinking, scheduling, executing, and terminating all crammed into one conversation.',
  'home.arch.overview.gap.context': 'Context dilution — conversations bloat in long tasks, diluting LLM attention with irrelevant history.',
  'home.arch.overview.gap.wander': 'Wandering / skipping / missing — without explicit decomposition, LLM easily skips intermediate steps.',
  'home.arch.overview.gap.deadloop': 'Dead loops / stuck — no external budget or fallback path; tasks hit the 1800s hard kill.',
  'home.arch.overview.solution.title': 'Plan–Schedule–Execute–Reflect loop',
  'home.arch.overview.solution.subtitle': 'Four responsibilities assigned to four roles; flow control delegated to deterministic code.',
  'home.arch.overview.solution.plan': 'Global Planning',
  'home.arch.overview.solution.planDesc': 'One LLM reviews the question + real data profile to produce a DAG plan.',
  'home.arch.overview.solution.exec': 'Local Execution',
  'home.arch.overview.solution.execDesc': 'Another LLM works within a focused prompt for each DAG node, calling tools.',
  'home.arch.overview.solution.review': 'Final Review',
  'home.arch.overview.solution.reviewDesc': 'A third LLM checks structure, units, row/column shape — deciding OK or RETRY.',
  'home.arch.overview.solution.scaffold': 'Control Flow Scaffold',
  'home.arch.overview.solution.scaffoldDesc': 'Scheduler, replanner, failure handler, idle nudge — all pure code nodes.',

  'home.arch.topology.title': '9 Node Types, 4 Responsibility Layers',
  'home.arch.topology.subtitle': 'Nodes grouped by responsibility: planning / scheduling / execution / supervision & fallback.',
  'home.arch.topology.scheduler': 'Scheduler',
  'home.arch.topology.schedulerDesc': 'The graph\'s "heartbeat" — no LLM calls; only dependency checks, focus switching, and termination detection. Pure code, zero hallucination.',
  'home.arch.topology.executor': 'Executor',
  'home.arch.topology.executorDesc': 'ChatLLM bound to all tools; sees only the focused prompt + recent turns, working on one DAG node at a time.',
  'home.arch.topology.reflector': 'Reflector',
  'home.arch.topology.reflectorDesc': 'Triggered after executor submits an answer; checks columns/rows/units/nulls/casing — verdict OK or RETRY.',
  'home.arch.topology.nodeFailure': 'Node Failure',
  'home.arch.topology.nodeFailureDesc': 'Entered when a node exhausts its step budget: soft retry if under attempt limit; else mark failed → replanner.',
  'home.arch.topology.nudge': 'Nudge',
  'home.arch.topology.nudgeDesc': 'Handles spurious empty AIMessages; reminds once without consuming the node\'s step budget.',
  'home.arch.topology.finalize': 'Finalize',
  'home.arch.topology.finalizeDesc': 'No-op leaf node — all paths converge here to reach END.',

  'home.arch.budget.title': 'Four Concentric Budget Layers',
  'home.arch.budget.subtitle': 'Every place the agent can get stuck has an explicit budget — no single LLM failure can freeze the whole run.',
  'home.arch.budget.l1.title': '① Single Tool Call',
  'home.arch.budget.l1.desc': 'Detects N consecutive identical-argument calls and excessive pagination of the same document; injects a one-shot SystemMessage warning.',
  'home.arch.budget.l2.title': '② Per-Node',
  'home.arch.budget.l2.desc': 'Each DAG node has a max_steps_per_node round budget + max_node_attempts full-retry chances.',
  'home.arch.budget.l3.title': '③ Overall Planning',
  'home.arch.budget.l3.desc': 'max_replans caps how many times the entire task can be re-planned; once exhausted → finalize.',
  'home.arch.budget.l4.title': '④ Overall Reflection',
  'home.arch.budget.l4.desc': 'max_reflections caps how many times the reflector can ask the executor to re-submit, preventing ping-pong.',

  'home.arch.antiHallucination.title': 'Pre-flight Data Profile — Planning on Facts',
  'home.arch.antiHallucination.subtitle': 'Before planner and replanner are called, context/ is scanned offline and compressed into a "dataset profile".',
  'home.arch.antiHallucination.without': 'Without data profile',
  'home.arch.antiHallucination.withoutDesc': '~80% of failures were planner/executor hallucinating non-existent file paths or table names.',
  'home.arch.antiHallucination.with': 'With data profile',
  'home.arch.antiHallucination.withDesc': 'Planning phase sees real file listing + table names + CSV headers + JSON prefixes, suppressing path hallucination at the source.',

  'steps.title': 'Execution Timeline',
  'steps.empty': 'No steps yet — agent is starting up…',
  'steps.executing': 'Executing node {index}: {desc}',
  'steps.plan': '📋 Task Planning',
  'steps.toolCall': '🔧 {action}',
  'steps.elapsed': '{ms}ms',
  'steps.tab.log': 'Log',
  'steps.tab.steps': 'Timeline',

  'agentGraph.title': 'Agent Topology',
  'agentGraph.empty': 'Waiting for agent to start…',
  'agentGraph.planner': 'Planner',
  'agentGraph.scheduler': 'Scheduler',
  'agentGraph.executor': 'Executor',
  'agentGraph.tools': 'Tools',
  'agentGraph.reflector': 'Reflector',
  'agentGraph.replanner': 'Replanner',
  'agentGraph.finalize': 'Finalize',
  'agentGraph.nudge': 'Nudge',
  'agentGraph.nodeFailure': 'Node Failure',
  'agentGraph.reasoning': 'Reasoning',

  'tasks.title': 'Tasks',
  'tasks.subtitle': 'Built-in task library · run instantly with current model defaults',
  'tasks.searchPlaceholder': 'Search task_id or question…',
  'tasks.count': '{count} tasks',
  'tasks.empty.title': 'No matching tasks',
  'tasks.empty.desc': 'Try clearing the search or switching difficulty.',
  'tasks.col.id': 'Task ID',
  'tasks.col.difficulty': 'Difficulty',
  'tasks.col.question': 'Question',
  'tasks.col.context': 'Context',
  'tasks.contextFiles': '{count} files',
  'tasks.runWithCurrent': 'Run with current settings',
  'tasks.run': 'Run',
  'tasks.drawer.question': 'Question',
  'tasks.drawer.contextFiles': 'Context files',
  'tasks.drawer.noContext': 'No context files',
  'tasks.detailLoadFailed': 'Failed to load task detail',

  'upload.title': 'Upload custom task',
  'upload.subtitle': 'Define your own data question, attach context files, and trigger the agent.',
  'upload.taskId': 'Task ID (optional)',
  'upload.taskIdPlaceholder': 'Leave blank to auto-generate task_upload_<timestamp>',
  'upload.difficulty': 'Difficulty',
  'upload.question': 'Question',
  'upload.questionPlaceholder': 'Describe the problem you want the agent to solve…',
  'upload.contextFiles': 'Context files',
  'upload.dropzoneTitle': 'Drop files / folders here',
  'upload.dropzoneHint':
    'csv, tsv, json, jsonl, xlsx, xls, parquet, db, sqlite, sqlite3, txt, md · ≤ 200 MB per file · ≤ 1 GB total',
  'upload.pickFiles': 'Choose files',
  'upload.pickFolder': 'Choose folder',
  'upload.filesSummary': '{count} files · {mb} MB',
  'upload.tooLargeTotal': 'Total exceeds 1 GB',
  'upload.uploading': 'Uploading…',
  'upload.uploaded': 'Uploaded ✓',
  'upload.action': 'Upload',
  'upload.runNow': 'Run now',
  'upload.reset': 'Reset',
  'upload.errors.questionRequired': 'Question is required',
  'upload.errors.fileRequired': 'At least one context file is required',
  'upload.errors.fixFiles': 'Please fix the highlighted files first',
  'upload.errors.failed': 'Upload failed',
  'upload.success': 'Upload succeeded',
  'upload.fileError.path': 'Path contains ..',
  'upload.fileError.pathSlash': 'Path must not start with /',
  'upload.fileError.ext': 'Unsupported extension .{ext}',
  'upload.fileError.size': 'Single file exceeds 200 MB',

  'runs.title': 'Runs',
  'runs.subtitle': 'Recent agent runs · open detail for live updates',
  'runs.empty.title': 'No runs yet',
  'runs.empty.desc': 'Pick a task or upload your own data to kick off the first run.',
  'runs.empty.cta': 'Browse tasks',
  'runs.col.runId': 'Run ID',
  'runs.col.task': 'Task',
  'runs.col.source': 'Source',
  'runs.col.status': 'Status',
  'runs.col.started': 'Started',
  'runs.col.duration': 'Duration',
  'runs.view': 'View',

  'run.back': '← runs',
  'run.cancel': 'Cancel',
  'run.cancelling': 'Cancelling…',
  'run.confirmCancel': 'Cancel this run?',
  'run.cancelSent': 'Cancel request sent',
  'run.cancelFailed': 'Cancel failed',
  'run.rerun': 'Re-run',
  'run.refresh': 'Refresh metadata',
  'run.refreshFailed': 'Refresh failed',
  'run.expandHint': 'Click to expand/collapse',

  'log.follow': 'Follow tail',
  'log.following': 'Following',
  'log.pause': 'Pause',
  'log.resume': 'Resume',
  'log.filterPlaceholder': 'Filter keyword…',
  'log.connection': 'WS connection',
  'log.downloadRaw': 'Download raw agent.log',
  'log.truncated': 'Snapshot truncated to last 1 MiB; load full log to inspect history.',
  'log.loadFull': 'Load full log',
  'log.loadFullSuccess': 'Full log loaded',
  'log.loadFullFailed': 'Load failed',

  'dag.empty': 'DAG not generated yet — agent is still planning…',
  'dag.node': 'Node',
  'dag.final': 'FINAL',
  'dag.goal': 'Goal',
  'dag.expectedOutput': 'Expected output',
  'dag.suggestedTools': 'Suggested tools',
  'dag.dependsOn': 'Depends on',
  'dag.outputSummary': 'Output summary',
  'dag.latestStep': 'Latest step',
  'dag.thought': 'thought',
  'dag.action': 'action',
  'dag.actionInput': 'action_input',
  'dag.observation': 'observation',

  'artifact.prediction': 'Prediction CSV',
  'artifact.trace': 'Trace JSON',
  'artifact.dagSvg': 'DAG SVG',
  'artifact.rawLog': 'Raw agent.log',
  'artifact.predictionMissing': 'prediction.csv not generated yet',
  'artifact.traceMissing': 'trace.json not generated yet',
  'artifact.dagMissing': 'dag.svg not generated yet',
  'artifact.parseFailed': 'Parse failed: {message}',
  'artifact.empty': 'Empty file',
  'artifact.svgUnsupported': 'Cannot render SVG',
  'artifact.first200': 'Only the first 200 rows are shown · download to view all',
  'artifact.metaLoading': 'Loading run metadata…',

  'runcfg.title': 'Run',
  'runcfg.task': 'Task',
  'runcfg.model': 'Model',
  'runcfg.apiBase': 'API Base',
  'runcfg.apiKey': 'API Key',
  'runcfg.apiKeyHasDefault': 'Using server default key (overridable)',
  'runcfg.apiKeyNoDefault': 'Required: no default key on server',
  'runcfg.maxSteps': 'Max Steps',
  'runcfg.temperature': 'Temperature',
  'runcfg.timeout': 'Task Timeout (s, 0 = ∞)',
  'runcfg.voteRounds': 'Vote Rounds',
  'runcfg.saveAsDefault': 'Save as default',
  'runcfg.saveAsDefaultHint': '(API Key, when included, is stored only in this browser)',
  'runcfg.show': 'Show',
  'runcfg.hide': 'Hide',
  'runcfg.submit': 'Run with these settings',
  'runcfg.submitting': 'Submitting…',
  'runcfg.warnApiKey': 'API Key required',
  'runcfg.warnApiKeyDesc': 'No default key configured on server, please provide one',
  'runcfg.runCreated': 'Run created',
  'runcfg.loadDefaultsFailed': 'Failed to load defaults',
  'runcfg.submitFailed': 'Submit failed',

  'settings.title': 'Settings',
  'settings.subtitle':
    'Default model / api_base / api_key and run parameters. These prefill the Run config modal.',
  'settings.privacy.title': 'Privacy notice',
  'settings.privacy.desc.before':
    'The API Key is stored only in your current browser localStorage and never logged.',
  'settings.privacy.desc.warn':
    'On a public computer, do NOT enable "Save as default".',
  'settings.saveLabel': 'Save API Key as default (writes to localStorage)',
  'settings.saved': 'Saved',
  'settings.savedMemoryOnly': 'API Key kept in memory only',
  'settings.savedPersisted': 'API Key written to browser localStorage',
  'settings.clear': 'Clear local config',
  'settings.cleared': 'Local config cleared',
  'settings.serverDefaults': 'Server defaults',

  'docs.openInNewTab': 'Open in new tab',

  'empty.loadFailed': 'Failed to load',

  'wsError.title': 'Agent error',
  'wsBufferDrop.title': 'Event buffer dropped',
  'wsBufferDrop.desc': 'Server event buffer rolled over; pulling a fresh snapshot…',
  'wsRunNotFound': 'Run not found',
  'wsRunNotFoundDesc': 'run_id={runId} was rejected by the server',
  'wsMaxReconnect': 'Live stream disconnected',
  'wsMaxReconnectDesc': 'Max reconnect attempts reached, please refresh',
};

export const LOCALES: Record<LocaleKey, LocaleDict> = { zh, en };

export type Translator = (
  key: keyof LocaleDict,
  vars?: Record<string, string | number>,
) => string;

export function makeTranslator(locale: LocaleKey): Translator {
  const dict = LOCALES[locale];
  return (key, vars) => {
    let value = dict[key] ?? key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        value = value.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
      }
    }
    return value;
  };
}

export function detectInitialLocale(): LocaleKey {
  try {
    const saved = localStorage.getItem('dabench.web.lang');
    if (saved === 'zh' || saved === 'en') return saved;
  } catch {
    // ignore
  }
  if (typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('zh')) {
    return 'zh';
  }
  return 'en';
}
