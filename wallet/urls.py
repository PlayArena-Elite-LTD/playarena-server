from django.urls import path
from . import views

urlpatterns = [
    path('', views.wallet_view, name='wallet'),
    path('balance/', views.check_balance, name='check_balance'),
    path('deposit/', views.deposit, name='deposit'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('transactions/', views.transaction_history, name='transaction_history'),
]











