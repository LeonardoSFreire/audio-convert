"""
Audio Converter API Service
Serviço de conversão de áudio usando FFmpeg
"""

import os
import io
import hashlib
import logging
import subprocess
import tempfile
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status, Depends, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import aiofiles
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE", "100"))
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
DEFAULT_BITRATE = os.getenv("DEFAULT_BITRATE", "128k")
DEFAULT_SAMPLE_RATE = os.getenv("DEFAULT_SAMPLE_RATE", "44100")
CACHE_DIR = "/app/cache"
API_KEY = os.getenv("API_KEY", "")

# Configurações S3/MinIO
S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() == "true"
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_BUCKET = os.getenv("S3_BUCKET", "audio-converter")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "")
S3_LIFETIME_DAYS = int(os.getenv("S3_LIFETIME_DAYS", "5"))

s3_client = None
s3_public_url = None

# Security scheme
security = HTTPBearer(auto_error=False)

# Formatos e codecs suportados
SUPPORTED_FORMATS = {
    # Formatos de entrada
    "input": [".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".wma", ".opus", 
              ".webm", ".mp4", ".3gp", ".aiff", ".au", ".m4p", ".m4b", ".weba"],
    
    # Formatos de saída e seus codecs padrão
    "output": {
        "mp3": {"ext": ".mp3", "mime": "audio/mpeg", "default_codec": "libmp3lame"},
        "wav": {"ext": ".wav", "mime": "audio/wav", "default_codec": "pcm_s16le"},
        "ogg": {"ext": ".ogg", "mime": "audio/ogg", "default_codec": "libvorbis"},
        "opus": {"ext": ".opus", "mime": "audio/opus", "default_codec": "libopus"},
        "oga": {"ext": ".oga", "mime": "audio/ogg", "default_codec": "libopus"},
        "m4a": {"ext": ".m4a", "mime": "audio/mp4", "default_codec": "aac"},
        "aac": {"ext": ".aac", "mime": "audio/aac", "default_codec": "aac"},
        "flac": {"ext": ".flac", "mime": "audio/flac", "default_codec": "flac"},
        "webm": {"ext": ".webm", "mime": "audio/webm", "default_codec": "libopus"},
        "weba": {"ext": ".weba", "mime": "audio/webm", "default_codec": "libopus"},
    },
    
    # Codecs disponíveis por formato
    "codecs": {
        "mp3": ["libmp3lame"],
        "wav": ["pcm_s16le", "pcm_s24le", "pcm_f32le"],
        "ogg": ["libvorbis", "libopus"],
        "opus": ["libopus"],
        "oga": ["libopus", "libvorbis"],
        "m4a": ["aac", "alac"],
        "aac": ["aac"],
        "flac": ["flac"],
        "webm": ["libopus"],
        "weba": ["libopus"],
    }
}


class ConvertRequest(BaseModel):
    output_format: str = Field(..., description="Formato de saída (mp3, wav, ogg, opus, m4a, flac, etc)")
    codec: Optional[str] = Field(None, description="Codec específico (opcional)")
    bitrate: Optional[str] = Field(None, description="Bitrate (ex: 128k, 192k)")
    sample_rate: Optional[int] = Field(None, description="Sample rate em Hz (22050, 44100, 48000)")
    channels: Optional[int] = Field(None, description="Canais (1=mono, 2=stereo)")


class FormatInfo(BaseModel):
    format: str
    extension: str
    mime_type: str
    default_codec: str
    available_codecs: List[str]


class FormatsListResponse(BaseModel):
    input_formats: List[str]
    output_formats: List[FormatInfo]


class InfoResponse(BaseModel):
    max_file_size_mb: int
    default_bitrate: str
    default_sample_rate: str
    cache_enabled: bool
    ffmpeg_version: str
    s3_enabled: bool = False
    s3_bucket: Optional[str] = None
    s3_endpoint: Optional[str] = None


class ConvertResponse(BaseModel):
    input_format: str
    output_format: str
    codec: str
    bitrate: str
    sample_rate: int
    channels: int
    duration_seconds: Optional[float] = None
    file_size_bytes: int


def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Valida a API Key do header Authorization: Bearer <token>"""
    if not API_KEY:
        return True
    
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key não fornecida. Use: Authorization: Bearer <sua-api-key>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return True


def get_ffmpeg_version() -> str:
    """Obtém versão do FFmpeg"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.split('\n')[0]
    except Exception as e:
        return f"Unknown ({str(e)})"




def init_s3_client():
    """Inicializa cliente S3/MinIO"""
    global s3_client, s3_public_url
    if not S3_ENABLED or not all([S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY]):
        return None
    try:
        s3_client = boto3.client('s3', endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY, aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION, config=Config(signature_version='s3v4'))
        s3_client.list_buckets()
        s3_public_url = S3_PUBLIC_URL or f"{S3_ENDPOINT}/{S3_BUCKET}"
        logger.info(f"☁️ S3 conectado: {S3_ENDPOINT}")
        # Criar bucket se não existir
        try:
            s3_client.head_bucket(Bucket=S3_BUCKET)
        except:
            s3_client.create_bucket(Bucket=S3_BUCKET)
            logger.info(f"☁️ Bucket '{S3_BUCKET}' criado")
        return s3_client
    except Exception as e:
        logger.error(f"❌ Erro S3: {e}")
        return None

def upload_to_s3(file_path: str, object_name: str, content_type: str) -> str:
    """Upload para S3"""
    s3_client.upload_file(file_path, S3_BUCKET, object_name,
        ExtraArgs={'ContentType': content_type, 'ACL': 'public-read'})
    return f"{s3_public_url}/{object_name}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação"""
    logger.info("🎧 Iniciando Audio Converter API...")
    
    # Criar diretório de cache
    if CACHE_ENABLED and not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        logger.info(f"📁 Cache criado em: {CACHE_DIR}")
    
    # Verificar FFmpeg
    ffmpeg_version = get_ffmpeg_version()
    logger.info(f"✅ FFmpeg: {ffmpeg_version}")
    
    # Inicializar S3
    init_s3_client()
    logger.info(f"✅ FFmpeg: {ffmpeg_version}")
    
    yield
    
    logger.info("🛑 Desligando serviço...")


app = FastAPI(
    title="Audio Converter API",
    description="API de conversão de áudio usando FFmpeg",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    """Health check do serviço - SEM autenticação"""
    ffmpeg_ok = False
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        ffmpeg_ok = True
    except:
        pass
    
    return {
        "status": "healthy" if ffmpeg_ok else "degraded",
        "ffmpeg_available": ffmpeg_ok,
        "cache_enabled": CACHE_ENABLED,
        "max_file_size_mb": MAX_FILE_SIZE_MB
    }


@app.get("/info", response_model=InfoResponse)
async def get_info(_: bool = Depends(verify_api_key)):
    """Informações sobre o serviço"""
    return InfoResponse(
        max_file_size_mb=MAX_FILE_SIZE_MB,
        default_bitrate=DEFAULT_BITRATE,
        default_sample_rate=DEFAULT_SAMPLE_RATE,
        cache_enabled=CACHE_ENABLED,
        ffmpeg_version=get_ffmpeg_version()
    )


@app.get("/formats", response_model=FormatsListResponse)
async def list_formats(_: bool = Depends(verify_api_key)):
    """Lista todos os formatos e codecs suportados"""
    output_formats = []
    
    for fmt, info in SUPPORTED_FORMATS["output"].items():
        codecs = SUPPORTED_FORMATS["codecs"].get(fmt, [info["default_codec"]])
        output_formats.append(FormatInfo(
            format=fmt,
            extension=info["ext"],
            mime_type=info["mime"],
            default_codec=info["default_codec"],
            available_codecs=codecs
        ))
    
    return FormatsListResponse(
        input_formats=SUPPORTED_FORMATS["input"],
        output_formats=output_formats
    )


def get_cache_key(input_file: str, output_format: str, codec: str, bitrate: str, 
                  sample_rate: int, channels: int) -> str:
    """Gera uma chave única para o cache"""
    content = f"{input_file}|{output_format}|{codec}|{bitrate}|{sample_rate}|{channels}"
    return hashlib.md5(content.encode()).hexdigest()


def run_ffmpeg(input_path: str, output_path: str, codec: str, bitrate: str,
               sample_rate: int, channels: int) -> tuple[bool, str]:
    """Executa FFmpeg para conversão"""
    cmd = [
        "ffmpeg",
        "-y",  # Sobrescrever arquivo de saída
        "-i", input_path,  # Input
        "-c:a", codec,  # Codec de áudio
        "-b:a", bitrate,  # Bitrate
        "-ar", str(sample_rate),  # Sample rate
        "-ac", str(channels),  # Canais
        "-loglevel", "error",  # Apenas erros
        output_path
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutos timeout
        )
        
        if result.returncode != 0:
            return False, result.stderr
        
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Timeout - conversão muito longa"
    except Exception as e:
        return False, str(e)


def get_audio_info(file_path: str) -> dict:
    """Obtém informações do arquivo de áudio usando ffprobe"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration,size",
                "-show_entries", "stream=codec_name,sample_rate,channels",
                "-of", "json",
                file_path
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
    except:
        pass
    
    return {}


@app.post("/convert")
async def convert_audio(
    file: UploadFile = File(..., description="Arquivo de áudio para converter"),
    output_format: str = Form(..., description="Formato de saída (mp3, wav, ogg, opus, m4a, flac, etc)"),
    codec: Optional[str] = Form(None, description="Codec específico (opcional)"),
    bitrate: Optional[str] = Form(None, description="Bitrate (ex: 128k, 192k, 320k)"),
    sample_rate: Optional[int] = Form(None, description="Sample rate (22050, 44100, 48000)"),
    channels: Optional[int] = Form(None, description="Canais (1=mono, 2=stereo)"),
    _: bool = Depends(verify_api_key)
):
    """
    Converte arquivo de áudio para o formato especificado.
    
    - **file**: Arquivo de áudio (máx 100MB)
    - **output_format**: Formato desejado (mp3, wav, ogg, opus, m4a, flac, webm)
    - **codec**: Codec específico (opcional, usa padrão se não informado)
    - **bitrate**: Qualidade (64k, 128k, 192k, 256k, 320k)
    - **sample_rate**: Taxa de amostragem (22050, 44100, 48000)
    - **channels**: 1 (mono) ou 2 (stereo)
    """
    # Validar formato de saída
    output_format = output_format.lower()
    if output_format not in SUPPORTED_FORMATS["output"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato de saída não suportado: {output_format}. "
                   f"Use: {', '.join(SUPPORTED_FORMATS['output'].keys())}"
        )
    
    # Obter configurações padrão
    format_info = SUPPORTED_FORMATS["output"][output_format]
    codec = codec or format_info["default_codec"]
    bitrate = bitrate or DEFAULT_BITRATE
    sample_rate = sample_rate or int(DEFAULT_SAMPLE_RATE)
    channels = channels or 2
    
    # Validar codec
    available_codecs = SUPPORTED_FORMATS["codecs"].get(output_format, [format_info["default_codec"]])
    if codec not in available_codecs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Codec não suportado para {output_format}: {codec}. "
                   f"Use: {', '.join(available_codecs)}"
        )
    
    input_path = None
    output_path = None
    
    try:
        # Salvar arquivo de entrada
        input_ext = os.path.splitext(file.filename)[1].lower()
        if not input_ext:
            input_ext = ".tmp"
        
        with tempfile.NamedTemporaryFile(suffix=input_ext, delete=False) as tmp_in:
            input_path = tmp_in.name
            content = await file.read()
            
            # Verificar tamanho
            file_size_mb = len(content) / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_MB:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Arquivo muito grande: {file_size_mb:.1f}MB (máx: {MAX_FILE_SIZE_MB}MB)"
                )
            
            tmp_in.write(content)
        
        logger.info(f"🎧 Convertendo: {file.filename} ({file_size_mb:.1f}MB) → {output_format}")
        
        # Verificar cache
        cache_key = get_cache_key(input_path, output_format, codec, bitrate, sample_rate, channels)
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}{format_info['ext']}") if CACHE_ENABLED else None
        
        if CACHE_ENABLED and os.path.exists(cache_file):
            logger.info(f"📦 Cache hit: {cache_key}")
            async with aiofiles.open(cache_file, "rb") as f:
                output_content = await f.read()
        else:
            # Criar arquivo de saída
            with tempfile.NamedTemporaryFile(suffix=format_info["ext"], delete=False) as tmp_out:
                output_path = tmp_out.name
            
            # Executar FFmpeg
            success, error_msg = run_ffmpeg(
                input_path, output_path, codec, bitrate, sample_rate, channels
            )
            
            if not success:
                logger.error(f"❌ FFmpeg error: {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erro na conversão: {error_msg}"
                )
            
            # Ler arquivo convertido
            async with aiofiles.open(output_path, "rb") as f:
                output_content = await f.read()
            
            # Salvar no cache
            if CACHE_ENABLED:
                async with aiofiles.open(cache_file, "wb") as f:
                    await f.write(output_content)
                logger.info(f"💾 Cache salvo: {cache_key}")
        
        # Obter info do áudio convertido
        audio_info = get_audio_info(output_path if output_path else cache_file)
        duration = None
        if audio_info and "format" in audio_info:
            try:
                duration = float(audio_info["format"].get("duration", 0))
            except:
                pass
        
        logger.info(f"✅ Conversão concluída: {len(output_content)} bytes")
        
        # Retornar arquivo
        return StreamingResponse(
            io.BytesIO(output_content),
            media_type=format_info["mime"],
            headers={
                "Content-Disposition": f"attachment; filename=converted_{output_format}{format_info['ext']}",
                "X-Output-Format": output_format,
                "X-Codec": codec,
                "X-Bitrate": bitrate,
                "X-Sample-Rate": str(sample_rate),
                "X-Channels": str(channels),
                "X-Duration": str(duration) if duration else "unknown",
                "X-Cache-Key": cache_key if CACHE_ENABLED else "none"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro na conversão: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao converter áudio: {str(e)}"
        )
    finally:
        # Limpar arquivos temporários
        for path in [input_path, output_path]:
            if path and os.path.exists(path):
                os.unlink(path)


@app.post("/convert-url")
async def convert_audio_to_url((
    file: UploadFile = File(..., description="Arquivo de áudio para converter"),
    output_format: str = Form(..., description="Formato de saída (mp3, wav, ogg, opus, m4a, flac, etc)"),
    codec: Optional[str] = Form(None, description="Codec específico (opcional)"),
    bitrate: Optional[str] = Form(None, description="Bitrate (ex: 128k, 192k, 320k)"),
    sample_rate: Optional[int] = Form(None, description="Sample rate (22050, 44100, 48000)"),
    channels: Optional[int] = Form(None, description="Canais (1=mono, 2=stereo)"),
    _: bool = Depends(verify_api_key)
):
    """
    Converte áudio e retorna URL para download.
    
    Útil quando você precisa passar a URL para outra API (ex: Meta/WhatsApp API).
    
    - **file**: Arquivo de áudio (máx 100MB)
    - **output_format**: Formato desejado
    - **codec, bitrate, sample_rate, channels**: Opcionais
    
    **Retorna:** JSON com URL pública para download do arquivo
    """
    # Validar formato de saída
    output_format = output_format.lower()
    if output_format not in SUPPORTED_FORMATS["output"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato de saída não suportado: {output_format}. "
                   f"Use: {', '.join(SUPPORTED_FORMATS['output'].keys())}"
        )
    
    # Obter configurações padrão
    format_info = SUPPORTED_FORMATS["output"][output_format]
    codec = codec or format_info["default_codec"]
    bitrate = bitrate or DEFAULT_BITRATE
    sample_rate = sample_rate or int(DEFAULT_SAMPLE_RATE)
    channels = channels or 2
    
    # Validar codec
    available_codecs = SUPPORTED_FORMATS["codecs"].get(output_format, [format_info["default_codec"]])
    if codec not in available_codecs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Codec não suportado para {output_format}: {codec}. "
                   f"Use: {', '.join(available_codecs)}"
        )
    
    input_path = None
    output_path = None
    
    try:
        # Salvar arquivo de entrada
        input_ext = os.path.splitext(file.filename)[1].lower()
        if not input_ext:
            input_ext = ".tmp"
        
        with tempfile.NamedTemporaryFile(suffix=input_ext, delete=False) as tmp_in:
            input_path = tmp_in.name
            content = await file.read()
            
            # Verificar tamanho
            file_size_mb = len(content) / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_MB:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Arquivo muito grande: {file_size_mb:.1f}MB (máx: {MAX_FILE_SIZE_MB}MB)"
                )
            
            tmp_in.write(content)
        
        logger.info(f"🎧 Convertendo para URL: {file.filename} ({file_size_mb:.1f}MB) → {output_format}")
        
        # Gerar chave única
        cache_key = get_cache_key(input_path, output_format, codec, bitrate, sample_rate, channels)
        output_filename = f"{cache_key}{format_info['ext']}"
        cache_file = os.path.join(CACHE_DIR, output_filename)
        
        # Verificar se já existe no cache
        cached = False
        if CACHE_ENABLED and os.path.exists(cache_file):
            logger.info(f"📦 Cache hit: {cache_key}")
            cached = True
        else:
            # Criar arquivo de saída
            with tempfile.NamedTemporaryFile(suffix=format_info["ext"], delete=False) as tmp_out:
                output_path = tmp_out.name
            
            # Executar FFmpeg
            success, error_msg = run_ffmpeg(
                input_path, output_path, codec, bitrate, sample_rate, channels
            )
            
            if not success:
                logger.error(f"❌ FFmpeg error: {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erro na conversão: {error_msg}"
                )
            
            # Mover para cache
            if CACHE_ENABLED:
                import shutil
                shutil.move(output_path, cache_file)
                logger.info(f"💾 Cache salvo: {cache_key}")
            else:
                cache_file = output_path
        
        # Obter info do áudio
        audio_info = get_audio_info(cache_file)
        duration = None
        file_size = os.path.getsize(cache_file)
        
        if audio_info and "format" in audio_info:
            try:
                duration = float(audio_info["format"].get("duration", 0))
            except:
                pass
        
        logger.info(f"✅ Conversão concluída: {file_size} bytes")
        
        # Upload para S3 se disponível
        file_url = f"/files/{output_filename}"
        storage_type = "local"
        
        if S3_ENABLED and s3_client is not None:
            try:
                # Gerar nome com timestamp
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                s3_filename = f"{timestamp}_{cache_key}{format_info['ext']}"
                file_url = upload_to_s3(cache_file, s3_filename, format_info["mime"])
                storage_type = "s3"
                logger.info(f"☁️ Upload S3: {file_url}")
            except Exception as s3_error:
                logger.warning(f"⚠️ Falha S3, usando local: {s3_error}")
        
        # Retornar URL
        return JSONResponse(content={
            "url": file_url,
            "public_url": file_url,
            "storage_type": storage_type,
            "filename": output_filename,
            "format": output_format,
            "codec": codec,
            "bitrate": bitrate,
            "sample_rate": sample_rate,
            "channels": channels,
            "duration_seconds": round(duration, 2) if duration else None,
            "file_size_bytes": file_size,
            "mime_type": format_info["mime"],
            "cached": cached,
            "expires_in_days": S3_LIFETIME_DAYS if storage_type == "s3" else None
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro na conversão: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao converter áudio: {str(e)}"
        )
    finally:
        # Limpar arquivos temporários
        for path in [input_path]:
            if path and os.path.exists(path):
                os.unlink(path)
        # Não remover output_path se foi movido para cache


@app.get("/files/{filename}")
async def get_file(filename: str):
    """Serve arquivos convertidos (público)"""
    cache_file = os.path.join(CACHE_DIR, filename)
    
    if not os.path.exists(cache_file):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo não encontrado"
        )
    
    # Detectar MIME type
    ext = os.path.splitext(filename)[1].lower()
    mime_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
        ".weba": "audio/webm",
    }
    mime_type = mime_types.get(ext, "application/octet-stream")
    
    async with aiofiles.open(cache_file, "rb") as f:
        content = await f.read()
    
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mime_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Length": str(len(content))
        }
    )


@app.get("/")
async def root():
    """Página inicial"""
    return {
        "service": "Audio Converter API",
        "version": "1.1.0",
        "description": "Conversão de áudio usando FFmpeg",
        "features": [
            "multi-format input",
            "multi-format output",
            "codec selection",
            "bitrate control",
            "sample rate conversion",
            "channel mixing",
            "url generation for external APIs"
        ],
        "endpoints": {
            "health": "/health",
            "info": "/info",
            "formats": "/formats",
            "convert": "/convert (POST - returns file)",
            "convert_url": "/convert/url (POST - returns URL)",
            "files": "/files/{filename} (GET - public download)"
        },
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
