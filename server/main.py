"""
VM-посредник для алертов Grafana/AlertManager
Docker-версия с поддержкой переменных окружения
"""
import os
import json
import asyncio
import logging
from typing import Set, Dict, Any
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'info').upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
HTTP_PORT = int(os.getenv('HTTP_PORT', '8080'))
WS_PORT = int(os.getenv('WS_PORT', '8081'))
HOST = os.getenv('HOST', '0.0.0.0')
ENABLE_AUTH = os.getenv('ENABLE_AUTH', 'false').lower() == 'true'
AUTH_TOKEN = os.getenv('AUTH_TOKEN', '')
MAX_ALERTS = int(os.getenv('MAX_ALERTS', '1000'))
MAX_CONNECTIONS = int(os.getenv('MAX_CONNECTIONS', '100'))

app = FastAPI(title="Grafana Alert Bridge")

# Разрешаем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище активных алертов и подключений
active_alerts: Dict[str, Dict[str, Any]] = {}
active_connections: Set[WebSocket] = set()

# Функция для проверки аутентификации (опционально)
async def verify_token(request: Request):
    if not ENABLE_AUTH:
        return True
    
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True

@app.on_event("startup")
async def startup_event():
    """Действия при запуске"""
    logger.info("=" * 50)
    logger.info("🚀 Grafana Alert Bridge Server starting...")
    logger.info(f"📡 HTTP Webhook: http://{HOST}:{HTTP_PORT}/webhook")
    logger.info(f"🔌 WebSocket: ws://{HOST}:{WS_PORT}/ws")
    logger.info(f"🔐 Authentication: {'enabled' if ENABLE_AUTH else 'disabled'}")
    logger.info(f"📊 Max alerts: {MAX_ALERTS}, Max connections: {MAX_CONNECTIONS}")
    logger.info("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке"""
    logger.info("Shutting down server...")
    # Закрываем все WebSocket соединения
    for connection in active_connections:
        await connection.close()
    active_connections.clear()

@app.post("/webhook")
async def webhook(request: Request, auth: bool = Depends(verify_token)):
    """
    Эндпоинт для приема вебхуков от AlertManager
    """
    try:
        payload = await request.json()
        logger.debug(f"Received webhook payload: {json.dumps(payload)[:500]}")
        
        # Парсим алерты
        alerts = AlertManager.parse_alertmanager_payload(payload)
        
        # Проверяем лимиты
        if len(active_alerts) > MAX_ALERTS:
            logger.warning(f"Alert storage limit reached ({MAX_ALERTS}). Pruning old alerts...")
            # Здесь можно добавить логику очистки старых алертов
        
        for alert in alerts:
            alert_id = alert['id']
            
            # Обновляем хранилище
            if alert['status'] == 'firing':
                active_alerts[alert_id] = alert
                logger.info(f"🔥 ALERT FIRING: {alert['name']} [{alert['severity']}] on {alert['instance']}")
            elif alert['status'] == 'resolved':
                if alert_id in active_alerts:
                    del active_alerts[alert_id]
                    logger.info(f"✅ ALERT RESOLVED: {alert['name']} on {alert['instance']}")
            
            # Рассылаем всем подключенным клиентам
            await broadcast_alert(alert)
        
        # Дополнительно отправляем обновленный список всех алертов
        await broadcast_active_alerts()
        
        return {"status": "ok", "received": len(alerts), "active_alerts": len(active_alerts)}
    
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}, 500

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint для подключения клиентов
    """
    # Проверяем лимит подключений
    if len(active_connections) >= MAX_CONNECTIONS:
        logger.warning(f"Max connections ({MAX_CONNECTIONS}) reached. Rejecting new client.")
        await websocket.close(code=1008, reason="Max connections limit reached")
        return
    
    # Опциональная аутентификация через WebSocket
    if ENABLE_AUTH:
        auth_header = websocket.headers.get('authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else auth_header
        if token != AUTH_TOKEN:
            logger.warning("WebSocket authentication failed")
            await websocket.close(code=1008, reason="Authentication failed")
            return
    
    await websocket.accept()
    active_connections.add(websocket)
    client_id = id(websocket)
    logger.info(f"Client {client_id} connected. Total clients: {len(active_connections)}")
    
    try:
        # Отправляем новому клиенту текущие активные алерты
        await websocket.send_json({
            'type': 'init',
            'alerts': list(active_alerts.values()),
            'timestamp': datetime.now().isoformat()
        })
        
        # Слушаем сообщения от клиента
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_client_message(websocket, message, client_id)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from client {client_id}")
                
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        logger.info(f"Client {client_id} disconnected. Total clients: {len(active_connections)}")
    except Exception as e:
        logger.error(f"Error with client {client_id}: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)

@app.get("/health")
async def health():
    """Проверка здоровья сервера"""
    return {
        "status": "healthy",
        "active_alerts": len(active_alerts),
        "connected_clients": len(active_connections),
        "max_alerts": MAX_ALERTS,
        "max_connections": MAX_CONNECTIONS,
        "uptime": "N/A",  # Можно добавить реальный uptime
        "version": "1.0.0"
    }

@app.get("/metrics")
async def metrics():
    """Метрики для Prometheus (опционально)"""
    return {
        "alert_bridge_active_alerts": len(active_alerts),
        "alert_bridge_connected_clients": len(active_connections),
        "alert_bridge_max_alerts": MAX_ALERTS,
        "alert_bridge_max_connections": MAX_CONNECTIONS
    }

def main():
    """Запуск сервера"""
    # Для продакшна лучше использовать несколько воркеров
    uvicorn.run(
        "main:app",
        host=HOST,
        port=HTTP_PORT,
        log_level=os.getenv('LOG_LEVEL', 'info').lower(),
        workers=int(os.getenv('WORKERS', '1')),
        proxy_headers=True,
        forwarded_allow_ips='*'
    )

if __name__ == "__main__":
    main()
