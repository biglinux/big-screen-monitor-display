# 14 — Detecção universal

## Princípios

1. **Somente leitura.** A descoberta lê `/sys/bus/usb/devices` (VID, PID,
   número de série, fabricante, produto, barramento/endereço, ttys). Nenhum
   dispositivo é aberto e nada é escrito. Roda a cada 2 s no serviço
   (hot-plug) e na interface, como usuário comum.
2. **Nada de sondagem experimental.** Um dispositivo desconhecido nunca
   recebe comandos para "ver se responde". O handshake só acontece em
   `open()`, e só para a família que os identificadores apontam (ou que o
   usuário escolheu).
3. **Nada de reivindicar o que não é display.** Interfaces de armazenamento,
   teclado, mouse e outros periféricos não são casadas por nenhuma regra; não
   há regra por vendor inteiro; gadgets Linux genéricos só contam com o
   serial do painel rev. C.

## Níveis de confiança

| Nível | Quando | Comportamento |
| --- | --- | --- |
| Confirmado | VID/PID + serial específico da família (ex.: `USB35INCHIPSV2`, `2017-2-25`, `AB…`) ou VID/PID exclusivo (AX206) | inicia automaticamente |
| Provável | VID/PID da família sem serial distintivo | inicia automaticamente; a interface mostra "Provável" |
| Ambíguo | duas famílias empatadas no topo | espera a escolha do usuário |
| Desconhecido | nenhuma regra | não é tocado; dispositivos seriais aparecem em "Outros dispositivos seriais" para identificação manual |

O id de cada display é o caminho da porta USB (`usb-5-1.4.4`): estável
entre reconexões na mesma porta, inclusive quando um rev. C acorda com outra
identidade, e diferente para dois painéis idênticos.

## Identificação manual assistida

Em **Meus Displays**:

- cada display tem "Modelo / protocolo" (automático ou uma família);
- dispositivos seriais não reconhecidos têm o botão "Escolher modelo…",
  que avisa que o serviço passará a falar aquele protocolo e só vale após
  "Aplicar";
- rev. C permite escolher o tamanho quando o painel não o informa.

A escolha é gravada em `displays.<id>.profile` e validada contra a lista de
famílias. A configuração global antiga `model` (`auto`/`ax206`/`turing`)
continua valendo como filtro da detecção automática.

## Linha de comando

```
$ python3 main.py --list-displays
usb-5-1.4.4        1908:0102  confirmed  AX206 DPF (AIDA64 / USB-Display)
$ python3 main.py --list-displays --json
```

## Permissões (udev)

`70-big-screen-monitor-display.rules` dá `0660` + grupo
`big-screen-monitor` + `uaccess` somente aos IDs/seriais da tabela de
compatibilidade. O serviço não está mais no grupo `uucp`, portanto não
alcança outras portas seriais (Arduino, modems, consoles). Um dispositivo
serial atribuído manualmente que não esteja nas regras precisa de uma regra
local equivalente (o diagnóstico mostra "permissão").
