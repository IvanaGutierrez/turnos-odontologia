"""Aplica SQL de migración en Postgres real sin servidor en vivo (solo RED/sandbox).

Transporte alternativo (documentado en el reporte apply-parte-1): el DDL
proviene 100 % del archivo de migración Alembic (render `alembic upgrade
--sql`); este script solo aplana cada sentencia a UNA línea porque
`postgres --single` ejecuta una sentencia por línea. En cuanto haya
Docker/Postgres con servidor en vivo, el flujo canónico es
`alembic upgrade head`.
"""

import subprocess
import sys


def aplanar_sentencias(sql: str) -> list[str]:
    """Quita comentarios/lineas vacías y une cada sentencia en una línea."""
    sentencias: list[str] = []
    acumulador: list[str] = []
    for linea in sql.splitlines():
        sin_comentario = linea.split("--", 1)[0].strip() if linea.lstrip().startswith("--") else linea.strip()
        if not sin_comentario:
            continue
        acumulador.append(sin_comentario)
        if sin_comentario.rstrip().endswith(";"):
            sentencias.append(" ".join(acumulador))
            acumulador = []
    return sentencias


def leer_sql(archivo_sql: str) -> str:
    with open(archivo_sql, "rb") as f:
        crudo = f.read()
    for codec in ("utf-8-sig", "utf-16"):
        try:
            return crudo.decode(codec)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"No se pudo decodificar {archivo_sql}")


def main(archivo_sql: str, datadir: str, base: str) -> int:
    sql = leer_sql(archivo_sql)
    sentencias = aplanar_sentencias(sql)
    entrada = "\n".join(sentencias) + "\n"
    proc = subprocess.run(
        [
            r"C:\Program Files\PostgreSQL\18\bin\postgres.exe",
            "--single",
            "-D",
            datadir,
            base,
        ],
        input=entrada,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
