from panel.models import Dispute
from django.core.cache import caches

def open_dispute_count(request):
    if request.user.is_authenticated and getattr(request.user, 'is_support_staff', False):
        cache = caches["ratelimit"]
        key = "open_dispute_count"
        cached = cache.get(key)
        if cached is None:
            cached = Dispute.objects.filter(status='OPEN').count()
            cache.set(key, cached, 15)
        return {'open_dispute_count': cached}
    return {}