"""
Lambda: Login_Usuario
Ruta:   POST /usuarios/login
Módulo: auth/

Autentica al usuario y genera un token de sesión.
Entrada (Body): email, password
Salida:         token, rol
"""

import uuid
import hashlib
import hmac
import os
import time

from utils import dynamodb, TABLA_USUARIOS, TABLA_TOKENS, respuesta, obtener_body


_SALT = os.environ.get("HASH_SALT", "bk-secret-salt-2024")
_TOKEN_TTL_SECONDS = 3600  # 1 hora de validez


def _hashear_password(password: str) -> str:
    """Genera un hash SHA-256 con sal del password proporcionado."""
    return hmac.HMAC(
        _SALT.encode(), password.encode(), hashlib.sha256
    ).hexdigest()


def handler(event, context):
    """Handler principal de la Lambda Login_Usuario."""
    try:
        body = obtener_body(event)

        email = body.get("email", "").strip()
        password = body.get("password", "")

        if not email or not password:
            return respuesta(400, {
                "mensaje": "Los campos 'email' y 'password' son obligatorios."
            })

        # --- Buscar usuario por email ---
        tabla_usuarios = dynamodb.Table(TABLA_USUARIOS)

        scan = tabla_usuarios.scan(
            FilterExpression="email = :e",
            ExpressionAttributeValues={":e": email}
        )
        items = scan.get("Items", [])
        if not items:
            return respuesta(401, {
                "mensaje": "Credenciales inválidas."
            })

        usuario = items[0]

        # --- Verificar password ---
        password_hash = _hashear_password(password)
        if usuario.get("password_hash") != password_hash:
            return respuesta(401, {
                "mensaje": "Credenciales inválidas."
            })

        # --- Generar token y guardar en t_tokens_acceso ---
        token = str(uuid.uuid4())
        fecha_expiracion = int(time.time()) + _TOKEN_TTL_SECONDS

        tabla_tokens = dynamodb.Table(TABLA_TOKENS)
        tabla_tokens.put_item(Item={
            "token": token,
            "usuario_id": usuario["usuario_id"],
            "rol": usuario["rol"],
            "fecha_expiracion": fecha_expiracion,
        })

        return respuesta(200, {
            "token": token,
            "rol": usuario["rol"],
        })

    except Exception as e:
        print(f"[ERROR] Login_Usuario: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
