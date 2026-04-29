# from passlib.hash import django_pbkdf2_sha256

from cryptography.fernet import Fernet

from config import SECRET_FOR_PASSWORD


# def encrypt_password(password: str):
#     return django_pbkdf2_sha256.encrypt(password)


# def verify_password(password: str, hashed: str) -> bool:
#     return django_pbkdf2_sha256.verify(password, hashed)


# key = Fernet.generate_key()
# print(key)

from cryptography.fernet import Fernet

cipher = Fernet(SECRET_FOR_PASSWORD)

def encrypt_password(password: str) -> str:
    return cipher.encrypt(password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    return cipher.decrypt(encrypted_password.encode()).decode()