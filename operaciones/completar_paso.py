"""
Lambda: Completar_Paso
Ruta:   POST /empleados/completar-paso (Protegida por Authorizer)
Módulo: operaciones/

Permite a un empleado marcar un paso como completado.
Recupera el task_token de Step Functions y llama a send_task_success().

Entrada (Body): pedido_id
Salida:         mensaje, siguiente_paso
"""

# -*- coding: utf-8 -*-
from utils import dynamodb, sfn_client, TABLA_STEP_TOKENS, TABLA_PEDIDOS, respuesta, obtener_body

import json
import boto3
import os
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

        # --- Obtener tenant_id del pedido para poder consultar t_step_tokens ---
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
        res_pedido = tabla_pedidos.get_item(Key={"pedido_id": pedido_id})
        pedido = res_pedido.get("Item")

        if not pedido:
            return respuesta(404, {"mensaje": f"No se encontró el pedido '{pedido_id}'."})

        step_tenant = pedido.get("tenant_id") or "GLOBAL"

        # --- Recuperar task_token de t_step_tokens ---
        tabla_step = dynamodb.Table(TABLA_STEP_TOKENS)
        resultado = tabla_step.get_item(Key={"tenant_id": step_tenant, "pedido_id": pedido_id})
        step_item = resultado.get("Item")

        if not step_item:
            return respuesta(404, {
                "mensaje": f"No se encontró un paso pendiente para el pedido '{pedido_id}'."
            })

        task_token = step_item.get("task_token", "")
        paso_actual = step_item.get("paso_actual", "")
        step_tenant = step_item.get("tenant_id")

        # Verificar que el empleado/admin opere sobre la misma sede
        authorizer_tenant = authorizer_context.get("tenant_id")
        if step_tenant and authorizer_tenant and step_tenant != authorizer_tenant:
            return respuesta(403, {"mensaje": "Acceso denegado. El pedido no pertenece a su sede."})

        if not task_token:
            return respuesta(500, {
                "mensaje": "El task_token no está disponible para este paso."
            })

        # --- Permitir cancelar el pedido o completarlo ---
        accion = body.get("accion", "completar").strip().lower()

        # Cliente SQS para DLQ
        sqs = boto3.client("sqs")
        queue_name = f"dlq-pedidos-{os.environ.get('STAGE', 'dev')}"
        try:
            queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        except Exception:
            queue_url = None

        if accion == "cancelar":
            # Enviar failure a Step Functions
            try:
                sfn_client.send_task_failure(
                    taskToken=task_token,
                    error="PedidoCancelado",
                    cause="Cancelado por empleado",
                )
            except Exception as e:
                print(f"[WARN] No se pudo enviar task_failure: {e}")

            # Actualizar estado del pedido a CANCELADO y notificar
            tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
            tabla_pedidos.update_item(
                Key={"pedido_id": pedido_id},
                UpdateExpression="SET estado = :e, notificacion = :n",
                ExpressionAttributeValues={
                    ":e": "CANCELADO",
                    ":n": "Hubo un problema, su pedido ha sido cancelado y se efectuará el reembolso correspondiente",
                },
            )

            # Eliminar token temporal
            tabla_step.delete_item(Key={"tenant_id": step_tenant, "pedido_id": pedido_id})

            # Enviar mensaje a DLQ si está disponible
            if queue_url:
                try:
                    sqs.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps({"pedido_id": pedido_id, "tenant_id": step_tenant, "motivo": "cancelado_por_empleado"}),
                    )
                except Exception as e:
                    print(f"[WARN] No se pudo enviar a DLQ: {e}")

            return respuesta(200, {
                "mensaje": "Pedido cancelado correctamente. Se gestionará el reembolso.",
                "pedido_id": pedido_id,
                "estado": "CANCELADO",
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
        tabla_step.delete_item(Key={"tenant_id": step_tenant, "pedido_id": pedido_id})

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
