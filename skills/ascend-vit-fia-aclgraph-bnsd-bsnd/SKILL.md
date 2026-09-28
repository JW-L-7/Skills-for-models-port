---
name: ascend-vit-fia-aclgraph-bnsd-bsnd
description: 为 quay.io/ascend/vllm-ascend:v0.23.0 的 ViT encoder ACL Graph 应用、查看或恢复 BNSD_BSND 布局实验补丁，覆盖捕获与 replay 参数更新。用户实际走 encoder Graph 时使用；eager 分支仍为 TND，不替代已有 eager layout skills。
---

# Encoder ACL Graph FIA BNSD_BSND

用户要求应用、恢复时执行对应操作，仅咨询时只解释。本目录独立可用。
这是未经 NPU 性能与精度验证的布局实验，不能承诺提速。

## 基线与范围

- 补丁取自原始 `quay.io/ascend/vllm-ascend:v0.23.0` 容器源码。镜像 digest、ARM64 架构、两个目标文件的前后 SHA-256 见 [baseline.json](assets/baseline.json)。其他环境仅在两个文件都匹配基线时允许应用，不能据此声称已验证其他架构或 CANN 版本。
- [attention.patch](assets/attention.patch) 修改 `vllm_ascend/ops/mm_encoder_attention.py` 的捕获路径与 FIA 布局参数；[graph.patch](assets/graph.patch) 修改 `vllm_ascend/worker/encoder_acl_graph.py` 的 replay、workspace 和长度处理。
- 本 skill **不负责启用模型的 encoder ACL Graph 协议或修改 vLLM 模型代码**。用户已有可用 Graph 配置时在其基础上应用；若模型实际不走 Graph，报告本方案不会命中。允许保留模型侧已经启用 Graph 的改动，只要这两个 vllm-ascend 文件仍匹配原始基线。哈希检查不是整个容器的纯净性证明。
- 保留原有三个 eager skills。新方案与全部旧 eager layout 补丁、另两个 Graph layout 补丁互斥，先用已应用方案的 skill 恢复再切换，不叠加布局补丁。保留其他不涉及目标文件的用户配置与修改。
- 修改共享视觉 attention 后，满足条件的其他视觉模型也会受到影响；语言模型 attention 不在修改范围。

## Graph 行为

- `C` 是捕获时的 token 容量，`L` 是 replay 时的真实序列长度。单序列 MHA、相同 Q/K/V shape 且容量大于 1 时，捕获输入 `[1,N,C,D]`、输出 `[1,C,N,D]`，再恢复上层需要的 TND。BNSD 输入显式转置并连续化；相应转换作为图的一部分被捕获。
- 捕获参数记录真实 layout、Q/KV 容量和 workspace 引用。输出 buffer、workspace 查询、捕获 `.out` 及 replay 更新使用同一布局。workspace 以预算、布局、shape、dtype、head 数及 scale 分开缓存，捕获后按原有方式管理弱引用。
- replay 使用有效长度 `[L]`，支持 `1 < L <= C`；不将容量 `C` 追加成第二个序列，不让 padding 参与有效 token 的 attention。允许 `[0,L]` 后重复终点或尾部零填充，不将多图累计终点当作长度数组直接传给固定布局。
- 固定布局图遇到多序列、单 token、缺失或不兼容的边界时，在提交 graph replay **之前**转为非捕获的 encoder forward，使用真实、未 padding 的 replay 输入，返回调用方需要的输出 Tensor。原始上层调用断言输出非空，因此不能简单返回 `None`。该回退内部走原有 eager TND；不会修复本来就无效的模型输入。
- 捕获本身不满足条件的任务保留 TND；现有 eager 方法保持不变。不硬编码 19276，不更改 dtype、scale 或注意力 mask 语义。

## 应用、状态与恢复

1. 确定目标容器、源码根目录及服务管理方式；停止使用相关源码的进程，但保持容器可进入。存在多个候选容器时询问用户，不猜测目标服务。
2. 将整个 skill 目录复制或挂载到容器。下面命令在容器内执行；替换 `SKILL_DIR` 为实际绝对路径。需要 Python 3.10+ 标准库及源码根目录写权限，不安装额外依赖。

```bash
SKILL_DIR=/opt/skills/ascend-vit-fia-aclgraph-bnsd-bsnd
python3 "$SKILL_DIR/scripts/patch_manager.py" status
python3 "$SKILL_DIR/scripts/patch_manager.py" apply
```

恢复时执行：

```bash
python3 "$SKILL_DIR/scripts/patch_manager.py" restore
```

源码默认根目录为 `/vllm-workspace/vllm-ascend`。需要指定其他目录时，为每个命令追加 `--source-root /实际/vllm-ascend`。

3. `status` 输出整体及每个文件状态与哈希。`original` 为原版，`applied` 为本方案，`other-variant` 为其他已知方案，`unknown-modification` 为未知修改。`mixed` 表示文件状态不一致；`partial-current-variant` 表示仅部分文件已应用本方案。
4. 应用前同时校验两个源码文件、两个真实 unified diff、修改后哈希及 Python 语法；原文件保存到源码根目录 `.fia-layout-patches/<原文件SHA-256>.original`。保留备份目录，其锁与旧 eager skills 共用。重复应用／恢复是无操作成功。
5. 两文件写入不具备跨文件系统原子性：普通失败尽力回滚，进程被强制终止后可能留下部分应用状态。此时仅在每个文件都匹配原版或本方案时允许 `restore`，完整恢复后才能重新应用。发现任何未知修改或其他方案时停止并报告，不强制覆盖或整仓库 reset。
6. 恢复前核验备份及当前源码，任一文件有应用后的用户修改则停止，不覆盖后续工作。旧 eager skill 不认识新方案，可能报未知修改；应始终用当前 Graph skill 恢复。
7. 应用或恢复完成后，按用户已有启动方式**重启相关服务，让 encoder Graph 重新捕获**。不能继续使用旧进程中已经捕获的图。不自行构造服务启动参数；重启不自动触发推理或测试。仅修改容器可写层时，重建容器会丢失补丁和备份，告知用户实际持久化方式。

## 完成报告与用户测试

报告当前方案、目标容器／两个源码文件、前后哈希、应用或恢复结果、备份位置，以及是否重启并重新捕获。应用后明确写“尚未验证性能及精度”；单纯修改文件不代表已确认 Graph 命中。

不预置或主动执行应用后的性能、精度、OCR、推理或服务测试。默认用户手动测试。只有用户提供测试命令、数据及判定方法后，才按用户的方法自动执行和报告；必要信息缺失时询问，不自行换成另一套测试。文件完整性和补丁工具检查不属于模型验证。
