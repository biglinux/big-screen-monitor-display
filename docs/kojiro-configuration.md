# Kojiro — configuração e formato

As configurações ficam em `/etc/big-screen-monitor-display/settings.json`
(fonte única, lida pelo serviço), gravadas de forma atômica pelo assistente
Polkit depois de validadas. A chave `kojiro` guarda o layout comum; cada
display pode ter o seu em `displays.<id>.kojiro`.

```json
{
  "theme": "kojiro",
  "kojiro": {
    "version": 1,
    "preset": "cyberpunk",
    "ref": [800, 480],
    "ref_portrait": [480, 800],
    "theme": {"font": "default", "animations": true, "reduce_motion": false, "speed": 100,
              "pulse": true, "alerts": true, "hysteresis": 3.0, "cooldown": 5.0,
              "contrast_assist": "auto", "bg_effect": "none", "bg_effect_strength": 25,
              "bg_effect_color": "#42E8FF", "demo": false},
    "wallpaper": {"source": "builtin:cyberpunk", "fit": "cover", "zoom": 100, "offset_x": 0, "offset_y": 0,
                  "rotation": 0, "mirror": false, "flip": false, "brightness": 100, "contrast": 100,
                  "saturation": 100, "gamma": 100, "blur": 0, "darken": 10, "tint": "#000000",
                  "tint_strength": 0, "vignette": 35, "protect": 0, "protect_side": "bottom",
                  "color": "#0B1020", "color2": "#3A1450", "angle": 135},
    "layouts": {
      "landscape": [
        {"id": "cpu-1", "type": "cpu", "style": "ring", "x": 0.0275, "y": 0.304, "w": 0.1875, "h": 0.3125,
         "anchor": "auto", "visible": true, "locked": false, "color": "#FF475C", "color2": "#FFD94A",
         "glow": 55, "opts": {"show_temp": true, "show_freq": true, "temp_sensor": "auto"}}
      ],
      "portrait": null
    }
  },
  "displays": {"usb-5-1.4.4": {"theme": "kojiro", "kojiro": {"...": "layout próprio deste display"}}}
}
```

- Lista `landscape`/`portrait` = ordem Z (o último fica por cima).
- `portrait: null` = layout retrato automático.
- Cada elemento tem `id` (`[a-z0-9_-]`, até 32), `type`, `style`, geometria
  normalizada (0–1, tolerando -0,5–1,5 para elementos parcialmente fora da tela),
  propriedades comuns e `opts` específicas do tipo (ver
  `bsmd/kojiro/model.py`, `COMMON` e `OPTIONS`).

## Validação e recuperação

- Valores inválidos são substituídos pelos padrões e registrados (problemas
  aparecem no diagnóstico); tipos desconhecidos, ids inválidos ou duplicados
  são descartados; no máximo 64 elementos; cores `#RRGGBB`; textos imprimíveis
  com limite; fontes só com nomes seguros; fonte de papel de parede só nas
  formas da tabela (nunca um caminho).
- `migrate()` converte versões antigas (o campo `version` permite evoluir o formato).
- Cada gravação guarda o arquivo anterior válido em `settings.json.bak`; um
  arquivo corrompido nunca substitui um `.bak` bom.
- Se alguém deixar o arquivo quebrado (edição manual, disco cheio), o serviço
  **mantém a última configuração válida** em vez de voltar aos padrões.

## Aplicação em tempo real

O serviço relê o arquivo em até 1 s e redesenha sem reiniciar. Nenhuma
alteração do Kojiro exige reinício. Aplicar configurações, enviar comandos ao
display e importar/remover papéis de parede usam ações Polkit liberadas para o
usuário **local e ativo** (sem senha); iniciar/parar/habilitar o serviço
continua exigindo administrador.

## Predefinições e compartilhamento

| Formato | Conteúdo |
| --- | --- |
| Predefinição do usuário | `~/.local/share/big-screen-monitor-display/kojiro/presets/<nome>.json` — `{"format": "kojiro-preset", "name", "config"}` |
| Exportação `.json` | mesmo formato; uma imagem importada **não** é referenciada (troca por arte incluída) |
| Pacote `.kojiro.zip` | `config.json`, `metadata.json` (`{"format": "kojiro-package", "version", "name", "widgets"}`), `thumbnail.png` e, só se o usuário confirmar, `wallpaper.png` |

Importação de pacote: apenas essas quatro entradas, sem diretórios, limites de
tamanho por entrada (12 MiB no total), proteção contra taxa de compressão
suspeita, PNG conferido estruturalmente, configuração validada inteira. O
papel de parede de um pacote passa pelo mesmo caminho de importação seguro.
