---
name: ascend-vit-fia-bsnd
description: 为 quay.io/ascend/vllm-ascend:v0.23.0 容器的 ViT eager FIA 应用、查看或恢复 BSND 布局实验补丁。适用于 DotsOCR 视觉 attention 布局对比，不修改语言模型 attention 或 encoder ACL Graph。
---

# ViT FIA BSND 布局实验

使用本 skill 自带的补丁和管理脚本；用户要求应用、恢复时执行相应操作，仅咨询时只解释。
未验证此方案能加速，不将补丁应用成功表述为功能、精度或性能验证成功。

## 适用范围

- 基于原始 `quay.io/ascend/vllm-ascend:v0.23.0` 容器内源码；镜像 digest、架构和文件哈希见 [baseline.json](assets/baseline.json)。不能以最新分支或同名版本标签代替源码匹配。
- 仅修改 `vllm_ascend/ops/mm_encoder_attention.py` 的 `_forward_eager_fia`。这是共享视觉 attention 实现，其他模型满足条件时也会使用该布局；不声称仅影响 DotsOCR。
- 单个完整有效、长度大于 1 的 MHA self-attention 序列走 `BSND`；检查 Q/K/V shape、head 数及实际序列边界。多序列、空序列、单 token、GQA 或不完整有效序列回退原 TND，不硬编码 19276。
- 输入 `[T,N,D]` 转为 `[1,T,N,D]`，算子输出 `[1,T,N,D]` 恢复为 `[T,N,D]`。连续的 TND 输入增加 batch 维即可；若输入不连续，显式连续化会产生拷贝。
- 保留 dtype、scale、mask、head 数等原有语义；encoder ACL Graph 的捕获、workspace 和 replay 路径保持 TND。
- 三种布局方案互斥，先用当前方案的 skill 恢复，再应用另一种。不混用既有 RoPE、cu_seqlens 或 encoder ACL Graph 实验镜像。脚本只校验目标文件，不能证明整个容器都未修改；用户环境不明确时先确认使用原始镜像。

## 操作步骤

1. 确定目标容器及源码根目录，操作前停止使用该源码的服务进程。容器需保持可进入状态；没有指定容器且存在多个候选时询问用户，不猜测生产服务。
2. 将本 skill **整个目录**挂载或复制到容器。以下命令在容器内执行，`SKILL_DIR` 替换成该 skill 的绝对路径；需要 Python 3.10+ 标准库以及源码目录写权限，不需要安装 torch、git 或 patch 工具。

```bash
SKILL_DIR=/opt/skills/ascend-vit-fia-bsnd
python3 "$SKILL_DIR/scripts/patch_manager.py" status
python3 "$SKILL_DIR/scripts/patch_manager.py" apply
```

恢复时执行：

```bash
python3 "$SKILL_DIR/scripts/patch_manager.py" restore
```

源码不在默认 `/vllm-workspace/vllm-ascend` 时，给每个命令追加 `--source-root /实际/vllm-ascend`。其他架构环境仅在目标源码哈希一致时允许应用；这不代表已验证该架构上的算子支持情况。

3. `status` 返回 `original`、`applied`、`other-variant` 或 `unknown-modification`，并显示实际 SHA-256。应用前检查 [layout.patch](assets/layout.patch)；脚本进行无 fuzz、无偏移的补丁检查、语法检查和前后哈希验证。
4. 原文件保存到源码根目录下 `.fia-layout-patches/<原文件SHA-256>.original`；同目录的锁防止多个 skill 同时写入。保留该目录，恢复需要原文件备份。
5. 重复应用或恢复是无操作成功。遇到其他方案、未知修改、损坏补丁或备份时停止，报告状态及哈希。不得强制覆盖、删除备份绕过检查或执行整仓库 reset。恢复只覆盖匹配当前补丁结果的目标文件，保留其他文件。
6. 应用或恢复后，按用户已有服务管理方式重新启动相关进程以加载源码；不自行构造启动参数，也不自动触发推理。服务信息缺失时说明需要重启并询问启动方式。

补丁管理脚本使用 [baseline.json](assets/baseline.json) 和 [layout.patch](assets/layout.patch)，不依赖另外两个 skill。只修改容器可写层时，重建容器会丢失变更和备份，应明确告知用户当前挂载／持久化情况。

## 完成报告与用户提供的测试

报告操作、目标容器／文件、layout、源码哈希、是否已恢复或已应用，以及是否已重启。应用后明确写“尚未验证性能及精度”。

不预置或主动执行应用后的性能、精度、OCR、推理或服务测试。用户默认手动测试；若用户提供测试命令、数据和判定方法，则严格按该方法自动执行并报告原始结果。缺少必要测试信息时询问，不自行补充另一套测试，不将文件完整性检查当作模型验证。
