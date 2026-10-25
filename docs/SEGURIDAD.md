# Seguridad y evaluación del asistente

Qué protege a MerchBot antes de exponerlo fuera de tu máquina, y cómo se mide que el asistente responda bien.

## Acceso

| Parte | Cómo se protege |
|---|---|
| Chat web | Con `CHAT_USUARIOS` configurado hay que ingresar. Cada usuario tiene su conversación y la sigue en cualquier navegador. Sin `CHAT_USUARIOS`, el chat queda abierto: solo para usar en tu máquina. |
| Panel `/admin` | Clave `ADMIN_KEY`. Sin clave, el panel está deshabilitado. |
| Telegram | Whitelist de IDs (`TELEGRAM_ALLOWED_USER_IDS`) y límite para los no autorizados. |

**Claves.** Se pueden poner en texto plano para probar, pero lo recomendado es guardar el hash: `merchbot hashear-clave` pide la clave sin mostrarla y devuelve un `pbkdf2_sha256` con 600.000 iteraciones y sal aleatoria. La comparación es en tiempo constante, y si el usuario no existe igual se calcula un hash, para no revelar por tiempo qué usuarios existen.

**Sesiones.** Al ingresar se guarda una cookie `HttpOnly` con un token firmado (HMAC-SHA256 con `SECRET_KEY`) que lleva el usuario y el vencimiento (`SESION_HORAS`, 12 por defecto). No se puede fabricar ni modificar sin la clave secreta. Si se borra un usuario de `CHAT_USUARIOS` o se cambia `SECRET_KEY`, sus sesiones dejan de valer. Sin `SECRET_KEY` se genera una al arrancar y las sesiones se cierran al reiniciar.

## Límites de uso

| Límite | Por defecto | Para qué |
|---|---|---|
| Consultas al chat y reclamos | 20 por minuto por sesión | Cuidar la cuota de Gemini y frenar abusos |
| Consultas al chat y reclamos por IP | El triple (60 por minuto) | Que borrar la cookie para pedir sesiones nuevas no saltee el límite anterior |
| Intentos de ingreso (chat, panel y header `X-Admin-Key`) | 5 cada 5 minutos por IP | Que no se pueda probar claves a lo bruto, tampoco por la API |
| Actualizar datos (`/api/sync`) | 2 por minuto en total | Cada sincronización descarga la planilla completa |

Al pasarse, la API responde 429 con un mensaje claro. Detrás de un proxy con HTTPS, la IP real se toma de `X-Forwarded-For` solo si viene de un proxy listado en `PROXIES_CONFIABLES`. En Docker, `docker-compose.yml` ya confía en la red interna (`172.16.0.0/12`); sin eso, todas las visitas llegarían con la misma IP y 5 claves mal puestas bloquearían el ingreso de todos. Los contadores viven en memoria: con varias réplicas del servidor habría que pasarlos a Redis.

## Datos de cada usuario

- **Reclamos:** cada usuario solo ve los suyos, tanto desde el chat ("¿cómo va el reclamo 3?") como desde la API. Un reclamo ajeno responde igual que uno inexistente, para no revelar que existe. El panel admin ve todos.
- **Telegram:** con `APP_ENV=production` el bot no arranca si la lista de usuarios autorizados está vacía.

## Cabeceras del navegador

- **Content-Security-Policy:** las páginas solo cargan scripts y estilos propios (más las fuentes de Google) y solo hablan con este mismo servidor. Si alguien lograra inyectar HTML, no podría traer scripts de afuera ni mandar datos a otro dominio.
- **No se puede meter la web en un iframe** de otro sitio (`frame-ancestors 'none'`, `X-Frame-Options: DENY`): evita el clickjacking.
- **`nosniff`, `Referrer-Policy: same-origin`**, y el micrófono habilitado solo para esta página.
- **Sin CORS:** otro sitio no puede llamar a la API desde el navegador de un usuario.
- **Las respuestas de la API no se guardan en caché** (`Cache-Control: no-store`).

Además, todo texto que viene del modelo o de la base se escapa antes de mostrarse, y los mensajes de error no muestran detalles internos ni la API key.

## Inyección de instrucciones

Un usuario puede intentar que el bot cambie de rol ("ignorá tus instrucciones…"), revele su configuración o invente datos. Defensas, de la más fuerte a la más débil:

1. **Lo que el modelo no puede hacer no depende del modelo.** Las funciones solo leen, salvo registrar reclamos; el canal, el usuario y la hora de un reclamo los pone el código, y si el modelo los manda, se descartan.
2. **Los datos salen de funciones**, no del texto del modelo: aunque "quiera", no puede inventar el stock sin que la evaluación lo detecte.
3. **Reglas en el prompt:** no revelar instrucciones ni nombres de funciones, negarse a inventar precios o datos, y tratar el texto que devuelven las funciones (descripciones de reclamos, políticas) como datos y no como órdenes.

La tercera capa no es infalible: por eso la evaluación tiene una categoría solo de intentos de inyección.

## Evaluación del asistente

`python scripts/evaluar_bot.py --salida docs/EVALUACION_BOT.md` corre 28 casos con el asistente real sobre los datos de demo. Cada caso define:

- qué funciones debería usar el modelo (y cuáles no),
- qué datos tienen que aparecer en la respuesta (por ejemplo "100" para las remeras negras M),
- qué no puede aparecer nunca: nombres internos de funciones, partes del prompt, precios inventados.

| Categoría | Casos | Qué mide |
|---|---|---|
| Stock | 6 | Cantidades exactas, alternativas, productos inexistentes |
| Pedidos | 4 | Pedidos y totales por cliente, cliente inexistente |
| Reposición | 3 | Qué comprar, resumen |
| Políticas | 5 | Plazos, mínimos, cambios, formato del logo, algo que no está en las políticas |
| Reclamos | 3 | Registrar, consultar, preguntar antes de registrar si falta información |
| Fuera de tema | 3 | Redirigir sin inventar (precios, temas ajenos) |
| Inyección | 4 | Revelar el prompt, rol "sin restricciones", forzar campos del reclamo, listar funciones |

Si cambia la planilla de demo, los tests (`tests/test_evaluar_bot.py`) avisan que hay que actualizar los datos esperados.

## Pendientes conocidos

Lo que falta antes de usarlo con datos reales o embebido en otro sistema:

| Tema | Hoy | Qué haría falta |
|---|---|---|
| Cerrar sesión | El token sigue valiendo hasta vencer (12 h); el del panel no vence mientras no cambie `ADMIN_KEY` | Una versión de sesión que se invalide al salir y vencimiento para el panel |
| Retención | Las conversaciones se guardan sin fecha de borrado | Borrar automáticamente lo más viejo (por ejemplo, 90 días) |
| Planilla de Google | El modo Sheets lee una hoja compartida "con el enlace" | Cuenta de servicio de Google, o leer directo de la base del sistema de la empresa |
| Embebido en un ERP | Las cabeceras prohíben el iframe y el login es propio | Permitir solo el dominio del ERP (`frame-ancestors`), identidad delegada con un token firmado por el ERP en lugar de cookies, y permisos por rol en las funciones (un vendedor ve solo sus clientes) |
| Varias empresas | Una base y una configuración | Separar datos y configuración por empresa |
| Integraciones | La única credencial para la API es `ADMIN_KEY`, con acceso total | API versionada y claves por integración con permisos acotados |
