"""
Lambda: Gestionar_Menu
Ruta:   POST /admin/menu (Protegida por Authorizer)
Módulo: catalogo/

Permite a un administrador agregar productos al menú.

Entrada (Body): tipo, nombre, precio, imagen_url
Salida:         mensaje, producto_id
"""

import uuid

from utils import dynamodb, TABLA_PRODUCTOS, respuesta, obtener_body
from decimal import Decimal


def handler(event, context):
    """Handler principal de la Lambda Gestionar_Menu."""
    try:
        # --- Verificar rol admin desde el context del authorizer ---
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        rol = authorizer_context.get("rol", "")

        if rol != "admin":
            return respuesta(403, {
                "mensaje": "Acceso denegado. Se requiere rol de administrador."
            })

        # --- Validar campos obligatorios ---
        body = obtener_body(event)
        tipo = body.get("tipo", "").strip()
        nombre = body.get("nombre", "").strip()
        precio = body.get("precio")
        imagen_url = body.get("imagen_url", "").strip()

        if not tipo or not nombre or precio is None:
            return respuesta(400, {
                "mensaje": "Los campos 'tipo', 'nombre' y 'precio' son obligatorios."
            })

        if tipo not in ("carta", "promo"):
            return respuesta(400, {
                "mensaje": "El campo 'tipo' debe ser 'carta' o 'promo'."
            })

        try:
            precio_decimal = Decimal(str(precio))
            if precio_decimal <= 0:
                raise ValueError
        except (ValueError, Exception):
            return respuesta(400, {
                "mensaje": "El campo 'precio' debe ser un número positivo."
            })

        # --- Guardar producto ---
        producto_id = str(uuid.uuid4())
        tabla = dynamodb.Table(TABLA_PRODUCTOS)

        tabla.put_item(Item={
            "producto_id": producto_id,
            "tipo": tipo,
            "nombre": nombre,
            "precio": precio_decimal,
            "imagen_url": imagen_url,
        })

        return respuesta(201, {
            "mensaje": "Producto agregado al menú exitosamente.",
            "producto_id": producto_id,
        })

    except Exception as e:
        print(f"[ERROR] Gestionar_Menu: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
