# Reflexión final

*Trabajo final de Técnicas de Procesamiento del Habla — IFTS N°18, 2do cuatrimestre 2026.*

## Qué pide la consigna y dónde está

| Consigna | Cómo lo resuelve MerchBot |
|---|---|
| Interfaz conversacional | Chat web en lenguaje natural (y el bot de Telegram original). También se le puede hablar por voz. |
| Al menos cuatro situaciones cotidianas | Consultar stock, ver los pedidos de un cliente, saber qué hay que reponer, preguntar políticas (cambios, envíos, plazos) y registrar o seguir un reclamo. |
| Simular atención a cualquier hora | Selector de hora en el chat: a las 3 de la mañana el bot responde igual y avisa que lo que necesite a una persona queda para el próximo día hábil. |
| Registro de interacciones o reclamos | Cada consulta queda guardada con hora, canal, tipo y tiempo de respuesta. Los reclamos tienen número, estado y una prioridad calculada según el tono del mensaje. Todo se ve en el panel `/admin`. |
| Lenguaje claro | El asistente responde en español rioplatense, corto y con los datos exactos que sacó de la base. No inventa precios ni datos. |
| Reflexión final | Este documento. |

## El valor de atender las 24 horas

La mayoría de las consultas que llegan a una empresa son repetitivas: ¿hay stock de tal cosa?, ¿en qué quedó mi pedido?, ¿cuánto tarda un envío? Cuando la única forma de responderlas es una persona en horario de oficina, pasan dos cosas: el que pregunta espera, y el que responde gasta su día en contestar lo mismo una y otra vez.

Un chatbot no reemplaza a esa persona, pero sí le saca de encima la parte mecánica. El vendedor que a las 22 hs necesita saber si puede prometerle 100 remeras a un cliente lo sabe en el momento, sin esperar a mañana. El cliente que quiere dejar un reclamo un domingo lo deja, recibe un número y sabe que el lunes alguien lo va a ver. Y el reclamo no entra al final de una pila: si el mensaje es urgente o muy enojado, el sistema lo marca con más prioridad para que se atienda primero.

Para mí ahí está el valor social: **el acceso a la información deja de depender del horario de alguien**. Eso mejora la calidad de vida de los dos lados. El que consulta no queda colgado esperando, y el que trabaja se puede dedicar a lo que de verdad necesita criterio humano: resolver el problema, negociar, decidir.

La voz suma en el mismo sentido. Poder hablarle al bot en vez de escribir ayuda a quien tiene las manos ocupadas en el depósito, a quien escribe con dificultad o a quien simplemente se maneja mejor hablando. Es el tema de la materia aplicado a algo concreto.

## Lo que aprendí haciéndolo

- **El modelo no tiene que saber los datos, tiene que saber buscarlos.** La primera versión le pasaba todo el stock en el prompt. La actual usa *function calling*: el modelo decide qué función llamar y los números salen de la base. Así las respuestas son exactas y verificables.
- **Las políticas de la empresa se consultan, no se memorizan.** Con RAG el bot busca en el documento de políticas el fragmento que corresponde y muestra de qué sección sacó la respuesta.
- **Un chatbot sin registro no se puede mejorar.** Gracias al registro de interacciones se puede ver qué se pregunta, a qué hora, cuánto tarda y dónde falla.
- **Hay que medir, no suponer.** Armé sets de evaluación para el RAG, para el análisis de sentimiento y para el asistente completo (28 casos, incluidos intentos de manipularlo). Sin eso, "anda bien" es una opinión.

## Límites y riesgos

Un chatbot 24/7 también tiene costos y riesgos que hay que decir:

- **Depende de un proveedor externo.** El asistente usa Gemini. Al evaluarlo me quedé sin cuota en el plan gratuito y el bot dejó de responder. Lo mitigué con modelos de respaldo: si uno se agota, sigue con otro. Igual, en un uso real hay que pagar el servicio y tener un plan B.
- **Puede equivocarse.** Que los datos salgan de la base reduce mucho las alucinaciones, pero no las elimina. Por eso el bot no puede modificar stock ni pedidos: lo único que escribe es el reclamo que le piden registrar.
- **No reemplaza el criterio humano.** El bot registra el reclamo y lo prioriza, pero quien lo resuelve es una persona. Si se usara para "sacarse de encima" a los clientes, el valor social se daría vuelta.
- **Privacidad y seguridad.** Las conversaciones quedan guardadas. Por eso hay login, límites de uso, protección contra intentos de manipular al bot y datos de demostración ficticios en el repositorio.

## Hacia dónde podría ir

Hoy MerchBot corre en una computadora local. Ya está preparado con Docker para subirlo a un servidor y que funcione las 24 horas de verdad, pero lo dejé como trabajo futuro. La misma idea sirve para cualquier oficina: un asistente de consulta interno conectado a los sistemas de la empresa, al que cualquiera le pregunta en lenguaje natural en vez de buscar en planillas o esperar a quien sabe la respuesta.
