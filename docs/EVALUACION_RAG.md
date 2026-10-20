# Evaluación del RAG de políticas

Generado con `python scripts/evaluar_rag.py`. Preguntas escritas como las haría un usuario, sin copiar las palabras del documento (22 con respuesta en las políticas y 3 fuera de tema).

| Método | Acierto@1 | Acierto@3 | MRR | Rechaza lo fuera de tema |
|---|---|---|---|---|
| Léxica (BM25 + sinónimos) | 73% | 95% | 0.82 | 100% |

## Léxica (BM25 + sinónimos)

| Pregunta | Esperada | Primera devuelta | |
|---|---|---|---|
| ¿Cuántos días tarda un pedido de 80 remeras? | Plazos de producción y entrega | Guía de talles | 🟡 |
| Si encargo 600 buzos, ¿para cuándo los tengo? | Plazos de producción y entrega | Guía de talles | 🟡 |
| ¿Hacen trabajos urgentes para pasado mañana? | Plazos de producción y entrega | Envíos y retiro | 🟡 |
| ¿Puedo pedir solo 5 remeras con mi logo? | Pedido mínimo | Archivos de diseño | 🟡 |
| ¿Cuál es la cantidad mínima de tazas? | Pedido mínimo | Pedido mínimo | ✅ |
| ¿Puedo mezclar talles en un mismo pedido? | Pedido mínimo | Pedido mínimo | ✅ |
| Me llegaron prendas con la impresión corrida, ¿me las cambian? | Cambios y devoluciones | Cambios y devoluciones | ✅ |
| ¿Cuántos días tengo para avisar de una falla? | Cambios y devoluciones | Cambios y devoluciones | ✅ |
| Una remera lisa me quedó chica, ¿la puedo cambiar? | Cambios y devoluciones | Cambios y devoluciones | ✅ |
| ¿Qué ancho de pecho tiene una remera L? | Guía de talles | Guía de talles | ✅ |
| Las dry-fit, ¿vienen chicas? | Guía de talles | Guía de talles | ✅ |
| ¿Sirve si les mando el logo en JPG que bajé de Instagram? | Archivos de diseño | Archivos de diseño | ✅ |
| ¿Respetan los colores Pantone? | Archivos de diseño | Archivos de diseño | ✅ |
| ¿Me lo pueden mandar a Córdoba? | Envíos y retiro | Envíos y retiro | ✅ |
| ¿Puedo pasar a buscar el pedido por el depósito? | Envíos y retiro | Envíos y retiro | ✅ |
| ¿Se puede meter en el secarropas una remera sublimada? | Cuidado de las prendas sublimadas | Cuidado de las prendas sublimadas | ✅ |
| ¿El estampado se despega con los lavados? | Cuidado de las prendas sublimadas | Cuidado de las prendas sublimadas | ✅ |
| ¿Atienden los sábados? | Horarios de atención | Horarios de atención | ✅ |
| ¿Qué pasos tengo que seguir para encargar remeras con mi marca? | Cómo hacer un pedido | Pedido mínimo | 🟡 |
| ¿Cuándo queda confirmado mi pedido? | Cómo hacer un pedido | Cómo hacer un pedido | ✅ |
| ¿En cuánto tiempo me responden un reclamo? | Reclamos | Reclamos | ✅ |
| ¿Puedo ver cómo queda una prenda antes de encargar 300? | Muestras | Cómo hacer un pedido | ❌ |
| ¿Quién ganó el último mundial? | (ninguna) | (ninguna) | ✅ |
| Pasame una receta de empanadas | (ninguna) | (ninguna) | ✅ |
| ¿Cuál es la capital de Francia? | (ninguna) | (ninguna) | ✅ |

✅ primera posición · 🟡 entre las 3 primeras · ❌ no aparece o respondió algo fuera de tema.
