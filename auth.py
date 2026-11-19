"""Senhas do painel: gera e confere hashes (só biblioteca padrão do Python).

A senha nunca é guardada em texto puro. Guardamos um "hash": uma impressão digital da senha,
que permite conferir se a senha digitada está certa, mas não permite descobrir a senha a partir dele.

Para cadastrar um usuário, rode no terminal (na pasta do projeto):
    python auth.py
Digite a senha duas vezes e cole a linha gerada no .streamlit/secrets.toml.
"""
import getpass
import hashlib
import hmac
import secrets

ALGORITMO = 'pbkdf2_sha256'
ITERACOES = 200_000          # quantas vezes a conta é repetida: deixa a força bruta lenta


def gerar_hash(senha: str) -> str:
    """Devolve 'pbkdf2_sha256$iteracoes$sal$hash' para guardar no secrets.toml."""
    sal = secrets.token_hex(16)          # sal aleatório: senhas iguais geram hashes diferentes
    digest = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), bytes.fromhex(sal), ITERACOES)
    return f'{ALGORITMO}${ITERACOES}${sal}${digest.hex()}'


def conferir_senha(senha: str, guardado: str) -> bool:
    """True se a senha digitada corresponde ao hash guardado."""
    try:
        algoritmo, iteracoes, sal, esperado = guardado.split('$')
    except ValueError:                   # hash mal formatado no secrets.toml
        return False
    if algoritmo != ALGORITMO:
        return False
    digest = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), bytes.fromhex(sal), int(iteracoes))
    # compare_digest leva sempre o mesmo tempo: não "vaza" quantos caracteres estavam certos
    return hmac.compare_digest(digest.hex(), esperado)


if __name__ == '__main__':
    usuario = input('Nome de login: ').strip()
    perfil = ''
    while perfil not in ('tecnico', 'leitor'):
        perfil = input('Perfil (tecnico ou leitor): ').strip().lower()
    senha = getpass.getpass('Senha: ')
    if senha != getpass.getpass('Repita a senha: '):
        raise SystemExit('As senhas não conferem.')
    if len(senha) < 8:
        raise SystemExit('Use pelo menos 8 caracteres.')
    print('\nCole no .streamlit/secrets.toml:\n')
    print(f'[usuarios.{usuario}]')
    print(f'senha_hash = "{gerar_hash(senha)}"')
    print(f'perfil = "{perfil}"')
