"""
Lambda: Ver_Cola_Trabajo
Ruta:   GET /empleados/cola (Protegida por Authorizer)
Módulo: operaciones/

Retorna los pedidos pendientes de procesamiento para los empleados,
cruzando t_step_tokens con t_pedidos.

Entrada: Rol del empleado (desde context del authorizer)
Salida:  Lista de {pedido_id, paso_actual, items_a_preparar}
"""

from utils import dynamodb, TABLA_STEP_TOKENS, TABLA_PEDIDOS, respuesta


# Roles permitidos para ver la cola de trabajo
_ROLES_PERMITIDOS = {"admin", "empleado", "cocina", "empaque", "reparto"}


def handler(event, context):
    """Handler principal de la Lambda Ver_Cola_Trabajo."""
    try:
        # --- Extraer rol del context del authorizer ---
        request_context = event.get("requestContext", {})
        authorizer_context = request_context.get("authorizer", {})
        rol = authorizer_context.get("rol", "")

        if rol not in _ROLES_PERMITIDOS:
            return respuesta(403, {
                "mensaje": "Acceso denegado. Se requiere rol de empleado o administrador."
            })

        # --- Escanear t_step_tokens para obtener pasos pendientes filtrando por tenant ---
        tabla_step = dynamodb.Table(TABLA_STEP_TOKENS)
        authorizer_tenant = authorizer_context.get("tenant_id")

        if authorizer_tenant:
            scan_tokens = tabla_step.scan(
                FilterExpression="tenant_id = :t",
                ExpressionAttributeValues={":t": authorizer_tenant},
            )
        else:
            scan_tokens = tabla_step.scan()

        step_items = scan_tokens.get("Items", [])

        if not step_items:
            return respuesta(200, {"cola": [], "mensaje": "No hay pedidos en cola."})

        # --- Cruzar con t_pedidos para obtener detalle ---
        tabla_pedidos = dynamodb.Table(TABLA_PEDIDOS)
        cola = []

        for step in step_items:
            pedido_id = step.get("pedido_id", "")
            paso_actual = step.get("paso_actual", "")
            step_tenant = step.get("tenant_id")

            # Si el step no pertenece a la sede del empleado, omitir
            if authorizer_tenant and step_tenant and step_tenant != authorizer_tenant:
                continue

            # Obtener detalle del pedido
            resultado = tabla_pedidos.get_item(Key={"pedido_id": pedido_id})
            pedido = resultado.get("Item")

            items_a_preparar = []
            if pedido:
                items_raw = pedido.get("items", [])
                for item in items_raw:
                    items_a_preparar.append({
                        "producto_id": item.get("producto_id", ""),
                        "nombre": item.get("nombre", ""),
                        "cantidad": item.get("cantidad", 1),
                    })

            cola.append({
                "pedido_id": pedido_id,
                "paso_actual": paso_actual,
                "estado": pedido.get("estado", "") if pedido else "DESCONOCIDO",
                "origen": pedido.get("origen", "") if pedido else "",
                "items_a_preparar": items_a_preparar,
            })

        return respuesta(200, {"cola": cola})

    except Exception as e:
        print(f"[ERROR] Ver_Cola_Trabajo: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
