"""
Managers layer - State & Lifecycle management.

Responsibilities:
- Manage database objects (views, tables)
- Track execution state (pipeline runs)
- Lifecycle operations (CRUD)
"""

from src.managers.view_manager import ViewManager

__all__ = ['ViewManager']
