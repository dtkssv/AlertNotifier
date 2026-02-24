"""
Desktop приложение для отображения алертов Grafana
Подключается к VM-посреднику через WebSocket
Поддерживает загрузку и выбор пользовательских звуков
"""
import json
import threading
import time
import os
import shutil
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

import flet as ft
from websocket import WebSocketApp
import pygame

# Константы
SOUND_ALERT = "alert.wav"
SOUND_RESOLVED = "resolved.wav"
SOUNDS_DIR = "sounds"  # Директория для хранения пользовательских звуков


class AlertColors:
    """Цвета для разных уровней серьезности"""
    CRITICAL = ft.Colors.RED_500
    HIGH = ft.Colors.ORANGE_500
    WARNING = ft.Colors.YELLOW_700
    INFO = ft.Colors.BLUE_500
    RESOLVED = ft.Colors.GREEN_500


class SoundManager:
    """Менеджер для работы со звуками"""

    def __init__(self):
        self.sounds_dir = Path(SOUNDS_DIR)
        self.sounds_dir.mkdir(exist_ok=True)

        # Инициализируем pygame mixer
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self.pygame_initialized = True
        except Exception as e:
            print(f"Warning: Could not initialize pygame mixer: {e}")
            self.pygame_initialized = False

        # Кэш для загруженных звуков
        self.sound_cache = {}

        # Текущие выбранные звуки
        self.current_alert_sound = "alert.wav"
        self.current_resolved_sound = "resolved.wav"

    def get_available_sounds(self) -> List[str]:
        """Получить список доступных звуков"""
        sounds = ["Без звука", "Системный звук"]

        # Добавляем файлы из директории sounds
        for file in self.sounds_dir.glob("*.wav"):
            sounds.append(file.name)
        for file in self.sounds_dir.glob("*.mp3"):
            sounds.append(file.name)
        for file in self.sounds_dir.glob("*.ogg"):
            sounds.append(file.name)

        return sounds

    def play_sound(self, sound_name: str, block: bool = False):
        """Воспроизвести звук"""
        if sound_name == "Без звука":
            return

        try:
            if sound_name == "Системный звук":
                print('\a')  # ASCII Bell
                return

            if not self.pygame_initialized:
                print('\a')
                return

            sound_path = self.sounds_dir / sound_name
            if sound_path.exists():
                if sound_name not in self.sound_cache:
                    self.sound_cache[sound_name] = pygame.mixer.Sound(str(sound_path))

                channel = self.sound_cache[sound_name].play()

                if block and channel:
                    while channel.get_busy():
                        pygame.time.wait(100)
            else:
                print(f"Sound file not found: {sound_path}")

        except Exception as e:
            print(f"Error playing sound {sound_name}: {e}")
            print('\a')

    def stop_all_sounds(self):
        """Остановить все звуки"""
        if self.pygame_initialized:
            pygame.mixer.stop()

    def preload_sound(self, sound_name: str):
        """Предзагрузить звук в память"""
        if not self.pygame_initialized or sound_name in ["Без звука", "Системный звук"]:
            return
        try:
            sound_path = self.sounds_dir / sound_name
            if sound_path.exists() and sound_name not in self.sound_cache:
                self.sound_cache[sound_name] = pygame.mixer.Sound(str(sound_path))
        except Exception as e:
            print(f"Error preloading sound {sound_name}: {e}")

    def import_sound(self, file_path: str, custom_name: str = None) -> tuple[bool, str]:
        """
        Импортировать звуковой файл
        Возвращает (успех, сообщение/имя файла)
        """
        try:
            src_path = Path(file_path)
            if not src_path.exists():
                return False, "Файл не найден"

            if src_path.suffix.lower() not in ['.wav', '.mp3', '.ogg']:
                return False, "Поддерживаются только .wav, .mp3 и .ogg"

            if custom_name:
                safe_name = "".join(c for c in custom_name if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_name:
                    safe_name = src_path.stem
            else:
                safe_name = src_path.stem

            dest_filename = f"{safe_name}{src_path.suffix}"
            dest_path = self.sounds_dir / dest_filename

            counter = 1
            while dest_path.exists():
                dest_filename = f"{safe_name}_{counter}{src_path.suffix}"
                dest_path = self.sounds_dir / dest_filename
                counter += 1

            shutil.copy2(src_path, dest_path)

            if dest_filename in self.sound_cache:
                del self.sound_cache[dest_filename]

            return True, dest_filename

        except Exception as e:
            return False, str(e)

    def delete_sound(self, sound_name: str) -> bool:
        """Удалить звуковой файл"""
        try:
            if sound_name in ["Без звука", "Системный звук"]:
                return False

            if sound_name in self.sound_cache:
                del self.sound_cache[sound_name]

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
        self.preload_sound(self.current_alert_sound)
        self.preload_sound(self.current_resolved_sound)

    def save_settings(self) -> dict:
        """Сохранить настройки звуков"""
        return {
            'alert_sound': self.current_alert_sound,
            'resolved_sound': self.current_resolved_sound
        }

    def __del__(self):
        if hasattr(self, 'pygame_initialized') and self.pygame_initialized:
            try:
                pygame.mixer.quit()
            except:
                pass


class AlertClient:
    """Клиент для подключения к VM-посреднику"""

    def __init__(self, on_alert_callback, on_connection_change):
        self.ws: Optional[WebSocketApp] = None
        self.connected = False
        self.server_url = ""
        self.on_alert_callback = on_alert_callback
        self.on_connection_change = on_connection_change
        self.should_reconnect = True

    def connect(self, server_url: str):
        self.server_url = server_url
        self.should_reconnect = True
        thread = threading.Thread(target=self._connect_ws, daemon=True)
        thread.start()

    def _connect_ws(self):
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
            if self.should_reconnect:
                time.sleep(5)
                self._connect_ws()

        def on_open(ws):
            print("WebSocket connected!")
            self.connected = True
            self.on_connection_change(True)

        self.ws = WebSocketApp(
            self.server_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        self.ws.run_forever()

    def disconnect(self):
        self.should_reconnect = False
        if self.ws:
            self.ws.close()

    def send_ack(self, alert_id: str):
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
        self.page.update()

    def open(self):
        available_sounds = self.sound_manager.get_available_sounds()

        self.alert_sound_dropdown = ft.Dropdown(
            label="Звук нового алерта",
            options=available_sounds,
            value=self.sound_manager.current_alert_sound,
            width=300,
        )

        self.resolved_sound_dropdown = ft.Dropdown(
            label="Звук разрешенного алерта",
            options=available_sounds,
            value=self.sound_manager.current_resolved_sound,
            width=300,
        )

        self.sounds_list = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
            height=200,
        )
        self.refresh_sounds_list()

        import_btn = ft.FilledButton(
            "Загрузить свой звук",
            icon='upload_file',
            on_click=lambda _: self.import_file_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=['wav', 'mp3', 'ogg']
            )
        )

        stop_sounds_btn = ft.FilledButton(
            "Остановить звуки",
            icon='stop',
            on_click=self.stop_all_sounds,
        )

        test_sound_btn = ft.FilledButton(
            "Тест",
            icon='play_arrow',
            on_click=self.test_sound,
        )

        def save_settings(e):
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
                    ft.Row([self.alert_sound_dropdown, test_sound_btn]),
                    self.resolved_sound_dropdown,
                    ft.Row([stop_sounds_btn]),
                    ft.Divider(),
                    ft.Text("Управление звуками", size=16, weight=ft.FontWeight.BOLD),
                    import_btn,
                    ft.Text("Загруженные звуки:", size=14),
                    self.sounds_list,
                ], tight=True, scroll=ft.ScrollMode.AUTO),
                width=500,
                height=600,
                padding=20,
            ),
            actions=[
                ft.TextButton("Отмена", on_click=cancel),
                ft.FilledButton("Сохранить", on_click=save_settings),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.dialog = self.dialog
        self.dialog.open = True
        self.page.update()

    def on_file_picked(self, e):
        if e.files:
            file_path = e.files[0].path

            def import_with_name(name: str):
                success, result = self.sound_manager.import_sound(file_path, name)
                if success:
                    self.show_snackbar(f"Звук '{result}' успешно загружен")
                    self.refresh_sounds_list()
                    self.update_sound_dropdowns()
                else:
                    self.show_snackbar(f"Ошибка: {result}", error=True)

            self.show_name_dialog(
                "Введите название звука",
                Path(file_path).stem,
                import_with_name
            )

    def show_name_dialog(self, title: str, default_value: str, callback):
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
                ft.FilledButton("ОК", on_click=on_confirm),
            ],
        )

        self.page.dialog = dialog
        dialog.open = True
        self.page.update()

    def refresh_sounds_list(self):
        self.sounds_list.controls.clear()
        for sound in self.sound_manager.get_available_sounds():
            if sound not in ["Без звука", "Системный звук"]:
                self.sounds_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(icon='audio_file', color=ft.Colors.BLUE_400),
                            ft.Text(sound, expand=True),
                            ft.IconButton(
                                icon='play_arrow',
                                tooltip="Тест",
                                on_click=lambda _, s=sound: self.test_specific_sound(s),
                                icon_size=20,
                            ),
                            ft.IconButton(
                                icon='delete',
                                tooltip="Удалить",
                                on_click=lambda _, s=sound: self.delete_sound(s),
                                icon_size=20,
                            ),
                        ]),
                        padding=5,
                        border=ft.border.all(1, ft.Colors.GREY_700),
                        border_radius=5,
                    )
                )
        if not self.sounds_list.controls:
            self.sounds_list.controls.append(
                ft.Text("Нет загруженных звуков", color=ft.Colors.GREY_500, italic=True)
            )
        self.page.update()

    def update_sound_dropdowns(self):
        available_sounds = self.sound_manager.get_available_sounds()
        self.alert_sound_dropdown.options = available_sounds
        self.resolved_sound_dropdown.options = available_sounds
        if self.alert_sound_dropdown.value not in available_sounds:
            self.alert_sound_dropdown.value = "Системный звук"
        if self.resolved_sound_dropdown.value not in available_sounds:
            self.resolved_sound_dropdown.value = "Системный звук"
        self.page.update()

    def test_sound(self, e):
        sound = self.alert_sound_dropdown.value
        self.sound_manager.play_sound(sound, block=True)

    def test_specific_sound(self, sound_name: str):
        self.sound_manager.play_sound(sound_name, block=True)

    def delete_sound(self, sound_name: str):
        if self.sound_manager.delete_sound(sound_name):
            self.show_snackbar(f"Звук '{sound_name}' удален")
            self.refresh_sounds_list()
            self.update_sound_dropdowns()

    def stop_all_sounds(self, e):
        self.sound_manager.stop_all_sounds()
        self.show_snackbar("Все звуки остановлены")

    def show_snackbar(self, message: str, error: bool = False):
        self.page.show_snackbar(
            ft.SnackBar(
                content=ft.Text(message),
                bgcolor=ft.Colors.RED_900 if error else ft.Colors.GREEN_900,
            )
        )


class AlertApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.sound_manager = SoundManager()
        self.client = AlertClient(self.on_alert_received, self.on_connection_changed)
        self.alerts: Dict[str, Dict[str, Any]] = {}
        self.settings = self.load_settings()
        self.current_filter = "Все"  # значение фильтра

        self.sound_manager.load_settings(self.settings)

        self.setup_page()
        self.create_ui()

        if self.settings.get('server_url'):
            self.connect_to_server(self.settings['server_url'])

    def setup_page(self):
        self.page.title = "Grafana Alert Desktop"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 10
        self.page.window_width = 1000
        self.page.window_height = 700
        self.page.window_min_width = 600
        self.page.window_min_height = 400

    def create_ui(self):
        self.connection_status = ft.Icon(
            icon='wifi_off',
            color=ft.Colors.RED_400,
            size=20
        )

        self.server_input = ft.TextField(
            hint_text="ws://localhost:8081/ws",
            value=self.settings.get('server_url', ''),
            width=300,
            height=40,
            border_radius=8
        )

        self.connect_btn = ft.FilledButton(
            "Подключиться",
            icon='link',
            on_click=self.toggle_connection,
            style=ft.ButtonStyle(
                color=ft.Colors.WHITE,
                bgcolor=ft.Colors.BLUE_600,
            )
        )

        settings_btn = ft.IconButton(
            icon='settings',
            tooltip="Настройки",
            on_click=self.open_settings,
        )

        stop_sounds_btn = ft.IconButton(
            icon='stop_circle',
            tooltip="Остановить все звуки",
            on_click=self.stop_all_sounds,
        )

        self.alerts_count = ft.Text("0", size=24, weight=ft.FontWeight.BOLD)
        self.critical_count = ft.Text("0", size=16)

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

        # Фильтр: dropdown + кнопка применения
        self.filter_dropdown = ft.Dropdown(
            options=["Все", "Critical", "High", "Warning"],
            value=self.current_filter,
            width=150,
        )
        apply_filter_btn = ft.IconButton(
            icon='filter_alt',
            tooltip="Применить фильтр",
            on_click=self.apply_filter,
        )

        # Основная компоновка
        self.page.add(
            ft.Container(
                expand=True,  # важно: контейнер занимает всё доступное место
                content=ft.Column([
                    # Шапка
                    ft.Container(
                        content=ft.Row([
                            ft.Row([
                                ft.Icon(icon='notifications_active', size=30, color=ft.Colors.BLUE_400),
                                ft.Text("Grafana Alert Desktop", size=24, weight=ft.FontWeight.BOLD),
                            ]),
                            ft.Row([
                                self.connection_status,
                                self.server_input,
                                self.connect_btn,
                                stop_sounds_btn,
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
                                    ft.Text("Активные алерты", size=14, color=ft.Colors.GREY_400),
                                    self.alerts_count,
                                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=15,
                                border_radius=10,
                                bgcolor=ft.Colors.GREY_900,
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Column([
                                    ft.Text("Критичные", size=14, color=ft.Colors.GREY_400),
                                    self.critical_count,
                                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=15,
                                border_radius=10,
                                bgcolor=ft.Colors.GREY_900,
                                expand=True,
                            ),
                        ], spacing=10),
                        padding=ft.Padding.only(bottom=10),
                    ),

                    # Заголовок таблицы с фильтрами
                    ft.Row([
                        ft.Text("Активные алерты", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            self.filter_dropdown,
                            apply_filter_btn,
                            ft.IconButton(
                                icon='refresh',
                                tooltip="Обновить",
                                on_click=self.refresh_alerts,
                            ),
                        ]),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                    # Таблица с алертами
                    ft.Container(
                        content=ft.Column([self.alerts_table], scroll=ft.ScrollMode.AUTO),
                        height=450,
                        border_radius=10,
                        bgcolor=ft.Colors.GREY_900,
                        padding=10,
                    ),
                ]),
                padding=10,
            )
        )
        self.page.update()  # принудительное обновление страницы

    def open_settings(self, e):
        settings_dialog = SettingsDialog(self.page, self.sound_manager, self.save_sound_settings)
        settings_dialog.open()

    def stop_all_sounds(self, e):
        self.sound_manager.stop_all_sounds()
        self.page.show_snackbar(
            ft.SnackBar(
                content=ft.Text("Все звуки остановлены"),
                bgcolor=ft.Colors.BLUE_900,
            )
        )

    def save_sound_settings(self):
        self.settings.update(self.sound_manager.save_settings())
        self.save_settings()

    def toggle_connection(self, e):
        if not self.client.connected:
            server_url = self.server_input.value
            if server_url:
                self.settings['server_url'] = server_url
                self.save_settings()
                self.connect_to_server(server_url)
        else:
            self.disconnect_from_server()

    def connect_to_server(self, server_url: str):
        if not server_url.endswith('/ws'):
            server_url = server_url.rstrip('/') + '/ws'
        self.client.connect(server_url)
        self.connect_btn.text = "Отключиться"
        self.connect_btn.style.bgcolor = ft.Colors.RED_600
        self.page.update()

    def disconnect_from_server(self):
        self.client.disconnect()
        self.connect_btn.text = "Подключиться"
        self.connect_btn.style.bgcolor = ft.Colors.BLUE_600
        self.connection_status.icon = 'wifi_off'
        self.connection_status.color = ft.Colors.RED_400
        self.page.update()

    def on_connection_changed(self, connected: bool):
        if connected:
            self.connection_status.icon = 'wifi'
            self.connection_status.color = ft.Colors.GREEN_400
        else:
            self.connection_status.icon = 'wifi_off'
            self.connection_status.color = ft.Colors.RED_400
        self.page.update()

    def on_alert_received(self, data: dict):
        alert_type = data.get('type')
        if alert_type in ('init', 'sync'):
            self.alerts = {a['id']: a for a in data.get('alerts', [])}
            self.update_alerts_table()
        elif alert_type == 'alert':
            alert = data.get('data', {})
            alert_id = alert.get('id')
            if alert.get('status') == 'resolved':
                if alert_id in self.alerts:
                    del self.alerts[alert_id]
                    self.sound_manager.play_sound(self.sound_manager.current_resolved_sound)
            else:
                self.alerts[alert_id] = alert
                self.sound_manager.play_sound(self.sound_manager.current_alert_sound)
                self.show_notification(alert)
            self.update_alerts_table()
        self.update_stats()

    def apply_filter(self, e):
        """Применить выбранный фильтр"""
        self.current_filter = self.filter_dropdown.value
        self.update_alerts_table()

    def update_alerts_table(self):
        rows = []
        for alert in self.alerts.values():
            severity = alert.get('severity', 'warning').lower()
            # Фильтрация
            if self.current_filter != "Все" and self.current_filter.lower() != severity:
                continue

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
                            icon='circle',
                            color=ft.Colors.RED_400 if alert.get('status') == 'firing' else ft.Colors.GREEN_400,
                            size=12,
                        )),
                        ft.DataCell(ft.Container(
                            content=ft.Text(severity_text, size=12),
                            bgcolor=color + "20",
                            padding=5,
                            border_radius=5,
                        )),
                        ft.DataCell(ft.Text(time_str, size=12)),
                        ft.DataCell(ft.Text(alert.get('name', 'N/A'), weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(alert.get('instance', 'N/A'), size=12)),
                        ft.DataCell(ft.Text(alert.get('description', '')[:50] + "...", size=12)),
                        ft.DataCell(ft.Row([
                            ft.IconButton(
                                icon='check_circle',
                                tooltip="Принять",
                                on_click=lambda _, aid=alert.get('id'): self.ack_alert(aid),
                                icon_size=20,
                            ),
                            ft.IconButton(
                                icon='open_in_browser',
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
        total = len(self.alerts)
        critical = sum(1 for a in self.alerts.values() if a.get('severity', '').lower() == 'critical')
        self.alerts_count.value = str(total)
        self.critical_count.value = str(critical)
        self.page.update()

    def show_notification(self, alert: dict):
        print(f"\n🔔 ALERT: {alert.get('name')} - {alert.get('description')}")

    def ack_alert(self, alert_id: str):
        self.client.send_ack(alert_id)

    def open_in_browser(self, url: str):
        import webbrowser
        webbrowser.open(url)

    def refresh_alerts(self, e):
        self.update_alerts_table()

    def load_settings(self) -> dict:
        settings_file = Path("settings.json")
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_settings(self):
        try:
            with open("settings.json", 'w') as f:
                json.dump(self.settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def update_tray_icon(self, has_critical: bool):
        pass


def main():
    # Запуск приложения
    ft.app(target=AlertApp)


if __name__ == "__main__":
    main()
