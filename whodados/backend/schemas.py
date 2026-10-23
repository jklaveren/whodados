"""Pydantic Schemas - WhoDados 2.0."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class UsuarioSchema(BaseModel):
    username: str
    email: Optional[str] = None
    is_admin: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None

class EmpresaSchema(BaseModel):
    cnpj_completo: str
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    municipio: Optional[str] = None
    cnae_principal: Optional[str] = None
    cnae_descricao: Optional[str] = None
    capital_social: Optional[float] = None
    divida_total: Optional[float] = None
    porte_nome: Optional[str] = None

class CRMUpdate(BaseModel):
    status: Optional[str] = None
    notas: Optional[str] = None

class TemplateCreate(BaseModel):
    nome: str
    assunto: str
    corpo_html: str
    corpo_texto: Optional[str] = None

class CampanhaCreate(BaseModel):
    nome: str
    template_id: int
    filtros: Optional[Dict[str, Any]] = {}
    eh_sequencia: bool = False
    agendada_para: Optional[str] = None

