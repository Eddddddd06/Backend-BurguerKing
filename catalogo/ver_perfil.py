"""
Lambda: Ver_Perfil
Ruta:   GET /perfil (Protegida por Authorizer)
Módulo: catalogo/

Retorna el perfil del usuario: datos personales, tarjeta ofuscada,
historial de pedidos y favoritos derivados del historial.

Entrada: usuario_id (desde el context del token)
Salida:  nombre, email, direccion, departamento, tarjeta,
         historial_pedidos, favoritos
"""

from utils import dynamodb, TABLA_USUARIOS, TABLA_PEDIDOS, respuesta


_ESTADOS_PAGADOS = {
    "PAGADO", "PAGADO_EXTERNO", "EN_COCINA", "EN_EMPAQUE", "EN_REPARTO", "ENTREGADO"
}


def _ofuscar_tarjeta(tarjeta: str) -> str:
    if not tarjeta or len(tarjeta) < 4:
        return None
    return "*" * (len(tarjeta) - 4) + tarjeta[-4:]


def _extraer_favoritos(pedidos: list) -> list:
    """
    Devuelve los productos únicos de todos los pedidos pagados.
    El orden refleja la primera aparición en el historial.
    """
    vistos = set()
    favoritos = []
    for pedido in pedidos:
        if pedido.get("estado") not in _ESTADOS_PAGADOS:
            continue
        for item in pedido.get("items", []):
            pid = item.get("producto_id")
            if pid and pid not in vistos:
                vistos.add(pid)
                favoritos.append({
                    "producto_id": pid,
                    "nombre": item.get("nombre"),
                    "precio_unitario": item.get("precio_unitario"),
                })
    return favoritos


def handler(event, context):
    """Handler principal de la Lambda Ver_Perfil."""
    try:
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        usuario_id = authorizer_context.get("usuario_id", "")

        if not usuario_id:
            return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

        # --- Datos del usuario ---
        tabla_usuarios = dynamodb.Table(TABLA_USUARIOS)
        resultado_usuario = tabla_usuarios.get_item(Key={"usuario_id": usuario_id})
        usuario = resultado_usuario.get("Item")

        if not usuario:
            return respuesta(404, {"mensaje": "Usuario no encontrado."})

        tarjeta_ofuscada = _ofuscar_tarjeta(usuario.get("tarjeta_guardada")) if usuario.get("tarjeta_guardada") else None

        # --- Historial de pedidos ---
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
        scan_result = tabla_pedidos.scan(
            FilterExpression="usuario_id = :uid",
            ExpressionAttributeValues={":uid": usuario_id},
        )
        pedidos = scan_result.get("Items", [])

        historial = [
            {
                "pedido_id": p.get("pedido_id"),
                "estado": p.get("estado"),
                "total": p.get("total"),
                "origen": p.get("origen"),
                "direccion_entrega": p.get("direccion_entrega"),
                "departamento_entrega": p.get("departamento_entrega"),
                "items": p.get("items", []),
            }
            for p in pedidos
        ]

        # --- Favoritos: productos únicos de pedidos pagados ---
        favoritos = _extraer_favoritos(pedidos)

        return respuesta(200, {
            "nombre": usuario.get("nombre"),
            "email": usuario.get("email"),
            "direccion": usuario.get("direccion"),
            "departamento": usuario.get("departamento"),
            "tarjeta": tarjeta_ofuscada,
            "historial_pedidos": historial,
            "favoritos": favoritos,
        })

    except Exception as e:
        print(f"[ERROR] Ver_Perfil: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
