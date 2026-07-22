import torch

print("=" * 50)
print("GPU / CUDA CHECK")
print("=" * 50)

cuda_available = torch.cuda.is_available()
print(f"torch version:      {torch.__version__}")
print(f"cuda_available:      {cuda_available}")

if cuda_available:
    print(f"cuda version (torch): {torch.version.cuda}")
    print(f"device count:         {torch.cuda.device_count()}")
    print(f"device name:          {torch.cuda.get_device_name(0)}")
    total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f"total VRAM:           {total_mem:.2f} GB")

    x = torch.rand(1000, 1000, device="cuda")
    y = x @ x
    torch.cuda.synchronize()
    print("GPU matmul test:      OK")
else:
    print()
    print("CUDA NOT AVAILABLE. Checklist:")
    print("  1. Run 'nvidia-smi' in Command Prompt - if unrecognized, install")
    print("     NVIDIA drivers first (Windows Update or nvidia.com).")
    print("  2. If nvidia-smi works but this still says False, torch is")
    print("     probably the CPU-only build. Fix with:")
    print("       pip uninstall torch torchvision -y")
    print("       pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")

print("=" * 50)