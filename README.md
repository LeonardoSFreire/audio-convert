# 🎧 Audio Converter API Service

Serviço de conversão de áudio usando **FFmpeg**, otimizado para API REST.

> 🎯 **Converte qualquer formato de áudio para qualquer formato!**

## 🚀 Deploy no EasyPanel

### 1. Crie um novo projeto
- Tipo: **Docker**
- Nome: `audio-converter-api`

### 2. Environment Variables
```env
API_KEY=sua-api-key-secreta-aqui
MAX_FILE_SIZE=100
CACHE_ENABLED=true
DEFAULT_BITRATE=128k
DEFAULT_SAMPLE_RATE=44100
```

### 3. Porta exposta
```
8000
```

### 4. Volumes (opcional)
```
/cache:/app/cache
```

## 📡 Endpoints da API

Todas as requisições (exceto `/` e `/health`) requerem autenticação via **Bearer Token**:

```
Authorization: Bearer sua-api-key-aqui
```

### Converter Áudio (Retorna Arquivo)
```bash
POST /convert
Content-Type: multipart/form-data

file: <arquivo_de_audio>
output_format: mp3
# Opcional:
# codec: libmp3lame
# bitrate: 128k
# sample_rate: 44100
# channels: 2
```

**Resposta:** Arquivo de áudio convertido (binary)

### Converter Áudio (Retorna URL) ⭐
```bash
POST /convert/url
Content-Type: multipart/form-data

file: <arquivo_de_audio>
output_format: m4a
# ...mesmos parâmetros opcionais
```

**Resposta:**
```json
{
  "url": "/files/abc123.m4a",
  "public_url": "/files/abc123.m4a",
  "filename": "abc123.m4a",
  "format": "m4a",
  "codec": "aac",
  "bitrate": "128k",
  "sample_rate": 44100,
  "channels": 2,
  "duration_seconds": 45.2,
  "file_size_bytes": 723456,
  "mime_type": "audio/mp4",
  "cached": false
}
```

Depois baixe o arquivo:
```bash
GET /files/abc123.m4a
```

### Listar Formatos Suportados
```bash
GET /formats
```

**Resposta:**
```json
{
  "input_formats": ["mp3", "wav", "ogg", "m4a", "flac", "aac", "wma", ...],
  "output_formats": ["mp3", "wav", "ogg", "m4a", "flac", "aac", "opus", ...],
  "codecs": {
    "mp3": ["libmp3lame"],
    "wav": ["pcm_s16le"],
    "ogg": ["libvorbis", "libopus"],
    ...
  }
}
```

### Health Check
```bash
GET /health
```

### Info do Serviço
```bash
GET /info
```

## 🧪 Teste Local

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 📋 Uso com n8n

### Converter MP3 → WAV
```json
{
  "method": "POST",
  "url": "http://IP_DA_VPS:8000/convert",
  "headers": {
    "Authorization": "Bearer sua-api-key"
  },
  "body": {
    "contentType": "multipart/form-data",
    "data": {
      "file": "={{ $binary.audio_file }}",
      "output_format": "wav",
      "sample_rate": "48000"
    }
  },
  "responseFormat": "file"
}
```

### Converter para OGG (WhatsApp)
```json
{
  "method": "POST",
  "url": "http://IP_DA_VPS:8000/convert",
  "body": {
    "contentType": "multipart/form-data",
    "data": {
      "file": "={{ $binary.audio_file }}",
      "output_format": "ogg",
      "codec": "libopus",
      "bitrate": "64k"
    }
  },
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sua-api-key"
      }
    ]
  }
}
```

## ⚙️ Formatos Suportados

### Entrada (Input)
- **MP3** - MPEG Audio Layer III
- **WAV** - Waveform Audio File Format
- **OGG** - Ogg Vorbis/Opus
- **M4A/AAC** - MPEG-4 Audio
- **FLAC** - Free Lossless Audio Codec
- **WMA** - Windows Media Audio
- **OPUS** - Opus Interactive Audio Codec
- **WEBM** - WebM Audio
- **MP4** - MPEG-4 (áudio only)
- **3GP** - 3GPP Audio
- **AIFF** - Audio Interchange File Format
- **AU** - Sun Audio

### Saída (Output)
- **MP3** - `libmp3lame` codec
- **WAV** - `pcm_s16le`, `pcm_s24le`
- **OGG Vorbis** - `libvorbis`
- **OGG Opus** - `libopus` ⭐ (ótimo para WhatsApp)
- **M4A/AAC** - `aac`
- **FLAC** - `flac` (lossless)
- **WEBM** - `libopus`

## 🔧 Parâmetros de Conversão

| Parâmetro | Opções | Descrição |
|-----------|--------|-----------|
| `output_format` | mp3, wav, ogg, m4a, flac, opus, webm | Formato de saída |
| `codec` | auto, libmp3lame, libvorbis, libopus, aac, flac, pcm_s16le | Codec de áudio |
| `bitrate` | 64k, 128k, 192k, 256k, 320k | Taxa de bits (qualidade) |
| `sample_rate` | 22050, 44100, 48000 | Taxa de amostragem (Hz) |
| `channels` | 1, 2 | Canais (1=mono, 2=stereo) |

## 💡 Exemplos de Uso

### 1. Otimizar para WhatsApp
```bash
POST /convert
file: <audio_grande.wav>
output_format: ogg
codec: libopus
bitrate: 64k
sample_rate: 24000
channels: 1
```

### 2. Converter para alta qualidade
```bash
POST /convert
file: <audio.mp3>
output_format: flac
codec: flac
sample_rate: 48000
channels: 2
```

### 3. Compactar MP3
```bash
POST /convert
file: <audio_alta_qualidade.wav>
output_format: mp3
codec: libmp3lame
bitrate: 128k
```

## 🔒 Segurança

- API Key via Bearer Token
- Limite de tamanho: 100MB padrão (configurável)
- Cache de conversões idênticas
- FFmpeg em container isolado

## 🚀 Performance

| Formato | Tempo p/ 1min de áudio |
|---------|------------------------|
| MP3 ↔ WAV | ~2 segundos |
| Para OGG Opus | ~3 segundos |
| FLAC (lossless) | ~5 segundos |

---

Criado com ❤️ para SDR elDuo
