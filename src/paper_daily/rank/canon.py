"""Papers that get read regardless of what the scoring says.

Ranking optimises for signal strength, which quietly punishes two kinds of paper:
the one so absorbed into the field that nobody cites it explicitly any more, and the
one whose importance is structural rather than numerical. This list overrides that.

Entries are matched by normalised title, so the venue/year are hints for the reader
rather than match keys. A title that never appears in the corpus is skipped silently.
"""

from __future__ import annotations

from paper_daily.store import title_key

# (title, venue, year, why it is on the list)
CANON: list[tuple[str, str, int, str]] = [
    (
        "Adam: A Method for Stochastic Optimization",
        "ICLR",
        2015,
        "The optimiser almost every later paper silently assumes.",
    ),
    (
        "Batch Normalization: Accelerating Deep Network Training by Reducing Internal "
        "Covariate Shift",
        "ICML",
        2015,
        "Made deep nets trainable; its stated explanation was later shown to be wrong.",
    ),
    (
        "Neural Machine Translation by Jointly Learning to Align and Translate",
        "ICLR",
        2015,
        "Attention's first appearance, two years before Transformers.",
    ),
    (
        "Auto-Encoding Variational Bayes",
        "ICLR",
        2014,
        "The reparameterisation trick, ancestor of most modern generative modelling.",
    ),
    (
        "Generative Adversarial Nets",
        "NeurIPS",
        2014,
        "Adversarial training as a learning principle.",
    ),
    (
        "Understanding deep learning requires rethinking generalization",
        "ICLR",
        2017,
        "Broke the classical generalisation story and started a decade of theory work.",
    ),
    (
        "Semi-Supervised Classification with Graph Convolutional Networks",
        "ICLR",
        2017,
        "The reference point for graph neural networks.",
    ),
    (
        "Categorical Reparameterization with Gumbel-Softmax",
        "ICLR",
        2017,
        "How to backpropagate through discrete choices.",
    ),
    (
        "Neural Architecture Search with Reinforcement Learning",
        "ICLR",
        2017,
        "Opened architecture search as a research programme.",
    ),
    (
        "Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks",
        "ICML",
        2017,
        "Meta-learning reduced to a clean gradient formulation.",
    ),
    (
        "Wasserstein Generative Adversarial Networks",
        "ICML",
        2017,
        "Diagnosed GAN instability as a divergence choice.",
    ),
    ("Attention Is All You Need", "NeurIPS", 2017, "The architecture the field still runs on."),
    (
        "Neural Discrete Representation Learning",
        "NeurIPS",
        2017,
        "VQ-VAE: discrete latents, ancestor of modern tokenised generation.",
    ),
    (
        "Deep Sets",
        "NeurIPS",
        2017,
        "Characterises what permutation-invariant functions must look like.",
    ),
    (
        "Graph Attention Networks",
        "ICLR",
        2018,
        "Attention on graphs; the other GNN reference point.",
    ),
    (
        "Mixed Precision Training",
        "ICLR",
        2018,
        "Why modern training is numerically possible at scale.",
    ),
    (
        "Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a "
        "Stochastic Actor",
        "ICML",
        2018,
        "Maximum-entropy RL that actually worked.",
    ),
    (
        "Neural Ordinary Differential Equations",
        "NeurIPS",
        2018,
        "Reframed depth as continuous time.",
    ),
    (
        "Neural Tangent Kernel: Convergence and Generalization in Neural Networks",
        "NeurIPS",
        2018,
        "The infinite-width limit that made theory tractable.",
    ),
    (
        "The Lottery Ticket Hypothesis: Finding Sparse, Trainable Neural Networks",
        "ICLR",
        2019,
        "Trainability as a property of initialisation, not just architecture.",
    ),
    (
        "Decoupled Weight Decay Regularization",
        "ICLR",
        2019,
        "AdamW: a one-line fix that changed every training recipe.",
    ),
    (
        "Generative Modeling by Estimating Gradients of the Data Distribution",
        "NeurIPS",
        2019,
        "Score matching -- the idea diffusion models are built on.",
    ),
    (
        "XLNet: Generalized Autoregressive Pretraining for Language Understanding",
        "NeurIPS",
        2019,
        "The autoregressive-vs-masked pretraining argument in one place.",
    ),
    (
        "Deep Double Descent: Where Bigger Models and More Data Hurt",
        "ICLR",
        2020,
        "Overparameterisation stops being a paradox.",
    ),
    (
        "A Simple Framework for Contrastive Learning of Visual Representations",
        "ICML",
        2020,
        "SimCLR: what self-supervised learning actually needs.",
    ),
    (
        "Denoising Diffusion Probabilistic Models",
        "NeurIPS",
        2020,
        "The paper that made diffusion practical.",
    ),
    (
        "Language Models are Few-Shot Learners",
        "NeurIPS",
        2020,
        "In-context learning as an emergent capability.",
    ),
    (
        "Bootstrap Your Own Latent - A New Approach to Self-Supervised Learning",
        "NeurIPS",
        2020,
        "Self-supervision without negative pairs, which theory said should collapse.",
    ),
    (
        "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
        "ICLR",
        2021,
        "Vision without convolutions.",
    ),
    (
        "Denoising Diffusion Implicit Models",
        "ICLR",
        2021,
        "Made diffusion sampling fast enough to use.",
    ),
    (
        "Score-Based Generative Modeling through Stochastic Differential Equations",
        "ICLR",
        2021,
        "Unified score matching and diffusion under one SDE.",
    ),
    (
        "Sharpness-Aware Minimization for Efficiently Improving Generalization",
        "ICLR",
        2021,
        "Optimising for flat minima, explicitly.",
    ),
    (
        "Learning Transferable Visual Models From Natural Language Supervision",
        "ICML",
        2021,
        "CLIP: supervision from captions instead of labels.",
    ),
    (
        "LoRA: Low-Rank Adaptation of Large Language Models",
        "ICLR",
        2022,
        "Why fine-tuning stopped needing full model copies.",
    ),
    (
        "Training Compute-Optimal Large Language Models",
        "NeurIPS",
        2022,
        "Chinchilla: the compute/data trade-off that redirected the field.",
    ),
    (
        "Training language models to follow instructions with human feedback",
        "NeurIPS",
        2022,
        "InstructGPT: RLHF, and the root of the alignment literature. On this list "
        "because the corpus said so -- 44 queued papers build on it, behind only "
        "Attention, AdamW, DDPM and GPT-3 in the whole reference graph.",
    ),
    (
        "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        "NeurIPS",
        2022,
        "Reasoning as a decoding-time phenomenon.",
    ),
    (
        "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
        "NeurIPS",
        2022,
        "Attention rewritten around memory hierarchy, not FLOPs.",
    ),
    (
        "Direct Preference Optimization: Your Language Model is Secretly a Reward Model",
        "NeurIPS",
        2023,
        "Collapsed RLHF into a single supervised objective.",
    ),
    (
        "QLoRA: Efficient Finetuning of Quantized LLMs",
        "NeurIPS",
        2023,
        "Quantisation and adaptation shown to compose.",
    ),
    (
        "Tree of Thoughts: Deliberate Problem Solving with Large Language Models",
        "NeurIPS",
        2023,
        "Search put back on top of a language model.",
    ),
    ("Consistency Models", "ICML", 2023, "One-step generation from a diffusion-trained model."),
    (
        "Toolformer: Language Models Can Teach Themselves to Use Tools",
        "NeurIPS",
        2023,
        "Self-supervised tool use, the root of the agent literature.",
    ),
]


def canon_index() -> dict[str, tuple[str, str, int, str]]:
    """Normalised title -> canon entry."""
    return {title_key(t): (t, v, y, why) for t, v, y, why in CANON}
