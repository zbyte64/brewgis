"""Shared feature column name constants.

Minimal module with no dependencies — safe for SQLMesh serializer traversal.
"""

_RESNET_PC_COLS = [f"pc{i + 1:02d}" for i in range(32)]
