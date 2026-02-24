import json
import base64
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.conf import settings
from .models import Alert, UserSound, UserSettings

@login_required
def index(request):
    """Главная страница"""
    context = {
        'bridge_server_url': settings.BRIDGE_SERVER_URL,
        'user': request.user,
    }
    return render(request, 'core/index.html', context)

@login_required
def sounds_list(request):
    """Получение списка звуков"""
    sounds = UserSound.objects.all()
    data = [
        {
            'id': s.id,
            'name': s.name,
            'url': s.file.url if s.file else None,
            'is_default': s.is_default,
        }
        for s in sounds
    ]
    return JsonResponse({'sounds': data})

@csrf_exempt
@login_required
def upload_sound(request):
    """Загрузка пользовательского звука"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        file_data = data.get('file')
        file_name = data.get('name')
        custom_name = data.get('custom_name')
        
        if not file_data or not file_name:
            return JsonResponse({'error': 'Missing file data'}, status=400)
        
        # Проверяем расширение
        ext = file_name.split('.')[-1].lower()
        if ext not in ['wav', 'mp3', 'ogg']:
            return JsonResponse({'error': 'Unsupported file format'}, status=400)
        
        # Генерируем имя для сохранения
        if custom_name:
            safe_name = ''.join(c for c in custom_name if c.isalnum() or c in ' -_').strip()
            if not safe_name:
                safe_name = file_name.split('.')[0]
        else:
            safe_name = file_name.split('.')[0]
        
        # Проверяем, существует ли уже такой звук
        base_name = safe_name
        counter = 1
        while UserSound.objects.filter(name=safe_name).exists():
            safe_name = f"{base_name}_{counter}"
            counter += 1
        
        # Декодируем и сохраняем файл
        format, imgstr = file_data.split(';base64,')
        file_content = ContentFile(
            base64.b64decode(imgstr),
            name=f"{safe_name}.{ext}"
        )
        
        sound = UserSound.objects.create(
            user=request.user if request.user.is_authenticated else None,
            name=safe_name,
            file=file_content
        )
        
        return JsonResponse({
            'success': True,
            'sound': {
                'id': sound.id,
                'name': sound.name,
                'url': sound.file.url,
            }
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def delete_sound(request, sound_id):
    """Удаление звука"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        sound = UserSound.objects.get(id=sound_id)
        
        # Проверяем права (только владелец или админ)
        if sound.user != request.user and not request.user.is_staff:
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        if sound.is_default:
            return JsonResponse({'error': 'Cannot delete default sound'}, status=400)
        
        sound.file.delete()
        sound.delete()
        
        return JsonResponse({'success': True})
        
    except UserSound.DoesNotExist:
        return JsonResponse({'error': 'Sound not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def get_settings(request):
    """Получение настроек пользователя"""
    settings, created = UserSettings.objects.get_or_create(user=request.user)
    
    return JsonResponse({
        'bridge_server_url': settings.bridge_server_url,
        'auto_connect': settings.auto_connect,
        'show_notifications': settings.show_notifications,
        'notification_volume': settings.notification_volume,
        'alert_sound': settings.alert_sound.name if settings.alert_sound else None,
        'resolved_sound': settings.resolved_sound.name if settings.resolved_sound else None,
    })

@csrf_exempt
@login_required
def update_settings(request):
    """Обновление настроек пользователя"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        settings, created = UserSettings.objects.get_or_create(user=request.user)
        
        if 'bridge_server_url' in data:
            settings.bridge_server_url = data['bridge_server_url']
        if 'auto_connect' in data:
            settings.auto_connect = data['auto_connect']
        if 'show_notifications' in data:
            settings.show_notifications = data['show_notifications']
        if 'notification_volume' in data:
            settings.notification_volume = int(data['notification_volume'])
        if 'alert_sound' in data:
            try:
                settings.alert_sound = UserSound.objects.get(name=data['alert_sound'])
            except UserSound.DoesNotExist:
                pass
        if 'resolved_sound' in data:
            try:
                settings.resolved_sound = UserSound.objects.get(name=data['resolved_sound'])
            except UserSound.DoesNotExist:
                pass
        
        settings.save()
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def get_alerts(request):
    """Получение списка алертов"""
    status = request.GET.get('status', 'firing')
    severity = request.GET.get('severity')
    limit = int(request.GET.get('limit', 100))
    
    alerts = Alert.objects.all()
    if status:
        alerts = alerts.filter(status=status)
    if severity:
        alerts = alerts.filter(severity=severity)
    
    alerts = alerts[:limit]
    
    data = [
        {
            'id': a.alert_id,
            'name': a.name,
            'status': a.status,
            'severity': a.severity,
            'instance': a.instance,
            'description': a.description,
            'starts_at': a.starts_at.isoformat() if a.starts_at else None,
            'generator_url': a.generator_url,
        }
        for a in alerts
    ]
    
    return JsonResponse({'alerts': data})

@csrf_exempt
@login_required
def acknowledge_alert(request, alert_id):
    """Подтверждение получения алерта"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        alert = Alert.objects.get(alert_id=alert_id)
        # Можно добавить логику подтверждения
        return JsonResponse({'success': True})
    except Alert.DoesNotExist:
        return JsonResponse({'error': 'Alert not found'}, status=404)