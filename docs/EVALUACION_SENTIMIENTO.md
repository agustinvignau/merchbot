# Evaluación del sentimiento de reclamos

Generado con `python scripts/evaluar_sentimiento.py` sobre `data/evaluacion/reclamos_etiquetados.csv` (24 reclamos etiquetados a mano con sentimiento y prioridad esperados).

| Motor | Exactitud sentimiento | F1 macro | Exactitud prioridad |
|---|---|---|---|
| Léxico propio (español) | 88% | 0.90 | 79% |
| VADER (NLTK, léxico en inglés) | 42% | 0.30 | 42% |

## Léxico propio (español)

Matriz de confusión (filas: real; columnas: predicho)

| | NEG | NEU | POS |
|---|---|---|---|
| **NEG** | 13 | 1 | 0 |
| **NEU** | 2 | 6 | 0 |
| **POS** | 0 | 0 | 2 |

Diferencias con lo esperado:

| Reclamo | Sentimiento (esperado → obtenido) | Prioridad (esperada → obtenida) |
|---|---|---|
| Pedí talle L y vinieron todas M | NEG → NEU | media → baja |
| El pedido viene con un día de demora, avisen cuando salga por favor | NEU → NEG | baja → media |
| Sigo esperando el reemplazo de las prendas falladas, ya pasó una semana | NEG → NEG | media → alta |
| El talle XL de las dry-fit vino más chico que la tabla | NEU → NEU | media → baja |
| Les escribo para cambiar el color de las gorras de un pedido que todavía no salió | NEU → NEG | baja → baja |
| Me cobraron envío cuando habíamos quedado en retirar por el depósito | NEG → NEG | media → baja |

## VADER (NLTK, léxico en inglés)

Matriz de confusión (filas: real; columnas: predicho)

| | NEG | NEU | POS |
|---|---|---|---|
| **NEG** | 5 | 8 | 1 |
| **NEU** | 2 | 5 | 1 |
| **POS** | 0 | 2 | 0 |

Diferencias con lo esperado:

| Reclamo | Sentimiento (esperado → obtenido) | Prioridad (esperada → obtenida) |
|---|---|---|
| Llegaron 20 remeras blancas M con manchas de tinta, así no las puedo entregar | NEG → NEG | alta → media |
| Es la segunda vez que me mandan las gorras rojas descosidas. Un desastre. | NEG → NEU | alta → media |
| El pedido para el evento de mañana todavía no llegó, necesito una solución urgente | NEG → NEG | alta → media |
| Me faltan 5 buzos del pedido de Globant | NEG → NEU | media → baja |
| Pedí talle L y vinieron todas M | NEG → POS | media → baja |
| El pedido viene con un día de demora, avisen cuando salga por favor | NEU → POS | baja → baja |
| Quería avisar que una taza llegó con el logo un poco corrido, nada grave | NEU → NEG | baja → media |
| Pésima atención, nadie me responde hace tres días y tengo 300 remeras paradas | NEG → NEU | alta → baja |
| Me mandaron 100 llaveros con el logo de otro cliente!!! Inaceptable | NEG → NEU | alta → media |
| Estoy muy enojado, el estampado se despegó al primer lavado en todas las prendas | NEG → NEU | alta → baja |
| Sigo esperando el reemplazo de las prendas falladas, ya pasó una semana | NEG → NEU | media → baja |
| Gracias por la rapidez, solo aviso que faltó una gorra | POS → NEU | baja → baja |
| Excelente trabajo como siempre, solamente una remera vino con una mancha chiquita | POS → NEU | baja → baja |
| No llegaron los buzos y el evento es hoy a la tarde | NEG → NEG | alta → media |
| El talle XL de las dry-fit vino más chico que la tabla | NEU → NEU | media → baja |
| Faltan 40 tazas del pedido de Movistar, necesitamos que las manden cuanto antes | NEG → NEU | alta → media |
| Les escribo para cambiar el color de las gorras de un pedido que todavía no salió | NEU → NEG | baja → baja |
| Me cobraron envío cuando habíamos quedado en retirar por el depósito | NEG → NEU | media → baja |
