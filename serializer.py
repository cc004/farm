from typing import _GenericAlias
from enum import Enum
from msgpack import packb, unpackb

def _get_annotations(cls):
    if hasattr(cls, '__annotations__'):
        yield from cls.__annotations__.items()
    for base in cls.__bases__:
        yield from _get_annotations(base)

def _dump(obj):
    if obj is list or obj is tuple:
        return [_dump(i) for i in obj]
    elif obj is dict:
        return obj
    elif obj is str or obj is int or obj is float:
        return obj
    elif isinstance(obj, Enum):
        return obj.value
    else:
        return {name: _dump(getattr(obj, name)) for name, cls in _get_annotations(obj.__class__)}

def _load(obj, cls):
    if cls is int or cls is float or cls is str or cls is Enum:
        return cls(obj)
    elif isinstance(cls, _GenericAlias):
        if cls._name == "List":           
            t = cls.__args__[0]
            return [_load(i, t) for i in obj]
        elif cls._name == "Dict":
            k = cls.__args__[0]
            v = cls.__args__[1]
            return {_load(i, k): _load(j, v) for i, j in obj.items()}
    else:
        inst = cls()
        for name, cls in _get_annotations(cls):
            if name in obj:
                setattr(inst, name, _load(obj[name], cls))
        return inst

def dump(obj: object) -> bytes:
    return packb(_dump(obj), use_bin_type=False)

def load(data: bytes, cls) -> object:
    return _load(unpackb(data, strict_map_key=False), cls)