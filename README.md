# MerchBot

Bot de Telegram que consulta el stock de una empresa de merchandising sublimado en lenguaje natural, usando Google Gemini como motor de IA y un Google Sheets compartido como fuente de verdad.

> Pensado para empresas que ya manejan su inventario en Sheets/Excel y quieren consultarlo desde el celu, sin migrar de sistema ni capacitar a nadie en SQL.

## Demo

```
vos:  cuántas remeras negras M tengo?
bot:  Tenés 100 unidades de Remera Cuello Redondo Negro M.

vos:  qué pidió Coca-Cola?
bot:  Coca-Cola - Evento Verano (15/04):
      • Remera Cuello Redondo Blanco M — 120 unidades
      • Remera Cuello Redondo Blanco L — 80 unidades
      • Gorra Con Respiración Rojo — 40 unidades

vos:  /comprar
bot:  ⚠️ 5 producto(s) por comprar:
      • Gorra Con Respiración Rojo (GOR-RES-ROJ) → faltan 20
      • Remera Dry-Fit Negro M (REM-DF-NEG-M) → faltan 15
      • Taza Mágica (TAZ-MAG) → faltan 10
      ...
      📦 Total a comprar: 60 unidades

vos:  necesito 200 buzos canguro grises L para un evento
bot:  Hoy tenés 30 unidades de Buzo Canguro Gris L. No alcanzan para 200.
      Te paso alternativas con stock disponible:
      • Buzo Canguro Gris XL — 20 unidades
      • Buzo Cuello Redondo Gris L — 50 unidades
```

## Arquitectura

```
┌──────────────────┐         ┌─────────────────┐         ┌──────────────────┐
│  Google Sheets   │◄────────│   Sheets Sync   │────────►│  SQLite local    │
│  (fuente de      │  cada   │   (requests +   │         │  (StockItem +    │
│   verdad)        │  N min  │    csv parser)  │         │   Pedido)        │
└──────────────────┘         └─────────────────┘         └─────────┬────────┘
                                                                    │
                                                                    ▼
┌──────────────────┐         ┌─────────────────┐         ┌──────────────────┐
│   Usuario        │────────►│  Bot Telegram   │────────►│   MerchBot       │
│   (Telegram)     │  msg    │  (handlers +    │  ask()  │   (Gemini 2.5 +  │
│                  │◄────────│   whitelist +   │◄────────│    memoria conv) │
│                  │  resp   │   rate limit)   │  resp   │                  │
└──────────────────┘         └─────────────────┘         └──────────────────┘
```

**Flujo de una consulta:**

1. El usuario escribe al bot en Telegram.
2. El handler chequea autorización (whitelist) y rate limit (anti-spam).
3. Si pasa, llama a `MerchBot.ask(user_id, query)`.
4. `MerchBot` arma el system prompt inyectando: stock actual + pedidos recientes + reglas anti-alucinación.
5. Llama a Gemini con el historial conversacional del usuario (últimos 10 turnos).
6. Devuelve la respuesta y la guarda en memoria.

**Flujo de actualización del stock:**

1. Alguien edita el Google Sheets (carga ingresos, registra pedido).
2. El scheduler hace sync cada N minutos (o un usuario manda `/sync`).
3. El módulo `sheets_sync` descarga el CSV del Sheets, parsea y hace upsert en la DB local.
4. La próxima consulta del bot ya refleja los cambios.

## Stack

| Capa | Tecnología | Por qué |
|---|---|---|
| Lenguaje | Python 3.11 | Madurez de SDKs para Telegram y Gemini |
| LLM | Google Gemini 2.5 Flash | Tier gratuito generoso, 1M tokens de contexto, rápido |
| Bot | python-telegram-bot 21 | Async, mantenido, soporta polling y webhook |
| ORM | SQLAlchemy 2.0 | Type-safe, fácil migración SQLite ↔ Postgres |
| DB | SQLite (dev) / PostgreSQL (prod) | SQLite no requiere instalar nada en dev |
| Sync Sheets | `requests` sobre endpoint público gviz | Sin OAuth, sin Google Cloud, sin service account |
| Scheduler | APScheduler | Background scheduler liviano |
| Config | pydantic-settings | Validación de tipos de env vars |
| Tests | pytest | 59 tests, < 3s de ejecución |

## Estructura del repo

```
merchbot/
├── data/
│   ├── Stock_Merchandising_Demo.xlsx   # template para subir a Google Sheets
│   ├── build_demo_sheets.py            # script que genera el xlsx
│   └── merchbot.db                     # SQLite local (se crea solo)
├── scripts/
│   ├── test_sync.py                    # prueba sync con Sheets sin Telegram
│   └── test_bot_interactive.py         # REPL del bot sin Telegram
├── src/
│   ├── config.py                       # pydantic-settings (lee .env)
│   ├── database.py                     # engine SQLAlchemy
│   ├── models.py                       # StockItem + Pedido (tabla plana)
│   ├── sheets_sync.py                  # lee Sheets, parsea CSV, upsert DB
│   ├── scheduler.py                    # APScheduler para sync periódico
│   ├── rate_limiter.py                 # anti-spam para no autorizados
│   ├── gemini_bot.py                   # MerchBot (cerebro IA)
│   ├── telegram_bot.py                 # handlers + auth + comandos
│   └── main.py                         # entry point
├── tests/
│   ├── conftest.py
│   ├── fixtures/                       # CSVs de ejemplo
│   ├── test_sheets_sync.py
│   ├── test_gemini_bot.py
│   ├── test_telegram_bot.py
│   └── test_rate_limiter.py
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

## Setup local

### 1. Clonar y crear el entorno

```powershell
git clone https://github.com/TU_USUARIO/merchbot.git
cd merchbot

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
```

### 2. Crear el bot de Telegram

1. Hablale a [@BotFather](https://t.me/BotFather) en Telegram.
2. Comando `/newbot`. Te pide nombre y username.
3. Te devuelve un **token** de la forma `1234567890:ABCdefGHIjkl...`. Guardalo.

### 3. Obtener la API key de Gemini

1. Andá a [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Create API key. Copiala.

### 4. Crear el Google Sheets

El bot lee de un Sheets compartido como "Cualquiera con el enlace - Lector".

**Opción A — usar el template:** subí `data/Stock_Merchandising_Demo.xlsx` a tu Google Drive, abrilo con Hojas de Cálculo, y guardalo como Sheets nativo.

**Opción B — adaptar al inventario real:** copiá la estructura del template (2 hojas: `Stock` y `Pedidos`, con las mismas columnas y la fórmula `Stock Actual = Inicial + Ingresos - SUMIF(Pedidos)`).

Después: **Compartir → Cualquiera con el enlace → Lector**. Copiá el ID del Sheets de la URL.

### 5. Configurar variables de entorno

```powershell
copy .env.example .env
```

Editá `.env` y completá:

```
GEMINI_API_KEY=tu_key_de_aistudio
TELEGRAM_BOT_TOKEN=tu_token_de_botfather
SHEETS_ID=el_id_de_tu_sheets
TELEGRAM_ALLOWED_USER_IDS=          # vacío al principio, ver paso 7
```

### 6. Probar el sync (sin Telegram)

```powershell
python scripts/test_sync.py
```

Debe imprimir algo como:

```
✅ Sync OK
• Stock: 37 productos (37 nuevos, 0 actualizados)
• Pedidos: 21 (21 nuevos)
```

### 7. Configurar la whitelist de usuarios

**Importante: si no configurás la whitelist, CUALQUIER persona con el username de tu bot puede usarlo y ver tu stock + clientes.**

Arrancá el bot:

```powershell
python -m src.main
```

En Telegram, hablale al bot y escribí `/whoami`. El bot te devuelve tu ID. Apagá el bot (Ctrl+C), pegá tu ID en `.env`:

```
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Volvé a arrancar. Ya sos el único autorizado. Para sumar usuarios, que cada uno haga `/whoami`, te pasen su ID, agregás separado por coma y reiniciás:

```
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321,555666777
```

### 8. Usar el bot

```
/start    – Bienvenida
/help     – Lista de comandos
/whoami   – Tu ID (público, para pedir acceso)
/sync     – Forzar sincronización con Google Sheets
/comprar  – Listar productos en rojo (stock <= 0)
/resumen  – Resumen ejecutivo
/clear    – Borrar historial de la conversación
```

O escribile en lenguaje natural:

- *"¿cuántas remeras negras M tengo?"*
- *"qué pidió Coca-Cola?"*
- *"necesito 200 buzos grises L para un evento"*
- *"qué tengo en gorras"*

## Tests

```powershell
pytest
```

Esperá ver `59 passed`. Los tests usan SQLite en memoria y mockean Gemini, no consumen cuota.

## Seguridad

- **Autorización por whitelist**: solo los user IDs en `TELEGRAM_ALLOWED_USER_IDS` pueden usar el bot. Sin whitelist configurada, el bot muestra un warning al arrancar.
- **Rate limiting anti-spam**: usuarios no autorizados solo reciben respuesta los primeros `UNAUTH_MAX_ATTEMPTS` intentos en una ventana de `UNAUTH_WINDOW_MINUTES` minutos. Más allá, el bot silencia las respuestas (sigue logueando como WARNING).
- **Logs de auditoría**: cada acceso denegado y cada silenciamiento queda en el log con user_id, username y mensaje truncado para auditoría.
- **Sheets read-only**: el bot NO escribe al Sheets, solo lee. La fuente de verdad sigue siendo Sheets.

## Limitaciones conocidas (v1)

- **Memoria conversacional en RAM**: si el bot se reinicia, se pierde el historial de cada usuario.
- **Sync read-only**: el bot no puede actualizar el Sheets desde Telegram. Para registrar movimientos, hay que editar el Sheets directamente.
- **Catálogo en el prompt**: todo el inventario se inyecta en cada llamada a Gemini. Funciona perfecto hasta ~500 SKUs; más allá conviene migrar a retrieval (RAG).
- **Anti-alucinación basado en prompt**: hay un piso bajo de alucinación gracias al prompt, pero no es cero. Ver "Roadmap".

## Roadmap (v2)

- [ ] **Escritura desde Telegram**: comando `/entrada <SKU> <cantidad>` y `/pedido <cliente> <SKU> <cantidad>` que actualicen el Sheets vía Sheets API (con OAuth o service account).
- [ ] **Multi-tenant**: un solo bot que sirve a varias empresas, cada una con su Sheets y su whitelist.
- [ ] **Deploy 24/7**: Railway o Render con scheduler vivo y memoria persistente en Redis.
- [ ] **Reducir alucinación con multi-agente**: agente clasificador → agente especializado por tipo de consulta (stock / pedidos / recomendación). Cada agente ve solo los datos que necesita.
- [ ] **Function calling**: en vez de inyectar todo el catálogo, exponer funciones tipo `buscar_por_atributos(producto, color, talle)` que Gemini llama él mismo.
- [ ] **Reportes diarios automáticos**: el bot manda al dueño cada mañana qué se vendió ayer, qué entró, qué hay que reponer.
- [ ] **Panel web admin**: una interfaz mínima para que un admin gestione la whitelist y vea logs sin tocar el `.env`.
- [ ] **Tests de carga**: validar comportamiento con 50+ usuarios concurrentes.

## Licencia

MIT
