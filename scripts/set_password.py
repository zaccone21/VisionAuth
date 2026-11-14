"""Stores the Windows password the credential provider uses to sign the owner in.

Windows only signs in with the account's real password (a PIN is not
enough), so VisionAuth keeps it in an LSA private data object that only
SYSTEM and administrators can read. The credential provider reads it from
LogonUI. Run from an administrator console, as the user to sign in:

    python scripts/set_password.py          store or replace the password
    python scripts/set_password.py --check  say whether one is stored
    python scripts/set_password.py --remove delete it

For a Microsoft account this is the Microsoft account password. The password
is checked with Windows before it is stored, and it is never printed.
"""

import argparse
import ctypes
import getpass
import sys
import winreg
from ctypes import wintypes

SECRET_NAME = "L$VisionAuthCredential"
MICROSOFT_ACCOUNT_DOMAIN = "MicrosoftAccount"

POLICY_GET_PRIVATE_INFORMATION = 0x00000004
POLICY_CREATE_SECRET = 0x00000020
LOGON32_LOGON_INTERACTIVE = 2
LOGON32_PROVIDER_DEFAULT = 0
ERROR_LOGON_FAILURE = 1326
STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034


class LSA_UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


class LSA_OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.c_void_p),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.LsaOpenPolicy.argtypes = [ctypes.c_void_p, ctypes.POINTER(LSA_OBJECT_ATTRIBUTES), wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.LsaOpenPolicy.restype = wintypes.ULONG
advapi32.LsaStorePrivateData.argtypes = [wintypes.HANDLE, ctypes.POINTER(LSA_UNICODE_STRING), ctypes.POINTER(LSA_UNICODE_STRING)]
advapi32.LsaStorePrivateData.restype = wintypes.ULONG
advapi32.LsaRetrievePrivateData.argtypes = [wintypes.HANDLE, ctypes.POINTER(LSA_UNICODE_STRING), ctypes.POINTER(ctypes.POINTER(LSA_UNICODE_STRING))]
advapi32.LsaRetrievePrivateData.restype = wintypes.ULONG
advapi32.LsaNtStatusToWinError.argtypes = [wintypes.ULONG]
advapi32.LsaNtStatusToWinError.restype = wintypes.ULONG
advapi32.LsaClose.argtypes = [wintypes.HANDLE]
advapi32.LsaFreeMemory.argtypes = [ctypes.c_void_p]
advapi32.LogonUserW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _lsa_string(text: str) -> tuple[LSA_UNICODE_STRING, ctypes.Array]:
    buffer = ctypes.create_unicode_buffer(text)
    size = len(text) * ctypes.sizeof(ctypes.c_wchar)
    return LSA_UNICODE_STRING(size, size + ctypes.sizeof(ctypes.c_wchar), ctypes.addressof(buffer)), buffer


def _open_policy(access: int) -> wintypes.HANDLE:
    attributes = LSA_OBJECT_ATTRIBUTES()
    attributes.Length = ctypes.sizeof(LSA_OBJECT_ATTRIBUTES)
    handle = wintypes.HANDLE()
    status = advapi32.LsaOpenPolicy(None, ctypes.byref(attributes), access, ctypes.byref(handle))
    if status:
        raise ctypes.WinError(advapi32.LsaNtStatusToWinError(status))
    return handle


def store_secret(value: str | None) -> None:
    """Stores the secret, or deletes it when value is None."""
    policy = _open_policy(POLICY_CREATE_SECRET)
    try:
        key, _key_buffer = _lsa_string(SECRET_NAME)
        if value is None:
            status = advapi32.LsaStorePrivateData(policy, ctypes.byref(key), None)
        else:
            data, data_buffer = _lsa_string(value)
            status = advapi32.LsaStorePrivateData(policy, ctypes.byref(key), ctypes.byref(data))
            ctypes.memset(data_buffer, 0, ctypes.sizeof(data_buffer))
        if status and not (value is None and status == STATUS_OBJECT_NAME_NOT_FOUND):
            raise ctypes.WinError(advapi32.LsaNtStatusToWinError(status))
    finally:
        advapi32.LsaClose(policy)


def secret_exists() -> bool:
    policy = _open_policy(POLICY_GET_PRIVATE_INFORMATION)
    try:
        key, _key_buffer = _lsa_string(SECRET_NAME)
        data = ctypes.POINTER(LSA_UNICODE_STRING)()
        status = advapi32.LsaRetrievePrivateData(policy, ctypes.byref(key), ctypes.byref(data))
        if status == STATUS_OBJECT_NAME_NOT_FOUND:
            return False
        if status:
            raise ctypes.WinError(advapi32.LsaNtStatusToWinError(status))
        ctypes.memset(data.contents.Buffer, 0, data.contents.Length)
        advapi32.LsaFreeMemory(data)
        return True
    finally:
        advapi32.LsaClose(policy)


def microsoft_account_email() -> str | None:
    """The Microsoft account linked to the current user, if any."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\IdentityCRL\UserExtendedProperties") as key:
            name = winreg.EnumKey(key, 0)
            return name if "@" in name else None
    except OSError:
        return None


def current_user_sid() -> str:
    import subprocess

    output = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True).stdout
    return output.strip().split(",")[-1].strip('"')


def password_is_valid(domain: str, user: str, password: str) -> bool | None:
    """True/False when Windows accepts/rejects it, None when it could not be checked."""
    token = wintypes.HANDLE()
    if advapi32.LogonUserW(user, domain, password, LOGON32_LOGON_INTERACTIVE, LOGON32_PROVIDER_DEFAULT, ctypes.byref(token)):
        ctypes.windll.kernel32.CloseHandle(token)
        return True
    error = ctypes.get_last_error()
    if error == ERROR_LOGON_FAILURE:
        return False
    print(f"(Windows no pudo verificar la contraseña: error {error})")
    return None


def is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Say whether a password is stored.")
    group.add_argument("--remove", action="store_true", help="Delete the stored password.")
    args = parser.parse_args()

    if not is_admin():
        sys.exit("Ejecutá este script desde una consola de administrador.")

    if args.check:
        print("Hay una contraseña guardada." if secret_exists() else "No hay contraseña guardada.")
        return
    if args.remove:
        store_secret(None)
        print("Contraseña borrada.")
        return

    email = microsoft_account_email()
    if email:
        domain, user = MICROSOFT_ACCOUNT_DOMAIN, email
        print(f"Cuenta de Microsoft: {email}")
    else:
        domain, user = ".", getpass.getuser()
        print(f"Cuenta local: {user}")
    sid = current_user_sid()

    password = getpass.getpass("Contraseña de esa cuenta (no se muestra): ")
    if not password:
        sys.exit("Cancelado.")
    valid = password_is_valid(domain, user, password)
    if valid is False:
        sys.exit("Windows rechazó esa contraseña. No se guardó nada.")
    if valid is None and input("¿Guardarla igual? (s/n): ").strip().lower() not in ("s", "si", "sí"):
        sys.exit("Cancelado.")

    store_secret(f"{sid}\n{domain}\n{user}\n{password}")
    password = ""
    print("Contraseña guardada. Solo SYSTEM y los administradores pueden leerla.")


if __name__ == "__main__":
    main()
