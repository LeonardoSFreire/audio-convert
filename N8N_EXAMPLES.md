# Exemplo de uso no n8n com Audio Converter

## Node HTTP Request - Converter e Obter URL (para Meta API) ⭐

Use este endpoint quando precisar passar a URL do arquivo para outra API (ex: Meta/WhatsApp API):

```json
{
  "method": "POST",
  "url": "http://IP_DA_VPS:8000/convert/url",
  "body": {
    "contentType": "multipart/form-data",
    "data": {
      "file": "={{ $binary.audio_ogg }}",
      "output_format": "m4a",
      "codec": "aac",
      "bitrate": "128k"
    }
  },
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sua-api-key-aqui"
      }
    ]
  }
}
```

**Resposta:**
```json
{
  "url": "/files/abc123.m4a",
  "filename": "abc123.m4a",
  "format": "m4a",
  "mime_type": "audio/mp4",
  "duration_seconds": 45.2,
  "file_size_bytes": 723456
}
```

### Fluxo completo: WhatsApp → Conversão → Meta API 🎯

```
[Recebe áudio OGG do WhatsApp]
         ↓
[n8n: HTTP Request → /convert/url]
   Envia: audio OGG
   Recebe: { "url": "/files/abc123.m4a" }
         ↓
[n8n: Monta URL completa]
   url_completa = "http://IP_DA_VPS:8000" + url
   → "http://IP:8000/files/abc123.m4a"
         ↓
[n8n: Envia para Meta API]
   POST https://graph.facebook.com/v18.0/...
   Body: { "messaging_product": "whatsapp", "recipient_type": "individual", "type": "audio", "audio": { "link": "http://IP:8000/files/abc123.m4a" } }
```

### Exemplo completo no n8n:

**Node 1: Converter áudio**
```json
{
  "method": "POST",
  "url": "http://SEU_IP:8000/convert/url",
  "body": {
    "contentType": "multipart/form-data",
    "data": {
      "file": "={{ $binary.data }}",
      "output_format": "m4a"
    }
  },
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sk-seu-token"
      }
    ]
  }
}
```

**Node 2: Enviar para Meta API**
```json
{
  "method": "POST",
  "url": "https://graph.facebook.com/v18.0/{{ $env.WHATSAPP_PHONE_ID }}/messages",
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer {{ $env.META_ACCESS_TOKEN }}"
      },
      {
        "name": "Content-Type",
        "value": "application/json"
      }
    ]
  },
  "body": {
    "contentType": "application/json",
    "data": {
      "messaging_product": "whatsapp",
      "recipient_type": "individual",
      "to": "={{ $json.from }}",
      "type": "audio",
      "audio": {
        "link": "=http://SEU_IP:8000{{ $json.url }}"
      }
    }
  }
}
```

**Importante:** A Meta API precisa de uma URL **pública e acessível** na internet. Se sua VPS estiver em rede privada, você precisará:
1. Usar um domínio com HTTPS (Let's Encrypt)
2. Ou usar um serviço de tunnel como ngrok
3. Ou fazer o upload para S3/Google Drive e usar essa URL

---

## Node HTTP Request - Converter MP3 → WAV

```json
{
  "method": "POST",
  "url": "http://IP_DA_VPS:8000/convert",
  "body": {
    "contentType": "multipart/form-data",
    "data": {
      "file": "={{ $binary.audio_mp3 }}",
      "output_format": "wav",
      "sample_rate": "48000",
      "channels": "2"
    }
  },
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sua-api-key-aqui"
      }
    ]
  },
  "responseFormat": "file"
}
```

## Converter para OGG Opus (WhatsApp) ⭐

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
      "bitrate": "64k",
      "sample_rate": "24000",
      "channels": "1"
    }
  },
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sua-api-key-aqui"
      }
    ]
  },
  "responseFormat": "file"
}
```

## Converter para FLAC (Alta Qualidade)

```json
{
  "method": "POST",
  "url": "http://IP_DA_VPS:8000/convert",
  "body": {
    "contentType": "multipart/form-data",
    "data": {
      "file": "={{ $binary.audio_file }}",
      "output_format": "flac",
      "sample_rate": "48000",
      "channels": "2"
    }
  },
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sua-api-key-aqui"
      }
    ]
  },
  "responseFormat": "file"
}
```

## Listar Formatos Suportados

```json
{
  "method": "GET",
  "url": "http://IP_DA_VPS:8000/formats",
  "headerParameters": {
    "parameters": [
      {
        "name": "Authorization",
        "value": "Bearer sua-api-key-aqui"
      }
    ]
  }
}
```

## Fluxo Completo: Otimizar áudio para WhatsApp

```
[Receber áudio de qualquer formato]
         ↓
[n8n: Enviar para /convert]
   - output_format: ogg
   - codec: libopus
   - bitrate: 64k
   - sample_rate: 24000
   - channels: 1
         ↓
[Receber OGG otimizado]
         ↓
[Enviar via WhatsApp API]
```

## Formatos Comuns de Conversão

### Para WhatsApp (recomendado):
```json
{
  "output_format": "ogg",
  "codec": "libopus",
  "bitrate": "64k",
  "sample_rate": "24000",
  "channels": "1"
}
```

### Para Telegram:
```json
{
  "output_format": "ogg",
  "codec": "libopus",
  "bitrate": "128k",
  "sample_rate": "48000",
  "channels": "2"
}
```

### Para Podcast/Edição:
```json
{
  "output_format": "wav",
  "codec": "pcm_s24le",
  "sample_rate": "48000",
  "channels": "2"
}
```

### Para Web (streaming):
```json
{
  "output_format": "mp3",
  "codec": "libmp3lame",
  "bitrate": "128k",
  "sample_rate": "44100",
  "channels": "2"
}
```

## Headers de Resposta

Após conversão, a API retorna headers úteis:

| Header | Descrição |
|--------|-----------|
| `X-Output-Format` | Formato de saída |
| `X-Codec` | Codec utilizado |
| `X-Bitrate` | Bitrate aplicado |
| `X-Sample-Rate` | Sample rate |
| `X-Channels` | Canais (1/2) |
| `X-Duration` | Duração em segundos |
| `X-Cache-Key` | Chave do cache |

## Troubleshooting

### Erro "Formato não suportado"
Verifique em `/formats` a lista atualizada de formatos.

### Erro "Codec não suportado"
Alguns codecs só funcionam com certos formatos:
- `libmp3lame` → apenas MP3
- `libopus` → OGG, OPUS, WEBM
- `aac` → M4A, AAC

### Qualidade ruim
Aumente o bitrate:
- Voz: 64k-96k
- Música: 192k-320k
- Edição: FLAC (lossless)
