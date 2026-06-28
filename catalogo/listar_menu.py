"""
Lambda: Listar_Menu
Ruta:   GET /menu
Módulo: catalogo/

Lista todos los productos del menú. Si el usuario envía un token válido,
marca con es_favorito: true los productos que ya ha pedido anteriormente
(derivado del historial de pedidos pagados, sin usar t_favoritos).

Entrada: Ninguna obligatoria. (Opcional: Header Authorization)
Salida:  Lista de objetos con producto_id, tipo, nombre, precio,
         imagen_url, es_favorito
"""

import time

from utils import dynamodb, TABLA_PRODUCTOS, TABLA_TOKENS, TABLA_PEDIDOS, respuesta


_ESTADOS_PAGADOS = {
    "PAGADO", "PAGADO_EXTERNO", "EN_COCINA", "EN_EMPAQUE", "EN_REPARTO", "ENTREGADO"
}


def _obtener_usuario_desde_token(event):
    """
    Extrae usuario_id desde el header Authorization si el token es válido.
    Retorna usuario_id o None. Esta ruta NO usa authorizer obligatorio.
    """
    headers = event.get("headers") or {}
    auth_header = headers.get("Authorization") or headers.get("authorization", "")

    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        return None

    try:
        tabla_tokens = dynamodb.Table(TABLA_TOKENS)
        resultado = tabla_tokens.get_item(Key={"token": token})
        item = resultado.get("Item")

        if not item:
            return None

        if int(time.time()) >= int(item.get("fecha_expiracion", 0)):
            return None

        return item.get("usuario_id")

    except Exception:
        return None


def _obtener_favoritos_usuario(usuario_id, tenant_id=None):
    """
    Retorna un set con los producto_id que el usuario ha pedido y pagado.
    Deriva favoritos del historial de pedidos en lugar de t_favoritos.
    """
    tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
    # Si se proporciona tenant_id, filtrar por tenant también
    if tenant_id:
        scan_result = tabla_pedidos.scan(
            FilterExpression="usuario_id = :uid AND tenant_id = :t",
            ExpressionAttributeValues={":uid": usuario_id, ":t": tenant_id},
        )
    else:
        scan_result = tabla_pedidos.scan(
            FilterExpression="usuario_id = :uid",
            ExpressionAttributeValues={":uid": usuario_id},
        )
    favoritos = set()
    for pedido in scan_result.get("Items", []):
        if pedido.get("estado") not in _ESTADOS_PAGADOS:
            continue
        for item in pedido.get("items", []):
            pid = item.get("producto_id")
            if pid:
                favoritos.add(pid)
    return favoritos


def handler(event, context):
    """Handler principal de la Lambda Listar_Menu."""
    try:
        tabla_productos = dynamodb.Table(TABLA_PRODUCTOS)

        # --- Obtener 'sede' desde query params ---
        qs = event.get("queryStringParameters") or {}
        sede = (qs.get("sede") or qs.get("tenant")) if qs else None
        if not sede:
            return respuesta(400, {"mensaje": "El parámetro de consulta 'sede' es obligatorio."})

        # Escanear productos filtrando por tenant_id
        scan_result = tabla_productos.scan(
            FilterExpression="tenant_id = :t",
            ExpressionAttributeValues={":t": sede},
        )
        productos = scan_result.get("Items", [])

        usuario_id = _obtener_usuario_desde_token(event)
        favoritos_set = set()

        if usuario_id:
            favoritos_set = _obtener_favoritos_usuario(usuario_id, tenant_id=sede)

        menu = [
            {
                "producto_id": p.get("producto_id"),
                "tipo": p.get("tipo"),
                "nombre": p.get("nombre"),
                "precio": p.get("precio"),
                "imagen_url": p.get("imagen_url"),
                "es_favorito": p.get("producto_id") in favoritos_set,
            }
            for p in productos
        ]

        return respuesta(200, {"menu": menu})

    except Exception as e:
        print(f"[ERROR] Listar_Menu: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
