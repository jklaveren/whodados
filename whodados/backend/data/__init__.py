
"""Data Module - carrega CSVs do WhoDados."""
from __future__ import annotations
import os, re
from typing import Optional

try:
    import pandas as pd
except ImportError:
    pd = None

DATA_ROOT = "data_files"
_empresas_cache: Optional["pd.DataFrame"] = None

def _emp_file() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DATA_ROOT, "subset_rs_final_completo.csv")

def _soc_file() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DATA_ROOT, "socios_rs.csv")

def carregar_empresas() -> "pd.DataFrame":
    global _empresas_cache
    if _empresas_cache is not None:
        return _empresas_cache
    if pd is None:
        class FakeDF:
            def __init__(self): self.empty = True
            def __getattr__(self, k): return self
        return FakeDF()
    f = _emp_file()
    if not os.path.exists(f):
        _empresas_cache = pd.DataFrame()
        return _empresas_cache
    try:
        _empresas_cache = pd.read_csv(f, dtype=str, low_memory=False, on_bad_lines="skip", encoding="utf-8-sig")
    except UnicodeDecodeError:
        _empresas_cache = pd.read_csv(f, dtype=str, low_memory=False, on_bad_lines="skip", encoding="latin1")
    return _empresas_cache

def carregar_socios() -> "pd.DataFrame":
    if pd is None:
        class FakeDF:
            def __init__(self): self.empty = True
            def __getattr__(self, k): return self
        return FakeDF()
    f = _soc_file()
    if not os.path.exists(f):
        return pd.DataFrame()
    try:
        return pd.read_csv(f, dtype=str, low_memory=False, on_bad_lines="skip")
    except Exception:
        return pd.DataFrame()

def carregar_empresa_detalhe(cnpj: str) -> dict:
    df = carregar_empresas()
    if df.empty:
        return {}
    cnpj_clean = re.sub(r"\D", "", cnpj)
    for col in ["CNPJ_COMPLETO", "CNPJ", "cnpj"]:
        if col in df.columns:
            mask = df[col].astype(str).str.replace(r"\D", "", regex=True) == cnpj_clean
            if mask.any():
                rec = df[mask].iloc[0].to_dict()
                return {k: ("" if (pd and pd.isna(v)) else v) for k, v in rec.items()}
    return {}

def filtrar_empresas(df: "pd.DataFrame", cidade=None, cnae=None, busca=None) -> "pd.DataFrame":
    if df.empty:
        return df
    result = df.copy()
    if cidade:
        col = "MUNIC_NOME" if "MUNIC_NOME" in result.columns else "MUNICIPIO" if "MUNICIPIO" in result.columns else None
        if col:
            result = result[result[col].astype(str).str.upper().str.contains(cidade.upper(), na=False)]
    if cnae:
        col = "CNAE_PRINCIPAL" if "CNAE_PRINCIPAL" in result.columns else "CNAE" if "CNAE" in result.columns else None
        if col:
            result = result[result[col].astype(str).str.contains(cnae, na=False)]
    if busca:
        cols_str = [c for c in result.columns if result[c].dtype == "object"]
        mask = result[cols_str].apply(lambda c: c.astype(str).str.upper().str.contains(busca.upper(), na=False)).any(axis=1)
        result = result[mask]
    return result

def get_metricas() -> dict:
    df = carregar_empresas()
    if df.empty:
        return {"total_empresas": 0, "por_cidade": {}, "por_porte": {}, "capital_total": 0.0, "divida_total": 0.0, "top_cnaes": {}}
    total = len(df)
    por_cidade = {}
    if "MUNIC_NOME" in df.columns:
        por_cidade = df["MUNIC_NOME"].value_counts().head(10).to_dict()
    por_porte = {}
    if "PORTE_NOME" in df.columns:
        por_porte = df["PORTE_NOME"].value_counts().to_dict()
    capital_total = 0.0
    if "CAPITAL_SOCIAL" in df.columns:
        try: capital_total = float(pd.to_numeric(df["CAPITAL_SOCIAL"], errors="coerce").sum())
        except: pass
    divida_total = 0.0
    if "DIVIDA_TOTAL" in df.columns:
        try: divida_total = float(pd.to_numeric(df["DIVIDA_TOTAL"], errors="coerce").sum())
        except: pass
    top_cnaes = {}
    if "CNAE_PRINCIPAL" in df.columns:
        top_cnaes = df["CNAE_PRINCIPAL"].value_counts().head(10).to_dict()
    return {"total_empresas": total, "por_cidade": por_cidade, "por_porte": por_porte, "capital_total": capital_total, "divida_total": divida_total, "top_cnaes": top_cnaes}
