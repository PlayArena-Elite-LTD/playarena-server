from django.urls import path
from . import views

urlpatterns = [
    path('messages/', views.messages_list, name='messages_list'),
    path('conversation/<int:user_id>/', views.conversation, name='conversation'),
    path('conversation/', views.conversation, name='conversation_redirect'),
]