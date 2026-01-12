from django.contrib import admin
from .models import Message, ReadMessage

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'sender',
        'receiver',
        'created_at',
    )
    list_filter = ('sender', 'receiver', 'created_at')
    search_fields = ('sender__username', 'receiver__username', 'message')
    readonly_fields = ('created_at',)


@admin.register(ReadMessage)
class ReadMessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'receiver',
        'read_at',
    )
    list_filter = ('receiver', 'read_at')
    search_fields = ('receiver__username', 'message__message')
    readonly_fields = ('read_at',)