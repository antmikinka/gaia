# GGUF Per-Layer Splitting & Sequential Inference: Schema & Implementation Plan

## Goal
1. Create `gguf_split_layers.py` (Completed) — a script that takes any GGUF model file and splits it into **per-layer GGUF files**.
2. **[NEW]** Modify and compile a custom `llama-server.exe` to natively drop mapped pages from Physical RAM after computing them layer-by-layer, maintaining ~1-2GB peak RAM.

## Background & Rationale
The user wants to plug a custom `llama-server` binary into **Lemonade Server** that sequentially executes the 19.8GB Qwen3.5-35B model layers natively in C++ without loading all 20GB into RAM at once ("No-Merge").

Writing a full inference server from scratch using purely `ggml.h` (to handle tokenization, sampling, KV caching, HTTP routing) is too complex for an MVP.

Instead, we will exploit how Windows memory mapping (`mmap`) works. When `llama.cpp` maps a 20GB file, it consumes 0GB of RAM initially. As the inference loop executes Layer 0, Windows pages it into RAM. Then Layer 1, 2, 3... until all 20GB is in RAM. 

To achieve our "Transient Layer / No-Merge" architecture, we will simply inject a tiny patch into the core `ggml` computation loop. Immediately after a graph node (tensor) is computed, we will call `VirtualUnlock` (on Windows) or `posix_madvise(MADV_DONTNEED)` (on Linux) on the tensor's memory address. This forcibly removes the tensor from the Physical RAM Working Set, returning it to disk instantly. 

Thus, Peak RAM will mathematically equal the KV Cache Size + the size of a single layer being computed!

---

## Proposed Changes

### 1. Phase 1: CPU Memory Eviction (`ggml-backend.cpp`) **[COMPLETED]**
- Modified `ggml_backend_sched_graph_compute` stringing a post-evaluation hook.
- Added `VirtualUnlock` (Windows) and `madvise` (Linux) hooks to immediately evict `mmap` pages from Physical RAM after a compute split finishes.
- Ensured Peak RAM equals KV Cache Size + current layer size.

### 2. Phase 2b: Vulkan True VRAM Streaming (`ggml-vulkan.cpp`) **[PLANNED]**
To achieve "infinite model size" on limited VRAM by streaming weights over PCIe on-demand, we must bypass the default `ggml_gallocr` which normally allocates all 20GB of weights in `VkDeviceMemory` at startup.

**Component A: The Streaming Buffer Type**
- Create `ggml_backend_vk_streaming_buffer_type` (a wrapper implementing `ggml_backend_buffer_type_i`).
- When `alloc_buffer` is called, it registers the requested size with `llama.cpp`'s allocator but leaves the physical `VkDeviceMemory` pointer as `VK_NULL_HANDLE`. It allocates 0 bytes of VRAM at startup.
- We intercept `llama_model_load` via the `set_usage` callback or environment variable (`GGML_VK_ENABLE_VRAM_STREAMING=1`) to force this buffer type for weights.

**Component B: Per-Batch JIT Allocator (Pre-Compute)**
- Inside `ggml_backend_vk_graph_compute` (around line 14280), *before* the batch is finalized and `ggml_vk_build_graph` is called:
- Iterate through the `cgraph_nodes` in the current batch.
- For each weight tensor using the streaming buffer:
  1. `vkAllocateMemory` an exact-fit block of VRAM.
  2. Map the pointer and use `vkCmdCopyBuffer` to stream the data from the CPU host pointer (`tensor->data` from the `mmap` file) to the VRAM.
  3. Update `tensor->buffer->context` so the `ggml_vk_build_graph` records the compute dispatch against this valid `VkBuffer` handle.

**Component C: Per-Batch VRAM Evictor (Post-Compute)**
- Still inside `ggml_backend_vk_graph_compute` (around line 14335), *after* the `ggml_vk_submit` and the `waitForFences` synchronization:
- Iterate through the exact same temporary weight buffers.
- Immediately call `vkFreeMemory` (`ggml_vk_destroy_buffer_device`) to destroy the VRAM allocations, ensuring VRAM peak footprint never exceeds the current batch.

### 3. Compilation
- Compile the entire `llama.cpp` project via CMake, producing our custom `llama-server.exe` handling both CPU and Vulkan tier streaming.

## Verification Plan
1. Apply the memory eviction code injection to `llama.cpp`.
2. Compile `llama-server.exe`.
3. Launch `llama-server.exe` using the Qwen3.5-35B GGUF model.
4. Open Windows Task Manager / Performance Monitor.
5. Watch the process Working Set (Private Bytes) during token generation. It should hover around 1-2GB instead of ballooning to 20GB.
