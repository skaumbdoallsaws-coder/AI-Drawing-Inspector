"""Bounded reuse of pure derivations within one request, never across requests.

Keys cover the complete inputs (including source, scene, layout and provenance).
Cached results are private; callers always receive their own mutable result.
There is no store, clock, artifact or permission caching here.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from hashlib import sha256
import json

_work = ContextVar("documentation_request_work", default=None)


@contextmanager
def work_scope():
    if _work.get() is not None:
        yield
        return
    token = _work.set({})
    try:
        yield
    finally:
        _work.reset(token)


def request_work(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        with work_scope():
            return method(*args, **kwargs)
    return wrapped


def _digest(inputs):
    try:
        return sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
            allow_nan=False).encode("ascii")).digest()
    except (TypeError, ValueError):
        # Invalid/non-JSON input must reach the existing validator and its existing refusal.
        return None


def memoized(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        work = _work.get()
        if work is None:
            return method(*args, **kwargs)
        hashed = _digest([args, kwargs])
        if hashed is None:
            return method(*args, **kwargs)
        key = (method.__module__, method.__name__, hashed)
        if key not in work:
            # Retain only a handful of publication derivations, not an unbounded history.
            if len(work) >= 32:
                work.pop(next(iter(work)))
            work[key] = method(*args, **kwargs)
        return deepcopy(work[key])
    return wrapped


def reuse(namespace, inputs, build):
    """Request-local read derivation; inputs include the on-disk replace identity for store reads."""
    work = _work.get()
    if work is None:
        return build()
    hashed = _digest(inputs)
    if hashed is None:
        return build()
    key = (namespace, hashed)
    if key not in work:
        if len(work) >= 32:
            work.pop(next(iter(work)))
        work[key] = build()
    return deepcopy(work[key])


def _identity_key(document):
    hashed = _digest(document)
    return ("identified", hashed) if hashed is not None else None


def mark_identified(document):
    """Only a completed compiler calls this. A mutation changes the full-content key."""
    work = _work.get()
    if work is not None:
        key = _identity_key(document)
        if key is None:
            return document
        if key not in work and len(work) >= 32:
            work.pop(next(iter(work)))
        work[key] = True
    return document


def is_identified(document):
    work = _work.get()
    return work is not None and work.get(_identity_key(document)) is True
