from inspect import getmembers
from types import FunctionType, ModuleType


def find_literals(module: ModuleType) -> list[str]:
    members = []
    for name, member in getmembers(module):
        if member == module:
            continue
        if isinstance(member, (ModuleType, FunctionType, type)):
            continue
        else:
            members.append(name)
    return members


def monkeypatch_literals(source: ModuleType, target: ModuleType) -> None:
    source_literals = find_literals(source)
    target_literals = find_literals(target)
    for attrname in set(source_literals).intersection(target_literals):
        setattr(target, attrname, getattr(source, attrname))
