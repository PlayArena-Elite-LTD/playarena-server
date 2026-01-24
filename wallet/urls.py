from django.urls import path
from . import views

urlpatterns = [
    path('', views.wallet_view, name='wallet'),
    path('balance/', views.check_balance, name='check_balance'),
    path('deposit/', views.deposit, name='deposit'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('transactions/', views.transaction_history, name='transaction_history'),
    # Payment callbacks (will be enhanced in Task 12)
    path('payment/success/<int:deposit_id>/', views.payment_success, name='payment_success'),
    path('payment/cancel/<int:deposit_id>/', views.payment_cancel, name='payment_cancel'),
]











