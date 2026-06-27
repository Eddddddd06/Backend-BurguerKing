"""
Lambda: Crear_Pedido
Rutas:  POST /pedidos/web    (Protegida por Token - Custom Authorizer)
        POST /pedidos/rappi  (Protegida por API Key nativa)
Módulo: core_pedidos/

Ruta Web (desde carrito):
  Entrada (Body): direccion_entrega, departamento_entrega (opcionales, usan dirección base si se omiten)
  Lógica:  Lee items del carrito del usuario. Calcula total desde t_productos.
           Guarda dirección de entrega en el pedido. Limpia el carrito.
           Estado = PENDIENTE_PAGO. Origen = web.
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
    TABLA_USUARIOS,
    TABLA_PRODUCTOS,
    TABLA_PEDIDOS,
    TABLA_CARRITOS,
    EVENT_BUS_NAME,
    respuesta,
    obtener_body,
    DecimalEncoder,
)

_TIEMPO_ESTIMADO_MINUTOS = 25


def _calcular_total(items: list) -> tuple:
    """
    Calcula el total leyendo precios reales desde t_productos.
    Retorna (total, items_detalle) o lanza ValueError si hay producto inválido.
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


def _limpiar_carrito(usuario_id: str):
    """Elimina todos los ítems del carrito del usuario."""
    tabla_carrito = dynamodb.Table(TABLA_CARRITOS)
    resultado = tabla_carrito.query(
        KeyConditionExpression="usuario_id = :uid",
        ExpressionAttributeValues={":uid": usuario_id},
    )
    for item in resultado.get("Items", []):
        tabla_carrito.delete_item(
            Key={"usuario_id": usuario_id, "producto_id": item["producto_id"]}
        )


def _handler_web(event, body):
    """Lógica para POST /pedidos/web — Pedido creado desde el carrito del usuario."""

    request_context = event.get("requestContext", {})
    authorizer_context = request_context.get("authorizer", {})
    usuario_id = authorizer_context.get("usuario_id", "")

    if not usuario_id:
        return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

    # --- Leer items desde el carrito ---
    tabla_carrito = dynamodb.Table(TABLA_CARRITOS)
    resultado_carrito = tabla_carrito.query(
        KeyConditionExpression="usuario_id = :uid",
        ExpressionAttributeValues={":uid": usuario_id},
    )
    items_carrito = resultado_carrito.get("Items", [])

    if not items_carrito:
        return respuesta(400, {
            "mensaje": "El carrito está vacío. Agrega productos antes de crear el pedido."
        })

    items_para_calcular = [
        {"producto_id": i["producto_id"], "cantidad": int(i["cantidad"])}
        for i in items_carrito
    ]

    # --- Calcular total con precios reales desde t_productos ---
    try:
        total, items_detalle = _calcular_total(items_para_calcular)
    except ValueError as e:
        return respuesta(400, {"mensaje": str(e)})

    # --- Dirección de entrega: body o dirección base del usuario ---
    direccion_entrega = body.get("direccion_entrega", "").strip()
    departamento_entrega = body.get("departamento_entrega", "").strip()

    if not direccion_entrega or not departamento_entrega:
        tabla_usuarios = dynamodb.Table(TABLA_USUARIOS)
        resultado_usuario = tabla_usuarios.get_item(Key={"usuario_id": usuario_id})
        usuario = resultado_usuario.get("Item", {})
        if not direccion_entrega:
            direccion_entrega = usuario.get("direccion", "")
        if not departamento_entrega:
            departamento_entrega = usuario.get("departamento", "")

    if not direccion_entrega or not departamento_entrega:
        return respuesta(400, {
            "mensaje": "Se requiere 'direccion_entrega' y 'departamento_entrega' (o tener una dirección base registrada)."
        })

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
        "direccion_entrega": direccion_entrega,
        "departamento_entrega": departamento_entrega,
    })

    # --- Limpiar carrito ---
    _limpiar_carrito(usuario_id)

    return respuesta(201, {
        "pedido_id": pedido_id,
        "total": total,
        "estado": "PENDIENTE_PAGO",
        "direccion_entrega": direccion_entrega,
        "departamento_entrega": departamento_entrega,
    })


def _handler_rappi(event, body):
    """Lógica para POST /pedidos/rappi — Pedidos desde plataforma Rappi."""
    origen = body.get("origen", "").strip()
    codigo_pedido_ext = body.get("codigo_pedido_ext", "").strip()
    cliente_nombre = body.get("cliente_nombre", "").strip()
    items = body.get("items", [])
    total_pagado = body.get("total_pagado")

    if not all([origen, codigo_pedido_ext, cliente_nombre, items, total_pagado]):
        return respuesta(400, {
            "mensaje": "Campos obligatorios: origen, codigo_pedido_ext, cliente_nombre, items, total_pagado."
        })

    pedido_id = str(uuid.uuid4())
    tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)

    items_detalle = json.loads(json.dumps(items), parse_float=Decimal)
    try:
        _, items_detalle = _calcular_total(items)
    except Exception as e:
        print(f"[ERROR calcular_total rappi] {e}")

    tabla_pedidos.put_item(Item={
        "pedido_id": pedido_id,
        "usuario_id": f"rappi_{cliente_nombre}",
        "codigo_pedido_ext": codigo_pedido_ext,
        "items": items_detalle,
        "total": Decimal(str(total_pagado)),
        "estado": "PAGADO_EXTERNO",
        "origen": origen,
    })

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
    """Handler principal. Detecta la ruta invocada y delega al sub-handler."""
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
