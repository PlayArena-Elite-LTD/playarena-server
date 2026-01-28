from django.urls import path
from . import views

urlpatterns = [
    path('open-disputes/', views.open_disputes, name='open_disputes'),
    path('attend-dispute/<int:dispute_id>/', views.attend_dispute, name='attend_dispute'),
    path('my-disputes/', views.my_disputes, name='my_disputes'),
    path('disputes/stats/', views.dispute_stats, name='dispute_stats'),
    path('dispute/<int:dispute_id>/', views.dispute_detail, name='dispute_detail'),
    path('dispute/<int:dispute_id>/resolve/', views.resolve_dispute, name='resolve_dispute'),
    path('dispute/<int:dispute_id>/suspend/<int:user_id>/', views.suspend_user, name='suspend_user'),
    path('evidence/<int:evidence_id>/notes/', views.update_evidence_notes, name='update_evidence_notes'),
]