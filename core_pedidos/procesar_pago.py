"""
Lambda: Procesar_Pago_Fake
Ruta:   POST /pedidos/{pedido_id}/pagar (Protegida por Authorizer)
Módulo: core_pedidos/

Simula el procesamiento de un pago.

Entrada (Body): numero_tarjeta
Lógica:  Actualiza pedido a PAGADO. Ofusca tarjeta y la guarda en t_usuarios.
         Dispara evento PedidoPagado a EventBridge.
Salida:  mensaje, estado_actual
"""

import json

from utils import (
    dynamodb,
    events_client,
    TABLA_PEDIDOS,
    TABLA_USUARIOS,
    EVENT_BUS_NAME,
    respuesta,
    obtener_body,
    DecimalEncoder,
)


def _ofuscar_tarjeta(numero: str) -> str:
    """Ofusca la tarjeta dejando solo los últimos 4 dígitos."""
    limpio = numero.replace(" ", "").replace("-", "")
    if len(limpio) < 4:
        return limpio
    return "*" * (len(limpio) - 4) + limpio[-4:]


def handler(event, context):
    """Handler principal de la Lambda Procesar_Pago_Fake."""
    try:
        # --- Extraer usuario_id del context del authorizer ---
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        usuario_id = authorizer_context.get("usuario_id", "")

        if not usuario_id:
            return respuesta(401, {"mensaje": "No se pudo identificar al usuario."})

        # --- Extraer pedido_id de los path parameters ---
        path_params = event.get("pathParameters") or {}
        pedido_id = path_params.get("pedido_id", "").strip()

        if not pedido_id:
            return respuesta(400, {"mensaje": "El parámetro 'pedido_id' es obligatorio."})

        # --- Validar número de tarjeta ---
        body = obtener_body(event)
        numero_tarjeta = body.get("numero_tarjeta", "").strip()

        if not numero_tarjeta:
            return respuesta(400, {
                "mensaje": "El campo 'numero_tarjeta' es obligatorio."
            })

        # --- Verificar que el pedido exista y pertenezca al usuario ---
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
        resultado = tabla_pedidos.get_item(Key={"pedido_id": pedido_id})
        pedido = resultado.get("Item")

        if not pedido:
            return respuesta(404, {"mensaje": "Pedido no encontrado."})

        if pedido.get("usuario_id") != usuario_id:
            return respuesta(403, {"mensaje": "Este pedido no pertenece al usuario."})

        if pedido.get("estado") != "PENDIENTE_PAGO":
            return respuesta(409, {
                "mensaje": f"El pedido no se puede pagar. Estado actual: {pedido.get('estado')}"
            })

        # --- Actualizar pedido a PAGADO ---
        tabla_pedidos.update_item(
            Key={"pedido_id": pedido_id},
            UpdateExpression="SET estado = :e",
            ExpressionAttributeValues={":e": "PAGADO"},
        )

        # --- Ofuscar tarjeta y guardarla en el perfil del usuario ---
        tarjeta_ofuscada = _ofuscar_tarjeta(numero_tarjeta)
        tabla_usuarios = dynamodb.Table(TABLA_USUARIOS)

        tabla_usuarios.update_item(
            Key={"usuario_id": usuario_id},
            UpdateExpression="SET tarjeta_guardada = :t",
            ExpressionAttributeValues={":t": tarjeta_ofuscada},
        )

        # --- Disparar evento PedidoPagado a EventBridge ---
        detalle = {
            "pedido_id": pedido_id,
            "usuario_id": usuario_id,
            "origen": pedido.get("origen", "web"),
            "tenant_id": pedido.get("tenant_id"),
        }

        events_client.put_events(
            Entries=[
                {
                    "Source": "burger-king.pedidos",
                    "DetailType": "PedidoPagado",
                    "Detail": json.dumps(detalle, cls=DecimalEncoder),
                    "EventBusName": EVENT_BUS_NAME,
                }
            ]
        )

        return respuesta(200, {
            "mensaje": "Pago procesado exitosamente.",
            "estado_actual": "PAGADO",
        })

    except Exception as e:
        print(f"[ERROR] Procesar_Pago_Fake: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
