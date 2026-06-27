"""
Lambda: Crear_Usuario
Ruta:   POST /usuarios/registro
Módulo: auth/

Registra un nuevo usuario con rol "cliente".
Entrada (Body): email, password
Salida:         mensaje, usuario_id
"""

import uuid
import hashlib
import hmac
import os

from utils import dynamodb, TABLA_USUARIOS, respuesta, obtener_body


# Sal fija para el hash (en producción usar bcrypt + sal única por usuario)
_SALT = os.environ.get("HASH_SALT", "bk-secret-salt-2024")


def _hashear_password(password: str) -> str:
    """Genera un hash SHA-256 con sal del password proporcionado."""
    return hmac.HMAC(
        _SALT.encode(), password.encode(), hashlib.sha256
    ).hexdigest()


def handler(event, context):
    """Handler principal de la Lambda Crear_Usuario."""
    try:
        body = obtener_body(event)

        # --- Validación de campos obligatorios ---
        email = body.get("email", "").strip()
        password = body.get("password", "")

        if not email or not password:
            return respuesta(400, {
                "mensaje": "Los campos 'email' y 'password' son obligatorios."
            })

        # --- Verificar que el email no esté ya registrado ---
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

        # --- Crear el usuario ---
        usuario_id = str(uuid.uuid4())
        password_hash = _hashear_password(password)

        tabla.put_item(Item={
            "usuario_id": usuario_id,
            "email": email,
            "password_hash": password_hash,
            "rol": "cliente",            # Forzado siempre a "cliente"
            "tarjeta_guardada": None,
        })

        return respuesta(201, {
            "mensaje": "Usuario registrado exitosamente.",
            "usuario_id": usuario_id,
        })

    except Exception as e:
        print(f"[ERROR] Crear_Usuario: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
