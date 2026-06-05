# Training Conventions (loaded on demand)

Loaded when the agent reviews `src/training/` or anything touching DDP, AMP, gradient accumulation, or distributed.

## AMP (mixed precision)

Modern (PyTorch ≥ 2.0):
```python
from torch.amp import autocast, GradScaler

scaler = GradScaler('cuda')  # only needed for fp16, not bf16

with autocast(device_type='cuda', dtype=torch.bfloat16):  # bf16 on A100/H100
    logits = model(inputs)
    loss = criterion(logits, targets)

# fp16 path (only on V100/T4):
# with autocast(device_type='cuda', dtype=torch.float16):
#     ...
# scaler.scale(loss).backward()
# scaler.step(optimizer)
# scaler.update()
```

**The agent verifies the current API via context7 before recommending — `torch.cuda.amp.autocast` is the deprecated form.**

## DDP

```python
# Required idioms:
sampler = DistributedSampler(dataset, shuffle=True, seed=42)
for epoch in range(epochs):
    sampler.set_epoch(epoch)  # else shuffle is the same every epoch
    for batch in loader:
        ...

# Save on rank 0 only:
if dist.get_rank() == 0:
    torch.save(model.module.state_dict(), 'ckpt.pt')
dist.barrier()  # everyone waits

# DDP wrapping:
model = DDP(model, device_ids=[local_rank], find_unused_parameters=False)
# find_unused_parameters=True is a perf trap; only enable if you actually have unused params.
```

## Gradient accumulation

```python
ACCUM = 4
for i, batch in enumerate(loader):
    with autocast(device_type='cuda', dtype=torch.bfloat16):
        loss = model(batch) / ACCUM  # scale BEFORE backward

    # Under DDP: no_sync() on intermediate microbatches
    if (i + 1) % ACCUM != 0 and isinstance(model, DDP):
        with model.no_sync():
            loss.backward()
    else:
        loss.backward()

    if (i + 1) % ACCUM == 0:
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)  # set_to_none is faster than =0
```

## Determinism (only if claimed)

```python
import os, random, numpy as np, torch
SEED = 42
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED)
torch.use_deterministic_algorithms(True)
os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False  # benchmark=True is faster but non-deterministic
```

## Checkpointing — atomic writes only

```python
tmp = path.with_suffix('.tmp')
torch.save({'model': m.state_dict(), 'opt': o.state_dict(),
            'scheduler': s.state_dict(), 'epoch': epoch,
            'rng': torch.get_rng_state()}, tmp)
tmp.replace(path)  # atomic on POSIX
```

A checkpoint without optimizer state cannot resume; a checkpoint without RNG state cannot reproduce.

## OOM playbook (tier list, cheapest first)

1. Reduce batch size + gradient accumulation to compensate
2. `gradient_checkpointing_enable()` on transformers
3. Mixed precision (bf16 on A100+, fp16 elsewhere)
4. CPU offload optimizer states (DeepSpeed Zero-2)
5. FSDP / DeepSpeed Zero-3 (parameter sharding)
6. Tensor parallelism (Megatron / DeepSpeed)

Above tier 3 → you're in distributed-systems territory; consider whether the experiment justifies the ops cost.
