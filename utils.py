"""
Utilidades compartidas para todas las Lambdas del backend Burger King.
Incluye helpers de respuesta HTTP, acceso a DynamoDB y validación de tokens.
"""

import json
import os
import boto3
from decimal import Decimal


# ---------------------------------------------------------------------------
# Clientes AWS (reutilizables entre invocaciones por el warm-start de Lambda)
# ---------------------------------------------------------------------------
dynamodb = boto3.resource("dynamodb")
events_client = boto3.client("events")
sfn_client = boto3.client("stepfunctions")

# ---------------------------------------------------------------------------
# Variables de entorno
# ---------------------------------------------------------------------------
TABLA_USUARIOS = os.environ.get("TABLA_USUARIOS", "t_usuarios")
TABLA_TOKENS = os.environ.get("TABLA_TOKENS", "t_tokens_acceso")
TABLA_PRODUCTOS = os.environ.get("TABLA_PRODUCTOS", "t_productos")
TABLA_FAVORITOS = os.environ.get("TABLA_FAVORITOS", "t_favoritos")
TABLA_PEDIDOS = os.environ.get("TABLA_PEDIDOS", "t_pedidos")
TABLA_STEP_TOKENS = os.environ.get("TABLA_STEP_TOKENS", "t_step_tokens")
S3_BUCKET = os.environ.get("S3_BUCKET", "burger-king-menu-bucket-dev")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "default")


# ---------------------------------------------------------------------------
# Helper: Serialización Decimal → int/float (DynamoDB usa Decimal)
# ---------------------------------------------------------------------------
class DecimalEncoder(json.JSONEncoder):
    """Codificador JSON que convierte Decimal a int o float."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


# ---------------------------------------------------------------------------
# Helper: Respuestas HTTP estandarizadas con CORS
# ---------------------------------------------------------------------------
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}


def respuesta(status_code: int, body: dict) -> dict:
    """Genera una respuesta HTTP para API Gateway con headers CORS."""
    return {
        "statusCode": status_code,
        "headers": _CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder, ensure_ascii=False),
    }


def obtener_body(event: dict) -> dict:
    """Parsea el body JSON del evento de API Gateway."""
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, str):
        return json.loads(body)
    return body
