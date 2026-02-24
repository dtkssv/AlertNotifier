from django.contrib import admin
from .models import Alert, UserSound, UserSettings

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('name', 'severity', 'status', 'instance', 'starts_at')
    list_filter = ('severity', 'status')
    search_fields = ('name', 'instance', 'description')
    readonly_fields = ('alert_id', 'created_at', 'updated_at')

@admin.register(UserSound)
class UserSoundAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'is_default', 'created_at')
    list_filter = ('is_default',)
    search_fields = ('name',)

@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'bridge_server_url', 'auto_connect', 'updated_at')
    list_filter = ('auto_connect', 'show_notifications')