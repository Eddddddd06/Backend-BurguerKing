"""
Lambda: Gestionar_Carrito
Rutas:  GET    /carrito                    - Ver carrito con subtotales y total
        POST   /carrito                    - Agregar/actualizar item {producto_id, cantidad}
        DELETE /carrito/{producto_id}      - Eliminar un item del carrito
Módulo: carrito/

Tabla t_carritos: PK=usuario_id, SK=producto_id
Cada ítem almacena cantidad y precio cacheado al momento de agregar.
El total final se recalcula siempre en el GET para consistencia.
"""

from decimal import Decimal

from utils import dynamodb, TABLA_CARRITOS, TABLA_PRODUCTOS, respuesta, obtener_body


def _obtener_usuario(event):
    ctx = event.get("requestContext", {}).get("authorizer", {})
    return ctx.get("usuario_id", "")


def _ver_carrito(usuario_id, sede):
    tabla = dynamodb.Table(TABLA_CARRITOS)
    resultado = tabla.query(
        KeyConditionExpression="tenant_id = :t AND begins_with(usuario_producto_id, :uid_prefix)",
        ExpressionAttributeValues={":t": sede, ":uid_prefix": f"{usuario_id}#"},
    )
    items = resultado.get("Items", [])

    total = Decimal("0")
    detalle = []
    for item in items:
        cantidad = int(item.get("cantidad", 1))
        precio_unitario = Decimal(str(item.get("precio_unitario", "0")))
        subtotal = precio_unitario * cantidad
        total += subtotal
        detalle.append({
            "producto_id": item.get("producto_id"),
            "nombre": item.get("nombre"),
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
            "subtotal": subtotal,
        })

    return respuesta(200, {
        "items": detalle,
        "total": total,
        "cantidad_productos": len(detalle),
    })


def _agregar_item(usuario_id, body, sede):
    producto_id = body.get("producto_id", "").strip()
    cantidad = body.get("cantidad", 1)

    if not producto_id:
        return respuesta(400, {"mensaje": "El campo 'producto_id' es obligatorio."})

    if not isinstance(cantidad, int) or cantidad <= 0:
        return respuesta(400, {"mensaje": "El campo 'cantidad' debe ser un entero positivo."})

    tabla_productos = dynamodb.Table(TABLA_PRODUCTOS)
    resultado = tabla_productos.get_item(Key={"tenant_id": sede, "producto_id": producto_id})
    producto = resultado.get("Item")

    if not producto:
        return respuesta(404, {"mensaje": f"Producto '{producto_id}' no encontrado en la sede especificada."})

    tabla_carrito = dynamodb.Table(TABLA_CARRITOS)
    tabla_carrito.put_item(Item={
        "tenant_id": sede,
        "usuario_producto_id": f"{usuario_id}#{producto_id}",
        "usuario_id": usuario_id,
        "producto_id": producto_id,
        "cantidad": cantidad,
        "nombre": producto.get("nombre"),
        "precio_unitario": Decimal(str(producto.get("precio", "0"))),
    })

    return respuesta(200, {
        "mensaje": "Producto agregado al carrito.",
        "producto_id": producto_id,
        "cantidad": cantidad,
    })


def _eliminar_item(usuario_id, producto_id, sede):
    if not producto_id:
        return respuesta(400, {"mensaje": "El 'producto_id' es obligatorio en la ruta."})

    tabla = dynamodb.Table(TABLA_CARRITOS)
    resultado = tabla.get_item(Key={"tenant_id": sede, "usuario_producto_id": f"{usuario_id}#{producto_id}"})

    if not resultado.get("Item"):
        return respuesta(404, {"mensaje": "El producto no está en el carrito."})

    tabla.delete_item(Key={"tenant_id": sede, "usuario_producto_id": f"{usuario_id}#{producto_id}"})

    return respuesta(200, {"mensaje": "Producto eliminado del carrito."})


def handler(event, context):
    """Handler principal del carrito — enruta por método HTTP."""
    try:
        usuario_id = _obtener_usuario(event)
        if not usuario_id:
            return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

        metodo = event.get("httpMethod", "").upper()
        qs = event.get("queryStringParameters") or {}
        sede_qs = qs.get("sede") or qs.get("tenant")

        if metodo == "GET":
            if not sede_qs:
                return respuesta(400, {"mensaje": "El parámetro 'sede' es obligatorio para ver el carrito."})
            return _ver_carrito(usuario_id, sede_qs)

        if metodo == "POST":
            body = obtener_body(event)
            sede_body = body.get("sede") or sede_qs
            if not sede_body:
                return respuesta(400, {"mensaje": "El campo 'sede' es obligatorio para agregar al carrito."})
            return _agregar_item(usuario_id, body, sede_body)

        if metodo == "DELETE":
            path_params = event.get("pathParameters") or {}
            producto_id = path_params.get("producto_id", "").strip()
            if not sede_qs:
                return respuesta(400, {"mensaje": "El parámetro 'sede' es obligatorio para eliminar un ítem."})
            return _eliminar_item(usuario_id, producto_id, sede_qs)

        return respuesta(405, {"mensaje": "Método no permitido."})

    except Exception as e:
        print(f"[ERROR] Gestionar_Carrito: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
