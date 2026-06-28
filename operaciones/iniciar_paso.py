"""
Lambda: Iniciar_Paso
Invocada por: AWS Step Functions (waitForTaskToken)
Módulo: operaciones/

Registra el paso actual del pedido y almacena el task_token de Step Functions
para que un empleado pueda completarlo manualmente después.

Entrada (del payload de Step Functions):
  - pedido_id
  - paso_actual  ("cocina", "empaque" o "reparto")
  - task_token

Lógica: Guarda en t_step_tokens el pedido_id, paso_actual y task_token.
        También actualiza el estado del pedido en t_pedidos.
"""

from utils import dynamodb, TABLA_STEP_TOKENS, TABLA_PEDIDOS


# Mapeo de paso a estado legible en t_pedidos
_ESTADO_POR_PASO = {
    "cocina": "EN_COCINA",
    "empaque": "EN_EMPAQUE",
    "reparto": "EN_REPARTO",
}


def handler(event, context):
    """Handler principal de la Lambda Iniciar_Paso."""
    try:
        pedido_id = event.get("pedido_id", "")
        paso_actual = event.get("paso_actual", "")
        task_token = event.get("task_token", "")

        if not pedido_id or not paso_actual or not task_token:
            print(f"[ERROR] Datos incompletos: pedido_id={pedido_id}, "
                  f"paso_actual={paso_actual}, task_token={'presente' if task_token else 'ausente'}")
            raise ValueError("pedido_id, paso_actual y task_token son obligatorios.")

        # --- Guardar token en t_step_tokens (incluyendo tenant_id tomado desde el pedido) ---
        tabla_tokens = dynamodb.Table(TABLA_STEP_TOKENS)
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
        pedido_res = tabla_pedidos.get_item(Key={"pedido_id": pedido_id})
        pedido = pedido_res.get("Item", {})
        tenant_id = pedido.get("tenant_id")

        item = {
            "pedido_id": pedido_id,
            "paso_actual": paso_actual,
            "task_token": task_token,
        }
        if tenant_id:
            item["tenant_id"] = tenant_id

        tabla_tokens.put_item(Item=item)

        # --- Actualizar estado del pedido en t_pedidos ---
        nuevo_estado = _ESTADO_POR_PASO.get(paso_actual, paso_actual.upper())
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)

        tabla_pedidos.update_item(
            Key={"pedido_id": pedido_id},
            UpdateExpression="SET estado = :e",
            ExpressionAttributeValues={":e": nuevo_estado},
        )

        print(f"[OK] Paso '{paso_actual}' iniciado para pedido '{pedido_id}'.")

        # Step Functions no espera respuesta HTTP, solo que no falle
        return {
            "pedido_id": pedido_id,
            "paso_actual": paso_actual,
            "estado": nuevo_estado,
        }

    except Exception as e:
        print(f"[ERROR] Iniciar_Paso: {e}")
        raise
