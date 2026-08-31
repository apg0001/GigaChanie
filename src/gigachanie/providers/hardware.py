"""하드웨어 감지.

OS / CPU / RAM / GPU(VRAM) 와 사용 가능한 로컬 백엔드를 감지한다.
모든 조회는 실패해도 예외를 전파하지 않고 None/빈 값으로 처리한다.
"""

from __future__ import annotations

import contextlib
import json
import platform
import shutil
import subprocess
from dataclasses import dataclass, field

import psutil

_SUBPROCESS_TIMEOUT = 4.0


def _run(cmd: list[str]) -> str | None:
    """명령을 실행하고 stdout 을 돌려준다. 실패 시 None."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


@dataclass(frozen=True)
class GPU:
    name: str
    vram_gb: float | None
    vendor: str  # "nvidia" | "amd" | "apple" | "intel" | "unknown"


@dataclass(frozen=True)
class Backend:
    name: str  # "ollama" | "llama.cpp" | "mlx" | "vllm"
    available: bool
    detail: str = ""


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str  # "Windows" | "macOS" | "Linux"
    os_version: str
    arch: str
    cpu_brand: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_gb: float
    ram_available_gb: float
    is_apple_silicon: bool
    unified_memory: bool
    gpus: tuple[GPU, ...] = ()
    backends: tuple[Backend, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_vram_gb(self) -> float | None:
        vrams = [g.vram_gb for g in self.gpus if g.vram_gb is not None]
        return sum(vrams) if vrams else None

    @property
    def has_discrete_gpu(self) -> bool:
        return any(g.vendor in ("nvidia", "amd") and g.vram_gb for g in self.gpus)

    def backend(self, name: str) -> Backend | None:
        for b in self.backends:
            if b.name == name:
                return b
        return None

    @property
    def available_backends(self) -> list[str]:
        return [b.name for b in self.backends if b.available]


# --------------------------------------------------------------------------- CPU


def _cpu_brand(os_name: str) -> str:
    if os_name == "Darwin":
        out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out:
            return out
    elif os_name == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif os_name == "Windows":
        out = _run(["wmic", "cpu", "get", "name", "/value"])
        if out:
            for line in out.splitlines():
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
    return platform.processor() or "알 수 없음"


# --------------------------------------------------------------------------- GPU


def _nvidia_gpus() -> list[GPU]:
    if not shutil.which("nvidia-smi"):
        return []
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return []
    gpus: list[GPU] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        name, mem = parts
        try:
            vram_gb = round(float(mem) / 1024, 1)
        except ValueError:
            vram_gb = None
        gpus.append(GPU(name=name, vram_gb=vram_gb, vendor="nvidia"))
    return gpus


def _amd_gpus() -> list[GPU]:
    if not shutil.which("rocm-smi"):
        return []
    out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    gpus: list[GPU] = []
    for card, info in data.items():
        if not card.lower().startswith("card"):
            continue
        name = info.get("Card series") or info.get("Card model") or "AMD GPU"
        vram_gb: float | None = None
        raw = info.get("VRAM Total Memory (B)")
        if raw:
            with contextlib.suppress(ValueError):
                vram_gb = round(int(raw) / (1024**3), 1)
        gpus.append(GPU(name=name, vram_gb=vram_gb, vendor="amd"))
    return gpus


def _apple_gpu(ram_total_gb: float) -> list[GPU]:
    out = _run(["system_profiler", "-json", "SPDisplaysDataType"])
    name = "Apple GPU"
    if out:
        try:
            data = json.loads(out)
            displays = data.get("SPDisplaysDataType", [])
            if displays:
                name = displays[0].get("sppci_model", name)
        except json.JSONDecodeError:
            pass
    # 통합 메모리: GPU가 시스템 RAM을 공유. VRAM은 대략 전체 RAM으로 본다.
    return [GPU(name=name, vram_gb=ram_total_gb, vendor="apple")]


def _detect_gpus(ram_total_gb: float, is_apple_silicon: bool) -> list[GPU]:
    if is_apple_silicon:
        return _apple_gpu(ram_total_gb)
    return _nvidia_gpus() + _amd_gpus()


# ----------------------------------------------------------------------- backends


def _ollama_backend() -> Backend:
    path = shutil.which("ollama")
    if not path:
        return Backend(name="ollama", available=False, detail="ollama 미설치")
    # 데몬이 떠 있는지 확인
    out = _run(["ollama", "list"])
    if out is None:
        return Backend(
            name="ollama",
            available=True,
            detail="설치됨 (데몬 미실행 가능성 - `ollama serve` 확인)",
        )
    lines = [ln for ln in out.splitlines()[1:] if ln.strip()]
    return Backend(name="ollama", available=True, detail=f"설치됨, 모델 {len(lines)}개")


def _llamacpp_backend() -> Backend:
    for exe in ("llama-server", "llama-cli", "llama.cpp"):
        if shutil.which(exe):
            return Backend(name="llama.cpp", available=True, detail=f"{exe} 발견")
    return Backend(name="llama.cpp", available=False)


def _mlx_backend(is_apple_silicon: bool) -> Backend:
    if not is_apple_silicon:
        return Backend(name="mlx", available=False, detail="Apple Silicon 전용")
    try:
        import importlib.util

        spec = importlib.util.find_spec("mlx_lm")
    except ModuleNotFoundError:
        spec = None
    if spec is not None:
        return Backend(name="mlx", available=True, detail="mlx_lm 설치됨")
    return Backend(name="mlx", available=False, detail="pip install mlx-lm 필요")


def _vllm_backend() -> Backend:
    if shutil.which("vllm"):
        return Backend(name="vllm", available=True, detail="vllm CLI 발견")
    return Backend(name="vllm", available=False)


def _detect_backends(is_apple_silicon: bool) -> list[Backend]:
    return [
        _ollama_backend(),
        _llamacpp_backend(),
        _mlx_backend(is_apple_silicon),
        _vllm_backend(),
    ]


# ------------------------------------------------------------------------ profile


_OS_DISPLAY = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}


def detect_hardware() -> HardwareProfile:
    raw_os = platform.system()
    os_name = _OS_DISPLAY.get(raw_os, raw_os or "알 수 없음")
    arch = platform.machine()
    is_apple_silicon = raw_os == "Darwin" and arch in ("arm64", "aarch64")

    vm = psutil.virtual_memory()
    ram_total_gb = round(vm.total / (1024**3), 1)
    ram_available_gb = round(vm.available / (1024**3), 1)

    warnings: list[str] = []
    gpus = _detect_gpus(ram_total_gb, is_apple_silicon)
    if not gpus and not is_apple_silicon:
        warnings.append(
            "GPU를 감지하지 못했습니다. CPU 추론은 느릴 수 있으며, "
            "감지 실패일 수도 있습니다(nvidia-smi/rocm-smi 확인)."
        )

    backends = _detect_backends(is_apple_silicon)
    if not any(b.available for b in backends):
        warnings.append(
            "사용 가능한 로컬 백엔드가 없습니다. Ollama 설치를 권장합니다: https://ollama.com"
        )

    return HardwareProfile(
        os_name=os_name,
        os_version=platform.version(),
        arch=arch,
        cpu_brand=_cpu_brand(raw_os),
        cpu_cores_physical=psutil.cpu_count(logical=False) or 0,
        cpu_cores_logical=psutil.cpu_count(logical=True) or 0,
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_available_gb,
        is_apple_silicon=is_apple_silicon,
        unified_memory=is_apple_silicon,
        gpus=tuple(gpus),
        backends=tuple(backends),
        warnings=tuple(warnings),
    )
