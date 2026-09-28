# Skills for Models Port

用于模型移植与优化实验的可复用 skills。每个 skill 目录可单独安装，包含说明、真实补丁、源码基线和应用／恢复脚本。

| Skill | 方案 |
|---|---|
| [ascend-vit-fia-bsnd](skills/ascend-vit-fia-bsnd/SKILL.md) | 单序列 ViT eager FIA：TND → BSND |
| [ascend-vit-fia-bnsd](skills/ascend-vit-fia-bnsd/SKILL.md) | 单序列 ViT eager FIA：TND → BNSD |
| [ascend-vit-fia-bnsd-bsnd](skills/ascend-vit-fia-bnsd-bsnd/SKILL.md) | 单序列 ViT eager FIA：BNSD 输入、BSND 输出 |

基于 `quay.io/ascend/vllm-ascend:v0.23.0` 原始容器源码制作。三个方案互斥，切换前恢复原版；这三个 eager 方案不修改 encoder ACL Graph。

已验证补丁管理工具的文件操作和完整性保护；未在 NPU 上验证功能、性能或精度。不预置应用后的模型测试，用户可手动测试，或提供自己的方法后自动执行。

## Encoder ACL Graph 方案

实际命中 encoder ACL Graph 时使用以下三个新增 skill。原有 eager skills 保留不变，二者互斥；切换前先恢复。

| Skill | 捕获与 replay 布局 |
|---|---|
| [ascend-vit-fia-aclgraph-bsnd](skills/ascend-vit-fia-aclgraph-bsnd/SKILL.md) | BSND |
| [ascend-vit-fia-aclgraph-bnsd](skills/ascend-vit-fia-aclgraph-bnsd/SKILL.md) | BNSD |
| [ascend-vit-fia-aclgraph-bnsd-bsnd](skills/ascend-vit-fia-aclgraph-bnsd-bsnd/SKILL.md) | BNSD 输入、BSND 输出 |

新方案以同一原始 v0.23.0 镜像的两个 vllm-ascend 文件为基线，不负责启用模型侧 Graph 协议。支持单序列实际长度小于捕获容量；不兼容输入在 replay 前改走非捕获的 encoder forward。应用和恢复后都需重启服务、重新捕获 Graph。

仅完成离线补丁工具及控制流检查，未在 NPU 上验证功能、性能、精度或 Graph 命中。测试仍由用户手动完成，或按用户随后提供的方法执行。
