from django.urls import path
from . import views
from .webhooks import paystack_webhook, flutterwave_webhook, lipila_callback

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
    # Webhook endpoints
    path('webhooks/paystack/', paystack_webhook, name='paystack_webhook'),
    path('webhooks/flutterwave/', flutterwave_webhook, name='flutterwave_webhook'),
    path('webhooks/lipila/', lipila_callback, name='lipila_callback'),
    path('lipila/callback/', lipila_callback, name='lipila_callback_redirect'),
]
