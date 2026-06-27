"""
Lambda: Completar_Paso
Ruta:   POST /empleados/completar-paso (Protegida por Authorizer)
Módulo: operaciones/

Permite a un empleado marcar un paso como completado.
Recupera el task_token de Step Functions y llama a send_task_success().

Entrada (Body): pedido_id
Salida:         mensaje, siguiente_paso
"""

from utils import dynamodb, sfn_client, TABLA_STEP_TOKENS, TABLA_PEDIDOS, respuesta, obtener_body

import json


# Roles permitidos para completar pasos
_ROLES_PERMITIDOS = {"admin", "empleado", "cocina", "empaque", "reparto"}

# Secuencia de pasos para determinar el siguiente
_SECUENCIA_PASOS = ["cocina", "empaque", "reparto"]


def handler(event, context):
    """Handler principal de la Lambda Completar_Paso."""
    try:
        # --- Verificar rol ---
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        rol = authorizer_context.get("rol", "")

        if rol not in _ROLES_PERMITIDOS:
            return respuesta(403, {
                "mensaje": "Acceso denegado. Se requiere rol de empleado o administrador."
            })

        # --- Validar pedido_id ---
        body = obtener_body(event)
        pedido_id = body.get("pedido_id", "").strip()

        if not pedido_id:
            return respuesta(400, {"mensaje": "El campo 'pedido_id' es obligatorio."})

        # --- Recuperar task_token de t_step_tokens ---
        tabla_step = dynamodb.Table(TABLA_STEP_TOKENS)
        resultado = tabla_step.get_item(Key={"pedido_id": pedido_id})
        step_item = resultado.get("Item")

        if not step_item:
            return respuesta(404, {
                "mensaje": f"No se encontró un paso pendiente para el pedido '{pedido_id}'."
            })

        task_token = step_item.get("task_token", "")
        paso_actual = step_item.get("paso_actual", "")

        if not task_token:
            return respuesta(500, {
                "mensaje": "El task_token no está disponible para este paso."
            })

        # --- Determinar siguiente paso ---
        idx_actual = _SECUENCIA_PASOS.index(paso_actual) if paso_actual in _SECUENCIA_PASOS else -1
        if idx_actual < len(_SECUENCIA_PASOS) - 1:
            siguiente_paso = _SECUENCIA_PASOS[idx_actual + 1]
        else:
            siguiente_paso = "ENTREGADO"

        # --- Enviar task_success a Step Functions ---
        sfn_client.send_task_success(
            taskToken=task_token,
            output=json.dumps({
                "pedido_id": pedido_id,
                "paso_completado": paso_actual,
                "siguiente_paso": siguiente_paso,
            }),
        )

        # --- Eliminar registro de la tabla temporal ---
        tabla_step.delete_item(Key={"pedido_id": pedido_id})

        # --- Si era el último paso, actualizar pedido a ENTREGADO ---
        if siguiente_paso == "ENTREGADO":
            tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
            tabla_pedidos.update_item(
                Key={"pedido_id": pedido_id},
                UpdateExpression="SET estado = :e",
                ExpressionAttributeValues={":e": "ENTREGADO"},
            )

        return respuesta(200, {
            "mensaje": f"Paso '{paso_actual}' completado exitosamente.",
            "siguiente_paso": siguiente_paso,
        })

    except Exception as e:
        print(f"[ERROR] Completar_Paso: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
