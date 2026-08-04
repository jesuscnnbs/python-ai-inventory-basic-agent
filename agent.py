import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
USE_FAKE_LLM = os.getenv("USE_FAKE_LLM", "true").lower() in ("true", "1", "yes")

LOG_FILE = os.path.join(os.path.dirname(__file__), "conversation_log.csv")
LOG_FIELDS = ["timestamp", "role", "content"]

MAX_ITERATIONS = 5

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_inventory",
            "description": "Obtiene la lista completa del inventario de productos.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_product",
            "description": "Crea un nuevo producto en el inventario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre del producto"},
                    "quantity": {"type": "integer", "description": "Cantidad inicial"},
                    "unit": {"type": "string", "description": "Unidad de medida (ej: kg, unidades, litros)"},
                },
                "required": ["name", "quantity", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stock",
            "description": "Actualiza el stock de un producto aplicando una variación (positiva o negativa).",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "ID del producto"},
                    "delta": {"type": "integer", "description": "Variación de stock (positivo para añadir, negativo para retirar)"},
                },
                "required": ["product_id", "delta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": "Obtiene los productos con stock por debajo del umbral de alerta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {"type": "integer", "description": "Umbral mínimo de stock (por defecto 10)"},
                },
                "required": [],
            },
        },
    },
]

TOOL_HANDLERS = {
    "get_inventory": lambda **kwargs: httpx.get(f"{API_BASE_URL}/inventory"),
    "create_product": lambda **kwargs: httpx.post(f"{API_BASE_URL}/inventory", json=kwargs),
    "update_stock": lambda **kwargs: httpx.patch(
        f"{API_BASE_URL}/inventory/{kwargs['product_id']}", json={"delta": kwargs["delta"]}
    ),
    "get_alerts": lambda **kwargs: httpx.get(
        f"{API_BASE_URL}/inventory/alerts",
        params={"threshold": kwargs.get("threshold", 10)},
    ),
}


def _log_event(role: str, content: str):
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        timestamp = datetime.now(timezone.utc).isoformat()
        writer.writerow({"timestamp": timestamp, "role": role, "content": content})


def _execute_tool(tool_name: str, arguments: dict) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        result = json.dumps({"error": f"Unknown tool: {tool_name}"})
        _log_event("tool_result", result)
        return result

    try:
        response = handler(**arguments)
        response.raise_for_status()
        result = response.text
    except httpx.HTTPStatusError as e:
        result = json.dumps({"error": f"HTTP {e.response.status_code}", "detail": e.response.text})
    except Exception as e:
        result = json.dumps({"error": str(e)})

    _log_event("tool_result", result)
    return result


def _llm_fake_response(messages: list[dict]) -> dict:
    last_user = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            last_user = msg["content"].lower()
            break

    system_msg = ""
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"].lower()
            break

    last_assistant = ""
    for msg in reversed(messages):
        if msg["role"] == "assistant" and isinstance(msg.get("content"), str) and msg["content"]:
            last_assistant = msg["content"].lower()
            break

    has_tool_results = any(msg["role"] == "tool" for msg in messages)

    if has_tool_results:
        results_text = "\n".join(
            msg.get("content", "") for msg in messages if msg["role"] == "tool"
        )
        return {"role": "assistant", "content": f"Procesé la información del inventario. Resultado: {results_text[:500]}"}

    combined = last_user

    if re.search(r"\b(alerta|bajo|crítico|umbral|poco\s+stock)\b", combined):
        threshold_match = re.search(r"(\d+)", last_user)
        threshold = int(threshold_match.group(1)) if threshold_match else 10
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "fake_call_1",
                    "type": "function",
                    "function": {"name": "get_alerts", "arguments": json.dumps({"threshold": threshold})},
                }
            ],
        }

    if re.search(r"\b(ver|mostrar|lista|consultar|inventario|qué hay|que hay|listar|productos)\b", combined):
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "fake_call_1",
                    "type": "function",
                    "function": {"name": "get_inventory", "arguments": json.dumps({})},
                }
            ],
        }

    if re.search(r"\b(actualizar|modificar|cambiar|aumentar|reducir|disminuir|retirar|quitar|sacar|añadir|agregar\s+(?:al|a)|sumar|restar)\b", combined):
        id_match = re.search(r"(?:producto|id)\s*(\d+)", last_user)
        product_id = int(id_match.group(1)) if id_match else 1

        delta_sign = -1 if re.search(r"\b(reducir|disminuir|retirar|quitar|sacar)\b", last_user) else 1
        qty_match = re.search(r"(\d+)\s*(?:unidades?|kilos?|kg|litros?|l|piezas?)", last_user)
        delta = int(qty_match.group(1)) * delta_sign if qty_match else 5 * delta_sign

        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "fake_call_1",
                    "type": "function",
                    "function": {
                        "name": "update_stock",
                        "arguments": json.dumps({"product_id": product_id, "delta": delta}),
                    },
                }
            ],
        }

    if re.search(r"\b(crear|agregar|nuevo|alta|registrar)\b", combined):
        name_match = re.search(
            r'(?:producto|artículo)\s+(?:llamado|denominado\s+)?["\u201c]?([\w\sáéíóúüñÁÉÍÓÚÜÑ-]+?)["\u201d]?(?:\s|$|,)',
            last_user,
        )
        if not name_match:
            name_match = re.search(
                r'(?:crear|agregar|nuevo|alta)\s+(?:producto\s+)?["\u201c]?([\w\sáéíóúüñÁÉÍÓÚÜÑ-]+?)["\u201d]?(?:\s|$|,)',
                last_user,
            )
        name = name_match.group(1).strip() if name_match else "Producto nuevo"

        qty_match = re.search(r"(\d+)\s*(?:unidades?|kilos?|kg|litros?|l|piezas?)", last_user)
        quantity = int(qty_match.group(1)) if qty_match else 10

        unit_match = re.search(r"(unidades?|kilos?|kg|litros?|l|piezas?)", last_user)
        unit = unit_match.group(1) if unit_match else "unidades"

        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "fake_call_1",
                    "type": "function",
                    "function": {
                        "name": "create_product",
                        "arguments": json.dumps({"name": name, "quantity": quantity, "unit": unit}),
                    },
                }
            ],
        }

    return {
        "role": "assistant",
        "content": "Soy un asistente de inventario. Puedo ayudarte a:\n"
        "- Ver el inventario (ej: 'muéstrame el inventario')\n"
        "- Ver alertas de stock bajo (ej: 'hay alertas?')\n"
        "- Crear productos (ej: 'crear producto Manzanas 50 kg')\n"
        "- Actualizar stock (ej: 'añadir 10 unidades al producto 1')",
    }


def _llm_real_response(client: OpenAI, messages: list[dict]) -> dict:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
    )
    choice = response.choices[0]
    msg = choice.message

    result = {"role": "assistant"}

    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
        result["content"] = msg.content
    else:
        result["content"] = msg.content

    return result


def run():
    print("\n=== Agente de Inventario ===\n")
    user_input = input("Tú: ").strip()

    if not user_input:
        print("No ingresaste ningún mensaje.")
        return

    _log_event("user", user_input)

    system_prompt = (
        "Eres un asistente de gestión de inventario. "
        "Usa las herramientas disponibles para gestionar productos. "
        "Responde siempre en español."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    if USE_FAKE_LLM:
        client = None
    else:
        if not GROQ_API_KEY:
            print("ERROR: GROQ_API_KEY no está configurada en el archivo .env")
            sys.exit(1)
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
        )

    for iteration in range(1, MAX_ITERATIONS + 1):
        if USE_FAKE_LLM:
            llm_response = _llm_fake_response(messages)
        else:
            llm_response = _llm_real_response(client, messages)

        content = llm_response.get("content", "") or ""
        tool_calls = llm_response.get("tool_calls", [])

        messages.append(llm_response)

        if content:
            log_content = content
            if tool_calls:
                log_content = json.dumps({
                    "content": content,
                    "tool_calls": [
                        {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
                        for tc in tool_calls
                    ],
                })
            _log_event("assistant", log_content)

        if not tool_calls:
            print(f"\nAgente: {content}\n")
            return

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            arguments = json.loads(tc["function"]["arguments"])
            print(f"  -> Llamando herramienta: {tool_name}({arguments})")

            result = _execute_tool(tool_name, arguments)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

    print("\nAgente: Alcanzado el límite máximo de iteraciones.")


if __name__ == "__main__":
    run()
