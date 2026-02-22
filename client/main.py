"""
Desktop приложение для отображения алертов Grafana
Подключается к VM-посреднику через WebSocket
"""
import json
import threading
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import os
import sys
from pathlib import Path

import flet as ft
from websocket import WebSocketApp
import playsound
from PIL import Image, ImageDraw
import pystray

# Константы
SOUND_ALERT = "alert.wav"  # Положите свой WAV файл в папку с приложением
SOUND_RESOLVED = "resolved.wav"

class AlertColors:
    """Цвета для разных уровней серьезности"""
    CRITICAL = ft.colors.RED_500
    HIGH = ft.colors.ORANGE_500
    WARNING = ft.colors.YELLELLOW_700
    INFO = ft.colors.BLUE_500
    RESOLVED = ft.colors.GREEN_500

class AlertClient:
    """Клиент для подключения к VM-посреднику"""
    
    def __init__(self, on_alert_callback, on_connection_change):
        self.ws: Optional[WebSocketApp] = None
        self.connected = False
        self.server_url = ""
        self.on_alert_callback = on_alert_callback
        self.on_connection_change = on_connection_change
        self.reconnect_thread: Optional[threading.Thread] = None
        self.should_reconnect = True
        
    def connect(self, server_url: str):
        """Подключение к WebSocket серверу"""
        self.server_url = server_url
        self.should_reconnect = True
        
        # Запускаем подключение в отдельном потоке
        thread = threading.Thread(target=self._connect_ws, daemon=True)
        thread.start()
    
    def _connect_ws(self):
        """Внутренний метод для установки WebSocket соединения"""
        def on_message(ws, message):
            try:
                data = json.loads(message)
                self.on_alert_callback(data)
            except Exception as e:
                print(f"Error parsing message: {e}")
        
        def on_error(ws, error):
            print(f"WebSocket error: {error}")
            self.connected = False
            self.on_connection_change(False)
        
        def on_close(ws, close_status_code, close_msg):
            print("WebSocket connection closed")
            self.connected = False
            self.on_connection_change(False)
            
            # Пытаемся переподключиться
            if self.should_reconnect:
                time.sleep(5)
                self._connect_ws()
        
        def on_open(ws):
            print("WebSocket connected!")
            self.connected = True
            self.on_connection_change(True)
        
        # Создаем WebSocket соединение
        self.ws = WebSocketApp(
            self.server_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # Запускаем цикл сообщений
        self.ws.run_forever()
    
    def disconnect(self):
        """Отключение от сервера"""
        self.should_reconnect = False
        if self.ws:
            self.ws.close()
    
    def send_ack(self, alert_id: str):
        """Отправка подтверждения о получении алерта"""
        if self.ws and self.connected:
            try:
                self.ws.send(json.dumps({
                    'type': 'ack',
                    'alert_id': alert_id
                }))
            except:
                pass

class AlertApp:
    """Основное GUI приложение"""
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.client = AlertClient(self.on_alert_received, self.on_connection_changed)
        self.alerts: Dict[str, Dict[str, Any]] = {}
        self.settings = self.load_settings()
        
        self.setup_page()
        self.create_ui()
        
        # Автоподключение если есть сохраненные настройки
        if self.settings.get('server_url'):
            self.connect_to_server(self.settings['server_url'])
        
    def setup_page(self):
        """Настройка страницы"""
        self.page.title = "Grafana Alert Desktop"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 10
        self.page.window_width = 1000
        self.page.window_height = 700
        self.page.window_min_width = 600
        self.page.window_min_height = 400
        
    def create_ui(self):
        """Создание пользовательского интерфейса"""
        
        # Верхняя панель с подключением
        self.connection_status = ft.Icon(
            name=ft.icons.WIFI_OFF,
            color=ft.colors.RED_400,
            size=20
        )
        
        self.server_input = ft.TextField(
            hint_text="ws://localhost:8081/ws",
            value=self.settings.get('server_url', ''),
            width=300,
            height=40,
            border_radius=8
        )
        
        self.connect_btn = ft.ElevatedButton(
            text="Подключиться",
            icon=ft.icons.LINK,
            on_click=self.toggle_connection,
            style=ft.ButtonStyle(
                color={"": ft.colors.WHITE},
                bgcolor={"": ft.colors.BLUE_600},
            )
        )
        
        # Статистика
        self.alerts_count = ft.Text("0", size=24, weight=ft.FontWeight.BOLD)
        self.critical_count = ft.Text("0", size=16)
        
        # Таблица с алертами
        self.alerts_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Статус")),
                ft.DataColumn(ft.Text("Уровень")),
                ft.DataColumn(ft.Text("Время")),
                ft.DataColumn(ft.Text("Название")),
                ft.DataColumn(ft.Text("Инстанс")),
                ft.DataColumn(ft.Text("Описание")),
                ft.DataColumn(ft.Text("Действия")),
            ],
            rows=[],
            column_spacing=20,
            horizontal_margin=10,
            data_row_max_height=60,
        )
        
        # Основная компоновка
        self.page.add(
            ft.Container(
                content=ft.Column([
                    # Шапка
                    ft.Container(
                        content=ft.Row([
                            ft.Row([
                                ft.Icon(ft.icons.NOTIFICATIONS_ACTIVE, size=30, color=ft.colors.BLUE_400),
                                ft.Text("Grafana Alert Desktop", size=24, weight=ft.FontWeight.BOLD),
                            ]),
                            ft.Row([
                                self.connection_status,
                                self.server_input,
                                self.connect_btn,
                            ]),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=10,
                    ),
                    
                    # Статистика
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                content=ft.Column([
                                    ft.Text("Активные алерты", size=14, color=ft.colors.GREY_400),
                                    self.alerts_count,
                                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=15,
                                border_radius=10,
                                bgcolor=ft.colors.GREY_900,
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Column([
                                    ft.Text("Критичные", size=14, color=ft.colors.GREY_400),
                                    self.critical_count,
                                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=15,
                                border_radius=10,
                                bgcolor=ft.colors.GREY_900,
                                expand=True,
                            ),
                        ], spacing=10),
                        padding=ft.padding.only(bottom=10),
                    ),
                    
                    # Заголовок таблицы с фильтрами
                    ft.Row([
                        ft.Text("Активные алерты", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.Dropdown(
                                options=[
                                    ft.dropdown.Option("Все"),
                                    ft.dropdown.Option("Critical"),
                                    ft.dropdown.Option("High"),
                                    ft.dropdown.Option("Warning"),
                                ],
                                value="Все",
                                width=150,
                                on_change=self.filter_alerts,
                            ),
                            ft.IconButton(
                                icon=ft.icons.REFRESH,
                                tooltip="Обновить",
                                on_click=self.refresh_alerts,
                            ),
                        ]),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    
                    # Таблица с алертами (в контейнере с прокруткой)
                    ft.Container(
                        content=ft.Column([
                            self.alerts_table
                        ], scroll=ft.ScrollMode.AUTO),
                        height=450,
                        border_radius=10,
                        bgcolor=ft.colors.GREY_900,
                        padding=10,
                    ),
                    
                ]),
                padding=10,
            )
        )
    
    def toggle_connection(self, e):
        """Подключение/отключение от сервера"""
        if not self.client.connected:
            server_url = self.server_input.value
            if server_url:
                # Сохраняем настройки
                self.settings['server_url'] = server_url
                self.save_settings()
                # Подключаемся
                self.connect_to_server(server_url)
        else:
            self.disconnect_from_server()
    
    def connect_to_server(self, server_url: str):
        """Подключение к серверу"""
        # Добавляем /ws если нужно
        if not server_url.endswith('/ws'):
            server_url = server_url.rstrip('/') + '/ws'
        
        self.client.connect(server_url)
        self.connect_btn.text = "Отключиться"
        self.connect_btn.style.bgcolor = {"": ft.colors.RED_600}
        self.page.update()
    
    def disconnect_from_server(self):
        """Отключение от сервера"""
        self.client.disconnect()
        self.connect_btn.text = "Подключиться"
        self.connect_btn.style.bgcolor = {"": ft.colors.BLUE_600}
        self.connection_status.name = ft.icons.WIFI_OFF
        self.connection_status.color = ft.colors.RED_400
        self.page.update()
    
    def on_connection_changed(self, connected: bool):
        """Обработка изменения состояния подключения"""
        if connected:
            self.connection_status.name = ft.cons.WIFI
            self.connection_status.color = ft.colors.GREEN_400
        else:
            self.connection_status.name = ft.icons.WIFI_OFF
            self.connection_status.color = ft.colors.RED_400
        self.page.update()
    
    def on_alert_received(self, data: dict):
        """Обработка полученного алерта"""
        alert_type = data.get('type')
        
        if alert_type == 'init' or alert_type == 'sync':
            # Полный список алертов
            self.alerts = {a['id']: a for a in data.get('alerts', [])}
            self.update_alerts_table()
            
        elif alert_type == 'alert':
            # Новый или обновленный алерт
            alert = data.get('data', {})
            alert_id = alert.get('id')
            
            if alert.get('status') == 'resolved':
                if alert_id in self.alerts:
                    del self.alerts[alert_id]
                    self.play_sound(SOUND_RESOLVED)
            else:
                self.alerts[alert_id] = alert
                self.play_sound(SOUND_ALERT)
                self.show_notification(alert)
            
            self.update_alerts_table()
        
        # Обновляем статистику
        self.update_stats()
    
    def update_alerts_table(self):
        """Обновление таблицы алертов"""
        rows = []
        
        for alert in self.alerts.values():
            # Определяем цвет для уровня серьезности
            severity = alert.get('severity', 'warning').lower()
            if severity == 'critical':
                color = AlertColors.CRITICAL
                severity_text = "🔥 Критичный"
            elif severity == 'high':
                color = AlertColors.HIGH
                severity_text = "⚠️ Высокий"
            elif severity == 'warning':
                color = AlertColors.WARNING
                severity_text = "⚠️ Средний"
            else:
                color = AlertColors.INFO
                severity_text = "ℹ️ Инфо"
            
            # Время начала
            starts_at = alert.get('starts_at', '')
            try:
                start_time = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
                time_str = start_time.strftime('%H:%M:%S')
            except:
                time_str = starts_at
            
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Icon(
                            name=ft.icons.CIRCLE,
                            color=ft.colors.RED_400 if alert.get('status') == 'firing' else ft.colors.GREEN_400,
                            size=12,
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text(severity_text, size=12),
                            bgcolor=color + "20",  # Добавляем прозрачность
                            padding=5,
                            border_radius=5,
                        )),
                        ft.DataCell(ft.Text(time_str, size=12)),
                        ft.DataCell(ft.Text(alert.get('name', 'N/A'), weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(alert.get('instance', 'N/A'), size=12)),
                        ft.DataCell(ft.Text(alert.get('description', '')[:50] + "...", size=12)),
                        ft.DataCell(ft.Row([
                            ft.IconButton(
                                icon=ft.icons.CHECK_CIRCLE,
                                tooltip="Принять",
                                on_click=lambda _, aid=alert.get('id'): self.ack_alert(aid),
                                icon_size=20,
                            ),
                            ft.IconButton(
                                icon=ft.cons.OPEN_IN_BROWSER,
                                tooltip="Открыть в Grafana",
                                on_click=lambda _, url=alert.get('generator_url'): self.open_in_browser(url),
                                icon_size=20,
                            ),
                        ])),
                    ],
                )
            )
        
        self.alerts_table.rows = rows
        self.page.update()
    
    def update_stats(self):
        """Обновление статистики"""
        total = len(self.alerts)
        critical = sum(1 for a in self.alerts.values() if a.get('severity', '').lower() == 'critical')
        
        self.alerts_count.value = str(total)
        self.critical_count.value = str(critical)
        
        # Обновляем цвет иконки в трее (если нужно)
        self.update_tray_icon(critical > 0)
    
    def play_sound(self, sound_file: str):
        """Воспроизведение звука"""
        try:
            if os.path.exists(sound_file):
                playsound.playsound(sound_file, block=False)
        except Exception as e:
            print(f"Error playing sound: {e}")
    
    def show_notification(self, alert: dict):
        """Показ системного уведомления"""
        # Для Windows можно использовать win10toast
        # Для macOS - pync
        # Пока просто выводим в консоль
        print(f"\n🔔 ALERT: {alert.get('name')} - {alert.get('description')}")
    
    def ack_alert(self, alert_id: str):
        """Подтверждение получения алерта"""
        self.client.send_ack(alert_id)
        # Можно добавить визуальное подтверждение
        
    def open_in_browser(self, url: str):
        """Открытие URL в браузере"""
        import webbrowser
        webbrowser.open(url)
    
    def filter_alerts(self, e):
        """Фильтрация алертов"""
        # Здесь можно реализовать фильтрацию
        pass
    
    def refresh_alerts(self, e):
        """Принудительное обновление"""
        self.update_alerts_table()
    
    def load_settings(self) -> dict:
        """Загрузка настроек из файла"""
        settings_file = Path("settings.json")
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def save_settings(self):
        """Сохранение настроек в файл"""
        try:
            with open("settings.json", 'w') as f:
                json.dump(self.settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def update_tray_icon(self, has_critical: bool):
        """Обновление иконки в системном трее"""
        # Здесь можно реализовать иконку в трее
        pass

def main():
    """Точка входа в приложение"""
    def run_app(page: ft.Page):
        AlertApp(page)
    
    ft.app(target=run_app)

if __name__ == "__main__":
    main()
