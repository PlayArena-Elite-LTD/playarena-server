from django.urls import path
from . import views

urlpatterns = [
    path('', views.wallet_view, name='wallet'),
    path('deposit/', views.deposit_view, name='deposit'),
    path('withdraw/', views.withdraw_view, name='withdraw'),
    path('transactions/', views.transaction_history, name='transaction_history'),
    # Payment method management
    path('payment-methods/', views.payment_methods_list, name='payment_methods_list'),
    path('payment-methods/add/', views.payment_method_create, name='payment_method_create'),
    path('payment-methods/<int:payment_method_id>/edit/', views.payment_method_edit, name='payment_method_edit'),
    path('payment-methods/<int:payment_method_id>/delete/', views.payment_method_delete, name='payment_method_delete'),
    path('payment-methods/<int:payment_method_id>/set-default/', views.payment_method_set_default, name='payment_method_set_default'),
]
