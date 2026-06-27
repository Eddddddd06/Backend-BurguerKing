"""
Lambda: Crear_Usuario
Ruta:   POST /usuarios/registro
Módulo: auth/

Registra un nuevo usuario con rol "cliente".
Entrada (Body): nombre, email, password, direccion, departamento
Salida:         mensaje, usuario_id
"""

import uuid
import hashlib
import hmac
import os

from utils import dynamodb, TABLA_USUARIOS, respuesta, obtener_body


_SALT = os.environ.get("HASH_SALT", "bk-secret-salt-2024")


def _hashear_password(password: str) -> str:
    return hmac.HMAC(
        _SALT.encode(), password.encode(), hashlib.sha256
    ).hexdigest()


def handler(event, context):
    """Handler principal de la Lambda Crear_Usuario."""
    try:
        body = obtener_body(event)

        nombre = body.get("nombre", "").strip()
        email = body.get("email", "").strip()
        password = body.get("password", "")
        direccion = body.get("direccion", "").strip()
        departamento = body.get("departamento", "").strip()

        if not all([nombre, email, password, direccion, departamento]):
            return respuesta(400, {
                "mensaje": "Los campos 'nombre', 'email', 'password', 'direccion' y 'departamento' son obligatorios."
            })

        tabla = dynamodb.Table(TABLA_USUARIOS)

        scan = tabla.scan(
            FilterExpression="email = :e",
            ExpressionAttributeValues={":e": email}
        )
        if scan.get("Items"):
            return respuesta(409, {
                "mensaje": "Ya existe un usuario registrado con ese email."
            })

        usuario_id = str(uuid.uuid4())
        password_hash = _hashear_password(password)

        tabla.put_item(Item={
            "usuario_id": usuario_id,
            "nombre": nombre,
            "email": email,
            "password_hash": password_hash,
            "direccion": direccion,
            "departamento": departamento,
            "rol": "cliente",
            "tarjeta_guardada": None,
        })

        return respuesta(201, {
            "mensaje": "Usuario registrado exitosamente.",
            "usuario_id": usuario_id,
        })

    except Exception as e:
        print(f"[ERROR] Crear_Usuario: {e}")
        return respuesta(500, {"mensaje": "Error interno del servidor."})
