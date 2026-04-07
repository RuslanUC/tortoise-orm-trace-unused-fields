import importlib
import importlib.abc
import importlib.util
import sys
import weakref
from importlib.machinery import ModuleSpec
from os import PathLike
from pathlib import Path
from types import ModuleType

TRACING_ATTRS_NAME = "_tracing_attrs"
TRACING_ATTRS_LOC_NAME = "_tracing_attrs_init"
TRACING_ATTRS_KNOWN = "_KNOWN_UNUSED"
KNOWN_ATTRS = {"_saved_in_db", "_partial", "_custom_generated_pk", "_await_when_save"}


class SomeClassMeta(type):
    @staticmethod
    def _finalize(instance: object):
        if not hasattr(instance, TRACING_ATTRS_NAME):
            return
        accessed_attrs = getattr(instance, TRACING_ATTRS_NAME)
        known_unused = set(getattr(instance.__class__, TRACING_ATTRS_KNOWN, ()))
        init_file, init_line = getattr(instance, TRACING_ATTRS_LOC_NAME, ("<UNKNOWN>", 0))
        for attr in instance.__dict__:
            if attr in accessed_attrs \
                    or attr in KNOWN_ATTRS \
                    or attr in known_unused \
                    or attr in (TRACING_ATTRS_NAME, TRACING_ATTRS_LOC_NAME):
                continue
            print(
                f"Attribute of {instance.__class__.__name__} "
                f"(initialized at {init_file}:{init_line}) "
                f"was not accessed: \"{attr}\"!"
            )

    def __new__(cls, name, bases, namespace):
        def __getattribute__(self, attr_name):
            if attr_name != TRACING_ATTRS_NAME and hasattr(self, TRACING_ATTRS_NAME):
                getattr(self, TRACING_ATTRS_NAME).add(attr_name)
            return object.__getattribute__(self, attr_name)

        def __setattr__(self, attr_name, value):
            object.__setattr__(self, attr_name, value)

        def __new__(clss, *args, **kwargs) -> ...:
            tortoise_root = Path(sys.modules["tortoise"].__file__).parent

            caller_frame = sys._getframe(1)
            instance = object.__new__(clss)
            if caller_frame is not None \
                    and caller_frame.f_code.co_name != "create" \
                    and Path(caller_frame.f_code.co_filename).is_relative_to(tortoise_root):
                setattr(instance, TRACING_ATTRS_NAME, set())

                init_frame = None
                frame = caller_frame
                while frame.f_back is not None:
                    if not Path(frame.f_code.co_filename).is_relative_to(tortoise_root):
                        init_frame = frame
                        break
                    frame = frame.f_back

                if init_frame is not None:
                    setattr(instance, TRACING_ATTRS_LOC_NAME, (init_frame.f_code.co_filename, init_frame.f_lineno))

            weakref.finalize(instance, cls._finalize, instance)
            return instance

        namespace["__setattr__"] = __setattr__
        namespace["__getattribute__"] = __getattribute__
        namespace["__new__"] = __new__

        return super().__new__(cls, name, bases, namespace)


class SourceModifyingLoader(importlib.abc.Loader):
    def __init__(self, file_path: str | PathLike) -> None:
        self.file_path = file_path

    def create_module(self, spec: ModuleSpec) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        with open(self.file_path, "r", encoding='utf-8') as f:
            source = f.read()

        modified_source = source.replace(
            "class ModelMeta(type):",
            "class ModelMeta(_ModelAttrsTracingMeta):"
        )

        if "class ModelMeta(type):" not in source or "class ModelMeta(_ModelAttrsTracingMeta):" not in modified_source:
            raise RuntimeError("Failed to replace metaclass line")

        code = compile(modified_source, self.file_path, "exec")

        module.__dict__["_ModelAttrsTracingMeta"] = SomeClassMeta
        exec(code, module.__dict__)


class ModuleOverrideFinder(importlib.abc.MetaPathFinder):
    def __init__(self, target_module_name: str, target_file_relative_path: str) -> None:
        self.target_module_name = target_module_name
        self.target_file_relative_path = target_file_relative_path

    def find_spec(self, fullname: str, path: list[str] | None, target: ModuleType | None = None) -> None:
        if fullname != self.target_module_name:
            return None

        meta_path_copy = list(sys.meta_path)
        sys.meta_path.remove(self)

        try:
            original_spec = importlib.util.find_spec(fullname)
        finally:
            sys.meta_path[:] = meta_path_copy

        if original_spec is None or original_spec.origin is None:
            return None

        file_path = Path(original_spec.origin).parent / self.target_file_relative_path
        if not file_path.exists():
            file_path = Path(original_spec.origin)

        return importlib.util.spec_from_file_location(
            fullname,
            file_path,
            loader=SourceModifyingLoader(file_path),
            submodule_search_locations=original_spec.submodule_search_locations
        )


_HOOKED = False


def hook_tortoise() -> None:
    global _HOOKED

    if _HOOKED:
        return

    sys.meta_path.insert(0, ModuleOverrideFinder("tortoise.models", "models.py"))
    _HOOKED = True
