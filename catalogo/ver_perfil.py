"""
Lambda: Ver_Perfil
Ruta:   GET /perfil (Protegida por Authorizer)
Módulo: catalogo/

Retorna el perfil del usuario: tarjeta ofuscada e historial de pedidos.

Entrada: usuario_id (desde el context del token)
Salida:  tarjeta, historial_pedidos (lista)
"""

from utils import dynamodb, TABLA_USUARIOS, TABLA_PEDIDOS, respuesta


def _ofuscar_tarjeta(tarjeta: str) -> str:
    """
    Ofusca una tarjeta mostrando solo los últimos 4 dígitos.
    Ejemplo: '4532123456789012' → '************9012'
    """
    if not tarjeta or len(tarjeta) < 4:
        return None
    return "*" * (len(tarjeta) - 4) + tarjeta[-4:]


def handler(event, context):
    """Handler principal de la Lambda Ver_Perfil."""
    try:
        # --- Extraer usuario_id del context del authorizer ---
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        usuario_id = authorizer_context.get("usuario_id", "")

        if not usuario_id:
            return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

        # --- Obtener datos del usuario ---
        tabla_usuarios = dynamodb.Table(TABLA_USUARIOS)
        resultado_usuario = tabla_usuarios.get_item(Key={"usuario_id": usuario_id})
        usuario = resultado_usuario.get("Item")

        if not usuario:
            return respuesta(404, {"mensaje": "Usuario no encontrado."})

        # --- Ofuscar tarjeta guardada ---
        tarjeta_raw = usuario.get("tarjeta_guardada")
        tarjeta_ofuscada = _ofuscar_tarjeta(tarjeta_raw) if tarjeta_raw else None

        # --- Obtener historial de pedidos ---
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)

        scan_result = tabla_pedidos.scan(
            FilterExpression="usuario_id = :uid",
            ExpressionAttributeValues={":uid": usuario_id},
        )
        pedidos = scan_result.get("Items", [])

        historial = []
        for pedido in pedidos:
            historial.append({
                "pedido_id": pedido.get("pedido_id"),
                "estado": pedido.get("estado"),
                "total": pedido.get("total"),
                "origen": pedido.get("origen"),
                "items": pedido.get("items", []),
            })

        return respuesta(200, {
            "tarjeta": tarjeta_ofuscada,
            "historial_pedidos": historial,
        })

    except Exception as e:
        print(f"[ERROR] Ver_Perfil: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
