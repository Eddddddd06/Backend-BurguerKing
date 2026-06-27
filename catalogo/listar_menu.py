"""
Lambda: Listar_Menu
Ruta:   GET /menu
Módulo: catalogo/

Lista todos los productos del menú. Si el usuario envía un token válido,
marca los productos favoritos con es_favorito: true.

Entrada: Ninguna obligatoria. (Opcional: Header Authorization)
Salida:  Lista de objetos con producto_id, tipo, nombre, precio, es_favorito
"""

from utils import dynamodb, TABLA_PRODUCTOS, TABLA_FAVORITOS, TABLA_TOKENS, respuesta

import time


def _obtener_usuario_desde_token(event):
    """
    Intenta extraer el usuario_id desde el token del header Authorization.
    Retorna usuario_id si el token es válido, None en caso contrario.
    Esta ruta NO usa authorizer, por lo que la validación es manual y opcional.
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

        # Verificar expiración
        fecha_expiracion = int(item.get("fecha_expiracion", 0))
        if int(time.time()) >= fecha_expiracion:
            return None

        return item.get("usuario_id")

    except Exception:
        return None


def _obtener_favoritos_usuario(usuario_id):
    """Retorna un set con los producto_id favoritos del usuario."""
    tabla_favoritos = dynamodb.Table(TABLA_FAVORITOS)

    resultado = tabla_favoritos.query(
        KeyConditionExpression="usuario_id = :uid",
        ExpressionAttributeValues={":uid": usuario_id},
    )

    return {item["producto_id"] for item in resultado.get("Items", [])}


def handler(event, context):
    """Handler principal de la Lambda Listar_Menu."""
    try:
        # --- Escanear todos los productos ---
        tabla_productos = dynamodb.Table(TABLA_PRODUCTOS)
        scan_result = tabla_productos.scan()
        productos = scan_result.get("Items", [])

        # --- Obtener favoritos si hay token válido ---
        usuario_id = _obtener_usuario_desde_token(event)
        favoritos_set = set()

        if usuario_id:
            favoritos_set = _obtener_favoritos_usuario(usuario_id)

        # --- Armar respuesta ---
        menu = []
        for producto in productos:
            menu.append({
                "producto_id": producto.get("producto_id"),
                "tipo": producto.get("tipo"),
                "nombre": producto.get("nombre"),
                "precio": producto.get("precio"),
                "imagen_url": producto.get("imagen_url"),
                "es_favorito": producto.get("producto_id") in favoritos_set,
            })

        return respuesta(200, {"menu": menu})

    except Exception as e:
        print(f"[ERROR] Listar_Menu: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
