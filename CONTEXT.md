# CONTEXT.md — Sesión de desarrollo

Documento vivo de la sesión: aquí se registra el desarrollo del **agente de IA básico con Groq API key**.

## Visión general

- Proyecto: agente de IA básico para gestión de inventario usando Groq.
- Dos procesos independientes:
  - **API** (FastAPI): `uvicorn api.app:app --reload`
  - **Agente** (CLI): `python agent.py`

## Arquitectura / Esquema de flujo

1. El usuario desde el terminal se comunica con `agent.py`.
2. `agent.py` envía LLM request con **tools** al LLM API (Groq).
3. `agent.py` envía **tool result** inyectado de vuelta al LLM.
4. El LLM devuelve una **tool call decision**.
5. El LLM devuelve la **respuesta final** después de varias iteraciones (empezamos con **5**).
6. El agente hace HTTP call a FastAPI (`api/app.py`), que devuelve un JSON y lee/escribe el archivo `products.csv`.
7. `agent.py` hace append de eventos en `conversation_log.csv`.

```
Usuario (terminal) ──> agent.py ──> LLM API (Groq) ──> tool call decision ──> agent.py
                                     │                                      │
                                     └──── tool result (inyectado) <────────┘
                                          (iteraciones máx. 5)
agent.py ──HTTP──> FastAPI (api/app.py) ──> products.csv / conversation_log.csv
```

## Estructura de archivos

```
api/app.py              # FastAPI app (API de inventario)
agent.py                # Agente CLI
products.csv            # Datos de inventario (runtime)
conversation_log.csv    # Log de eventos (runtime)
.env                    # GROQ_API_KEY (no versionado)
.env.example            # Plantilla de variables de entorno
CONTEXT.md              # Este documento
```

## API de referencia (contracto)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET    | `/inventory`              | Devuelve la lista actual de productos. |
| POST   | `/inventory`              | Crea un producto (campos requeridos: `name`, `quantity`, `unit`). |
| PATCH  | `/inventory/{product_id}` | Aplica delta de stock con signo y valida la existencia del producto. |
| GET    | `/inventory/alerts`       | Devuelve productos por debajo del umbral (umbral por defecto: **10**). |

## Tools del agente (mapeo a API)

| Tool | Llamada HTTP |
|------|--------------|
| `get_inventory`  | `GET /inventory` |
| `create_product` | `POST /inventory` |
| `update_stock`   | `PATCH /inventory/{product_id}` |
| `get_alerts`     | `GET /inventory/alerts` |

## Modo desarrollo

- Se usará **`LLM_fake_response`** para testear el sistema en desarrollo sin depender de la API de Groq.

## Historial de la sesión

- [ ] Crear `CONTEXT.md` con el contexto del proyecto.
- [ ] Definir la API FastAPI (`api/app.py`) según el contracto.
- [ ] Implementar persistencia en `products.csv`.
- [ ] Implementar `agent.py` con bucle de iteraciones (máx. 5).
- [ ] Registrar eventos en `conversation_log.csv`.
- [ ] Implementar `LLM_fake_response` para desarrollo.
- [ ] Integrar Groq (modo producción).
- [ ] Probar flujo completo.
