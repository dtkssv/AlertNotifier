// AlertBridge Web Client JavaScript

class AlertBridgeClient {
    constructor() {
        this.ws = null;
        this.connected = false;
        this.bridgeConnected = false;
        this.alerts = [];
        this.sounds = [];
        this.settings = {
            bridgeServerUrl: document.getElementById('server-url').value,
            alertSound: 'alert.wav',
            resolvedSound: 'resolved.wav',
            volume: 70,
            autoConnect: true,
            showNotifications: true,
        };
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 3000;
        
        this.initEventListeners();
        this.loadSettings();
        this.connectWebSocket();
    }
    
    initEventListeners() {
        document.getElementById('connect-btn').addEventListener('click', () => this.toggleConnection());
        document.getElementById('settings-btn').addEventListener('click', () => this.openSettings());
        document.getElementById('stop-sounds-btn').addEventListener('click', () => this.stopAllSounds());
        document.getElementById('refresh-btn').addEventListener('click', () => this.refreshAlerts());
        document.getElementById('severity-filter').addEventListener('change', () => this.filterAlerts());
        
        // Settings modal
        document.getElementById('settings-cancel-btn').addEventListener('click', () => this.closeSettings());
        document.getElementById('settings-save-btn').addEventListener('click', () => this.saveSettings());
        document.getElementById('choose-file-btn').addEventListener('click', () => this.chooseFile());
        document.getElementById('sound-file-input').addEventListener('change', (e) => this.fileSelected(e));
        
        // Close modal on outside click
        document.getElementById('settings-modal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.closeSettings();
        });
    }
    
    connectWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws/alerts/`;
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.connected = true;
            this.updateConnectionUI();
            this.sendMessage({ type: 'get_alerts' });
            this.sendMessage({ type: 'get_sounds' });
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.connected = false;
            this.bridgeConnected = false;
            this.updateConnectionUI();
            
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                setTimeout(() => this.connectWebSocket(), this.reconnectDelay);
            }
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };
    }
    
    handleMessage(data) {
        switch (data.type) {
            case 'connection':
                console.log('Bridge connection:', data.message);
                break;
            case 'status':
                this.bridgeConnected = data.connected_to_bridge;
                this.updateConnectionUI();
                break;
            case 'alert':
                this.addOrUpdateAlert(data.data);
                break;
            case 'alerts_list':
                this.alerts = data.alerts;
                this.renderAlerts();
                break;
            case 'sounds_list':
                this.sounds = data.sounds;
                this.updateSoundsUI();
                break;
            case 'bridge.message':
                // Handle messages from bridge server
                if (data.message.type === 'alert') {
                    this.addOrUpdateAlert(data.message.data);
                }
                break;
            default:
                console.log('Unknown message type:', data.type);
        }
    }
    
    sendMessage(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    }
    
    toggleConnection() {
        const btn = document.getElementById('connect-btn');
        const span = btn.querySelector('span');
        const icon = btn.querySelector('i');
        
        if (this.connected) {
            // Disconnect logic (close WebSocket)
            this.ws.close();
        } else {
            // Reconnect
            this.reconnectAttempts = 0;
            this.connectWebSocket();
        }
    }
    
    updateConnectionUI() {
        const statusDiv = document.getElementById('connection-status');
        const icon = statusDiv.querySelector('i');
        const text = statusDiv.querySelector('span');
        const btn = document.getElementById('connect-btn');
        const btnSpan = btn.querySelector('span');
        
        if (this.connected) {
            if (this.bridgeConnected) {
                icon.className = 'fas fa-wifi text-green-500';
                text.textContent = 'Подключено к Bridge';
            } else {
                icon.className = 'fas fa-wifi text-yellow-500';
                text.textContent = 'Подключено, ожидание Bridge';
            }
            btnSpan.textContent = 'Отключиться';
            btn.classList.remove('bg-blue-600', 'hover:bg-blue-700');
            btn.classList.add('bg-red-600', 'hover:bg-red-700');
        } else {
            icon.className = 'fas fa-wifi text-red-500';
            text.textContent = 'Отключено';
            btnSpan.textContent = 'Подключиться';
            btn.classList.remove('bg-red-600', 'hover:bg-red-700');
            btn.classList.add('bg-blue-600', 'hover:bg-blue-700');
        }
    }
    
    addOrUpdateAlert(alert) {
        const index = this.alerts.findIndex(a => a.id === alert.id);
        if (index !== -1) {
            if (alert.status === 'resolved') {
                this.alerts.splice(index, 1);
                this.playSound(this.settings.resolvedSound);
            } else {
                this.alerts[index] = alert;
            }
        } else {
            if (alert.status === 'firing') {
                this.alerts.push(alert);
                this.playSound(this.settings.alertSound);
                this.showNotification('Новый алерт', alert);
            }
        }
        this.renderAlerts();
        this.updateStats();
    }
    
    renderAlerts() {
        const tbody = document.getElementById('alerts-table-body');
        const filter = document.getElementById('severity-filter').value;
        
        let filteredAlerts = this.alerts;
        if (filter !== 'all') {
            filteredAlerts = this.alerts.filter(a => a.severity === filter);
        }
        
        if (filteredAlerts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-gray-500">Нет активных алертов</td></tr>`;
            return;
        }
        
        tbody.innerHTML = filteredAlerts.map(alert => {
            const severityClass = `severity-${alert.severity}`;
            const time = alert.starts_at ? new Date(alert.starts_at).toLocaleTimeString() : '';
            
            return `
            <tr class="hover:bg-gray-700">
                <td class="px-4 py-3">
                    <i class="fas fa-circle text-${alert.status === 'firing' ? 'red' : 'green'}-500 text-xs"></i>
                </td>
                <td class="px-4 py-3">
                    <span class="px-2 py-1 rounded text-xs ${severityClass}">
                        ${alert.severity}
                    </span>
                </td>
                <td class="px-4 py-3 text-sm">${time}</td>
                <td class="px-4 py-3 font-medium">${alert.name}</td>
                <td class="px-4 py-3 text-sm">${alert.instance}</td>
                <td class="px-4 py-3 text-sm text-gray-400">${alert.description || ''}</td>
                <td class="px-4 py-3">
                    <button class="ack-btn text-green-500 hover:text-green-400 mr-2" data-id="${alert.id}">
                        <i class="fas fa-check-circle"></i>
                    </button>
                    ${alert.generator_url ? `
                    <button class="open-url-btn text-blue-500 hover:text-blue-400" data-url="${alert.generator_url}">
                        <i class="fas fa-external-link-alt"></i>
                    </button>
                    ` : ''}
                </td>
            </tr>
            `;
        }).join('');
        
        // Add event listeners to buttons
        document.querySelectorAll('.ack-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = e.currentTarget.dataset.id;
                this.acknowledgeAlert(id);
            });
        });
        
        document.querySelectorAll('.open-url-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const url = e.currentTarget.dataset.url;
                window.open(url, '_blank');
            });
        });
    }
    
    updateStats() {
        const total = this.alerts.length;
        const critical = this.alerts.filter(a => a.severity === 'critical').length;
        
        document.getElementById('total-alerts').textContent = total;
        document.getElementById('critical-alerts').textContent = critical;
    }
    
    filterAlerts() {
        this.renderAlerts();
    }
    
    refreshAlerts() {
        this.sendMessage({ type: 'get_alerts' });
        this.showSnackbar('Список обновлен');
    }
    
    acknowledgeAlert(alertId) {
        fetch(`/api/alerts/${alertId}/ack/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.getCSRFToken(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showSnackbar('Алерт принят');
            }
        })
        .catch(error => console.error('Error acknowledging alert:', error));
    }
    
    playSound(soundName) {
        if (!soundName || soundName === 'Без звука') return;
        
        if (soundName === 'Системный звук') {
            this.systemBeep();
            return;
        }
        
        const sound = this.sounds.find(s => s.name === soundName);
        if (sound && sound.url) {
            const audio = new Audio(sound.url);
            audio.volume = this.settings.volume / 100;
            audio.play().catch(e => console.log('Audio play failed:', e));
        }
    }
    
    systemBeep() {
        try {
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();
            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            oscillator.frequency.value = 800;
            gainNode.gain.value = 0.1;
            oscillator.start();
            oscillator.stop(audioCtx.currentTime + 0.1);
        } catch (e) {
            console.log('Beep error:', e);
        }
    }
    
    stopAllSounds() {
        const audios = document.getElementsByTagName('audio');
        for (let audio of audios) {
            audio.pause();
            audio.currentTime = 0;
        }
        this.showSnackbar('Все звуки остановлены');
    }
    
    showNotification(title, alert) {
        if (!this.settings.showNotifications) return;
        
        if (Notification.permission === 'granted') {
            new Notification(title, {
                body: `${alert.name} - ${alert.instance}`,
                icon: '/static/favicon.ico',
            });
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission();
        }
    }
    
    // Settings methods
    async openSettings() {
        // Load current settings
        const response = await fetch('/api/settings/');
        const data = await response.json();
        this.settings = { ...this.settings, ...data };
        
        // Populate UI
        document.getElementById('bridge-url-input').value = this.settings.bridgeServerUrl;
        document.getElementById('auto-connect-checkbox').checked = this.settings.autoConnect;
        document.getElementById('show-notifications-checkbox').checked = this.settings.showNotifications;
        document.getElementById('volume-slider').value = this.settings.notification_volume;
        
        // Update sound dropdowns
        this.updateSoundDropdowns();
        
        document.getElementById('settings-modal').classList.remove('hidden');
    }
    
    closeSettings() {
        document.getElementById('settings-modal').classList.add('hidden');
    }
    
    async saveSettings() {
        const newSettings = {
            bridgeServerUrl: document.getElementById('bridge-url-input').value,
            autoConnect: document.getElementById('auto-connect-checkbox').checked,
            showNotifications: document.getElementById('show-notifications-checkbox').checked,
            notificationVolume: parseInt(document.getElementById('volume-slider').value),
            alertSound: document.getElementById('alert-sound-select').value,
            resolvedSound: document.getElementById('resolved-sound-select').value,
        };
        
        const response = await fetch('/api/settings/update/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.getCSRFToken(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(newSettings),
        });
        
        const data = await response.json();
        if (data.success) {
            this.settings = { ...this.settings, ...newSettings };
            this.showSnackbar('Настройки сохранены');
            this.closeSettings();
            
            // Reconnect if bridge URL changed
            if (this.settings.bridgeServerUrl !== document.getElementById('server-url').value) {
                document.getElementById('server-url').value = this.settings.bridgeServerUrl;
                // TODO: reconnect bridge connection
            }
        } else {
            this.showSnackbar('Ошибка сохранения', true);
        }
    }
    
    updateSoundDropdowns() {
        const alertSelect = document.getElementById('alert-sound-select');
        const resolvedSelect = document.getElementById('resolved-sound-select');
        
        const options = ['Без звука', 'Системный звук', ...this.sounds.map(s => s.name)];
        
        alertSelect.innerHTML = options.map(opt => 
            `<option value="${opt}" ${opt === this.settings.alertSound ? 'selected' : ''}>${opt}</option>`
        ).join('');
        
        resolvedSelect.innerHTML = options.map(opt => 
            `<option value="${opt}" ${opt === this.settings.resolvedSound ? 'selected' : ''}>${opt}</option>`
        ).join('');
    }
    
    updateSoundsUI() {
        const container = document.getElementById('sounds-list');
        container.innerHTML = this.sounds.map(sound => `
            <div class="flex items-center justify-between bg-gray-700 p-2 rounded">
                <span class="text-sm">${sound.name}</span>
                <div>
                    <button class="play-sound-btn text-green-500 hover:text-green-400 mr-2" data-name="${sound.name}">
                        <i class="fas fa-play"></i>
                    </button>
                    ${!sound.is_default ? `
                    <button class="delete-sound-btn text-red-500 hover:text-red-400" data-id="${sound.id}">
                        <i class="fas fa-trash"></i>
                    </button>
                    ` : ''}
                </div>
            </div>
        `).join('');
        
        // Add event listeners
        document.querySelectorAll('.play-sound-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const name = e.currentTarget.dataset.name;
                this.playSound(name);
            });
        });
        
        document.querySelectorAll('.delete-sound-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const id = e.currentTarget.dataset.id;
                this.deleteSound(id);
            });
        });
        
        this.updateSoundDropdowns();
    }
    
    chooseFile() {
        document.getElementById('sound-file-input').click();
    }
    
    fileSelected(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        document.getElementById('selected-file-name').textContent = file.name;
        
        // Ask for custom name
        const customName = prompt('Введите название для звука (оставьте пустым для имени файла):', file.name.split('.')[0]);
        if (customName === null) return;
        
        this.uploadSound(file, customName || file.name.split('.')[0]);
    }
    
    async uploadSound(file, customName) {
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64Data = e.target.result;
            
            const response = await fetch('/api/sounds/upload/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken(),
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    file: base64Data,
                    name: file.name,
                    custom_name: customName,
                }),
            });
            
            const data = await response.json();
            if (data.success) {
                this.sounds.push(data.sound);
                this.updateSoundsUI();
                this.showSnackbar('Звук загружен');
            } else {
                this.showSnackbar('Ошибка загрузки: ' + data.error, true);
            }
        };
        reader.readAsDataURL(file);
    }
    
    async deleteSound(soundId) {
        if (!confirm('Удалить этот звук?')) return;
        
        const response = await fetch(`/api/sounds/${soundId}/delete/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.getCSRFToken(),
            },
        });
        
        const data = await response.json();
        if (data.success) {
            this.sounds = this.sounds.filter(s => s.id !== soundId);
            this.updateSoundsUI();
            this.showSnackbar('Звук удален');
        } else {
            this.showSnackbar('Ошибка удаления', true);
        }
    }
    
    loadSettings() {
        // Load from localStorage or defaults
        const saved = localStorage.getItem('alertbridge-settings');
        if (saved) {
            try {
                this.settings = JSON.parse(saved);
            } catch (e) {}
        }
    }
    
    saveSettingsToStorage() {
        localStorage.setItem('alertbridge-settings', JSON.stringify(this.settings));
    }
    
    showSnackbar(message, isError = false) {
        const snackbar = document.createElement('div');
        snackbar.className = 'snackbar';
        snackbar.style.backgroundColor = isError ? '#dc2626' : '#1f2937';
        snackbar.textContent = message;
        document.body.appendChild(snackbar);
        
        setTimeout(() => {
            snackbar.remove();
        }, 3000);
    }
    
    getCSRFToken() {
        const name = 'csrftoken';
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [key, value] = cookie.trim().split('=');
            if (key === name) return value;
        }
        return '';
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new AlertBridgeClient();
});