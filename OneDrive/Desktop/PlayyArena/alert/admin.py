from django.contrib import admin
from .models import Notification, ReadNotification

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'short_message',
        'created_at',
        'is_read_display',
    )
    list_filter = ('user', 'created_at')
    search_fields = ('user__username', 'message')
    readonly_fields = ('created_at',)

    def short_message(self, obj):
        return obj.message[:50]
    short_message.short_description = 'Message Preview'

    def is_read_display(self, obj):
        return obj.is_read
    is_read_display.boolean = True
    is_read_display.short_description = 'Read?'

@admin.register(ReadNotification)
class ReadNotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'read_at',
    )
    list_filter = ('user', 'read_at')
    search_fields = ('user__username', 'notification__message')
    readonly_fields = ('read_at',)
