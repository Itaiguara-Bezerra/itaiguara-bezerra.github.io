from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
import time
from dataclasses import dataclass

# ==============================================================================
# CONFIGURAÇÃO — URLs diretas (raw) do seu GitHub
# ==============================================================================

_BASE_DIR_PADRAO = r"C:\Users\ITAIGUARA\Dropbox\Relatorio_IPCA_Domicilio_Renda"
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_relatorio import BASE_DIR as _BASE_DIR_IMPORTADO  # type: ignore

    _BASE_DIR_PADRAO = _BASE_DIR_IMPORTADO
    print(f"[config] BASE_DIR importado de build_relatorio.py: {_BASE_DIR_PADRAO}")
except Exception as e:
    print(
        f"[config] Usando o valor padrao definido neste script: {_BASE_DIR_PADRAO}"
    )

CONFIG = {
    "pasta_base": _BASE_DIR_PADRAO,
    "arquivos": {
        "inflacao_mensal_ipca_renda.parquet": {
            "url": "https://raw.githubusercontent.com/Itaiguara-Bezerra/itaiguara-bezerra.github.io/main/dados/inflacao_mensal_ipca_renda.parquet",
            "colunas_minimas": ["data_base"] + [
                "Renda Muito Baixa",
                "Renda Baixa",
                "Renda Média-Baixa",
                "Renda Média",
                "Renda Média-Alta",
                "Renda Alta",
            ],
        },
        "ipca_alimentacao_subitens_historico_completo.parquet": {
            "url": "https://raw.githubusercontent.com/Itaiguara-Bezerra/itaiguara-bezerra.github.io/main/dados/ipca_alimentacao_subitens_historico_completo.parquet",
            "colunas_minimas": ["data_base", "subitem_nome", "variacao_preco_t"],
        },
        "pesos_pof_normalizados.parquet": {
            "url": "https://raw.githubusercontent.com/Itaiguara-Bezerra/itaiguara-bezerra.github.io/main/dados/pesos_pof_normalizados.parquet",
            "colunas_minimas": ["codigo_subitem"] + [
                "Renda Muito Baixa",
                "Renda Baixa",
                "Renda Média-Baixa",
                "Renda Média",
                "Renda Média-Alta",
                "Renda Alta",
            ],
        },
    },
    "tamanho_minimo_bytes": 1024,
}


# ==============================================================================
# EXCEÇÕES PRÓPRIAS
# ==============================================================================
class ErroDownload(RuntimeError):
    pass


class ErroValidacao(RuntimeError):
    pass


@dataclass
class ResultadoArquivo:
    nome: str
    sucesso: bool
    mensagem: str
    bytes_baixados: int = 0


# ==============================================================================
# DOWNLOAD
# ==============================================================================
def _baixar_via_requests(url: str, destino: str, tentativas: int = 3) -> None:
    """Baixa um arquivo via HTTP direto (GitHub raw)."""
    import requests

    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            with requests.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(destino, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            return
        except Exception as e:
            ultimo_erro = e
            print(f"   [tentativa {tentativa}/{tentativas}] falhou: {e}")
            time.sleep(2 * tentativa)
    raise ErroDownload(f"Falha ao baixar {url} via requests: {ultimo_erro}")


def baixar_arquivo(url: str, destino: str) -> None:
    _baixar_via_requests(url, destino)


# ==============================================================================
# VALIDAÇÃO DE INTEGRIDADE (Tenta pyarrow e depois fastparquet)
# ==============================================================================
def validar_parquet(caminho: str, colunas_minimas: list[str], tamanho_minimo: int) -> None:
    tamanho = os.path.getsize(caminho) if os.path.exists(caminho) else 0
    if tamanho < tamanho_minimo:
        raise ErroValidacao(
            f"Arquivo baixado tem apenas {tamanho} bytes (minimo esperado: "
            f"{tamanho_minimo}). O arquivo pode estar corrompido ou inacessivel."
        )

    # 1. Validação estrutural do arquivo Parquet
    try:
        import pyarrow.parquet as pq
        metadata = pq.read_metadata(caminho)
        schema = metadata.schema
        colunas_encontradas = schema.names
        num_linhas = metadata.num_rows
    except Exception:
        try:
            import fastparquet
            pf = fastparquet.ParquetFile(caminho)
            colunas_encontradas = pf.columns
            num_linhas = pf.count
        except Exception:
            # Fallback com pandas
            import pandas as pd
            df = pd.read_parquet(caminho)
            colunas_encontradas = list(df.columns)
            num_linhas = len(df)

    if num_linhas == 0:
        raise ErroValidacao("Arquivo parquet abriu, mas esta vazio (0 linhas).")

    faltando = [c for c in colunas_minimas if c not in colunas_encontradas]
    if faltando:
        raise ErroValidacao(
            f"Arquivo parquet valido, mas faltam colunas esperadas por "
            f"build_relatorio.py: {faltando}. Colunas encontradas: "
            f"{colunas_encontradas}"
        )


# ==============================================================================
# ROTINA ATÔMICA
# ==============================================================================
def atualizar_arquivo(
    nome_arquivo: str,
    url: str,
    colunas_minimas: list[str],
    pasta_base: str,
    tamanho_minimo: int,
    dry_run: bool,
) -> ResultadoArquivo:
    pasta_tmp = os.path.join(pasta_base, ".tmp_download_parquet")
    pasta_backup = os.path.join(pasta_base, ".backup_parquet")
    os.makedirs(pasta_tmp, exist_ok=True)
    os.makedirs(pasta_backup, exist_ok=True)

    destino_final = os.path.join(pasta_base, nome_arquivo)
    destino_tmp = os.path.join(pasta_tmp, nome_arquivo)

    print(f"\n=== {nome_arquivo} ===")

    try:
        print(f"  Baixando de: {url}")
        baixar_arquivo(url, destino_tmp)

        print("  Validando integridade e schema...")
        validar_parquet(destino_tmp, colunas_minimas, tamanho_minimo)

        bytes_baixados = os.path.getsize(destino_tmp)
        print(f"  OK: {bytes_baixados:,} bytes, schema confere.")

        if dry_run:
            print("  [dry-run] Arquivo validado, mas NAO substituido (--dry-run ativo).")
            if os.path.exists(destino_tmp):
                os.remove(destino_tmp)
            return ResultadoArquivo(
                nome_arquivo, True, "Validado em modo dry-run (nao substituido).",
                bytes_baixados,
            )

        # Backup do arquivo definitivo atual, se existir
        if os.path.exists(destino_final):
            carimbo = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            caminho_backup = os.path.join(
                pasta_backup, f"{nome_arquivo}.{carimbo}.bak"
            )
            shutil.copy2(destino_final, caminho_backup)
            print(f"  Backup do arquivo anterior salvo em: {caminho_backup}")

        # Troca atômica via os.replace()
        os.replace(destino_tmp, destino_final)
        print(f"  Arquivo definitivo atualizado: {destino_final}")

        return ResultadoArquivo(nome_arquivo, True, "Atualizado com sucesso.", bytes_baixados)

    except (ErroDownload, ErroValidacao) as e:
        print(f"  FALHOU: {e}")
        if os.path.exists(destino_tmp):
            os.remove(destino_tmp)
        print("  Arquivo definitivo anterior foi preservado (nao alterado).")
        return ResultadoArquivo(nome_arquivo, False, str(e))


# ==============================================================================
# MAIN
# ==============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Baixa e atualiza os 3 .parquet do pipeline do Monitor de Inflacao."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Baixa e valida os arquivos, mas nao substitui os definitivos.",
    )
    args = parser.parse_args()

    pasta_base = CONFIG["pasta_base"]
    os.makedirs(pasta_base, exist_ok=True)

    print(f"Pasta base: {pasta_base}")
    if args.dry_run:
        print("Modo: DRY-RUN (nenhum arquivo definitivo sera alterado)")

    resultados: list[ResultadoArquivo] = []
    for nome_arquivo, spec in CONFIG["arquivos"].items():
        resultado = atualizar_arquivo(
            nome_arquivo=nome_arquivo,
            url=spec["url"],
            colunas_minimas=spec["colunas_minimas"],
            pasta_base=pasta_base,
            tamanho_minimo=CONFIG["tamanho_minimo_bytes"],
            dry_run=args.dry_run,
        )
        resultados.append(resultado)

    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    algum_falhou = False
    for r in resultados:
        status = "OK" if r.sucesso else "FALHOU"
        print(f"  [{status}] {r.nome} — {r.mensagem}")
        if not r.sucesso:
            algum_falhou = True

    if algum_falhou:
        print(
            "\nAo menos um arquivo nao foi atualizado. Os arquivos definitivos "
            "correspondentes foram preservados como estavam."
        )
        return 1

    print("\nTodos os arquivos processados com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())