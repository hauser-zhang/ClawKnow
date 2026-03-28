# LLM 学习笔记示例

> 这是一份演示文档，供 ClawKnow 检索层测试使用。
> 运行 `python tools/seed_demo.py` 后可通过 `search_kb.py --kb demo` 搜索本文内容。

---

## Transformer 架构基础

Transformer 是当前主流大语言模型的基础架构，由 Vaswani 等人在 2017 年论文
"Attention Is All You Need" 中提出，完全依赖注意力机制（Attention Mechanism），
摒弃了 RNN 和 CNN。

核心组件：
- **多头自注意力（Multi-Head Self-Attention）**：允许模型在不同的表示子空间同时关注序列的不同位置
- **前馈网络（FFN）**：每个位置独立的两层线性变换，中间有 ReLU/GELU 激活
- **残差连接（Residual Connection）**：缓解梯度消失，加速训练
- **层归一化（Layer Norm）**：稳定训练过程

---

## 注意力机制（Attention Mechanism）

### Scaled Dot-Product Attention

$$\text{Attention}(Q, K, V) = \text{softmax}\!\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$

其中 $d_k$ 是 Key 向量的维度，除以 $\sqrt{d_k}$ 是为了防止点积值过大导致 softmax 梯度消失。

### Multi-Head Attention

将 $Q$、$K$、$V$ 分别投影到 $h$ 个不同的子空间，分别计算注意力后拼接：

$$\text{MultiHead}(Q,K,V) = \text{Concat}(\text{head}_1, \ldots, \text{head}_h)W^O$$

好处：不同的 head 可以捕获不同类型的依赖关系（语法、语义、共指等）。

### KV Cache

推理时，Decoder 的 Key 和 Value 矩阵可以被缓存（KV Cache），避免重复计算已生成 token 的 KV。
内存占用估算：$2 \times L \times d_{model} \times \text{seq\_len} \times \text{precision}$，
其中 $L$ 为层数。

---

## 混合专家模型（Mixture of Experts, MoE）

### 基本原理

MoE 将 Transformer FFN 层替换为多个"专家"子网络，每个 token 只路由给其中 Top-K 个专家。

路由机制：
1. Gate 网络对每个 token 计算所有专家的 logit：$g(x) = \text{softmax}(xW_g)$
2. 取 Top-K 个专家，仅激活它们进行前向计算
3. 输出为 K 个专家输出的加权和：$y = \sum_{i \in \text{TopK}} g_i(x) \cdot E_i(x)$

### 稀疏激活

关键优势：参数量大但每次前向计算的 FLOPs 不变（只激活 K/N 比例的专家）。
代表模型：Mixtral 8×7B（每个 token 激活 2/8 个专家）、DeepSeek-MoE。

### 负载均衡损失

训练时需要辅助 Load Balancing Loss 防止所有 token 都路由给同一个专家：

$$\mathcal{L}_{aux} = \alpha \cdot N \cdot \sum_{i=1}^{N} f_i \cdot P_i$$

其中 $f_i$ 是专家 $i$ 的实际处理比例，$P_i$ 是路由概率，$\alpha$ 是超参数权重。

---

## 后训练对齐（Post-Training Alignment）

### 监督微调（SFT）

在标注的指令-回复对上进行标准监督训练，使模型学会遵循指令格式。
数据质量远比数量重要：少量高质量对话数据（数千条）效果优于大量低质量数据。

### RLHF（基于人类反馈的强化学习）

三阶段流程：
1. **SFT**：基础对齐
2. **奖励模型训练（RM）**：用人类偏好标注数据（chosen/rejected 对）训练奖励模型
3. **PPO 强化学习**：以奖励模型为环境，用 PPO 算法优化策略模型

PPO 目标函数（带 KL 惩罚防止偏离参考策略）：
$$J(\theta) = \mathbb{E}\left[r_\phi(x,y) - \beta \cdot \text{KL}(\pi_\theta \| \pi_{ref})\right]$$

### GRPO（Group Relative Policy Optimization）

DeepSeek-R1 使用的轻量化 RLHF 变体，无需训练单独的奖励模型。

核心思路：对同一问题采样 G 个回复，以组内相对奖励替代绝对奖励：
$$A_i = \frac{r_i - \text{mean}(r_{1..G})}{\text{std}(r_{1..G})}$$

优点：消除奖励模型偏差，计算更稳定，适合数学/代码等有明确答案的任务。

---

## Flash Attention

传统注意力计算需要将 $N \times N$ 的注意力矩阵写入 HBM（显存），复杂度为 $O(N^2)$。

Flash Attention（Dao et al., 2022）通过**分块计算（Tiling）**和**重计算（Recomputation）**：
- 不显式实例化完整注意力矩阵
- 将 Q、K、V 分块加载到 SRAM（片上内存），分块计算并累积结果
- 显存复杂度降至 $O(N)$，速度提升 2-4x

Flash Attention 2 进一步优化了线程块并行度和工作分配，是目前主流 LLM 推理框架的标配。
