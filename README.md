# Skills for Models Port

用于模型移植与优化实验的可复用 skills。每个 skill 目录可单独安装，包含说明、真实补丁、源码基线和应用／恢复脚本。

| Skill | 方案 |
|---|---|
| [ascend-vit-fia-bsnd](skills/ascend-vit-fia-bsnd/SKILL.md) | 单序列 ViT eager FIA：TND → BSND |
| [ascend-vit-fia-bnsd](skills/ascend-vit-fia-bnsd/SKILL.md) | 单序列 ViT eager FIA：TND → BNSD |
| [ascend-vit-fia-bnsd-bsnd](skills/ascend-vit-fia-bnsd-bsnd/SKILL.md) | 单序列 ViT eager FIA：BNSD 输入、BSND 输出 |

基于 `quay.io/ascend/vllm-ascend:v0.23.0` 原始容器源码制作。三个方案互斥，切换前恢复原版；本轮不修改 encoder ACL Graph。

已验证补丁管理工具的文件操作和完整性保护；未在 NPU 上验证功能、性能或精度。不预置应用后的模型测试，用户可手动测试，或提供自己的方法后自动执行。
