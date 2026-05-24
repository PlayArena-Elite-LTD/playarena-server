"""
Backward-compatible re-exports — use services.payments instead.
"""
from services.payments.lipila_service import LipilaService, get_lipila_service

# Legacy alias
LipilaClient = LipilaService
get_lipila_client = get_lipila_service

__all__ = ['LipilaService', 'LipilaClient', 'get_lipila_service', 'get_lipila_client']
