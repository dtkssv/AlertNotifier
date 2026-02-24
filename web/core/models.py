from django.db import models
from django.contrib.auth import get_user_model
import json

User = get_user_model()

class Alert(models.Model):
    """Модель для хранения алертов"""
    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    ]
    
    STATUS_CHOICES = [
        ('firing', 'Firing'),
        ('resolved', 'Resolved'),
    ]
    
    alert_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='firing')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    instance = models.CharField(max_length=255, blank=True)
    job = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    generator_url = models.URLField(blank=True)
    raw_data = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-starts_at']
        indexes = [
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['-starts_at']),
        ]
    
    def __str__(self):
        return f"{self.name} [{self.severity}] on {self.instance}"

class UserSound(models.Model):
    """Модель для пользовательских звуков"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to='user_sounds/')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        unique_together = [['user', 'name']]
    
    def __str__(self):
        return self.name

class UserSettings(models.Model):
    """Модель для настроек пользователя"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='alert_settings')
    alert_sound = models.ForeignKey(UserSound, on_delete=models.SET_NULL, null=True, 
                                   related_name='+', blank=True)
    resolved_sound = models.ForeignKey(UserSound, on_delete=models.SET_NULL, null=True,
                                      related_name='+', blank=True)
    bridge_server_url = models.CharField(max_length=255, default='ws://localhost:8081/ws')
    auto_connect = models.BooleanField(default=True)
    show_notifications = models.BooleanField(default=True)
    notification_volume = models.IntegerField(default=70, help_text="Volume 0-100")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Settings for {self.user.username}"