"""
Lambda: Crear_Pedido
Rutas:  POST /pedidos/web   (Protegida por Token - Custom Authorizer)
        POST /pedidos/rappi  (Protegida por API Key nativa)
Módulo: core_pedidos/

Maneja DOS rutas con comportamientos distintos desde un único handler.

Ruta Web:
  Entrada (Body): items (lista de {producto_id, cantidad})
  Lógica:  Calcula total desde t_productos. Estado = PENDIENTE_PAGO. Origen = web.
  Salida:  pedido_id, total, estado

Ruta Rappi:
  Entrada (Body): origen, codigo_pedido_ext, cliente_nombre, items, total_pagado
  Lógica:  Estado = PAGADO_EXTERNO. Dispara evento PedidoRappiRecibido a EventBridge.
  Salida:  mensaje, pedido_id_bk, estado_actual, tiempo_estimado_minutos
"""

import uuid
import json
from decimal import Decimal

from utils import (
    dynamodb,
    events_client,
    TABLA_PRODUCTOS,
    TABLA_PEDIDOS,
    EVENT_BUS_NAME,
    respuesta,
    obtener_body,
    DecimalEncoder,
)

# Tiempo estimado por defecto para pedidos Rappi (en minutos)
_TIEMPO_ESTIMADO_MINUTOS = 25


def _calcular_total(items: list) -> tuple:
    """
    Calcula el total del pedido leyendo precios desde t_productos.
    Retorna (total, items_detalle) o lanza ValueError si hay un producto inválido.
    """
    tabla_productos = dynamodb.Table(TABLA_PRODUCTOS)
    total = Decimal("0")
    items_detalle = []

    for item in items:
        producto_id = item.get("producto_id", "").strip()
        cantidad = item.get("cantidad", 0)

        if not producto_id or not isinstance(cantidad, int) or cantidad <= 0:
            raise ValueError(f"Item inválido: producto_id='{producto_id}', cantidad={cantidad}")

        resultado = tabla_productos.get_item(Key={"producto_id": producto_id})
        producto = resultado.get("Item")

        if not producto:
            raise ValueError(f"Producto '{producto_id}' no encontrado.")

        precio_unitario = Decimal(str(producto["precio"]))
        subtotal = precio_unitario * cantidad

        items_detalle.append({
            "producto_id": producto_id,
            "nombre": producto.get("nombre"),
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
            "subtotal": subtotal,
        })

        total += subtotal

    return total, items_detalle


def _handler_web(event, body):
    """Lógica para POST /pedidos/web — Pedidos desde la app/web propia."""

    # --- Extraer usuario_id del context del authorizer ---
    request_context = event.get("requestContext", {})
    authorizer_context = request_context.get("authorizer", {})
    usuario_id = authorizer_context.get("usuario_id", "")

    if not usuario_id:
        return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

    # --- Validar items ---
    items = body.get("items", [])
    if not items or not isinstance(items, list):
        return respuesta(400, {
            "mensaje": "El campo 'items' es obligatorio y debe ser una lista."
        })

    # --- Calcular total ---
    try:
        total, items_detalle = _calcular_total(items)
    except ValueError as e:
        return respuesta(400, {"mensaje": str(e)})

    # --- Crear pedido ---
    pedido_id = str(uuid.uuid4())
    tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)

    tabla_pedidos.put_item(Item={
        "pedido_id": pedido_id,
        "usuario_id": usuario_id,
        "items": items_detalle,
        "total": total,
        "estado": "PENDIENTE_PAGO",
        "origen": "web",
    })

    return respuesta(201, {
        "pedido_id": pedido_id,
        "total": total,
        "estado": "PENDIENTE_PAGO",
    })


def _handler_rappi(event, body):
    """Lógica para POST /pedidos/rappi — Pedidos desde plataforma Rappi."""

    # --- Validar campos obligatorios ---
    origen = body.get("origen", "").strip()
    codigo_pedido_ext = body.get("codigo_pedido_ext", "").strip()
    cliente_nombre = body.get("cliente_nombre", "").strip()
    items = body.get("items", [])
    total_pagado = body.get("total_pagado")

    if not all([origen, codigo_pedido_ext, cliente_nombre, items, total_pagado]):
        return respuesta(400, {
            "mensaje": "Campos obligatorios: origen, codigo_pedido_ext, cliente_nombre, items, total_pagado."
        })

    # --- Crear pedido con estado PAGADO_EXTERNO ---
    pedido_id = str(uuid.uuid4())
    tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)

    tabla_pedidos.put_item(Item={
        "pedido_id": pedido_id,
        "usuario_id": f"rappi_{cliente_nombre}",
        "codigo_pedido_ext": codigo_pedido_ext,
        "items": items,
        "total": Decimal(str(total_pagado)),
        "estado": "PAGADO_EXTERNO",
        "origen": origen,
    })

    # --- Disparar evento a EventBridge (el pago ya se hizo en Rappi) ---
    detalle = {
        "pedido_id": pedido_id,
        "origen": origen,
        "codigo_pedido_ext": codigo_pedido_ext,
    }

    events_client.put_events(
        Entries=[
            {
                "Source": "burger-king.pedidos",
                "DetailType": "PedidoRappiRecibido",
                "Detail": json.dumps(detalle, cls=DecimalEncoder),
                "EventBusName": EVENT_BUS_NAME,
            }
        ]
    )

    return respuesta(201, {
        "mensaje": "Pedido de Rappi recibido y enviado a cocina.",
        "pedido_id_bk": pedido_id,
        "estado_actual": "PAGADO_EXTERNO",
        "tiempo_estimado_minutos": _TIEMPO_ESTIMADO_MINUTOS,
    })


def handler(event, context):
    """
    Handler principal. Detecta la ruta invocada y delega al sub-handler
    correspondiente (web o rappi).
    """
    try:
        body = obtener_body(event)
        path = event.get("path", "")

        if path.endswith("/rappi"):
            return _handler_rappi(event, body)
        else:
            return _handler_web(event, body)

    except Exception as e:
        print(f"[ERROR] Crear_Pedido: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
