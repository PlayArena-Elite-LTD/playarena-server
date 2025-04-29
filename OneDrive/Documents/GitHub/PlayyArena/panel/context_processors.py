from panel.models import Dispute

def open_dispute_count(request):
    if request.user.is_authenticated and getattr(request.user, 'is_support_staff', False):
        count = Dispute.objects.filter(status='OPEN').count()
        return {'open_dispute_count': count}
    return {}