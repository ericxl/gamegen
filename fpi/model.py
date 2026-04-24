"""Gemma 4 vision-language backbone + flow-matching action expert.

Same architectural recipe as NitroGen (DiT-style action expert, action chunks,
behavior cloning) but with a Gemma 4 VL backbone in place of NitroGen's
SigLip-only encoder. The Gemma backbone provides language conditioning that
NitroGen lacks; the action expert provides the smooth, multi-modal continuous
output that LM heads cannot.

Forward in training: flow_matching_loss(target_actions, backbone_inputs) -> scalar.
Forward at inference: sample_actions(backbone_inputs) -> (B, T, ACTION_DIM).

Caller is responsible for preprocessing images + text via the Gemma 4 processor
and passing the resulting kwargs as `backbone_inputs`. Two Gemma 4 quirks that
matter at preprocessing time:
- Image height/width must be divisible by 48 (patch 16 x pool 3).
- The processor normalizes pixels to [-1, 1] internally; do not pre-normalize.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModelForImageTextToText

from fpi.action_space import ACTION_DIM


@dataclass
class Gemma4VLAConfig:
    # Default: Gemma 4 E4B-it (4.5B effective / 8B total, 128K ctx, vision+audio+text).
    # Swap to "google/gemma-4-E2B-it" (kv_dim=1536) for a smaller/faster backbone.
    backbone_model_id: str = "google/gemma-4-E4B-it"
    backbone_dtype: str = "bfloat16"

    chunk_len: int = 16
    expert_d_model: int = 1024
    expert_n_layers: int = 6
    expert_n_heads: int = 16
    expert_ffn_mult: int = 4
    n_inference_steps: int = 10

    # Text-decoder hidden_size (last_hidden_state width). E4B=2560, E2B=1536.
    kv_dim: int = 2560


def sinusoidal_time_emb(t: torch.Tensor, d: int) -> torch.Tensor:
    half = d // 2
    freqs = torch.exp(-math.log(10000.0) * torch.arange(half, device=t.device) / half)
    args = t[:, None] * freqs[None]
    return torch.cat([torch.sin(args), torch.cos(args)], dim=-1)


class ExpertBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, ffn_mult: int, kv_dim: int):
        super().__init__()
        self.ln_self = nn.LayerNorm(d_model)
        self.self_attn = nn.MultiheadAttention(d_model, n_heads, batch_first=True)
        self.ln_cross = nn.LayerNorm(d_model)
        self.cross_attn = nn.MultiheadAttention(
            d_model, n_heads, kdim=kv_dim, vdim=kv_dim, batch_first=True
        )
        self.ln_ffn = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_model * ffn_mult),
            nn.GELU(),
            nn.Linear(d_model * ffn_mult, d_model),
        )

    def forward(
        self,
        x: torch.Tensor,
        kv: torch.Tensor,
        kp_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        h = self.ln_self(x)
        x = x + self.self_attn(h, h, h, need_weights=False)[0]
        h = self.ln_cross(x)
        x = x + self.cross_attn(h, kv, kv, key_padding_mask=kp_mask, need_weights=False)[0]
        x = x + self.ffn(self.ln_ffn(x))
        return x


class FlowMatchingActionExpert(nn.Module):
    def __init__(self, cfg: Gemma4VLAConfig):
        super().__init__()
        self.cfg = cfg
        self.action_in = nn.Linear(ACTION_DIM, cfg.expert_d_model)
        self.t_proj = nn.Linear(cfg.expert_d_model, cfg.expert_d_model)
        self.pos_emb = nn.Parameter(torch.zeros(1, cfg.chunk_len, cfg.expert_d_model))
        nn.init.normal_(self.pos_emb, std=0.02)
        self.blocks = nn.ModuleList([
            ExpertBlock(cfg.expert_d_model, cfg.expert_n_heads, cfg.expert_ffn_mult, cfg.kv_dim)
            for _ in range(cfg.expert_n_layers)
        ])
        self.ln_out = nn.LayerNorm(cfg.expert_d_model)
        self.action_out = nn.Linear(cfg.expert_d_model, ACTION_DIM)

    def forward(
        self,
        noisy_actions: torch.Tensor,
        t: torch.Tensor,
        kv: torch.Tensor,
        kp_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        assert noisy_actions.shape[1] == self.cfg.chunk_len, "action chunk len mismatch"
        x = self.action_in(noisy_actions) + self.pos_emb
        t_emb = self.t_proj(sinusoidal_time_emb(t, self.cfg.expert_d_model))
        x = x + t_emb[:, None, :]
        for block in self.blocks:
            x = block(x, kv, kp_mask)
        return self.action_out(self.ln_out(x))


class GemmaVLBackbone(nn.Module):
    def __init__(self, model_id: str, dtype: torch.dtype):
        super().__init__()
        self.model = AutoModelForImageTextToText.from_pretrained(model_id, torch_dtype=dtype)

    def forward(self, **inputs) -> torch.Tensor:
        outputs = self.model(**inputs, output_hidden_states=True)
        return outputs.hidden_states[-1]


def _kp_mask_from_attention(attention_mask: torch.Tensor | None) -> torch.Tensor | None:
    """HF attention_mask uses 1=keep; nn.MultiheadAttention key_padding_mask uses True=mask out."""
    if attention_mask is None:
        return None
    return attention_mask == 0


class Gemma4VLA(nn.Module):
    def __init__(self, cfg: Gemma4VLAConfig):
        super().__init__()
        self.cfg = cfg
        dtype = getattr(torch, cfg.backbone_dtype)
        self.backbone = GemmaVLBackbone(cfg.backbone_model_id, dtype=dtype)
        self.expert = FlowMatchingActionExpert(cfg)

    def flow_matching_loss(
        self,
        target_actions: torch.Tensor,
        backbone_inputs: dict,
    ) -> torch.Tensor:
        kv = self.backbone(**backbone_inputs).float()
        kp_mask = _kp_mask_from_attention(backbone_inputs.get("attention_mask"))
        B = target_actions.shape[0]
        x0 = torch.randn_like(target_actions)
        t = torch.rand(B, device=target_actions.device)
        xt = (1.0 - t)[:, None, None] * x0 + t[:, None, None] * target_actions
        v_target = target_actions - x0
        v_pred = self.expert(xt, t, kv, kp_mask)
        return F.mse_loss(v_pred, v_target)

    @torch.no_grad()
    def sample_actions(self, backbone_inputs: dict) -> torch.Tensor:
        kv = self.backbone(**backbone_inputs).float()
        kp_mask = _kp_mask_from_attention(backbone_inputs.get("attention_mask"))
        B = kv.shape[0]
        x = torch.randn(B, self.cfg.chunk_len, ACTION_DIM, device=kv.device)
        dt = 1.0 / self.cfg.n_inference_steps
        for i in range(self.cfg.n_inference_steps):
            t = torch.full((B,), i * dt, device=kv.device)
            v = self.expert(x, t, kv, kp_mask)
            x = x + v * dt
        return x.clamp(-1.0, 1.0)
