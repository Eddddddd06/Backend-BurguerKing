"""
Lambda: Seed_Usuarios  *** ENDPOINT TEMPORAL - SOLO PARA INICIALIZACIÓN ***
Ruta:   POST /admin/seed-usuarios
Módulo: auth/

Crea usuarios internos con rol 'admin' o 'empleado' directamente en la BD.
No requiere autenticación. ELIMINAR o proteger en producción real.

Entrada (Body): email, password, rol ("admin" | "empleado")
Salida:         mensaje, usuario_id, email, rol
"""

import uuid
import hashlib
import hmac
import os

from utils import dynamodb, TABLA_USUARIOS, respuesta, obtener_body


_SALT = os.environ.get("HASH_SALT", "bk-secret-salt-2024")
_ROLES_PERMITIDOS = {"admin", "empleado"}


def _hashear_password(password: str) -> str:
    return hmac.HMAC(
        _SALT.encode(), password.encode(), hashlib.sha256
    ).hexdigest()


def handler(event, context):
    """Handler del endpoint temporal de seed de usuarios."""
    try:
        body = obtener_body(event)

        email = body.get("email", "").strip()
        password = body.get("password", "")
        rol = body.get("rol", "").strip().lower()

        if not email or not password or not rol:
            return respuesta(400, {
                "mensaje": "Los campos 'email', 'password' y 'rol' son obligatorios."
            })

        if rol not in _ROLES_PERMITIDOS:
            return respuesta(400, {
                "mensaje": f"El campo 'rol' debe ser 'admin' o 'empleado'."
            })

        tabla = dynamodb.Table(TABLA_USUARIOS)

        scan = tabla.scan(
            FilterExpression="email = :e",
            ExpressionAttributeValues={":e": email},
            Limit=1,
        )
        if scan.get("Items"):
            return respuesta(409, {
                "mensaje": "Ya existe un usuario registrado con ese email."
            })

        usuario_id = str(uuid.uuid4())
        password_hash = _hashear_password(password)

        # Intentar inferir 'tenant_id' desde el body o desde el email (p.ej. admin.barranco@...)
        tenant_id = body.get("sede") or None
        if not tenant_id:
            local = email.split("@")[0]
            if "." in local:
                parts = local.split(".", 1)
                if len(parts) > 1 and parts[1]:
                    tenant_id = parts[1]

        item = {
            "usuario_id": usuario_id,
            "email": email,
            "password_hash": password_hash,
            "rol": rol,
            "nombre": f"Usuario {rol.capitalize()}",
            "tarjeta_guardada": None,
        }
        if tenant_id:
            item["tenant_id"] = tenant_id

        tabla.put_item(Item=item)

        return respuesta(201, {
            "mensaje": f"Usuario '{rol}' creado exitosamente.",
            "usuario_id": usuario_id,
            "email": email,
            "rol": rol,
        })

    except Exception as e:
        print(f"[ERROR] Seed_Usuarios: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
