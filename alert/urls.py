from django.urls import path
from . import views

urlpatterns = [
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/mark-read/<int:notification_id>/', views.mark_notification_read, name='mark_notification_read'),
]