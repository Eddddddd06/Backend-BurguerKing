"""
Lambda: Alternar_Favorito
Ruta:   POST /perfil/favoritos (Protegida por Authorizer)
Módulo: catalogo/

Agrega o elimina un producto de los favoritos del usuario (toggle).
Solo permite agregar ítems de tipo "carta".

Entrada (Body): producto_id
Salida:         mensaje, estado_actual_favorito (booleano)
"""

from utils import dynamodb, TABLA_FAVORITOS, TABLA_PRODUCTOS, respuesta, obtener_body


def handler(event, context):
    """Handler principal de la Lambda Alternar_Favorito."""
    try:
        # --- Extraer usuario_id del context del authorizer ---
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        usuario_id = authorizer_context.get("usuario_id", "")

        if not usuario_id:
            return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

        # --- Validar producto_id ---
        body = obtener_body(event)
        producto_id = body.get("producto_id", "").strip()

        if not producto_id:
            return respuesta(400, {
                "mensaje": "El campo 'producto_id' es obligatorio."
            })

        # --- Verificar que el producto exista y sea de tipo "carta" ---
        tabla_productos = dynamodb.Table(TABLA_PRODUCTOS)
        resultado_producto = tabla_productos.get_item(Key={"producto_id": producto_id})
        producto = resultado_producto.get("Item")

        if not producto:
            return respuesta(404, {"mensaje": "Producto no encontrado."})

        if producto.get("tipo") != "carta":
            return respuesta(400, {
                "mensaje": "Solo se pueden marcar como favoritos los productos de tipo 'carta'."
            })

        # --- Toggle: verificar si ya es favorito ---
        tabla_favoritos = dynamodb.Table(TABLA_FAVORITOS)
        resultado_fav = tabla_favoritos.get_item(
            Key={"usuario_id": usuario_id, "producto_id": producto_id}
        )

        if resultado_fav.get("Item"):
            # Ya es favorito → eliminar
            tabla_favoritos.delete_item(
                Key={"usuario_id": usuario_id, "producto_id": producto_id}
            )
            return respuesta(200, {
                "mensaje": "Producto eliminado de favoritos.",
                "estado_actual_favorito": False,
            })
        else:
            # No es favorito → agregar
            tabla_favoritos.put_item(Item={
                "usuario_id": usuario_id,
                "producto_id": producto_id,
            })
            return respuesta(200, {
                "mensaje": "Producto agregado a favoritos.",
                "estado_actual_favorito": True,
            })

    except Exception as e:
        print(f"[ERROR] Alternar_Favorito: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
