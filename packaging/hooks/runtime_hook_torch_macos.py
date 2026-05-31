"""Runtime adjustments for PyInstaller + PyTorch on macOS."""

import importlib.abc
import importlib.machinery
import os
import sys
import types


class _TorchUtilsInternalLoader(importlib.abc.Loader):
    def __init__(self, wrapped_loader):
        self._wrapped_loader = wrapped_loader

    def create_module(self, spec):
        create_module = getattr(self._wrapped_loader, "create_module", None)
        if create_module is None:
            return None
        return create_module(spec)

    def exec_module(self, module):
        self._wrapped_loader.exec_module(module)
        module.USE_GLOBAL_DEPS = False


class _TorchUtilsInternalFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != "torch._utils_internal":
            return None

        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.loader:
            spec.loader = _TorchUtilsInternalLoader(spec.loader)
        return spec


def _install_distributed_stub():
    # libtorch_python.dylib registers c10d pybind11 types via C++ static
    # initialization. torch.distributed/__init__.py then explicitly calls
    # torch._C._c10d_init(), which re-registers GradBucket and aborts with
    # "cannot initialize type GradBucket: an object with that name is already
    # defined". We don't use torch.distributed for anything (inference only),
    # so install a no-op stub before torch/__init__.py reaches its
    # `from torch import distributed` import.
    if "torch.distributed" in sys.modules:
        return

    stub = types.ModuleType("torch.distributed")
    stub.__path__ = []  # mark as package so submodule imports resolve
    stub.is_available = lambda: False
    stub.is_initialized = lambda: False

    def _stub_getattr(name):
        if name.startswith("__"):
            raise AttributeError(name)
        return None

    stub.__getattr__ = _stub_getattr  # type: ignore[attr-defined]

    meta_stub = types.ModuleType("torch.distributed._meta_registrations")

    sys.modules["torch.distributed"] = stub
    sys.modules["torch.distributed._meta_registrations"] = meta_stub


if sys.platform == "darwin" and getattr(sys, "frozen", False):
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    sys.meta_path.insert(0, _TorchUtilsInternalFinder())
    _install_distributed_stub()
