"""
Desktop приложение для отображения алертов Grafana
Подключается к VM-посреднику через WebSocket
Поддерживает загрузку и выбор пользовательских звуков
"""
import json
import threading
import time
import os
import sys
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import hashlib

import flet as ft
from websocket import WebSocketApp
import playsound
from PIL import Image, ImageDraw
import pystray

# Константы
SOUND_ALERT = "alert.wav"
SOUND_RESOLVED = "resolved.wav"
SOUNDS_DIR = "sounds"  # Директория для хранения пользовательских звуков

class AlertColors:
    """Цвета для разных уровней серьезности"""
    CRITICAL = ft.colors.RED_500
    HIGH = ft.colors.ORANGE_500
    WARNING = ft.colors.YELLOW_700
    INFO = ft.colors.BLUE_500
    RESOLVED = ft.colors.GREEN_500

class SoundManager:
    """Менеджер для работы со звуками"""
    
    def __init__(self):
        self.sounds_dir = Path(SOUNDS_DIR)
        self.sounds_dir.mkdir(exist_ok=True)
        
        # Копируем стандартные звуки если их нет
        self._init_default_sounds()
        
        # Текущие выбранные звуки
        self.current_alert_sound = "alert.wav"
        self.current_resolved_sound = "resolved.wav"
        
    def _init_default_sounds(self):
        """Инициализация стандартных звуков"""
        default_sounds = {
            "alert.wav": None,  # Если файла нет, будет использован системный звук
            "resolved.wav": None
        }
        
        # Если стандартных файлов нет, создаем пустые заглушки
        # В реальном проекте можно добавить встроенные звуки
    
    def get_available_sounds(self) -> List[str]:
        """Получить список доступных звуков"""
        sounds = ["Без звука", "Системный звук"]
        
        # Добавляем файлы из директории sounds
        for file in self.sounds_dir.glob("*.wav"):
            sounds.append(file.name)
        for file in self.sounds_dir.glob("*.mp3"):
            sounds.append(file.name)
            
        return sounds
    
    def play_sound(self, sound_name: str, block: bool = False):
        """Воспроизвести звук"""
        if sound_name == "Без звука":
            return
            
        try:
            if sound_name == "Системный звук":
                # Используем системный звук (beep)
                print('\a')  # ASCII Bell
                return
                
            sound_path = self.sounds_dir / sound_name
            if sound_path.exists():
                playsound.playsound(str(sound_path), block=block)
        except Exception as e:
            print(f"Error playing sound {sound_name}: {e}")
    
    def import_sound(self, file_path: str, custom_name: str = None) -> tuple[bool, str]:
        """
        Импортировать звуковой файл
        Возвращает (успех, сообщение/имя файла)
        """
        try:
            src_path = Path(file_path)
            if not src_path.exists():
                return False, "Файл не найден"
            
            # Проверяем расширение
            if src_path.suffix.lower() not in ['.wav', '.mp3']:
                return False, "Поддерживаются только файлы .wav и .mp3"
            
            # Генерируем имя для сохранения
            if custom_name:
                # Очищаем имя от недопустимых символов
                safe_name = "".join(c for c in custom_name if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_name:
                    safe_name = src_path.stem
            else:
                safe_name = src_path.stem
            
            # Добавляем хеш для уникальности (если файл с таким именем уже есть)
            dest_filename = f"{safe_name}{src_path.suffix}"
            dest_path = self.sounds_dir / dest_filename
            
            # Если файл уже существует, добавляем число
            counter = 1
            while dest_path.exists():
                dest_filename = f"{safe_name}_{counter}{src_path.suffix}"
                dest_path = self.sounds_dir / dest_filename
                counter += 1
            
            # Копируем файл
            shutil.copy2(src_path, dest_path)
            
            return True, dest_filename
            
        except Exception as e:
            return False, str(e)
    
    def delete_sound(self, sound_name: str) -> bool:
        """Удалить звуковой файл"""
        try:
            if sound_name in ["Без звука", "Системный звук"]:
                return False
            
            sound_path = self.sounds_dir / sound_name
            if sound_path.exists():
                sound_path.unlink()
                return True
        except Exception as e:
            print(f"Error deleting sound {sound_name}: {e}")
        return False
    
    def load_settings(self, settings: dict):
        """Загрузить настройки звуков"""
        self.current_alert_sound = settings.get('alert_sound', 'alert.wav')
        self.current_resolved_sound = settings.get('resolved_sound', 'resolved.wav')
    
    def save_settings(self) -> dict:
        """Сохранить настройки звуков"""
        return {
            'alert_sound': self.current_alert_sound,
            'resolved_sound': self.current_resolved_sound
        }

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

class SettingsDialog:
    """Диалог настроек приложения"""
    
    def __init__(self, page: ft.Page, sound_manager: SoundManager, on_save_callback):
        self.page = page
        self.sound_manager = sound_manager
        self.on_save_callback = on_save_callback
        self.dialog = None
        self.import_file_picker = ft.FilePicker(on_result=self.on_file_picked)
        self.page.overlay.append(self.import_file_picker)
        
    def open(self):
        """Открыть диалог настроек"""
        
        # Получаем список доступных звуков
        available_sounds = self.sound_manager.get_available_sounds()
        
        # Создаем элементы управления
        self.alert_sound_dropdown = ft.Dropdown(
            label="Звук нового алерта",
            options=[ft.dropdown.Option(sound) for sound in available_sounds],
            value=self.sound_manager.current_alert_sound,
            width=300,
        )
        
        self.resolved_sound_dropdown = ft.Dropdown(
            label="Звук разрешенного алерта",
            options=[ft.dropdown.Option(sound) for sound in available_sounds],
            value=self.sound_manager.current_resolved_sound,
            width=300,
        )
        
        # Список загруженных звуков
        self.sounds_list = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
            height=200,
        )
        self.refresh_sounds_list()
        
        # Кнопка импорта
        import_btn = ft.ElevatedButton(
            "Загрузить свой звук",
            icon=ft.icons.UPLOAD_FILE,
            on_click=lambda _: self.import_file_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=['wav', 'mp3']
            )
        )
        
        # Поле для тестирования звука
        test_sound_btn = ft.ElevatedButton(
            "Тест",
            icon=ft.icons.PLAY_ARROW,
            on_click=self.test_sound,
        )
        
        # Кнопки сохранения/отмены
        def save_settings(e):
            # Сохраняем выбранные звуки
            self.sound_manager.current_alert_sound = self.alert_sound_dropdown.value
            self.sound_manager.current_resolved_sound = self.resolved_sound_dropdown.value
            self.on_save_callback()
            self.dialog.open = False
            self.page.update()
        
        def cancel(e):
            self.dialog.open = False
            self.page.update()
        
        self.dialog = ft.AlertDialog(
            title=ft.Text("Настройки"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Звуковые уведомления", size=16, weight=ft.FontWeight.BOLD),
                    ft.Row([
                        self.alert_sound_dropdown,
                        test_sound_btn,
                    ]),
                    self.resolved_sound_dropdown,
                    ft.Divider(),
                    ft.Text("Управление звуками", size=16, weight=ft.FontWeight.BOLD),
                    import_btn,
                    ft.Text("Загруженные звуки:", size=14),
                    self.sounds_list,
                ], tight=True, scroll=ft.ScrollMode.AUTO),
                width=500,
                height=500,
                padding=20,
            ),
            actions=[
                ft.TextButton("Отмена", on_click=cancel),
                ft.ElevatedButton("Сохранить", on_click=save_settings),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = self.dialog
        self.dialog.open = True
        self.page.update()
    
    def on_file_picked(self, e: ft.FilePickerResultEvent):
        """Обработка выбора файла для импорта"""
        if e.files:
            file_path = e.files[0].path
            
            # Спрашиваем имя для звука
            def import_with_name(name: str):
                success, result = self.sound_manager.import_sound(file_path, name)
                if success:
                    self.show_snackbar(f"Звук '{result}' успешно загружен")
                    self.refresh_sounds_list()
                    self.update_sound_dropdowns()
                else:
                    self.show_snackbar(f"Ошибка: {result}", error=True)
            
            # Показываем диалог для ввода имени
            self.show_name_dialog(
                "Введите название звука",
                Path(file_path).stem,
                import_with_name
            )
    
    def show_name_dialog(self, title: str, default_value: str, callback):
        """Показать диалог ввода имени"""
        name_field = ft.TextField(
            label="Название",
            value=default_value,
            autofocus=True,
        )
        
        def on_confirm(e):
            dialog.open = False
            self.page.update()
            callback(name_field.value)
        
        def on_cancel(e):
            dialog.open = False
            self.page.update()
        
        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=name_field,
            actions=[
                ft.TextButton("Отмена", on_click=on_cancel),
                ft.ElevatedButton("ОК", on_click=on_confirm),
            ],
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def refresh_sounds_list(self):
        """Обновить список загруженных звуков"""
        self.sounds_list.controls.clear()
        
        for sound in self.sound_manager.get_available_sounds():
            if sound not in ["Без звука", "Системный звук"]:
                self.sounds_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.icons.AUDIO_FILE, color=ft.colors.BLUE_400),
                            ft.Text(sound, expand=True),
                            ft.IconButton(
                                icon=ft.icons.PLAY_ARROW,
                                tooltip="Тест",
                                on_click=lambda _, s=sound: self.test_specific_sound(s),
                                icon_size=20,
                            ),
                            ft.IconButton(
                                icon=ft.icons.DELETE,
                                tooltip="Удалить",
                                on_click=lambda _, s=sound: self.delete_sound(s),
                                icon_size=20,
                            ),
                        ]),
                        padding=5,
                        border=ft.border.all(1, ft.colors.GREY_700),
                        border_radius=5,
                    )
                )
        
        if not self.sounds_list.controls:
            self.sounds_list.controls.append(
                ft.Text("Нет загруженных звуков", color=ft.colors.GREY_500, italic=True)
            )
    
    def update_sound_dropdowns(self):
        """Обновить выпадающие списки звуков"""
        available_sounds = self.sound_manager.get_available_sounds()
        
        self.alert_sound_dropdown.options = [ft.dropdown.Option(s) for s in available_sounds]
        self.resolved_sound_dropdown.options = [ft.dropdown.Option(s) for s in available_sounds]
        
        # Проверяем, что текущие значения все еще доступны
        if self.alert_sound_dropdown.value not in available_sounds:
            self.alert_sound_dropdown.value = "Системный звук"
        if self.resolved_sound_dropdown.value not in available_sounds:
            self.resolved_sound_dropdown.value = "Системный звук"
    
    def test_sound(self, e):
        """Тест выбранного звука"""
        sound = self.alert_sound_dropdown.value
        self.sound_manager.play_sound(sound, block=True)
    
    def test_specific_sound(self, sound_name: str):
        """Тест конкретного звука"""
        self.sound_manager.play_sound(sound_name, block=True)
    
    def delete_sound(self, sound_name: str):
        """Удалить звук"""
        if self.sound_manager.delete_sound(sound_name):
            self.show_snackbar(f"Звук '{sound_name}' удален")
            self.refresh_sounds_list()
            self.update_sound_dropdowns()
    
    def show_snackbar(self, message: str, error: bool = False):
        """Показать всплывающее сообщение"""
        self.page.show_snackbar(
            ft.SnackBar(
                content=ft.Text(message),
                bgcolor=ft.colors.RED_900 if error else ft.colors.GREEN_900,
            )
        )

class AlertApp:
    """Основное GUI приложение"""
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.sound_manager = SoundManager()
        self.client = AlertClient(self.on_alert_received, self.on_connection_changed)
        self.alerts: Dict[str, Dict[str, Any]] = {}
        self.settings = self.load_settings()
        
        # Загружаем настройки звуков
        self.sound_manager.load_settings(self.settings)
        
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
        
        # Кнопка настроек
        settings_btn = ft.IconButton(
            icon=ft.icons.SETTINGS,
            tooltip="Настройки",
            on_click=self.open_settings,
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
                                settings_btn,
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
    
    def open_settings(self, e):
        """Открыть окно настроек"""
        settings_dialog = SettingsDialog(self.page, self.sound_manager, self.save_sound_settings)
        settings_dialog.open()
    
    def save_sound_settings(self):
        """Сохранить настройки звуков"""
        self.settings.update(self.sound_manager.save_settings())
        self.save_settings()
    
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
            self.connection_status.name = ft.icons.WIFI
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
                    # Воспроизводим звук разрешения
                    self.sound_manager.play_sound(self.sound_manager.current_resolved_sound)
            else:
                self.alerts[alert_id] = alert
                # Воспроизводим звук нового алерта
                self.sound_manager.play_sound(self.sound_manager.current_alert_sound)
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
                                icon=ft.icons.OPEN_IN_BROWSER,
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
