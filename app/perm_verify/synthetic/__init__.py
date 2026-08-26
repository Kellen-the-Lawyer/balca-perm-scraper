"""Canonical data contracts for synthetic PWD/PERM training records."""

from .models import PermPwdPair
from .oflc_seed import build_pair_seed

__all__ = ["PermPwdPair", "build_pair_seed"]
