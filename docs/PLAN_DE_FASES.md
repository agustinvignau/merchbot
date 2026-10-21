# MerchBot — Plan de evolución por fases

> Objetivo doble: (1) TP final de *Técnicas de Procesamiento del Habla* (IFTS N°18) y (2) pieza central del portfolio.
> Regla de trabajo: **una fase por vez**. Cada fase termina con algo que corre, tiene tests y se puede mostrar. No se arranca la siguiente hasta cumplir el criterio de "Hecho cuando".

## Fechas de referencia (cursada 2C 2026)

| Fecha | Hito |
|---|---|
| Vie 30/10 | Preentrega del Proyecto Integrador |
| Vie 20/11 | Presentación de proyectos finales |
| Jue 26/11 | Exposición final y cierre |
| Mar 1/12 (00:00) | Cierre de la entrega en el aula |

La entrega final es **presencial con defensa individual**: cada fase tiene que ser algo que puedas explicar con tus palabras.

## Vista general

| Fase | Nombre | Qué suma | Cubre del enunciado | Meta |
|---|---|---|---|---|
| 0 | Base saneada ✅ | Paquete `merchbot`, capa de servicio común, limpieza | — | Hecha 20/10 |
| 1 | Interfaz web + Docker ✅ | Chat en el navegador, deploy local con un comando | Interfaz conversacional | Hecha 20/10 |
| 2 | Registro, hora simulada y reclamos | Tabla de interacciones, selector de hora, `/reclamo` | Registro, cualquier hora, 4+ situaciones | 28/10 |
| 3 | Panel admin con métricas | Dashboard de uso y reclamos | Realismo, valor demostrable | 30/10 (preentrega) |
| 4 | Voz | Hablarle al bot y que responda en voz | Originalidad (tema de la materia) | 05/11 |
| 5 | RAG de políticas | Preguntas frecuentes y procedimientos con embeddings | Guiar al usuario en procedimientos | 11/11 |
| 6 | Sentimiento y prioridad de reclamos | Clasificación con `transformers` | Capacidad de resolver problemas | 15/11 |
| 7 | Evaluación y seguridad | Set de pruebas, login, rate limit web | Coherencia, confiabilidad | 18/11 |
| 8 | Deploy 24/7 y portfolio | VPS, HTTPS, capturas, reflexión final | Valor social 24/7, reflexión | 24/11 |

Las fechas son metas, no promesas: si una fase se alarga, se recorta alcance dentro de la fase, no se salta el criterio de "Hecho cuando".

---

## Fase 0 — Base saneada ✅

> **Hecha el 20/10.** Paquete instalable en `src/merchbot/` (core, data, interfaces, security), `pyproject.toml`, `ChatService`, reportes separados del asistente, fechas con zona horaria, `LICENSE`, `SHEETS_ID` reemplazado por placeholder. 110 tests en verde.

**Objetivo.** Dejar el repo listo para crecer sin romper lo que ya anda.

**Qué se hace**
- Crear la rama `web-ui` (nada se toca en `main` hasta que una fase esté terminada).
- Extraer un `ChatService` (`src/merchbot/core/chat_service.py`) que envuelve `MerchBot.ask()` y queda como **única puerta de entrada** para Telegram y web. Así las dos interfaces comparten lógica.
- Reemplazar `datetime.utcnow()` (deprecado) por fechas con zona horaria.
- Sacar de `.env.example` el `SHEETS_ID` real y poner un placeholder (el repo va a ser público en el portfolio).
- Revisar que `data/merchbot.db` y `.env` no estén versionados.

**Archivos:** `src/merchbot/core/chat_service.py`, `src/merchbot/data/models.py`, `.env.example`, `.gitignore`.

**Hecho cuando**
- `pytest` sigue en verde (hoy 98 tests).
- Telegram funciona igual que antes, pasando por `ChatService`.

**Riesgo:** bajo. Es refactor mínimo.

---

## Fase 1 — Interfaz web + Docker ✅

> **Hecha el 20/10.** FastAPI en `interfaces/web/app.py` con `/api/chat`, historial, atajos sin IA (`/api/comprar`, `/api/resumen`), `/api/sync` y `/health`; chat en un solo HTML; memoria de conversación en la tabla `mensajes`; sesión por cookie; datos de demo desde la planilla (`DATA_SOURCE`); CLI `merchbot web | telegram | cargar-demo`; `Dockerfile` y `docker-compose.yml`. 162 tests en verde.
> Pendiente de verificar: el build de Docker (el entorno donde se construyó no tenía acceso a Docker Hub) y las respuestas reales de Gemini.

**Objetivo.** Salir de Telegram: un chat en el navegador que corre local con un comando y se despliega igual en un VPS.

**Qué se hace**
- Backend **FastAPI** (`src/merchbot/interfaces/web/app.py`) con `POST /api/chat`, `GET /api/historial`, `GET /health`.
- Frontend de un solo archivo (`src/merchbot/interfaces/web/static/index.html`): burbujas de chat, indicador de "escribiendo…", responsive. Sin build ni Node.
- Memoria de conversación persistida en la base (hoy está en RAM y se pierde al reiniciar).
- `Dockerfile` y `docker-compose.yml`; configuración 100% por `.env`.
- Telegram se mantiene como segunda interfaz opcional (`python -m merchbot telegram`).
- Datos de demo desde `data/Stock_Merchandising_Demo.xlsx` para correr sin Google Sheets (agregado durante la fase).

**Archivos nuevos:** `src/merchbot/interfaces/web/app.py`, `src/merchbot/interfaces/web/static/index.html`, `Dockerfile`, `docker-compose.yml`.

**Hecho cuando**
- `docker compose up` levanta el chat en `http://localhost:8000`.
- Una consulta ("¿cuántas remeras negras M tengo?") se responde desde el navegador usando function calling.
- Hay tests de los endpoints (con Gemini mockeado).

**Qué cubre del TP:** interfaz conversacional clara y amigable.

**Riesgo:** bajo-medio. La memoria persistida requiere una tabla nueva (`conversaciones`).

---

## Fase 2 — Registro de interacciones, hora simulada y reclamos

**Objetivo.** Cubrir los tres requisitos que hoy faltan: registro, atención a cualquier hora y reclamos.

**Qué se hace**
- Tabla `interacciones`: id, fecha real, **hora simulada**, usuario, consulta, respuesta, herramientas usadas, duración.
- **Selector de hora simulada** en la UI (mañana / tarde / noche / madrugada, o una hora libre). Se manda con cada mensaje y el bot ajusta el saludo y el contexto ("son las 3:20, el depósito está cerrado…"). Todo queda registrado.
- Tabla `reclamos` y función `registrar_reclamo(descripcion, tipo)` expuesta al modelo, más botón "Registrar reclamo" en la UI.
- Cuatro situaciones diferenciadas y documentadas: **stock, pedidos de un cliente, reposición (qué comprar) y reclamos**.
- Guion de **4 a 5 conversaciones de demo** en distintos horarios (para capturas y para la defensa).

**Archivos:** `src/merchbot/data/models.py` (tablas nuevas), `src/merchbot/core/tools.py` (`registrar_reclamo`), `src/merchbot/core/chat_service.py` (registro), UI.

**Hecho cuando**
- Cada intercambio queda en `interacciones` con hora simulada.
- Un reclamo dicho en lenguaje natural ("me llegó la remera manchada") queda guardado con su tipo.
- Hay un script `scripts/demo_dialogos.py` que reproduce las conversaciones de demo.

**Qué cubre del TP:** registro de interacciones o reclamos, simular atención a cualquier hora, 4+ situaciones.

**Decisión a tomar:** la regla original "el bot nunca escribe" se mantiene para **stock y pedidos**; solo se permite escribir en `interacciones` y `reclamos`. Documentarlo explícitamente.

---

## Fase 3 — Panel admin con métricas

**Objetivo.** Mostrar lo que pasó con los datos: tu fuerte como analista y lo que más impresiona en una demo.

**Qué se hace**
- Ruta `/admin` protegida por clave simple (la seguridad completa llega en la Fase 7).
- Métricas: consultas por hora del día, por tipo de consulta, tiempo medio de respuesta, herramientas más usadas, reclamos por estado.
- Tabla del registro con filtros (fecha, hora simulada, tipo).
- Gráficos con Chart.js (un solo `<script>` de CDN) o SVG propio.

**Hecho cuando**
- Después de correr el guion de demo, el panel muestra la actividad correctamente.
- Los números del panel coinciden con consultas SQL directas (verificación en tests).

**Entregable de la preentrega (30/10):** Fases 1 a 3 funcionando + guion de demo + capturas.

---

## Fase 4 — Voz

**Objetivo.** Hablarle al bot y que responda en voz. Es el diferencial más fuerte para una materia que se llama *Procesamiento del Habla*.

**Qué se hace**
- Botón de micrófono con **Web Speech API** (`SpeechRecognition`, `es-AR`) para dictar la consulta.
- Respuesta en voz con `speechSynthesis`, con botón para silenciar.
- Normalización del texto dictado (números, "ele" → "L", etc.) antes de enviarlo.
- Documento breve que explica cómo conecta con lo visto en clase (reconocimiento y síntesis de voz, Unidad 4).

**Hecho cuando**
- Dictar "cuántos buzos grises talle ele hay" devuelve la respuesta hablada.
- Si el navegador no soporta voz, la UI lo avisa y sigue funcionando por texto.

**Riesgo:** la calidad del reconocimiento depende del navegador (mejor en Chrome) y requiere internet. Se prueba y se documenta la limitación. Como alternativa opcional, Whisper local.

---

## Fase 5 — RAG de políticas

**Objetivo.** Que el bot guíe en procedimientos y responda preguntas frecuentes con conocimiento en texto libre.

**Por qué RAG acá y no sobre el stock:** el stock es dato estructurado y SQL es más preciso que embeddings. RAG se usa donde hay texto libre.

**Qué se hace**
- Documento de políticas ficticio para el TP: plazos de entrega, cambios y devoluciones, guía de talles, cómo hacer un pedido, cómo reclamar, horarios de atención humana.
- Pipeline de ingesta: dividir en fragmentos, generar embeddings con Gemini, guardar en SQLite.
- Búsqueda por similitud de coseno con numpy (sin pgvector, para mantener el deploy simple).
- Nueva función `consultar_politicas(pregunta)` para el modelo. El modelo decide si usar SQL o RAG, y cita el fragmento usado.

**Hecho cuando**
- "¿Cuánto tarda un pedido de 50 buzos?" responde con el plazo del documento y lo cita.
- Una pregunta que no está en el documento responde "no tengo esa información" y no inventa.
- Tests de recuperación (la pregunta correcta trae el fragmento correcto).

**Qué cubre del TP:** guiar al usuario en procedimientos simples.

---

## Fase 6 — Sentimiento y prioridad de reclamos

**Objetivo.** Que cada reclamo se clasifique y se ordene por urgencia.

**Qué se hace**
- Clasificador de sentimiento en español con `transformers` (modelo entrenado en español). VADER de NLTK se evalúa y se documenta por qué no alcanza: está pensado para inglés.
- Clasificación de tipo de reclamo (producto defectuoso, demora, error de pedido, otro).
- Prioridad = sentimiento + palabras clave + antigüedad. El panel ordena por prioridad.
- **Derivación a humano:** si el reclamo es grave o el bot no resuelve, se marca "requiere atención humana".

**Hecho cuando**
- Un set de 20 reclamos de prueba se clasifica con una precisión medida y reportada.
- El panel muestra los reclamos urgentes primero.

**Qué conecta con la cursada:** TP3 (NLTK / sentimiento) y TP4 (BERT).

---

## Fase 7 — Evaluación y seguridad

**Objetivo.** Que sea confiable y que se pueda poner en un VPS público sin riesgo.

**Qué se hace**
- **Set de evaluación**: 25 a 30 preguntas con respuesta esperada (stock, pedidos, políticas, fuera de tema, intentos de inyección de prompt). `scripts/evaluar.py` mide aciertos y guarda un reporte.
- Login simple (usuario y clave en `.env`, sesión con cookie firmada) para el chat y el panel.
- Rate limiting en la API web (reutilizando `rate_limiter.py`).
- Límite de tamaño de mensaje, cabeceras de seguridad, CORS cerrado.
- Revisión de datos sensibles en logs.

**Hecho cuando**
- El reporte de evaluación da un porcentaje de aciertos y lista los fallos.
- Sin login no se accede al chat ni al panel.
- El bot rechaza consultas fuera de tema y no revela el prompt de sistema.

---

## Fase 8 — Deploy 24/7 y portfolio

**Objetivo.** Dejarlo corriendo de verdad y presentable.

**Qué se hace**
- VPS con `docker compose`, Caddy (o nginx) para HTTPS, reinicio automático y backups de la base.
- GitHub Actions: tests en cada push.
- README final con capturas, GIF de la demo y diagrama de arquitectura (ya hay una primera versión en el README).
- **Reflexión final del TP** (cómo la tecnología mejora la calidad de vida y el acceso a la información) y justificación del valor social de la atención 24/7.
- Guion de defensa: qué hace cada módulo y por qué se tomó cada decisión.
- Publicación en el portfolio (agustinvignau.com) con enlace a la demo.

**Hecho cuando**
- La demo pública responde a cualquier hora.
- El repo se clona, se configura el `.env` y levanta con un comando.
- Podés explicar cada decisión técnica sin mirar el código.

---

## Qué NO entra (para no desbordarse)

- Escritura de stock o pedidos desde el bot.
- Multi-empresa (multi-tenant).
- App móvil nativa.
- Fine-tuning de modelos.

## Cómo trabajamos cada fase

1. Se lee la fase y se confirma el alcance.
2. Se implementa en la rama `web-ui` con tests.
3. Se corre `pytest` y se prueba a mano.
4. Se actualiza la tabla de estado del README.
5. Recién ahí pasamos a la siguiente.
