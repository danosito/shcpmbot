import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
# from config import key
import hashlib
# def encrypt(s, key) -> str:
#     t = (str(s) + str(key)).encode('utf-8')
#     return hashlib.sha256(t).hexdigest()


def decrypt(e: str, key):
    iv = bytes(key, 'utf-8')
    encrypted_data = base64.b64decode(e)
    cipher = AES.new(bytes(key, 'utf-8'), AES.MODE_CBC, iv)
    decrypted_data = unpad(cipher.decrypt(encrypted_data), AES.block_size)
    decrypted_data = decrypted_data.decode('utf-8').replace("null", 'None').replace('false', 'False').replace('true', 'True')
    try:
        return eval(decrypted_data)
    except SyntaxError:
        return decrypted_data