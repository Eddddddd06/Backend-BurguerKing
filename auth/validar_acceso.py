"""
Lambda: Validar_Acceso_API
Tipo:   Custom Authorizer (REQUEST type)
Módulo: auth/

Valida el token Bearer del header Authorization.
Retorna una IAM Policy (Allow/Deny) y pasa usuario_id y rol en el context.
"""

import time

from utils import dynamodb, TABLA_TOKENS


def _generar_policy(principal_id: str, effect: str, resource: str, context: dict = None):
    """Genera la política IAM que API Gateway espera del Custom Authorizer."""
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        # API Gateway solo acepta strings, números o booleanos en el context
        policy["context"] = context
    return policy


def handler(event, context):
    """Handler principal del Custom Authorizer."""
    try:
        # --- Extraer token del header Authorization ---
        auth_header = event.get("headers", {}).get("Authorization", "")

        if not auth_header:
            # Intentar con minúscula (algunos clientes lo envían así)
            auth_header = event.get("headers", {}).get("authorization", "")

        if not auth_header or not auth_header.startswith("Bearer "):
            print("[WARN] Token ausente o formato inválido.")
            return _generar_policy("anonymous", "Deny", event["methodArn"])

        token = auth_header.replace("Bearer ", "").strip()

        if not token:
            return _generar_policy("anonymous", "Deny", event["methodArn"])

        # --- Buscar token en t_tokens_acceso ---
        tabla_tokens = dynamodb.Table(TABLA_TOKENS)
        resultado = tabla_tokens.get_item(Key={"token": token})
        item = resultado.get("Item")

        if not item:
            print("[WARN] Token no encontrado en la tabla.")
            return _generar_policy("anonymous", "Deny", event["methodArn"])

        # --- Verificar expiración ---
        fecha_expiracion = int(item.get("fecha_expiracion", 0))
        ahora = int(time.time())

        if ahora >= fecha_expiracion:
            print("[WARN] Token expirado.")
            return _generar_policy("anonymous", "Deny", event["methodArn"])

        # --- Token válido: generar Allow con context ---
        usuario_id = item["usuario_id"]
        rol = item["rol"]
        tenant_id = item.get("tenant_id", "")

        # Construir un ARN comodín para permitir todos los métodos del stage
        # Esto evita problemas de caché del authorizer entre rutas
        arn_parts = event["methodArn"].split(":")
        api_gateway_arn = ":".join(arn_parts[:5])
        api_id_stage = arn_parts[5].split("/")
        wildcard_resource = f"{api_gateway_arn}:{api_id_stage[0]}/{api_id_stage[1]}/*"

        ctx = {
            "usuario_id": usuario_id,
            "rol": rol,
        }
        if tenant_id:
            ctx["tenant_id"] = tenant_id

        return _generar_policy(
            principal_id=usuario_id,
            effect="Allow",
            resource=wildcard_resource,
            context=ctx,
        )

    except Exception as e:
        print(f"[ERROR] Validar_Acceso_API: {e}")
        return _generar_policy("anonymous", "Deny", event.get("methodArn", "*"))
