import json
import asyncio
import logging
import threading
import time
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.conf import settings
import websocket

logger = logging.getLogger(__name__)

class AlertBridgeConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bridge_ws = None
        self.bridge_thread = None
        self.reconnect_attempts = 0
        self.connected_to_bridge = False
        self.user_settings = None
        self._loop = None

    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

        self._loop = asyncio.get_event_loop()
        self.user_settings = await self.get_user_settings()

        await self.accept()
        logger.info(f"Client {self.user.username} connected")

        await self.send(text_data=json.dumps({
            'type': 'connection',
            'status': 'connected',
            'message': 'Connected to AlertBridge'
        }))

        await self.connect_to_bridge()

    async def disconnect(self, close_code):
        logger.info(f"Client {self.user.username} disconnected")
        await self.disconnect_from_bridge()

    async def connect_to_bridge(self):
        bridge_url = self.user_settings.bridge_server_url if self.user_settings else settings.BRIDGE_SERVER_URL
        self.bridge_thread = threading.Thread(
            target=self._bridge_ws_loop,
            args=(bridge_url,),
            daemon=True
        )
        self.bridge_thread.start()

    def _bridge_ws_loop(self, bridge_url):
        def on_message(ws, message):
            asyncio.run_coroutine_threadsafe(
                self.handle_bridge_message(message), self._loop
            )

        def on_error(ws, error):
            logger.error(f"Bridge WebSocket error: {error}")
            self.connected_to_bridge = False
            asyncio.run_coroutine_threadsafe(self.send_status_update(), self._loop)

        def on_close(ws, close_status_code, close_msg):
            logger.info("Bridge WebSocket closed")
            self.connected_to_bridge = False
            asyncio.run_coroutine_threadsafe(self.send_status_update(), self._loop)

            if settings.BRIDGE_MAX_RECONNECT_ATTEMPTS == 0 or \
               self.reconnect_attempts < settings.BRIDGE_MAX_RECONNECT_ATTEMPTS:
                self.reconnect_attempts += 1
                logger.info(f"Reconnecting to bridge (attempt {self.reconnect_attempts})...")
                time.sleep(settings.BRIDGE_RECONNECT_DELAY)
                self._bridge_ws_loop(bridge_url)

        def on_open(ws):
            logger.info("Connected to Bridge server")
            self.connected_to_bridge = True
            self.reconnect_attempts = 0
            asyncio.run_coroutine_threadsafe(self.send_status_update(), self._loop)

        self.bridge_ws = websocket.WebSocketApp(
            bridge_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        self.bridge_ws.run_forever()

    async def handle_bridge_message(self, message):
        try:
            data = json.loads(message)
            if data.get('type') == 'alert':
                await self.save_alert(data.get('data', {}))
            await self.channel_layer.group_send(
                f"user_{self.user.id}",
                {
                    'type': 'bridge.message',
                    'message': data
                }
            )
        except Exception as e:
            logger.error(f"Error handling bridge message: {e}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            if msg_type == 'ack':
                alert_id = data.get('alert_id')
                await self.acknowledge_alert(alert_id)
            elif msg_type == 'get_alerts':
                await self.send_active_alerts()
            elif msg_type == 'get_sounds':
                await self.send_available_sounds()
            elif msg_type == 'update_settings':
                settings_data = data.get('settings', {})
                await self.update_settings(settings_data)
        except Exception as e:
            logger.error(f"Error processing client message: {e}")

    async def bridge_message(self, event):
        await self.send(text_data=json.dumps(event['message']))

    async def send_status_update(self):
        await self.send(text_data=json.dumps({
            'type': 'status',
            'connected_to_bridge': self.connected_to_bridge,
            'timestamp': time.time()
        }))

    async def send_active_alerts(self):
        alerts = await self.get_active_alerts()
        await self.send(text_data=json.dumps({
            'type': 'alerts_list',
            'alerts': alerts
        }))

    async def send_available_sounds(self):
        sounds = await self.get_available_sounds()
        await self.send(text_data=json.dumps({
            'type': 'sounds_list',
            'sounds': sounds
        }))

    async def disconnect_from_bridge(self):
        if self.bridge_ws:
            self.bridge_ws.close()

    @database_sync_to_async
    def get_user_settings(self):
        from .models import UserSettings
        try:
            return UserSettings.objects.get(user=self.user)
        except UserSettings.DoesNotExist:
            return None

    @database_sync_to_async
    def save_alert(self, alert_data):
        from .models import Alert
        from datetime import datetime
        alert_id = alert_data.get('id')
        if not alert_id:
            return
        try:
            Alert.objects.update_or_create(
                alert_id=alert_id,
                defaults={
                    'name': alert_data.get('name', ''),
                    'status': alert_data.get('status', 'firing'),
                    'severity': alert_data.get('severity', 'warning'),
                    'instance': alert_data.get('instance', ''),
                    'job': alert_data.get('job', ''),
                    'description': alert_data.get('description', ''),
                    'summary': alert_data.get('summary', ''),
                    'starts_at': alert_data.get('starts_at', datetime.now()),
                    'generator_url': alert_data.get('generator_url', ''),
                    'raw_data': alert_data,
                }
            )
        except Exception as e:
            logger.error(f"Error saving alert: {e}")

    @database_sync_to_async
    def get_active_alerts(self):
        from .models import Alert
        alerts = Alert.objects.filter(status='firing')[:100]
        return [
            {
                'id': a.alert_id,
                'name': a.name,
                'status': a.status,
                'severity': a.severity,
                'instance': a.instance,
                'description': a.description,
                'starts_at': a.starts_at.isoformat() if a.starts_at else None,
            }
            for a in alerts
        ]

    @database_sync_to_async
    def get_available_sounds(self):
        from .models import UserSound
        sounds = UserSound.objects.all()
        return [
            {
                'id': s.id,
                'name': s.name,
                'url': s.file.url if s.file else None,
                'is_default': s.is_default,
            }
            for s in sounds
        ]

    @database_sync_to_async
    def acknowledge_alert(self, alert_id):
        from .models import Alert
        try:
            alert = Alert.objects.get(alert_id=alert_id)
            logger.info(f"Alert {alert_id} acknowledged by {self.user.username}")
        except Alert.DoesNotExist:
            pass