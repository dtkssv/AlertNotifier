from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/sounds/', views.sounds_list, name='sounds-list'),
    path('api/sounds/upload/', views.upload_sound, name='upload-sound'),
    path('api/sounds/<int:sound_id>/delete/', views.delete_sound, name='delete-sound'),
    path('api/settings/', views.get_settings, name='get-settings'),
    path('api/settings/update/', views.update_settings, name='update-settings'),
    path('api/alerts/', views.get_alerts, name='get-alerts'),
    path('api/alerts/<str:alert_id>/ack/', views.acknowledge_alert, name='ack-alert'),
]